"""
qc_result_990.csv의 판정/점수/오류코드/보정지침을
qa_combined_990.csv의 빈 4개 컬럼(Confidence_Score, 검수자_평가, 비고, 문제점_및_해결방안)에 병합.
"""
import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QA_CSV = ROOT / "11_data_quality" / "qa_combined_990.csv"
QC_CSV = ROOT / "11_data_quality" / "qc_result_990.csv"
OUT_CSV = ROOT / "11_data_quality" / "qa_evaluated_990.csv"


def load(path):
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    qa_rows = load(QA_CSV)
    qc_rows = load(QC_CSV)

    qc_index = {r["QA_ID"]: r for r in qc_rows}
    fields = list(qa_rows[0].keys()) if qa_rows else []

    matched = 0
    judgment_count = Counter()

    for r in qa_rows:
        qc = qc_index.get(r["ID"])
        if not qc:
            continue
        matched += 1
        r["Confidence_Score"] = qc.get("score_total", "")
        r["검수자_평가"] = qc.get("judgment", "")
        r["비고"] = qc.get("error_codes", "")
        r["문제점_및_해결방안"] = qc.get("correction_note", "")
        judgment_count[qc.get("judgment", "")] += 1

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(qa_rows)

    print(f"입력: {QA_CSV.name} ({len(qa_rows)}행) + {QC_CSV.name} ({len(qc_rows)}행)")
    print(f"매칭: {matched}/{len(qa_rows)} ({matched/len(qa_rows)*100:.1f}%)")
    print(f"\n검수자_평가 분포:")
    for j, c in judgment_count.most_common():
        print(f"  {j or '(빈값)'}: {c}건 ({c/len(qa_rows)*100:.1f}%)")

    avg_score = sum(int(r["Confidence_Score"]) for r in qa_rows if r["Confidence_Score"]) / max(matched, 1)
    print(f"\nConfidence_Score 평균: {avg_score:.1f}")

    notes_filled = sum(1 for r in qa_rows if r["문제점_및_해결방안"].strip())
    print(f"문제점_및_해결방안 채워진 행: {notes_filled}건")

    print(f"\n출력: {OUT_CSV}")


if __name__ == "__main__":
    main()
