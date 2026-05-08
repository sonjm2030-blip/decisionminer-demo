"""
04_raw_outputs/<case>/{facts,legal,sanction}.json 에서
요약/사실관계/분류/추론 4종 메타 데이터셋 CSV 생성.
"""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "04_raw_outputs"
OUT_DIR = ROOT / "11_data_quality"

CASE_TYPE_ENUM = [
    "담합", "하도급", "거래상지위", "표시광고", "전자상거래",
    "사업자단체", "가맹사업", "부당고객유인", "부당지원", "재판매가격", "기타",
]

SKIP_DIRS = {"_failed"}
SKIP_PREFIXES = ("v2_시범_", ".")


def load_json(path):
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sanction_text(s):
    if not s:
        return ""
    parts = []
    types = s.get("처분유형") or []
    if isinstance(types, list) and types:
        parts.append(", ".join(str(t) for t in types))
    if s.get("과징금"):
        parts.append(str(s["과징금"]))
    elif s.get("과징금액"):
        parts.append(f"과징금 {s['과징금액']:,}원")
    return " | ".join(parts)


def map_to_enum(t):
    if not t:
        return ""
    t = t.strip()
    return t if t in CASE_TYPE_ENUM else "기타"


def build_summary(name, facts, legal, sanction, idx):
    classif = (legal or {}).get("classification_tags") or {}
    summary_short = ""
    if isinstance(facts, dict):
        summary_short = (facts.get("summary_short") or facts.get("결과") or "").strip()
    return {
        "ID": f"summary_{idx:03d}",
        "사건키": name,
        "사건유형": classif.get("사건유형_대분류", ""),
        "적용법령": (legal or {}).get("법령", ""),
        "처분결과": sanction_text(sanction),
        "summary_short": summary_short,
        "의결일": "",
        "출처": "공정거래위원회 의결서",
    }


def build_facts(name, facts, legal, sanction, idx):
    classif = (legal or {}).get("classification_tags") or {}
    fs = (facts or {}).get("facts_structured") or {}
    if not isinstance(fs, dict):
        fs = {}

    def fb(field):
        # facts_structured 우선, 없으면 facts.json 본문 동일명 필드
        return (fs.get(field) or (facts or {}).get(field) or "").strip() if isinstance(fs.get(field, "") or "", str) else fs.get(field, "")

    return {
        "ID": f"facts_{idx:03d}",
        "사건키": name,
        "사건유형": classif.get("사건유형_대분류", ""),
        "적용법령": (legal or {}).get("법령", ""),
        "당사자": fs.get("당사자") if isinstance(fs.get("당사자"), str) else (
            "; ".join(fs.get("당사자", [])) if isinstance(fs.get("당사자"), list) else ""
        ),
        "기간": fs.get("기간", ""),
        "행위": fs.get("행위") or (facts or {}).get("행위", ""),
        "피해규모": fs.get("피해규모", ""),
        "피해범위": fs.get("피해범위", ""),
        "처분결과": sanction_text(sanction),
    }


def build_classification(name, legal, idx):
    classif = (legal or {}).get("classification_tags") or {}
    if not isinstance(classif, dict):
        classif = {}
    types = classif.get("처분_유형") or []
    if isinstance(types, list):
        types_str = ", ".join(str(t) for t in types)
    else:
        types_str = str(types)
    return {
        "ID": f"class_{idx:03d}",
        "사건키": name,
        "사건유형_대분류": map_to_enum(classif.get("사건유형_대분류", "")),
        "사건유형_세분류": classif.get("사건유형_세분류", ""),
        "위반조문": classif.get("위반_조문", ""),
        "처분유형": types_str,
        "산업분야": classif.get("산업분야", ""),
        "신뢰도": "",
    }


def pick_step(chain, i):
    """inference_chain의 i단계 dict 반환 (단계 필드 또는 인덱스 기반)."""
    if not isinstance(chain, list):
        return {}
    for step in chain:
        if isinstance(step, dict) and step.get("단계") == i:
            return step
    if 0 <= i - 1 < len(chain) and isinstance(chain[i - 1], dict):
        return chain[i - 1]
    return {}


