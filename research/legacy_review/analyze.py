"""Offline retrospective analysis of existing review records; no new human labels."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "09_code"))
from quality_checker_grounding import csv_to_record, validate

LABELS = ["적합", "검토", "부적합"]
HUMAN = {"OK": "적합", "보정 필요": "검토", "환각": "부적합"}
SHARED = [(1, "페르소나"), (2, "사건유형"), (3, "적용법령"),
          (4, "적용조문"), (5, "질문"), (6, "답변")]


def norm(value):
    return unicodedata.normalize("NFC", str(value or "")).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def obj_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def shared_mismatches(row, master):
    return [field for index, field in SHARED if norm(row[index]) != norm(master[field])]


def metrics(truth, predictions):
    """Rows=existing human labels; columns=rule predictions. Undefined rates stay null."""
    if len(truth) != len(predictions) or not truth:
        raise ValueError("Nonempty aligned observations required")
    if set(truth + predictions) - set(LABELS):
        raise ValueError("Unknown category")
    n = len(truth)
    counts = Counter(zip(truth, predictions))
    per_class = {}
    for label in LABELS:
        tp = counts[label, label]
        actual = sum(t == label for t in truth)
        predicted = sum(p == label for p in predictions)
        per_class[label] = {
            "support": actual, "predicted": predicted, "true_positive": tp,
            "precision": tp / predicted if predicted else None,
            "recall": tp / actual if actual else None,
            "f1": 2 * tp / (actual + predicted) if actual + predicted else None,
        }
    average = lambda key: sum(v[key] for v in per_class.values() if v[key] is not None) / sum(v[key] is not None for v in per_class.values())
    correct = sum(t == p for t, p in zip(truth, predictions))
    observed = correct / n
    expected = sum(per_class[k]["support"] * per_class[k]["predicted"] for k in LABELS) / n**2
    needs = [t != "적합" for t in truth]
    routed = [p != "적합" for p in predictions]
    tp = sum(t and p for t, p in zip(needs, routed))
    fp = sum(not t and p for t, p in zip(needs, routed))
    fn = sum(t and not p for t, p in zip(needs, routed))
    return {
        "n": n, "strict_matches": correct, "strict_agreement": observed,
        "balanced_accuracy": average("recall"), "macro_f1": average("f1"),
        "cohen_kappa": (observed - expected) / (1 - expected) if expected != 1 else None,
        "per_class": per_class,
        "confusion_rows_human_cols_rule": [[counts[t, p] for p in LABELS] for t in LABELS],
        "usable_binary_matches": sum((t == "부적합") == (p == "부적합") for t, p in zip(truth, predictions)),
        "needs_review_detection": {"tp": tp, "fp": fp, "fn": fn, "tn": n-tp-fp-fn,
                                   "precision": tp/(tp+fp) if tp+fp else None,
                                   "recall": tp/(tp+fn) if tp+fn else None,
                                   "routed_count": sum(routed)},
    }


def budget_yield(items, budget):
    """Equal-cost count proxy; uniform tie handling, never sort ties by human outcomes."""
    if not 0 <= budget <= len(items):
        raise ValueError("Budget outside corpus")
    groups = defaultdict(list)
    for item in items:
        groups[tuple(item["priority"])].append(item["needs_review"])
    remaining, expected, lower, upper = budget, 0.0, 0, 0
    for priority in sorted(groups, reverse=True):
        group = groups[priority]
        take = min(remaining, len(group))
        positives = sum(group)
        expected += take * positives / len(group)
        lower += max(0, take - (len(group) - positives))
        upper += min(take, positives)
        remaining -= take
        if not remaining:
            break
    return {"budget_items": budget, "expected_needs_review_found": expected,
            "tie_min": lower, "tie_max": upper,
            "random_expected": budget * sum(i["needs_review"] for i in items) / len(items)}


def main():
    paths = [ROOT / "releases/reviewer_100.xlsx", ROOT / "releases/competition_final.xlsx",
             ROOT / "11_data_quality/qa_evaluated_990.csv", ROOT / "qa_corrections_100.csv",
             ROOT / "09_code/quality_checker_grounding.py"]
    baseline = json.loads((ROOT / "docs/baseline_metrics.json").read_text())
    for path in paths[:3]:
        assert sha(path) == baseline["input_sha256"][str(path.relative_to(ROOT))]
    w = openpyxl.load_workbook(paths[0], read_only=True, data_only=True)
    raw = list(w.active.values)
    headers, reviewed = list(raw[0]), raw[1:]
    w.close()
    assert len(reviewed) == len({norm(r[0]) for r in reviewed}) == 100
    assert set(r[9] for r in reviewed) == set(HUMAN)
    final = openpyxl.load_workbook(paths[1], read_only=True, data_only=True)
    mapping_rows = [r for r in final["법리_검수"].values if str(r[0]).startswith("QA-") and r[1]]
    mapping = {norm(r[0]): norm(r[1]) for r in mapping_rows}
    final.close()
    assert len(mapping) == len(mapping_rows) == 100
    master_rows = read_csv(paths[2])
    master = {norm(r["ID"]): r for r in master_rows}
    assert len(master) == len(master_rows) == 990
    correction_export = read_csv(paths[3])
    legacy = {norm(r[0]): r for r in reviewed}
    assert len(correction_export) == len({norm(r["qa_id_b"]) for r in correction_export}) == 63
    assert all(norm(r["correction_full"]) == norm(legacy[norm(r["qa_id_b"])][10]) and
               norm(r["memo_full"]) == norm(legacy[norm(r["qa_id_b"])][12]) for r in correction_export)
    duplicate_corrections = defaultdict(list)
    for row in reviewed:
        if row[10]:
            duplicate_corrections[norm(row[10])].append(norm(row[0]))
    duplicate_groups = [ids for ids in duplicate_corrections.values() if len(ids) > 1]
    held = {rid for group in duplicate_groups for rid in group}
    records, replay, correction_pairs = [], [], []
    mode_predictions = {"always_review": [], "text_grounding": [], "structured_grounding": []}
    truth = []
    budget_items = []
    for index, row in enumerate(reviewed, 2):
        rid = norm(row[0])
        mapped_id = mapping[rid]
        current = master[mapped_id]
        mismatch = shared_mismatches(row, current)
        record = dict(zip(headers, row))
        record.update({"원본_시트행": index, "대응_전체ID": mapped_id,
                       "공통6항목_일치": not mismatch, "상이항목": ";".join(mismatch),
                       "보정안_동일문장_보류": rid in held,
                       "보정안_용도": "보류: 다른 ID와 동일문장" if rid in held else
                       ("제안쌍: 미재검증" if row[10] and row[9] != "OK" else
                        "참고: OK 판정의 보완안" if row[10] else "보정안 없음"),
                       "원본행_sha256": obj_sha(dict(zip(headers, row)))})
        records.append(record)
        if row[10] and row[9] != "OK" and rid not in held:
            correction_pairs.append({"QA_ID": rid, "질문": row[5], "기존답변": row[6],
                                     "검수자_제안답변": row[10], "기존판정": row[9], "기존메모": row[12],
                                     "상태": "미재검증 제안쌍; 학습용 선호/정답 확정 아님"})
        if mismatch:
            continue
        # csv_to_record exposes only task inputs, never confidence, label, memo, or correction.
        task_input = csv_to_record(current)
        assert not set(task_input) & {"검수자_평가", "Confidence_Score", "검수자 평가", "보정안", "메모", "신뢰도"}
        human = HUMAN[row[9]]
        truth.append(human)
        result = {"QA_ID": rid, "대응_전체ID": mapped_id, "기존판정": row[9],
                  "분석용_사람범주": human, "질문유형": current["질문유형"],
                  "페르소나": current["페르소나"], "난이도": current["난이도"],
                  "입력_sha256": obj_sha(task_input)}
        for mode, grounding in [("text_grounding", False), ("structured_grounding", True)]:
            prediction = validate(task_input, grounding=grounding)
            mode_predictions[mode].append(prediction["tier"])
            result[mode] = prediction["tier"]
            result[mode + "_blocks"] = prediction["blockN"]
            result[mode + "_warnings"] = prediction["advN"]
            result[mode + "_codes"] = ";".join(prediction["block_codes"])
            if grounding:
                priority = [LABELS.index(prediction["tier"]), prediction["blockN"], prediction["advN"]]
                budget_items.append({"priority": priority, "needs_review": human != "적합"})
                if row[10] and rid not in held:
                    revised_input = {**task_input, "답변": row[10]}
                    # Diagnostic sensitivity only; no assumption that the proposed answer is correct.
                    revised = validate(revised_input, grounding=True)
                    result["보정안_입력시_규칙범주"] = revised["tier"]
                    result["보정안_입력_sha256"] = obj_sha(revised_input)
                else:
                    result["보정안_입력시_규칙범주"] = ""
                    result["보정안_입력_sha256"] = ""
        mode_predictions["always_review"].append("검토")
        replay.append(result)
    # Make the CSV schema stable even if the first row has no proposed correction.
    assert len(replay) == 79
    report = {
        "status": "retrospective_calibration_analysis_no_new_labels_or_model_calls",
        "baseline_commit": "74135adccfc916b164546c7d6db0e50c170657d5",
        "inputs_sha256": {str(p.relative_to(ROOT)): sha(p) for p in paths},
        "analysis_code_sha256": sha(Path(__file__)),
        "human_records": len(reviewed), "human_labels": dict(Counter(r[9] for r in reviewed)),
        "correction_texts": sum(bool(r[10]) for r in reviewed), "memos": sum(bool(r[12]) for r in reviewed),
        "confidence_missing": sum(r[11] is None for r in reviewed),
        "confidence_values": dict(Counter(str(r[11]) for r in reviewed)),
        "correction_export_rows": len(correction_export),
        "correction_export_exact_matches": len(correction_export),
        "OK_with_proposed_corrections": [norm(r[0]) for r in reviewed if r[9] == "OK" and r[10]],
        "duplicate_correction_groups": duplicate_groups, "held_correction_texts": len(held),
        "non_OK_correction_candidates": len(correction_pairs),
        "replay_records": len(replay), "replay_human_labels": dict(Counter(r["기존판정"] for r in replay)),
        "excluded_records": len(reviewed)-len(replay),
        "excluded_ids": [r["QA_ID"] for r in records if not r["공통6항목_일치"]],
        "shared_fields_required": [field for _, field in SHARED],
        "context_provenance": "Evidence, question type and difficulty restored from frozen master; original review form does not contain the same fields. Full historical context equivalence is not established.",
        "prediction_inputs_exclude": ["human label", "human confidence", "memo", "correction", "final static labels"],
        "category_mapping": HUMAN, "category_semantics": "Analytic proxy: rule warnings are not identical to legal correctness.",
        "evaluation_order": LABELS,
        "metrics": {mode: metrics(truth, pred) for mode, pred in mode_predictions.items()},
        "paired_proposed_answer_diagnostic": dict(Counter(
            r["structured_grounding"] + "→" + r["보정안_입력시_규칙범주"]
            for r in replay if r["보정안_입력시_규칙범주"])),
        "review_budget_proxy": [budget_yield(budget_items, b) for b in [10,20,40,60]],
        "budget_policy": "Descending (tier index, block count, warning count); exact expected yield under uniform ties. No label, memo, correction or human confidence used in ranking. One item assumed equal effort; not monetary/time savings.",
        "scope": "Previously used calibration sample; descriptive only, not independent generalization or expert certification.",
    }
    write_csv(OUT / "existing_review100.csv", records)
    write_csv(OUT / "rule_replay79.csv", replay)
    write_csv(OUT / "proposed_correction_pairs61.csv", correction_pairs)
    (OUT / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k,v in report.items() if k in ["human_labels", "correction_texts", "memos", "replay_human_labels", "duplicate_correction_groups", "non_OK_correction_candidates", "metrics", "paired_proposed_answer_diagnostic", "review_budget_proxy"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
