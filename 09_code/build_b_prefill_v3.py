"""
B 검수 prefill 3차 빌드 — 16사건 중 8사건×6건 + 2사건×1건 = 50행

기존 1·2차에서 B에게 보낸 6사건 (쿠팡·네이버·카카오엔터·엘지생건·삼성전자·홈플러스) 제외.
남은 16사건에서 사건유형 다양성 우선으로 10사건 선정 (메인 8 + extra 2).

선정 전략:
  메인 8사건 (각 6건 = 48):
    담합 ×2 (Confidence top), 하도급 ×2 (top),
    사업자단체 ×2, 부당지원 ×1, 재판매가격 ×1
  extra 2사건 (각 1건 = 2):
    가맹사업 (비에이치씨) ×1, 전자상거래 (신세계) ×1

사건당 6건 sub-selection:
  페르소나 3종 × 2건 + 난이도 3종 × 2건 = 6 (페르소나×난이도 6 슬롯 매칭).
  질문유형 5종 다양화 (slot별 미사용 qtype 우선).

출력: 05_xlsx/학습데이터_설계서_구조_v3_4_B용_3차.xlsx (시트 "법리_검수" 13컬럼)
포맷: 1·2차와 동일 (색상 tint 없음, B 입력 영역만 연노랑)
"""

from __future__ import annotations
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ============================ CONFIG ============================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR  = PROJECT_ROOT / "04_raw_outputs"
XLSX_OUT = PROJECT_ROOT / "05_xlsx" / "학습데이터_설계서_구조_v3_4_B용_3차.xlsx"

# 1·2차에서 이미 B에게 보낸 6사건 — 키워드 매칭으로 제외
EXCLUDED_KEYWORDS = ["쿠팡", "네이버", "카카오엔터", "엘지생활건강", "삼성전자", "홈플러스"]

# 사건키워드 → 약어 (build_b_prefill_v2.py 와 동일)
ALIASES = {
    "쿠팡":            "쿠팡",
    "네이버":          "네이버",
    "남양유업":        "남양유업",
    "삼성전자":        "삼성전자",
    "신세계":          "신세계",
    "에스피피조선":    "에스피피조선",
    "새마을금고":      "새마을금고",
    "조달청":          "조달청",
    "경상북도교육청":   "경북교육청",
    "글락소":          "글락소",
    "평화이엔지":      "평화이엔지",
    "케이티디에스":    "케이티디에스",
    "동원건설":        "동원건설",
    "홈플러스":        "홈플러스",
    "카카오엔터":      "카카오엔터",
    "경상북도개인택시": "경북택시",
    "한국과수종묘":    "과수종묘",
    "엘지생활건강":    "엘지생건",
    "비에이치씨":      "비에이치씨",
    "금호아시아나":    "금호아시아나",
    "아모레퍼시픽":    "아모레",
    "롯데쇼핑":        "롯데쇼핑",
}

# Confidence Score 가중치 (build_b_prefill_v2.py 와 동일)
WHITELIST = ["공정거래법", "표시광고법", "전자상거래법", "약관법", "약관규제법",
             "하도급법", "가맹사업법", "대규모유통업법", "대리점법"]
ACADEMIC_TERMS = ["사안", "당해", "유의미", "함의", "본고", "고찰", "전제로",
                  "기인", "내재", "포섭", "수반", "기제", "패러다임", "프레임워크", "메커니즘"]

# 메인 8사건 — 사건유형별 픽 수 (Confidence Score top 순)
MAIN_PICKS = {
    "담합":      2,
    "하도급":     2,
    "사업자단체":  2,
    "부당지원":   1,
    "재판매가격":  1,
}
ITEMS_PER_MAIN = 6

# extra 2사건 — 사건키워드 직접 지정 (도메인 중복이지만 다양성 보강)
EXTRA_KEYWORDS = ["비에이치씨", "신세계"]
ITEMS_PER_EXTRA = 1

# 사건당 6건 sub-selection — (페르소나, 난이도) 6 슬롯
SUB_SLOTS = [
    ("일반국민",                "기초"),
    ("일반국민",                "심화"),
    ("기업 컴플라이언스 담당자", "기초"),
    ("기업 컴플라이언스 담당자", "전문가"),
    ("논문 준비 학생",          "심화"),
    ("논문 준비 학생",          "전문가"),
]


