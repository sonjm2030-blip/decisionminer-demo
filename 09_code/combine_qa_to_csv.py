"""
04_raw_outputs/<case>/{qa_list,facts,legal,sanction}.json 들을 모아
quality_checker_v2_4 입력용 CSV(17 컬럼) 생성.
"""
import csv
import json
import re
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "04_raw_outputs"
INV_CSV = ROOT / "01_data_inventory" / "inventory_full.csv"
OUT_CSV = ROOT / "11_data_quality" / "qa_combined_990.csv"

REQUIRED_COLS = [
    "ID", "사건키", "사건유형", "페르소나", "난이도", "질문유형",
    "질문", "답변", "핵심키워드", "적용법령", "적용조문", "처분결과",
    "근거", "Confidence_Score", "검수자_평가", "비고", "문제점_및_해결방안",
]

SKIP_DIRS = {"_failed"}
SKIP_PREFIXES = ("v2_시범_", ".")


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ! JSON 파싱 실패 {path.name}: {e}")
        return None


def load_inventory_typemap() -> dict:
    m = {}
    if not INV_CSV.exists():
        return m
    with INV_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row.get("사건키", "").strip()
            t = row.get("추정유형", "").strip()
            if key and t:
                m[key] = t
    return m


def build_sanction_text(s: dict) -> str:
    if not s:
        return ""
    parts = []
    types = s.get("처분유형") or []
    if isinstance(types, list) and types:
        parts.append(", ".join(str(t) for t in types))
    fine_text = s.get("과징금")
    fine_amt = s.get("과징금액")
    if fine_text:
        parts.append(str(fine_text))
    elif fine_amt:
        parts.append(f"과징금 {fine_amt:,}원")
    if s.get("시정명령"):
        parts.append(f"시정명령: {s['시정명령']}")
    return " | ".join(parts)


def build_law_article(legal: dict) -> tuple[str, str]:
    if not legal:
        return "", ""
    law = (legal.get("법령") or "").strip()
    art = (legal.get("조문") or "").strip()
    if not art:
        tags = legal.get("classification_tags") or {}
        art = (tags.get("위반_조문") or "").strip()
    return law, art


CHUNK_ID_RE = re.compile(r"^(\S+_\d+)")


def build_chunk_index(evidence: dict) -> dict:
    """evidence.json 안의 모든 섹션을 훑어 chunk_id -> [근거_원문, ...] 딕셔너리 생성."""
    idx: dict[str, list[str]] = {}

    def add(cid, text):
        if not cid or cid == "매칭 불가" or not text:
            return
        text = text.strip()
        if not text:
            return
        bucket = idx.setdefault(cid, [])
        if text not in bucket:
            bucket.append(text)

    for top_key in ("facts_evidence", "legal_evidence", "sanction_evidence"):
        section = evidence.get(top_key) or {}
        if isinstance(section, dict):
            for cat_items in section.values():
                if isinstance(cat_items, list):
                    for it in cat_items:
                        if isinstance(it, dict):
                            add(it.get("chunk_id"), it.get("근거_원문"))

    ke = evidence.get("key_evidence") or {}
    if isinstance(ke, dict):
        add(ke.get("chunk_id"), ke.get("근거_원문"))

    return idx


def key_evidence_text(evidence: dict) -> str:
    ke = evidence.get("key_evidence") or {}
    if isinstance(ke, dict):
        return (ke.get("근거_원문") or "").strip()
    return ""


def facts_fallback_text(facts: dict) -> str:
    if not facts:
        return ""
    parts = []
    for k in ("summary_short", "행위", "결과"):
        v = facts.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    fs = facts.get("facts_structured") or {}
    if isinstance(fs, dict):
        for k in ("행위", "피해규모", "피해범위"):
            v = fs.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
    seen = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return " | ".join(seen)


def collect_section_texts(evidence: dict, top_key: str) -> List[str]:
    """evidence.json 의 한 최상위 섹션을 dict→list 구조로 훑어 모든 근거_원문을 dedup하여 반환."""
    out = []
    seen = set()
    sec = evidence.get(top_key) or {}
    if not isinstance(sec, dict):
        return out
    for cat_items in sec.values():
        if not isinstance(cat_items, list):
            continue
        for it in cat_items:
            if not isinstance(it, dict):
                continue
            t = (it.get("근거_원문") or "").strip()
            if not t or t.startswith("<사유"):
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
    return out


