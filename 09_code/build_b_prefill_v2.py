"""
B 검수 prefill 2차 빌드 — 22사건 × 1건 + 기존 8건 = 30행

분포 강제:
  페르소나: 일반국민 8 + 기업 컴플라이언스 담당자 8 + 논문 준비 학생 6
  난이도: 기초 8 + 심화 8 + 전문가 6 (사용자 라벨 "기초/중급/심화"에 매핑)
  질문유형: 5종 × 4-5
  색상: GREEN 8 + YELLOW 8 + RED 6 (Confidence Score 기준)

출력: 05_xlsx/학습데이터_설계서_구조_v3.4_B용_2차.xlsx (시트 "법리_검수" 13컬럼)
"""

from __future__ import annotations
import json
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR  = PROJECT_ROOT / "04_raw_outputs"
XLSX_IN  = PROJECT_ROOT / "05_xlsx" / "학습데이터_설계서_구조_v3.4.xlsx"
XLSX_OUT = PROJECT_ROOT / "05_xlsx" / "학습데이터_설계서_구조_v3.4_B용_2차.xlsx"
LOCKED_CSV = PROJECT_ROOT / "01_data_inventory" / "22_LOCKED_v1.csv"

# 사건키워드 → 약어
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

# Confidence Score 가중치 (05_confidence/confidence_score_v1.py 와 동일)
WHITELIST = ["공정거래법", "표시광고법", "전자상거래법", "약관법", "약관규제법", "하도급법", "가맹사업법", "대규모유통업법", "대리점법"]
ACADEMIC_TERMS = ["사안","당해","유의미","함의","본고","고찰","전제로","기인","내재","포섭","수반","기제","패러다임","프레임워크","메커니즘"]

# 22 (persona, level, qtype) 타겟 분포 — 페르소나 8/8/6, 난이도 8/8/6, 질문유형 ~4-5
# 페르소나·난이도 cell 채움:
#   기초 심화 전문가
# 일반  3   3   2  = 8
# 기업  3   3   2  = 8
# 논문  2   2   2  = 6
TARGETS = [
    # 일반·기초 (3)
    ("일반국민",                "기초",   "제재중심"),
    ("일반국민",                "기초",   "법령중심"),
    ("일반국민",                "기초",   "유사사례"),
    # 일반·심화 (3)
    ("일반국민",                "심화",   "통계기반"),
    ("일반국민",                "심화",   "시장영향"),
    ("일반국민",                "심화",   "제재중심"),
    # 일반·전문가 (2)
    ("일반국민",                "전문가", "법령중심"),
    ("일반국민",                "전문가", "유사사례"),
    # 기업·기초 (3)
    ("기업 컴플라이언스 담당자", "기초",   "통계기반"),
    ("기업 컴플라이언스 담당자", "기초",   "시장영향"),
    ("기업 컴플라이언스 담당자", "기초",   "제재중심"),
    # 기업·심화 (3)
    ("기업 컴플라이언스 담당자", "심화",   "법령중심"),
    ("기업 컴플라이언스 담당자", "심화",   "유사사례"),
    ("기업 컴플라이언스 담당자", "심화",   "통계기반"),
    # 기업·전문가 (2)
    ("기업 컴플라이언스 담당자", "전문가", "시장영향"),
    ("기업 컴플라이언스 담당자", "전문가", "제재중심"),
    # 논문·기초 (2)
    ("논문 준비 학생",          "기초",   "법령중심"),
    ("논문 준비 학생",          "기초",   "유사사례"),
    # 논문·심화 (2)
    ("논문 준비 학생",          "심화",   "통계기반"),
    ("논문 준비 학생",          "심화",   "시장영향"),
    # 논문·전문가 (2)
    ("논문 준비 학생",          "전문가", "제재중심"),
    ("논문 준비 학생",          "전문가", "법령중심"),
]


# ============================ Confidence Score ============================
def walk_get(d, key):
    if isinstance(d, dict):
        if key in d: return d[key]
        for v in d.values():
            r = walk_get(v, key)
            if r is not None: return r
    return None


def is_filled(v) -> bool:
    if v is None: return False
    if isinstance(v, str):
        s = v.strip()
        return s != "" and s not in ("정보 없음", "값 없음", "null")
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def confidence_score(facts: dict, legal: dict) -> tuple[float, dict]:
    # 0.4 법조문 매칭 (화이트리스트)
    law = (walk_get(legal, "법령") or "")
    s_law = 1.0 if any(w in str(law) for w in WHITELIST) else 0.0
    # 0.3 근거 정합성: 필수 필드 채움 ratio
    required = [
        ("facts.summary_short",    walk_get(facts, "summary_short")),
        ("facts.facts_structured", walk_get(facts, "facts_structured")),
        ("legal.classification_tags", walk_get(legal, "classification_tags")),
        ("legal.inference_chain",     walk_get(legal, "inference_chain")),
    ]
    filled = sum(1 for _, v in required if is_filled(v))
    s_evi = filled / len(required)
    # 0.2 5요소 완전성
    five = ["주체","상대방","시장","행위","결과"]
    s_5e = sum(1 for k in five if is_filled(walk_get(facts, k))) / len(five)
    # 0.1 페르소나 톤: summary_short에 학술용어 없음
    summary = str(walk_get(facts, "summary_short") or "")
    s_tone = 0.0 if any(t in summary for t in ACADEMIC_TERMS) else 1.0
    score = s_law * 0.4 + s_evi * 0.3 + s_5e * 0.2 + s_tone * 0.1
    return score, {"law": s_law, "evi": s_evi, "5e": s_5e, "tone": s_tone}


