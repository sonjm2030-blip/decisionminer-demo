"""Compare recorded judge responses with legacy development labels, including abstentions."""
import argparse
import csv
import hashlib
import importlib.util
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("legacy_metrics", ROOT/"research/legacy_review/analyze.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
LABELS = ["적합","검토","부적합"]


def read_csv(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))


def effective_prediction(record):
    if record is None:
        return "미실행"
    if record["status"] != "ok":
        return "출력검증실패"
    return record["review"]["verdict"]


def summarize(truth, predictions):
    decided = [i for i,p in enumerate(predictions) if p in LABELS]
    subset = legacy.metrics([truth[i] for i in decided],[predictions[i] for i in decided]) if decided else None
    return {"n":len(truth), "predictions":dict(Counter(predictions)),
            "definite_count":len(decided),"coverage":len(decided)/len(truth),
            "matching_definite_over_all":sum(t==p for t,p in zip(truth,predictions))/len(truth),
            "matching_count":sum(t==p for t,p in zip(truth,predictions)),
            "conditional_metrics_on_decided_subset":subset,
            "confusion_columns":LABELS+["판단보류","출력검증실패","미실행"],
            "confusion_rows_human":[[sum(t==label and p==pred for t,p in zip(truth,predictions))
                                      for pred in LABELS+["판단보류","출력검증실패","미실행"]] for label in LABELS]}


def hybrid(rule, model):
    """Route uncertainty to human review; never automatically certify or reject from judge alone."""
    if rule != "적합":
        return rule
    return "적합" if model == "적합" else "검토"