# ============================ Confidence Score (v2 동일) ============================
def walk_get(d, key):
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = walk_get(v, key)
            if r is not None:
                return r
    return None


def is_filled(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip()
        return s != "" and s not in ("정보 없음", "값 없음", "null")
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def confidence_score(facts: dict, legal: dict) -> float:
    law = walk_get(legal, "법령") or ""
    s_law = 1.0 if any(w in str(law) for w in WHITELIST) else 0.0
    required = [
        walk_get(facts, "summary_short"),
        walk_get(facts, "facts_structured"),
        walk_get(legal, "classification_tags"),
        walk_get(legal, "inference_chain"),
    ]
    s_evi = sum(1 for v in required if is_filled(v)) / len(required)
    five = ["주체", "상대방", "시장", "행위", "결과"]
    s_5e = sum(1 for k in five if is_filled(walk_get(facts, k))) / len(five)
    summary = str(walk_get(facts, "summary_short") or "")
    s_tone = 0.0 if any(t in summary for t in ACADEMIC_TERMS) else 1.0
    return s_law * 0.4 + s_evi * 0.3 + s_5e * 0.2 + s_tone * 0.1


# ============================ DATA LOAD ============================
def find_alias(case_name: str) -> str | None:
    for kw, alias in ALIASES.items():
        if kw in case_name:
            return alias
    return None


def load_all_cases() -> list[dict]:
    """22사건 전체 로드 + Confidence Score + classification_tags.사건유형_대분류 추출."""
    cases = []
    for d in sorted(RAW_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("v2_"):
            continue
        if not (d / "qa_list.json").exists():
            continue
        alias = find_alias(d.name)
        if alias is None:
            print(f"  [WARN] 약어 매핑 없음: {d.name}")
            continue
        qa_raw = json.loads((d / "qa_list.json").read_text(encoding="utf-8"))
        items = qa_raw if isinstance(qa_raw, list) else (qa_raw.get("qa_list") or [])
        facts = json.loads((d / "facts.json").read_text(encoding="utf-8"))
        legal = json.loads((d / "legal.json").read_text(encoding="utf-8"))
        tags = legal.get("classification_tags") if isinstance(legal.get("classification_tags"), dict) else {}
        case_type = (tags.get("사건유형_대분류") or "").strip()
        cases.append({
            "name":      d.name,
            "alias":     alias,
            "items":     items,
            "case_type": case_type,
            "법령":       (legal.get("법령") or "").strip(),
            "조문":       (legal.get("조문") or "").strip(),
            "판단요건":    legal.get("판단요건") if isinstance(legal.get("판단요건"), list) else [],
            "inference_chain": legal.get("inference_chain") if isinstance(legal.get("inference_chain"), list) else [],
            "score":     confidence_score(facts, legal),
        })
    return cases


# ============================ 선정 알고리즘 ============================
def filter_excluded(cases: list[dict]) -> list[dict]:
    return [c for c in cases if not any(ex in c["name"] for ex in EXCLUDED_KEYWORDS)]


def select_main_cases(cases: list[dict]) -> list[dict]:
    """MAIN_PICKS 정의대로 사건유형별 top score N개씩 선정."""
    by_type: dict[str, list[dict]] = {}
    for c in cases:
        by_type.setdefault(c["case_type"], []).append(c)
    picked = []
    for ct, n in MAIN_PICKS.items():
        cands = sorted(by_type.get(ct, []), key=lambda c: c["score"], reverse=True)
        if len(cands) < n:
            print(f"  [WARN] {ct}: 후보 {len(cands)}건 < 요구 {n}건")
        picked.extend(cands[:n])
    return picked


def select_extra_cases(cases: list[dict], used_aliases: set[str]) -> list[dict]:
    """EXTRA_KEYWORDS 순서로 매칭, 이미 메인에 들어간 사건 중복 회피."""
    extras = []
    for kw in EXTRA_KEYWORDS:
        for c in cases:
            if kw in c["name"] and c["alias"] not in used_aliases:
                extras.append(c)
                used_aliases.add(c["alias"])
                break
        else:
            print(f"  [WARN] extra 키워드 '{kw}' 매칭 사건 없음")
    return extras


def pick_qa_items(case: dict, n_items: int) -> list[tuple[int, dict]]:
    """사건의 qa_list 에서 n_items 선택.

    n_items == 1: 첫 항목
    n_items > 1 : SUB_SLOTS 6개 슬롯 매칭. 각 슬롯에서 미사용 질문유형 우선.
                  슬롯 매칭 실패 시 남은 항목으로 채움.
    """
    items = case["items"]
    if not items:
        return []
    if n_items == 1:
        return [(1, items[0])]

    selected: list[tuple[int, dict]] = []
    used_indices: set[int] = set()
    used_qtypes: list[str] = []

    for persona, level in SUB_SLOTS:
        cands = [
            (i, qa) for i, qa in enumerate(items, 1)
            if i not in used_indices
            and qa.get("페르소나") == persona
            and qa.get("난이도") == level
        ]
        if not cands:
            continue
        # 미사용 질문유형 우선 — used_qtypes 빈도 낮은 순
        cands.sort(key=lambda x: used_qtypes.count(x[1].get("질문유형", "")))
        idx, qa = cands[0]
        selected.append((idx, qa))
        used_indices.add(idx)
        used_qtypes.append(qa.get("질문유형", ""))

    # 6건 미달 시 남은 항목으로 채움
    if len(selected) < n_items:
        for i, qa in enumerate(items, 1):
            if i not in used_indices:
                selected.append((i, qa))
                used_indices.add(i)
                if len(selected) >= n_items:
                    break

    return selected[:n_items]


# ============================ 셀 포맷팅 ============================
def format_판단요건(items) -> str:
    if not isinstance(items, list) or not items:
        return ""
    return "\n".join(f"{i}. {x}" for i, x in enumerate(items, 1) if isinstance(x, str) and x.strip())


def format_inference_chain(items) -> str:
    """[1단계] 법령확인: ... / 사실인정: ...
       [2단계] ..."""
    if not isinstance(items, list) or not items:
        return ""
    parts = []
    for d in items:
        if not isinstance(d, dict):
            continue
        step = d.get("단계") or d.get("step") or ""
        body_parts = []
        for k, v in d.items():
            if k in ("단계", "step"):
                continue
            if isinstance(v, str) and v.strip():
                body_parts.append(f"{k}: {v}")
            elif isinstance(v, list) and v:
                body_parts.append(f"{k}: {', '.join(str(x) for x in v)}")
        body = " / ".join(body_parts)
        parts.append(f"[{step}단계] {body}" if step != "" else body)
    return "\n".join(parts)


# ============================ 출력 빌드 ============================
HEADERS = [
    "QA_ID", "페르소나", "사건유형", "적용 법령", "적용 조문",
    "질문", "답변",
    "판단 요건", "본건 적용 이유", "검수자 평가", "보정안", "신뢰도", "메모",
]

HEADER_FILL = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")
HEADER_FONT = Font(name="맑은 고딕", size=10, bold=True, color="000000")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
DATA_FONT = Font(name="맑은 고딕", size=10)
DATA_ALIGN = Alignment(vertical="top", wrap_text=True)
B_AREA_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # J~M (검수자 입력)

THIN_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)

COL_WIDTHS = {1: 18, 2: 22, 3: 12, 4: 14, 5: 22, 6: 50, 7: 60, 8: 35, 9: 40, 10: 14, 11: 35, 12: 10, 13: 25}


def build_row(case: dict, qa_idx: int, qa: dict) -> list:
    qa_id = f"QA-{case['alias']}-{qa_idx:03d}"
    return [
        qa_id,
        qa.get("페르소나", ""),
        case["case_type"],
        case["법령"],
        case["조문"],
        qa.get("질문", ""),
        qa.get("답변", ""),
        format_판단요건(case["판단요건"]),
        format_inference_chain(case["inference_chain"]),
        "", "", "", "",  # J~M: 검수자 입력 (빈칸)
    ]


def main():
    print("=" * 70)
    print("B prefill 3차 빌드 — 50건 (8사건×6 + 2사건×1)")
    print("=" * 70)

    all_cases = load_all_cases()
    print(f"\n[1] 22사건 전체 로드: {len(all_cases)}")

    cases16 = filter_excluded(all_cases)
    print(f"\n[2] 6사건 제외 후: {len(cases16)} (제외 키워드: {EXCLUDED_KEYWORDS})")
    if len(cases16) != 16:
        print(f"  [WARN] 16건 예상, 실제 {len(cases16)}건")

    main_cases = select_main_cases(cases16)
    used_aliases = {c["alias"] for c in main_cases}
    extra_cases = select_extra_cases(cases16, used_aliases)
    print(f"\n[3] 메인 8사건 + extra 2사건 = {len(main_cases) + len(extra_cases)}사건 선정")
    print(f"  메인 (사건당 {ITEMS_PER_MAIN}건):")
    for c in main_cases:
        print(f"    [{c['case_type']:8s}] score={c['score']:.3f}  {c['alias']:14s}  {c['name'][:35]}")
    print(f"  extra (사건당 {ITEMS_PER_EXTRA}건):")
    for c in extra_cases:
        print(f"    [{c['case_type']:8s}] score={c['score']:.3f}  {c['alias']:14s}  {c['name'][:35]}")

    # 행 빌드
    rows: list[list] = []
    for c in main_cases:
        picks = pick_qa_items(c, ITEMS_PER_MAIN)
        if len(picks) < ITEMS_PER_MAIN:
            print(f"  [WARN] {c['alias']}: {len(picks)}건만 선택됨 (목표 {ITEMS_PER_MAIN})")
        for idx, qa in picks:
            rows.append(build_row(c, idx, qa))
    for c in extra_cases:
        picks = pick_qa_items(c, ITEMS_PER_EXTRA)
        for idx, qa in picks:
            rows.append(build_row(c, idx, qa))
    print(f"\n[4] 총 {len(rows)}행 빌드 (목표 50)")

    # 워크북 생성
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("법리_검수")

    for c_idx, h in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[cell.column_letter].width = COL_WIDTHS.get(c_idx, 15)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"

    for r_offset, row in enumerate(rows):
        r_idx = 2 + r_offset
        for c_idx, val in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = DATA_FONT
            cell.alignment = DATA_ALIGN
            cell.border = THIN_BORDER
            # J~M (10~13) 빈칸 → B 입력 영역 연노랑
            if c_idx >= 10 and (val is None or val == ""):
                cell.fill = B_AREA_FILL
        ws.row_dimensions[r_idx].height = 80  # 판단요건/inference_chain wrap 고려

    XLSX_OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(XLSX_OUT)
    print(f"\n[5] 저장: {XLSX_OUT.relative_to(PROJECT_ROOT)}")

    # 검증
    print()
    print("=" * 70)
    print("검증")
    print("=" * 70)
    from collections import Counter
    case_count = Counter()
    persona_count = Counter()
    level_count = Counter()
    qtype_count = Counter()
    for r in rows:
        qa_id = r[0]
        if qa_id.startswith("QA-"):
            parts = qa_id.split("-")
            if len(parts) >= 3:
                case_count[parts[1]] += 1
        persona_count[r[1]] += 1

    # 메타 카운트는 picks 다시 계산하지 않고 row 자체에서
    for c in main_cases:
        for idx, qa in pick_qa_items(c, ITEMS_PER_MAIN):
            level_count[qa.get("난이도", "")] += 1
            qtype_count[qa.get("질문유형", "")] += 1

    print(f"\n  총 행: {len(rows)} (목표 50) {'OK' if len(rows) == 50 else 'FAIL'}")

    print(f"\n  [사건별 행 수]")
    for alias, n in sorted(case_count.items(), key=lambda x: -x[1]):
        expect = ITEMS_PER_MAIN if any(c["alias"] == alias for c in main_cases) else ITEMS_PER_EXTRA
        marker = "OK" if n == expect else "FAIL"
        print(f"    {marker:4s} {alias:14s}: {n} (목표 {expect})")

    print(f"\n  [페르소나 분포 — 50행 전체]")
    for p, n in persona_count.most_common():
        print(f"    {p:30s}: {n}")

    print(f"\n  [난이도 분포 — 메인 48건만]")
    for lv, n in level_count.most_common():
        print(f"    {lv:6s}: {n}")
    print(f"    (목표: 사건당 기초/심화/전문가 2건씩 = 8사건×2 = 각 16)")

    print(f"\n  [질문유형 분포 — 메인 48건만]")
    for qt, n in qtype_count.most_common():
        print(f"    {qt:8s}: {n}")


if __name__ == "__main__":
    main()