# ============================ 데이터 적재 ============================
def find_alias(case_name: str) -> str | None:
    for kw, alias in ALIASES.items():
        if kw in case_name:
            return alias
    return None


def load_all_cases() -> list[dict]:
    """22사건 + qa_list + facts + legal 적재 + Confidence Score."""
    cases = []
    for d in sorted(RAW_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        if not (d / "qa_list.json").exists():
            continue
        case_name = d.name
        alias = find_alias(case_name)
        if alias is None:
            print(f"  [WARN] 약어 매핑 없음: {case_name}")
            continue
        qa = json.loads((d / "qa_list.json").read_text(encoding="utf-8"))
        items = qa if isinstance(qa, list) else (qa.get("qa_list") or [])
        facts = json.loads((d / "facts.json").read_text(encoding="utf-8"))
        legal = json.loads((d / "legal.json").read_text(encoding="utf-8"))

        # 사건유형 (피해범위 [태그] 추출)
        scope = walk_get(facts, "피해범위") or ""
        m = re.search(r"\[([^\]]+)\]\s*$", scope) if isinstance(scope, str) else None
        case_type = m.group(1).strip() if m else ""

        score, breakdown = confidence_score(facts, legal)
        cases.append({
            "name":  case_name,
            "alias": alias,
            "items": items,
            "case_type": case_type,
            "법령": walk_get(legal, "법령") or "",
            "조문": walk_get(legal, "조문") or "",
            "score": score,
            "breakdown": breakdown,
        })
    return cases


# ============================ 22 선정 알고리즘 ============================
def assign_targets(cases: list[dict]) -> list[dict]:
    """22사건에 (persona, level, qtype) 타겟 할당.

    - 사건들을 Confidence Score 내림차순 정렬
    - 색상: 상위 8 GREEN / 중간 8 YELLOW / 하위 6 RED
    - 22 타겟 튜플을 사건에 round-robin 배정
    - 각 사건의 qa_list에서 타겟 매치 Q&A 1건 선택
    """
    assert len(cases) == 22, f"22사건이어야 함, 현재 {len(cases)}"
    assert len(TARGETS) == 22, f"타겟 22개여야 함, 현재 {len(TARGETS)}"

    sorted_cases = sorted(cases, key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(sorted_cases):
        if   i < 8:  c["color"] = "GREEN"
        elif i < 16: c["color"] = "YELLOW"
        else:        c["color"] = "RED"

    # 타겟 배정: 사건 순서대로 TARGETS[i] 할당
    for i, c in enumerate(sorted_cases):
        c["target"] = TARGETS[i]

        # 매치 Q&A 찾기
        target_persona, target_level, target_qtype = c["target"]
        matched = None
        for idx, item in enumerate(c["items"], start=1):
            if (item.get("페르소나") == target_persona
                    and item.get("난이도") == target_level
                    and item.get("질문유형") == target_qtype):
                matched = (idx, item)
                break
        if matched is None:
            print(f"  [WARN] {c['alias']}: target {c['target']} 매치 실패")
            # fallback: 첫 번째 item
            matched = (1, c["items"][0])
        c["qa_idx"], c["qa_item"] = matched

    return sorted_cases


# ============================ 기존 8건 로드 ============================
def load_existing_b_rows() -> list[list]:
    """학습데이터_설계서_구조_v3.4.xlsx 법리_검수 시트의 2~9행 로드 (13컬럼)."""
    wb = load_workbook(XLSX_IN)
    ws = wb["법리_검수"]
    rows = []
    for row in ws.iter_rows(min_row=2, max_row=9, max_col=13, values_only=True):
        rows.append(list(row))
    return rows


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
B_AREA_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # H~M

ROW_TINT = {
    "GREEN":  PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid"),
    "YELLOW": PatternFill(start_color="FFF9C4", end_color="FFF9C4", fill_type="solid"),
    "RED":    PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid"),
}

THIN_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)

COL_WIDTHS = {1:16, 2:22, 3:12, 4:14, 5:22, 6:50, 7:60, 8:35, 9:35, 10:14, 11:35, 12:10, 13:25}


def build_row(qa_id, persona, case_type, law, article, question, answer):
    """A~G prefill, H~M 빈."""
    return [qa_id, persona, case_type, law, article, question, answer, "", "", "", "", "", ""]


def main():
    print("=" * 70)
    print("B prefill 2차 빌드")
    print("=" * 70)

    cases = load_all_cases()
    print(f"\n[1] 22사건 적재: {len(cases)}")

    sorted_cases = assign_targets(cases)
    print(f"\n[2] Confidence + 타겟 할당 완료")
    for c in sorted_cases:
        print(f"  {c['color']:6s} {c['score']:.3f}  {c['alias']:14s}  → {c['target'][0][:8]:8s} / {c['target'][1]:5s} / {c['target'][2]:6s}  (qa_idx={c['qa_idx']})")

    existing = load_existing_b_rows()
    print(f"\n[3] 기존 8행 로드: {len(existing)}")

    # 신규 22행 빌드 — RED 우선 → YELLOW → GREEN
    color_order = {"RED": 0, "YELLOW": 1, "GREEN": 2}
    sorted_for_output = sorted(sorted_cases, key=lambda c: (color_order[c["color"]], -c["score"]))

    new_rows = []
    for c in sorted_for_output:
        item = c["qa_item"]
        qa_id = f"QA-{c['alias']}-{c['qa_idx']:03d}"
        new_rows.append((c, build_row(
            qa_id,
            item.get("페르소나", ""),
            c["case_type"],
            c["법령"],
            c["조문"],
            item.get("질문", ""),
            item.get("답변", ""),
        )))

    print(f"\n[4] 신규 22행 빌드 완료")

    # === 워크북 생성 ===
    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("법리_검수")

    # 헤더
    for c_idx, h in enumerate(HEADERS, start=1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[cell.column_letter].width = COL_WIDTHS.get(c_idx, 15)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"

    # 행 2~9: 기존 8건 (보존)
    for r_offset, ex_row in enumerate(existing):
        r_idx = 2 + r_offset
        for c_idx, val in enumerate(ex_row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = DATA_FONT
            cell.alignment = DATA_ALIGN
            cell.border = THIN_BORDER
            if c_idx >= 8 and (val is None or val == ""):  # H~M 빈칸 → 연노랑
                cell.fill = B_AREA_FILL
        ws.row_dimensions[r_idx].height = 50

    # 행 10~31: 신규 22건 (RED → YELLOW → GREEN, 색 tint)
    for r_offset, (case, row) in enumerate(new_rows):
        r_idx = 10 + r_offset
        tint = ROW_TINT[case["color"]]
        for c_idx, val in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = DATA_FONT
            cell.alignment = DATA_ALIGN
            cell.border = THIN_BORDER
            if c_idx >= 8 and (val is None or val == ""):
                cell.fill = B_AREA_FILL  # H~M 빈칸 연노랑
            else:
                cell.fill = tint  # A~G 사건 색상 tint
        ws.row_dimensions[r_idx].height = 50

    XLSX_OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(XLSX_OUT)
    print(f"\n[5] 저장: {XLSX_OUT.relative_to(PROJECT_ROOT)}")

    # === 검증 ===
    print()
    print("=" * 70)
    print("검증")
    print("=" * 70)
    wb2 = load_workbook(XLSX_OUT, read_only=True)
    ws2 = wb2["법리_검수"]
    total_rows = ws2.max_row - 1  # exclude header
    print(f"  총 행: {total_rows} (예상 30)  {'✅' if total_rows == 30 else '❌'}")

    # 사건별 분배
    from collections import Counter
    case_alias_count = Counter()
    persona_count = Counter()
    level_count = Counter()
    qtype_count = Counter()
    for row in ws2.iter_rows(min_row=2, values_only=True):
        qa_id = row[0]
        persona = row[1]
        if qa_id and qa_id.startswith("QA-"):
            parts = qa_id.split("-")
            if len(parts) >= 3:
                case_alias_count[parts[1]] += 1
        if persona: persona_count[persona] += 1

    # qtype·level은 신규 22건에서만 (기존 8건은 답변·질문 가지지만 메타정보 없음)
    for c, _ in new_rows:
        item = c["qa_item"]
        level_count[item.get("난이도","")] += 1
        qtype_count[item.get("질문유형","")] += 1

    print(f"\n  [사건별 행 수]")
    for alias, n in sorted(case_alias_count.items(), key=lambda x: -x[1]):
        marker = "✅" if (alias in ("쿠팡","네이버") and n == 5) or (alias not in ("쿠팡","네이버") and n == 1) else "❌"
        print(f"    {marker} {alias:15s}: {n}")

    print(f"\n  [페르소나 분포 — 30행 전체]")
    for p, n in persona_count.most_common():
        print(f"    {p:30s}: {n}")
    print(f"    (신규 22건만의 분포 목표: 일반 8 + 기업 8 + 논문 6)")

    print(f"\n  [난이도 분포 — 신규 22건만]")
    for lv, n in level_count.most_common():
        print(f"    {lv:6s}: {n}")
    print(f"    (목표: 기초 8 + 심화 8 + 전문가 6)")

    print(f"\n  [질문유형 분포 — 신규 22건만]")
    for qt, n in qtype_count.most_common():
        print(f"    {qt:8s}: {n}")
    print(f"    (목표: 5종 × 4-5)")

    print(f"\n  [색상 분포]")
    color_count = Counter(c["color"] for c in sorted_cases)
    for col, n in color_count.items():
        print(f"    {col:6s}: {n}")
    print(f"    (목표: GREEN 8 + YELLOW 8 + RED 6)")


if __name__ == "__main__":
    main()