def resolve_evidence(
    rgshort: str,
    chunk_idx: dict,
    key_text: str,
    facts_fb: str,
    evidence: dict,
    qtype: str,
) -> str:
    """질문유형별로 evidence.json 섹션을 추가 결합해 풍부한 근거 텍스트 반환 (≤1500자)."""
    parts = []
    seen = set()

    def add(t):
        if not t:
            return
        t = t.strip()
        if not t or t in seen:
            return
        seen.add(t)
        parts.append(t)

    # 1. chunk_id 매칭 텍스트(들)
    cid = ""
    if rgshort:
        m = CHUNK_ID_RE.match(rgshort.strip())
        if m:
            cid = m.group(1)
    if cid and cid in chunk_idx:
        for t in chunk_idx[cid]:
            add(t)

    # 2. 질문유형별 추가 evidence
    if qtype == "제재중심":
        for t in collect_section_texts(evidence, "sanction_evidence"):
            add(t)
        add(key_text)
    elif qtype == "법령중심":
        for t in collect_section_texts(evidence, "legal_evidence"):
            add(t)
        add(key_text)
    elif qtype == "통계기반":
        for t in collect_section_texts(evidence, "facts_evidence"):
            add(t)
        for t in collect_section_texts(evidence, "sanction_evidence"):
            add(t)
    elif qtype in ("시장영향", "유사사례"):
        for t in collect_section_texts(evidence, "facts_evidence"):
            add(t)
        add(key_text)
    else:
        add(key_text)

    combined = " | ".join(parts).strip()

    # 50자 미만이면 facts_fb 보강
    if len(combined) < 50 and facts_fb:
        combined = (combined + " | " + facts_fb).strip(" |") if combined else facts_fb

    # 그래도 없으면 원문이라도 반환
    if not combined:
        combined = rgshort or ""

    # 추적성 유지를 위한 1500자 truncate
    if len(combined) > 1500:
        combined = combined[:1500]

    return combined


def build_case_type(legal: dict, folder: str, inv_map: dict) -> str:
    if legal:
        tags = legal.get("classification_tags") or {}
        t = (tags.get("사건유형_대분류") or "").strip()
        if t:
            return t
    return inv_map.get(folder, "")


def main():
    inv_map = load_inventory_typemap()
    rows = []
    case_count = 0
    missing = []
    skipped_empty = []

    folders = sorted([p for p in RAW_DIR.iterdir() if p.is_dir()])
    for folder in folders:
        name = folder.name
        if name in SKIP_DIRS or name.startswith(SKIP_PREFIXES):
            continue

        qa_path = folder / "qa_list.json"
        facts_path = folder / "facts.json"
        legal_path = folder / "legal.json"
        sanction_path = folder / "sanction.json"
        evidence_path = folder / "evidence.json"

        if not qa_path.exists():
            skipped_empty.append(name)
            continue

        qa_items = load_json(qa_path)
        if not qa_items:
            skipped_empty.append(name)
            continue

        miss_for_case = []
        if not facts_path.exists():
            miss_for_case.append("facts.json")
        if not legal_path.exists():
            miss_for_case.append("legal.json")
        if not sanction_path.exists():
            miss_for_case.append("sanction.json")
        if not evidence_path.exists():
            miss_for_case.append("evidence.json")
        if miss_for_case:
            missing.append((name, miss_for_case))

        facts = load_json(facts_path) or {}
        legal = load_json(legal_path) or {}
        sanction = load_json(sanction_path) or {}
        evidence = load_json(evidence_path) or {}

        case_type = build_case_type(legal, name, inv_map)
        law, article = build_law_article(legal)
        sanction_text = build_sanction_text(sanction)
        chunk_idx = build_chunk_index(evidence)
        ke_text = key_evidence_text(evidence)
        facts_fb = facts_fallback_text(facts)

        case_count += 1
        for i, item in enumerate(qa_items, 1):
            row_id = f"{name}_{i:03d}"
            evid_text = resolve_evidence(
                item.get("근거_short", ""), chunk_idx, ke_text, facts_fb,
                evidence, item.get("질문유형", ""),
            )
            rows.append({
                "ID": row_id,
                "사건키": name,
                "사건유형": case_type,
                "페르소나": item.get("페르소나", ""),
                "난이도": item.get("난이도", ""),
                "질문유형": item.get("질문유형", ""),
                "질문": item.get("질문", ""),
                "답변": item.get("답변", ""),
                "핵심키워드": "",
                "적용법령": law,
                "적용조문": article,
                "처분결과": sanction_text,
                "근거": evid_text,
                "Confidence_Score": "",
                "검수자_평가": "",
                "비고": "",
                "문제점_및_해결방안": "",
            })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REQUIRED_COLS)
        w.writeheader()
        w.writerows(rows)

    over_50 = sum(1 for r in rows if len(r["근거"]) >= 50)
    pct = (over_50 / len(rows) * 100) if rows else 0.0

    print(f"\n=== 변환 결과 ===")
    print(f"출력: {OUT_CSV}")
    print(f"총 QA 행수: {len(rows)}")
    print(f"사건 수: {case_count}")
    print(f"근거 50자 이상: {over_50}/{len(rows)} ({pct:.1f}%)")
    if rows:
        lengths = sorted(len(r["근거"]) for r in rows)
        print(f"근거 길이 - min:{lengths[0]} median:{lengths[len(lengths)//2]} max:{lengths[-1]}")
    print(f"빈/QA없음으로 스킵: {len(skipped_empty)}")
    for s in skipped_empty:
        print(f"  - {s}")
    if missing:
        print(f"\n부분누락 사건: {len(missing)}")
        for name, miss in missing:
            print(f"  - {name}: {', '.join(miss)}")
    else:
        print("\n부분누락 없음.")


if __name__ == "__main__":
    main()
