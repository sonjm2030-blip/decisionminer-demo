"""
Confidence Score v1
- 가중치(잠금 #3): 법조문 0.4 / 근거 정합성 0.3 / 5요소 0.2 / 페르소나 톤 0.1
- 임계값: GREEN >= 0.85, YELLOW >= 0.7, RED < 0.7
"""

import csv
import json
from pathlib import Path

WEIGHTS = {
    "law_match": 0.40,
    "evidence_consistency": 0.30,
    "five_elements": 0.20,
    "persona_tone": 0.10,
}

THRESHOLD_GREEN = 0.85
THRESHOLD_YELLOW = 0.70

APPLIED_LAW_WHITELIST = [
    "공정거래법",
    "표시광고법",
    "전자상거래법",
    "약관법",
    "하도급법",
    "가맹사업법",
    "대리점법",
]

REQUIRED_FACTS_FIELDS = [
    "주체", "상대방", "시장", "행위", "결과",
    "summary_short", "facts_structured",
]
REQUIRED_FACTS_STRUCTURED_FIELDS = [
    "당사자", "기간", "행위", "피해규모", "피해범위",
]
REQUIRED_LEGAL_FIELDS = [
    "법령", "조문", "위반유형", "판단요건",
    "classification_tags", "inference_chain",
]
REQUIRED_TAG_FIELDS = [
    "사건유형_대분류", "사건유형_세분류",
    "위반_조문", "처분_유형", "산업분야",
]

FIVE_ELEMENTS = ["주체", "상대방", "시장", "행위", "결과"]

ACADEMIC_TERMS = [
    "사안", "당해", "유의미", "함의", "본고", "본 연구", "고찰",
    "전제로", "기인", "내재", "포섭", "도출", "수반", "기제",
    "패러다임", "프레임워크", "메커니즘", "거버넌스", "스탠스",
    "본 사건은", "본 건은", "상기", "전술한", "후술",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_OUTPUTS_DIR = PROJECT_ROOT / "04_raw_outputs"
OUTPUT_CSV = PROJECT_ROOT / "05_confidence" / "confidence_v1.csv"


def is_filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        v = value.strip()
        return v != "" and v != "정보 없음"
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def score_law_match(legal: dict) -> float:
    """법조문 매칭: 화이트리스트 7종 매칭 시 1.0"""
    if not isinstance(legal, dict):
        return 0.0
    candidates = []
    candidates.append(str(legal.get("법령", "")))
    tags = legal.get("classification_tags", {}) or {}
    candidates.append(str(tags.get("위반_조문", "")))
    haystack = " ".join(candidates)
    for law in APPLIED_LAW_WHITELIST:
        if law in haystack:
            return 1.0
    return 0.0


def score_evidence_consistency(facts: dict, legal: dict) -> float:
    """근거 정합성: facts + legal 필수 필드 완전성"""
    total = 0
    filled = 0

    for f in REQUIRED_FACTS_FIELDS:
        total += 1
        if is_filled(facts.get(f)):
            filled += 1

    facts_structured = facts.get("facts_structured", {}) or {}
    for f in REQUIRED_FACTS_STRUCTURED_FIELDS:
        total += 1
        if is_filled(facts_structured.get(f)):
            filled += 1

    for f in REQUIRED_LEGAL_FIELDS:
        total += 1
        if is_filled(legal.get(f)):
            filled += 1

    tags = legal.get("classification_tags", {}) or {}
    for f in REQUIRED_TAG_FIELDS:
        total += 1
        if is_filled(tags.get(f)):
            filled += 1

    return filled / total if total else 0.0


def score_five_elements(facts: dict) -> float:
    """5요소 완전성: 주체·상대방·시장·행위·결과 모두 '정보 없음' 아닐 때 1.0"""
    if not isinstance(facts, dict):
        return 0.0
    filled = sum(1 for k in FIVE_ELEMENTS if is_filled(facts.get(k)))
    return filled / len(FIVE_ELEMENTS)


def score_persona_tone(facts: dict) -> float:
    """페르소나 톤: summary_short에 학술용어 없으면 1.0"""
    summary = str(facts.get("summary_short", "") or "")
    if not summary.strip():
        return 0.0
    for term in ACADEMIC_TERMS:
        if term in summary:
            return 0.0
    return 1.0


def classify(score: float) -> str:
    if score >= THRESHOLD_GREEN:
        return "GREEN"
    if score >= THRESHOLD_YELLOW:
        return "YELLOW"
    return "RED"


def evaluate(json_path: Path) -> dict:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    facts = data.get("facts", {}) or {}
    legal = data.get("legal", {}) or {}

    s_law = score_law_match(legal)
    s_evi = score_evidence_consistency(facts, legal)
    s_five = score_five_elements(facts)
    s_tone = score_persona_tone(facts)

    total = (
        s_law * WEIGHTS["law_match"]
        + s_evi * WEIGHTS["evidence_consistency"]
        + s_five * WEIGHTS["five_elements"]
        + s_tone * WEIGHTS["persona_tone"]
    )

    return {
        "case_id": json_path.parent.name,
        "path": str(json_path.relative_to(PROJECT_ROOT)),
        "law_match": round(s_law, 4),
        "evidence_consistency": round(s_evi, 4),
        "five_elements": round(s_five, 4),
        "persona_tone": round(s_tone, 4),
        "total": round(total, 4),
        "grade": classify(total),
    }


def main():
    targets = sorted(RAW_OUTPUTS_DIR.glob("*/step1_step2.json"))
    if not targets:
        print(f"[!] step1_step2.json 파일을 찾지 못했습니다: {RAW_OUTPUTS_DIR}")
        return

    results = [evaluate(p) for p in targets]

    print("=" * 80)
    print(f"Confidence Score v1  |  대상 {len(results)}건")
    print("=" * 80)
    for r in results:
        print(
            f"[{r['grade']:6s}] {r['case_id']:30s}  total={r['total']:.4f}  "
            f"(법조문={r['law_match']:.2f} 정합성={r['evidence_consistency']:.2f} "
            f"5요소={r['five_elements']:.2f} 톤={r['persona_tone']:.2f})"
        )
    counts = {"GREEN": 0, "YELLOW": 0, "RED": 0}
    for r in results:
        counts[r["grade"]] += 1
    print("-" * 80)
    print(f"GREEN={counts['GREEN']}  YELLOW={counts['YELLOW']}  RED={counts['RED']}")

    fieldnames = [
        "case_id", "path",
        "law_match", "evidence_consistency", "five_elements", "persona_tone",
        "total", "grade",
    ]
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(f"\nCSV 저장: {OUTPUT_CSV.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