def build_inference(name, facts, legal, sanction, idx):
    classif = (legal or {}).get("classification_tags") or {}
    chain = (legal or {}).get("inference_chain") or []
    s1 = pick_step(chain, 1)
    s2 = pick_step(chain, 2)
    s3 = pick_step(chain, 3)
    s4 = pick_step(chain, 4)
    return {
        "ID": f"infer_{idx:03d}",
        "사건키": name,
        "사건유형": classif.get("사건유형_대분류", ""),
        "전제1": s1.get("법령확인") or s1.get("전제") or "",
        "전제2": s2.get("구성요건") or s2.get("전제") or "",
        "결론": s4.get("결론") or "",
        "근거": s3.get("근거인용") or s3.get("근거") or "",
        "적용법령": (legal or {}).get("법령", ""),
        "적용조문": (legal or {}).get("조문", ""),
        "처분결과": sanction_text(sanction),
    }


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def missing_rate(rows, fields):
    """행수 대비 빈/None 셀 비율(%)."""
    if not rows:
        return 0.0
    total = len(rows) * len(fields)
    miss = sum(1 for r in rows for c in fields if not str(r.get(c, "")).strip())
    return miss / total * 100


def main():
    summary_rows, facts_rows, classif_rows, infer_rows = [], [], [], []
    type_counter = Counter()
    missing_meta = []

    folders = sorted([p for p in RAW_DIR.iterdir() if p.is_dir()])
    idx = 0
    for folder in folders:
        name = folder.name
        if name in SKIP_DIRS or name.startswith(SKIP_PREFIXES):
            continue
        if not (folder / "qa_list.json").exists():
            continue

        idx += 1
        facts = load_json(folder / "facts.json") or {}
        legal = load_json(folder / "legal.json") or {}
        sanction = load_json(folder / "sanction.json") or {}

        miss_files = []
        if not facts: miss_files.append("facts.json")
        if not legal: miss_files.append("legal.json")
        if miss_files:
            missing_meta.append((name, miss_files))

        ct = ((legal.get("classification_tags") or {}).get("사건유형_대분류") or "").strip()
        type_counter[ct or "(없음)"] += 1

        summary_rows.append(build_summary(name, facts, legal, sanction, idx))
        facts_rows.append(build_facts(name, facts, legal, sanction, idx))
        classif_rows.append(build_classification(name, legal, idx))
        infer_rows.append(build_inference(name, facts, legal, sanction, idx))

    SUMMARY_FIELDS = ["ID","사건키","사건유형","적용법령","처분결과","summary_short","의결일","출처"]
    FACTS_FIELDS = ["ID","사건키","사건유형","적용법령","당사자","기간","행위","피해규모","피해범위","처분결과"]
    CLASS_FIELDS = ["ID","사건키","사건유형_대분류","사건유형_세분류","위반조문","처분유형","산업분야","신뢰도"]
    INFER_FIELDS = ["ID","사건키","사건유형","전제1","전제2","결론","근거","적용법령","적용조문","처분결과"]

    write_csv(OUT_DIR / "dataset_summary_22.csv", summary_rows, SUMMARY_FIELDS)
    write_csv(OUT_DIR / "dataset_facts_22.csv", facts_rows, FACTS_FIELDS)
    write_csv(OUT_DIR / "dataset_classification_22.csv", classif_rows, CLASS_FIELDS)
    write_csv(OUT_DIR / "dataset_inference_22.csv", infer_rows, INFER_FIELDS)

    print("=" * 60)
    print(f"4종 데이터셋 생성 완료 (총 {idx}건)")
    print("=" * 60)

    print("\n[1] 사건유형 분포 (11종 enum)")
    enum_set = set(CASE_TYPE_ENUM)
    covered = set()
    for t, c in type_counter.most_common():
        mark = "✓" if t in enum_set else " "
        if t in enum_set: covered.add(t)
        print(f"  {mark} {t}: {c}건")
    print(f"  → 11종 중 {len(covered)}종 커버 ({len(covered)/11*100:.1f}%)")
    not_covered = [t for t in CASE_TYPE_ENUM if t not in covered]
    if not_covered:
        print(f"  → 미커버: {', '.join(not_covered)}")

    print("\n[2] 4종 데이터셋 결측률")
    for label, rows, fields in [
        ("요약", summary_rows, SUMMARY_FIELDS),
        ("사실관계", facts_rows, FACTS_FIELDS),
        ("분류", classif_rows, CLASS_FIELDS),
        ("추론", infer_rows, INFER_FIELDS),
    ]:
        rate = missing_rate(rows, fields)
        print(f"  {label} ({len(fields)}열, {len(rows)}행): 결측 {rate:.1f}%")

    print("\n[3] 메타 누락 사건")
    if missing_meta:
        for name, miss in missing_meta:
            print(f"  - {name}: {', '.join(miss)}")
    else:
        print("  (없음)")

    print("\n[4] 생성 경로")
    for fn in ["dataset_summary_22.csv","dataset_facts_22.csv","dataset_classification_22.csv","dataset_inference_22.csv"]:
        print(f"  - {OUT_DIR / fn}")


if __name__ == "__main__":
    main()