def quote_audit(records, items):
    compact = lambda text: re.sub(r"\s+","",unicodedata.normalize("NFC",text))
    counts = Counter()
    for record in records:
        sources = {c["chunk_id"]:compact(c["text"]) for c in items[record["item_id"]]["payload"]["sources"]}
        for issue in record.get("review",{}).get("issues",[]):
            for evidence in issue.get("evidence",[]):
                quote = compact(evidence["quote"])
                if evidence["chunk_id"] not in sources:
                    counts["unknown_chunk"] += 1
                elif len(quote)<8:
                    counts["under_8_characters"] += 1
                elif quote in sources[evidence["chunk_id"]]:
                    counts["exact_in_cited_chunk"] += 1
                elif any(quote in text for text in sources.values()):
                    counts["present_in_different_provided_chunk"] += 1
                else:
                    counts["not_verbatim_in_any_provided_chunk"] += 1
    return dict(counts)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run",type=Path,required=True)
    ap.add_argument("--inputs",type=Path,required=True,help="Frozen label-free inputs, for quotation audit")
    args = ap.parse_args()
    records = [json.loads(line) for line in (args.run/"responses.jsonl").read_text().splitlines()]
    responses = {(r["item_id"],r["arm"]):r for r in records}
    assert len(records)==len(responses), "Duplicate item/arm records"
    manifest = json.loads((HERE/"input_manifest.json").read_text())
    index = manifest["items"]
    assert hashlib.sha256(args.inputs.read_bytes()).hexdigest()==manifest["data_file_sha256"]
    run_manifest = json.loads((args.run/"run_manifest.json").read_text())
    assert run_manifest["inputs_sha256"]==manifest["data_file_sha256"]
    assert hashlib.sha256((HERE/"run.py").read_bytes()).hexdigest()==run_manifest["runner_sha256"]
    for name,expected_hash in run_manifest["prompts_sha256"].items():
        assert hashlib.sha256((HERE/(name+".txt")).read_bytes()).hexdigest()==expected_hash
    input_items = {r["item_id"]:r for r in [json.loads(line) for line in args.inputs.read_text().splitlines()]}
    assert set(input_items)=={i["item_id"] for i in index}
    assert all(input_items[i["item_id"]]["payload_sha256"]==i["payload_sha256"] for i in index)
    expected = {(item["item_id"],arm) for item in index for arm in ["generic","rubric"]}
    assert set(responses)==expected, "Full 79x2 run required; do not silently score a partial run"
    execution = json.loads((args.run/"execution_summary.json").read_text())
    assert execution["records"]==len(records), "Execution summary has not been finalized"
    assert abs(execution["estimated_usd"]-sum(r.get("estimated_usd",0) for r in records))<1e-6
    assert all(r.get("response_model")==run_manifest["model"] for r in records if "response_model" in r)
    baseline = {r["QA_ID"]:r for r in read_csv(ROOT/"research/legacy_review/rule_replay79.csv")}
    truth, rules = [], []
    predictions = {"generic":[],"rubric":[]}
    rows = []
    for item in index:
        base = baseline[item["legacy_id"]]
        human = base["분석용_사람범주"]
        rule = base["structured_grounding"]
        truth.append(human); rules.append(rule)
        row = {"item_id":item["item_id"],"QA_ID":item["legacy_id"],"기존사람판정":human,
               "기존규칙":rule,"원문문맥_sha256":item["context_sha256"]}
        for arm in predictions:
            record = responses[item["item_id"],arm]
            assert record["payload_sha256"] == item["payload_sha256"]
            prediction = effective_prediction(record)
            predictions[arm].append(prediction)
            row[arm] = prediction
            row[arm+"_원출력"] = record.get("review",{}).get("verdict","")
            row[arm+"_요약"] = record.get("review",{}).get("summary","")
            row[arm+"_검증오류"] = ";".join(record.get("validation_errors",[]))
            row[arm+"_결합규칙"] = hybrid(rule,prediction)
        row["검수순서구분"] = ("기존 규칙 검토" if rule!="적합" else
                           "모델 확인 후 통과 후보" if row["rubric"]=="적합" else "규칙 통과 후 추가 확인")
        rows.append(row)
    model_summaries = {arm:summarize(truth,preds) for arm,preds in predictions.items()}
    common = [i for i in range(79) if all(predictions[a][i] in LABELS for a in predictions)]
    common_metrics = {arm:legacy.metrics([truth[i] for i in common], [preds[i] for i in common])
                      for arm,preds in predictions.items()} if common else {}
    pair = Counter((t==a,t==b) for t,a,b in zip(truth,predictions["generic"],predictions["rubric"]))
    hybrid_results = {}
    for arm,preds in predictions.items():
        routed = [hybrid(r,p) for r,p in zip(rules,preds)]
        extra = [i for i,(r,p) in enumerate(zip(rules,routed)) if r=="적합" and p!="적합"]
        reasons = {}
        for reason in ["검토","부적합","판단보류","출력검증실패"]:
            members = [i for i in extra if preds[i]==reason]
            reasons[reason] = {"count":len(members),
                               "existing_non_OK":sum(truth[i]!="적합" for i in members),
                               "existing_OK":sum(truth[i]=="적합" for i in members)}
        hybrid_results[arm] = {"metrics":legacy.metrics(truth,routed),
                               "extra_routing_reasons":reasons,
                               "extra_routed":len(extra),
                               "extra_existing_non_OK":sum(truth[i]!="적합" for i in extra),
                               "extra_existing_OK":sum(truth[i]=="적합" for i in extra),
                               "judge_calls_in_simulated_policy":sum(r=="적합" for r in rules),
                               "sum_observed_call_costs_for_policy_subset":sum(responses[index[i]["item_id"],arm].get("estimated_usd",0)
                                                                               for i,r in enumerate(rules) if r=="적합")}
    policies = {"rule_priority":[], "rubric_priority":[], "prompt_disagreement_priority":[]}
    for i,item in enumerate(index):
        base = baseline[item["legacy_id"]]
        a,b = predictions["generic"][i],predictions["rubric"][i]
        uncertain = a not in LABELS or b not in LABELS
        disagreement = not uncertain and a!=b
        severity = max([LABELS.index(p) for p in [a,b] if p in LABELS],default=0)
        priorities = {"rule_priority":[LABELS.index(rules[i]),int(base["structured_grounding_blocks"]),int(base["structured_grounding_warnings"])],
                      "rubric_priority":[3 if b not in LABELS else LABELS.index(b)],
                      "prompt_disagreement_priority":[int(uncertain),int(disagreement),severity]}
        for name,priority in priorities.items():
            policies[name].append({"priority":priority,"needs_review":truth[i]!="적합"})
    budget_summaries = {name:[legacy.budget_yield(items,b) for b in [10,20,40,60]]
                        for name,items in policies.items()}
    schema_diagnostics = Counter()
    schema = json.loads((HERE/"schema.json").read_text())
    assert legacy.obj_sha(schema)==run_manifest["schema_sha256"]
    for record in records:
        if "schema_invalid" in record.get("validation_errors",[]):
            for error in jsonschema.Draft202012Validator(schema).iter_errors(record.get("review")):
                schema_diagnostics[str(error.validator)+":"+".".join(map(str,error.absolute_path))] += 1
    report = {"scope":"Development-only retrospective comparison; rubric developer previously saw all 79 records.",
              "evaluation_code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "n":79,"arms":model_summaries,"rule_baseline":legacy.metrics(truth,rules),
              "all_review_baseline":legacy.metrics(truth,["검토"]*79),
              "paired_common_definite_count":len(common),"paired_common_definite_metrics":common_metrics,
              "paired_full79_matching_counts":{"both":pair[True,True],"generic_only":pair[True,False],
                                              "rubric_only":pair[False,True],"neither":pair[False,False]},
              "hybrid_simulation":hybrid_results,
              "review_budget_exploration":budget_summaries,
              "budget_note":"Post-hoc ranking, uniform tie expectations, equal effort per item. Prompt disagreement uses two instruction variants of one model, not calibrated uncertainty or a replication of CoAnnotating.",
              "hybrid_note":"Post-hoc routing simulation reusing the same model responses; abstentions/invalid outputs route to review, not asserted legal errors. Production data and labels remain unchanged.",
              "response_integrity":{"total":len(records),"statuses":dict(Counter(r["status"] for r in records)),
                                    "validation_errors":dict(Counter(error for r in records for error in r.get("validation_errors",[]))),
                                    "schema_diagnostics":dict(schema_diagnostics),
                                    "quote_diagnostics":quote_audit(records,input_items)},
              "execution":execution,
              "comparison_limit":"Prompt comparison uses identical source chunks. Rule vs judge also differs in evidence context, so differences cannot be attributed solely to the model.",
              "quote_check_limit":"Substring and source-ID checks establish quotation presence only, not legal support or correct entailment."}
    (args.run/"evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    with (args.run/"item_comparison79.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n")
        writer.writeheader();writer.writerows(rows)
    print(json.dumps({"arms":{a:{k:v for k,v in m.items() if k in ["matching_count","definite_count","coverage","predictions"]} for a,m in model_summaries.items()},
                      "hybrid":{a:{k:v for k,v in m.items() if k not in ["metrics"]} for a,m in hybrid_results.items()},
                      "execution":report["execution"]},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
