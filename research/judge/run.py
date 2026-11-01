"""Run two label-blind judge prompts with bounded spend and resumable, append-only results."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import anthropic
import jsonschema

HERE = Path(__file__).resolve().parent
VERDICTS = {"적합", "검토", "부적합", "판단보류"}
PRICING_URL = "https://platform.claude.com/docs/en/models/sonnet-4-6/overview"


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def validate_review(review, payload, schema):
    """Check structure and quote presence. This does not verify legal entailment."""
    errors = sorted(error.message for error in jsonschema.Draft202012Validator(schema).iter_errors(review))
    if errors:
        return ["schema_invalid"]
    if review["verdict"] in {"적합", "판단보류"} and review["issues"]:
        errors.append("issues_present_for_pass_or_abstain")
    if review["verdict"] in {"검토", "부적합"} and not review["issues"]:
        errors.append("negative_verdict_without_issue")
    sources = {c["chunk_id"]: compact(c["text"]) for c in payload["sources"]}
    for issue in review["issues"]:
        for evidence in issue["evidence"]:
            quote = compact(evidence["quote"])
            source = sources.get(evidence["chunk_id"])
            if source is None:
                errors.append("unknown_source_chunk")
            elif len(quote) < 8 or quote not in source:
                errors.append("quote_not_found_verbatim")
    return sorted(set(errors))


def request_arguments(item, arm, schema, prompts, model):
    return {"model": model, "system": prompts["common"]+"\n\n"+prompts[arm],
            "messages": [{"role":"user", "content":json.dumps(item["payload"],ensure_ascii=False)}],
            "tools":[{"name":"record_review", "description":"Record the QA quality assessment with short source quotations. This tool only records data and executes no action.",
                      "input_schema":schema}],
            "tool_choice":{"type":"tool", "name":"record_review", "disable_parallel_tool_use":True}}


def dollars(usage):
    return (usage.get("input_tokens",0)*3 + usage.get("output_tokens",0)*15
            + usage.get("cache_creation_input_tokens",0)*3.75
            + usage.get("cache_read_input_tokens",0)*0.3)/1_000_000


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--limit",type=int,default=79)
    ap.add_argument("--budget-usd",type=float,default=12.0)
    ap.add_argument("--workers",type=int,default=4)
    ap.add_argument("--max-output-tokens",type=int,default=1800)
    args = ap.parse_args()
    if not 0 < args.limit <= 79 or not 1 <= args.workers <= 4 or not 0 < args.budget_usd <= 12:
        raise ValueError("Invalid request count, concurrency, or budget")
    key = os.environ.get("ANTHROPIC_API_KEY","").strip()
    if not key or not key.isascii() or any(ord(c)<33 or ord(c)>=127 for c in key):
        raise ValueError("ANTHROPIC_API_KEY is missing or invalid; no calls made")
    prompts = {name:(HERE/(name+".txt")).read_text() for name in ["common","generic","rubric"]}
    schema = json.loads((HERE/"schema.json").read_text())
    items = [json.loads(line) for line in args.inputs.read_text().splitlines() if line.strip()]
    if len(items) != 79 or any(canonical_hash(i["payload"]) != i["payload_sha256"] for i in items):
        raise ValueError("Input corpus mismatch")
    input_manifest = json.loads((HERE/"input_manifest.json").read_text())
    if hashlib.sha256(args.inputs.read_bytes()).hexdigest() != input_manifest["data_file_sha256"]:
        raise ValueError("Input file differs from prepared manifest")
    selected = items[:args.limit]
    args.out.mkdir(parents=True,exist_ok=True)
    manifest = {"experiment":"judge-dev-v1", "model":"claude-sonnet-4-6", "temperature":0,
                "thinking":"disabled", "max_output_tokens":args.max_output_tokens,
                "inputs_sha256":input_manifest["data_file_sha256"],
                "prompts_sha256":{k:hashlib.sha256(v.encode()).hexdigest() for k,v in prompts.items()},
                "schema_sha256":canonical_hash(schema), "sdk_version":anthropic.__version__,
                "runner_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "budget_usd":args.budget_usd,"price_input_per_million":3,"price_output_per_million":15,
                "pricing_source":PRICING_URL,"pricing_checked":"2026-11-01",
                "label_exposure":"None in requests; all items previously inspected by rubric developer.",
                "max_retries":0}
    manifest_file = args.out/"run_manifest.json"
    if manifest_file.exists():
        if json.loads(manifest_file.read_text()) != manifest:
            raise ValueError("Existing run settings differ; use a distinct run folder")
    else:
        manifest_file.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    result_file = args.out/"responses.jsonl"
    previous = [json.loads(line) for line in result_file.read_text().splitlines()] if result_file.exists() else []
    completed = {(r["item_id"],r["arm"]) for r in previous}
    if len(completed) != len(previous):
        raise ValueError("Duplicate existing request records")
    spent = sum(r.get("estimated_usd",0) for r in previous)
    lock = threading.Lock()
    client = anthropic.Anthropic(api_key=key,max_retries=0,timeout=60)
    jobs = []
    for position,item in enumerate(selected):
        arms = ["generic","rubric"] if position%2==0 else ["rubric","generic"]
        jobs += [(item,arm) for arm in arms if (item["item_id"],arm) not in completed]
    print(f"Pending {len(jobs)} requests; previous records {len(previous)}; spent estimate ${spent:.4f}",flush=True)

    def count(job):
        item,arm = job
        kwargs = request_arguments(item,arm,schema,prompts,manifest["model"])
        n = client.messages.count_tokens(**kwargs).input_tokens
        bound = (n*3+args.max_output_tokens*15)/1_000_000
        return item,arm,kwargs,n,bound

    # Count all pending requests first. Never start a paid call after an over-budget plan.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        counted = list(pool.map(count,jobs))
    upper_bound = spent+sum(j[4] for j in counted)
    if upper_bound > args.budget_usd:
        raise ValueError(f"Requested output-token upper bound ${upper_bound:.4f} exceeds budget; no new model calls made")
    print(f"Token-count upper bound including output caps: ${upper_bound:.4f}",flush=True)

    def call(job):
        item,arm,kwargs,counted_input,bound = job
        started = time.monotonic()
        record = {"item_id":item["item_id"],"arm":arm,"payload_sha256":item["payload_sha256"],
                  "started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "counted_input_tokens":counted_input,"max_request_usd":bound}
        try:
            response = client.messages.create(**kwargs,max_tokens=args.max_output_tokens,
                                              temperature=0,thinking={"type":"disabled"})
            record.update({"response_id":response.id,"response_model":response.model,
                           "stop_reason":response.stop_reason,"usage":response.usage.model_dump()})
            record["estimated_usd"] = dollars(record["usage"])
            tools = [b for b in response.content if b.type=="tool_use" and b.name=="record_review"]
            if response.stop_reason != "tool_use" or len(tools)!=1:
                record.update({"status":"invalid_response","validation_errors":["missing_or_truncated_tool_record"]})
            else:
                result = tools[0].input
                errors = validate_review(result,item["payload"],schema)
                record.update({"status":"ok" if not errors else "invalid_response", "review":result,
                               "validation_errors":errors})
        except anthropic.APIStatusError as exc:
            record.update({"status":"api_error","error_type":type(exc).__name__,"http_status":exc.status_code})
        except Exception as exc:
            record.update({"status":"request_error","error_type":type(exc).__name__})
        record["latency_seconds"] = round(time.monotonic()-started,3)
        with lock:
            with result_file.open("a",encoding="utf-8") as f:
                f.write(json.dumps(record,ensure_ascii=False)+"\n"); f.flush()
            print(f'{record["item_id"]} {arm}: {record["status"]}',flush=True)
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        new = list(pool.map(call,counted))
    all_records = previous+new
    summary = {"records":len(all_records),"valid":sum(r["status"]=="ok" for r in all_records),
               "invalid_or_failed":sum(r["status"]!="ok" for r in all_records),
               "estimated_usd":round(sum(r.get("estimated_usd",0) for r in all_records),6),
               "usage_unavailable_requests":sum("usage" not in r for r in all_records),
               "cost_note":"Token-based estimate using published rates; not an invoice. Failed requests without usage are reported separately."}
    (args.out/"execution_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
