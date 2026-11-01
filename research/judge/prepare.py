"""Build label-free, primary-document context for the same 79 development items."""
import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def norm(value):
    return unicodedata.normalize("NFC", str(value or "")).strip()


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def terms(text):
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", norm(text).lower())
    # Korean bigrams help with line breaks and inflections without a morphological package.
    return words + ["~" + w[i:i+2] for w in words if re.fullmatch("[가-힣]+", w)
                    for i in range(len(w)-1)]


def chunks_for_pdf(path, case_id):
    pages = [norm(p.extract_text()) for p in PdfReader(path).pages]
    joined = "\n".join(pages)
    start = re.search(r"(?m)^\s*주\s*문\s*$", joined)
    end = re.search(r"(?m)^\s*이\s*유\s*$", joined[start.end():]) if start else None
    order_start = start.start() if start else -1
    order_end = start.end()+end.start() if end else order_start
    chunks, offset = [], 0
    for page, text in enumerate(pages, 1):
        for part, pos in enumerate(range(0, len(text), 800), 1):
            fragment = text[pos:pos+950]
            if len(fragment) < 40:
                continue
            chunks.append({"chunk_id": f"{case_id}-p{page:03d}-s{part:02d}",
                           "pdf_page": page, "text": fragment,
                           "order": offset+pos < order_end and offset+pos+len(fragment) > order_start})
        offset += len(text)+1
    return chunks


def retrieve(chunks, query, char_limit=10500):
    bags = [Counter(terms(c["text"])) for c in chunks]
    df = Counter(t for bag in bags for t in bag)
    avg_len = sum(sum(b.values()) for b in bags)/len(bags)
    q = set(terms(query))
    scored = []
    for index, (chunk, bag) in enumerate(zip(chunks, bags)):
        length = sum(bag.values())
        score = 0.0
        for t in q:
            tf = bag[t]
            if tf:
                idf = math.log(1+(len(bags)-df[t]+0.5)/(df[t]+0.5))
                score += idf*tf*2.2/(tf+1.2*(0.25+0.75*length/avg_len))
        scored.append((score, index))
    # Always include up to four order chunks, then BM25-like lexical retrieval.
    order = [i for i,c in enumerate(chunks) if c["order"]][:4]
    ranks = order + [i for _,i in sorted(scored, key=lambda x:(-x[0],x[1])) if i not in order]
    selected, total = [], 0
    for index in ranks:
        chunk = chunks[index]
        if total+len(chunk["text"]) > char_limit:
            continue
        selected.append({k:chunk[k] for k in ["chunk_id","pdf_page","text"]})
        total += len(chunk["text"])
        if len(selected) == 11:
            break
    return selected


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf-root", type=Path, required=True, help="Folder containing the source manifest's C01.pdf etc.")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    sources = json.loads((ROOT/"research/review100/target_manifest.json").read_text())["sources"]
    source_by_case = {s["case"]:s for s in sources}
    corpus = {}
    for source in sources:
        pdf = args.pdf_root/Path(source["path"]).name
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == source["sha256"]
        corpus[source["case_id"]] = chunks_for_pdf(pdf, source["case_id"])
    master = {norm(r["ID"]):r for r in csv_rows(ROOT/"11_data_quality/qa_evaluated_990.csv")}
    reviewed = {r["QA_ID"]:r for r in csv_rows(ROOT/"research/legacy_review/existing_review100.csv")}
    subset = csv_rows(ROOT/"research/legacy_review/rule_replay79.csv")
    dataset, index = [], []
    for number, row in enumerate(subset, 1):
        original = reviewed[row["QA_ID"]]
        item = master[norm(row["대응_전체ID"])]
        assert all(norm(original[a]) == norm(item[b]) for a,b in
                   [("페르소나","페르소나"),("사건유형","사건유형"),("적용 법령","적용법령"),
                    ("적용 조문","적용조문"),("질문","질문"),("답변","답변")])
        case = source_by_case[norm(item["사건키"])]
        task = {k:item[k] for k in ["페르소나","사건유형","질문유형","난이도","적용법령","적용조문","질문","답변"]}
        task["사건명"] = case["case"]
        query = "\n".join(task[k] for k in ["질문","답변","적용법령","적용조문"])
        context = retrieve(corpus[case["case_id"]], query)
        model_input = {"task": task, "sources": context}
        item_id = f"J{number:03d}"
        dataset.append({"item_id":item_id, "payload":model_input,
                        "payload_sha256":canonical_hash(model_input)})
        index.append({"item_id":item_id, "legacy_id":row["QA_ID"],
                      "payload_sha256":canonical_hash(model_input), "case_id":case["case_id"],
                      "source_pdf_sha256":case["sha256"], "context_sha256":canonical_hash(context),
                      "source_chunks":[c["chunk_id"] for c in context],
                      "context_characters":sum(len(c["text"]) for c in context)})
    assert len(dataset) == 79
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in dataset), encoding="utf-8")
    manifest = {"version":"judge-dev-v1", "count":79,
                "scope":"All 79 items previously inspected: development comparison, no independent held-out claim.",
                "retrieval":"Case-local Korean token/bigram BM25 (k1=1.2,b=0.75); first <=4 order chunks, then rank; <=11 chunks, <=10500 characters. No human fields in query.",
                "full_document_coverage":False,
                "data_file_sha256":hashlib.sha256(args.out.read_bytes()).hexdigest(),
                "preparation_code_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "items":index}
    (HERE/"input_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Prepared {len(dataset)} label-free inputs; context chars min/max: "
          f"{min(i['context_characters'] for i in index)}/{max(i['context_characters'] for i in index)}")


if __name__ == "__main__":
    main()
