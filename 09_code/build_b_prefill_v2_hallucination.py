"""
B prefill 2차 — 환각 우선 6사건 × 5건 = 30건 재추출.

대상 6사건 + 분량:
  쿠팡        5건 (기존 4 + 신규 1)
  네이버      5건 (기존 4 + 신규 1)
  카카오엔터  5건 (전부 신규)
  엘지생건    5건 (전부 신규, "독점금지법" 환각 2건 우선 포함)
  삼성전자    5건 (전부 신규)
  홈플러스    5건 (전부 신규)
  ─────────────
  합          30건 (기존 8 + 신규 22)

사건당 5건 페르소나·난이도 균등:
  페르소나: 일반국민 2 + 기업 컴플라이언스 담당자 2 + 논문 준비 학생 1
  난이도:   기초 2 + 심화 2 + 전문가 1
  질문유형: 5종 균등 (각 1건)

환각 우선 규칙:
  엘지생건       — 답변 내 "독점금지법" 매칭 2건 반드시 포함
  카카오/네이버  — 답변 내 "광고법" 약칭 (표시광고법 제외) 우선
  쿠팡/삼성/홈플 — 답변 내 잡법령 (whitelist 7종 외) 우선

출력: 05_xlsx/학습데이터_설계서_구조_v3.4_B용_2차_사건그룹.xlsx
백업: 직전 _2차_사건별.xlsx → _2차_사건별_22사건균등.xlsx
"""

from __future__ import annotations
import csv
import json
import re
import shutil
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


PROJECT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT / "04_raw_outputs"
SRC = PROJECT / "05_xlsx" / "학습데이터_설계서_구조_v3.4_B용_2차_사건별.xlsx"
BAK = PROJECT / "05_xlsx" / "학습데이터_설계서_구조_v3.4_B용_2차_사건별_22사건균등.xlsx"
OUT = PROJECT / "05_xlsx" / "학습데이터_설계서_구조_v3.4_B용_2차_사건그룹.xlsx"
LOCKED_CSV = PROJECT / "01_data_inventory" / "22_LOCKED_v1.csv"

# 6 대상 사건 (alias → kw → quota[기존, 신규])
TARGETS = [
    ("쿠팡",       "쿠팡",       4, 1),  # alias, keyword, existing, new
    ("네이버",     "네이버",     4, 1),
    ("카카오엔터", "카카오엔터", 0, 5),
    ("엘지생건",   "엘지생활건강", 0, 5),
    ("삼성전자",   "삼성전자",   0, 5),
    ("홈플러스",   "홈플러스",   0, 5),
]

# 5건 템플릿 — 페르소나 일반2+기업2+논문1, 난이도 기초2+심화2+전문가1, 질문유형 5종 unique
TEMPLATE_5 = [
    ("일반국민",                    "기초",   "제재중심"),
    ("일반국민",                    "심화",   "법령중심"),
    ("기업 컴플라이언스 담당자",    "기초",   "유사사례"),
    ("기업 컴플라이언스 담당자",    "심화",   "통계기반"),
    ("논문 준비 학생",              "전문가", "시장영향"),
]

# 화이트리스트 7종 (이외 인용은 환각 후보)
WHITELIST_LAWS = [
    "공정거래법", "표시광고법", "전자상거래법", "가맹사업법",
    "대규모유통업법", "약관규제법", "하도급법",
]

# 잡법령 후보 (whitelist 외)
SUSPICIOUS_LAWS = [
    "독점금지법", "소비자기본법", "민법", "상법", "형법", "약관법",
    "공정거래 및 독점규제법", "독점규제법",
]

# 페르소나·난이도·질문유형 정렬 순서 (within case)
PERSONA_ORDER = {"일반국민": 0, "기업 컴플라이언스 담당자": 1, "논문 준비 학생": 2}
LEVEL_ORDER   = {"기초": 0, "심화": 1, "전문가": 2}


# ============================ 환각 검출 ============================
def is_hallucination(item: dict, case_alias: str) -> str | None:
    """답변에서 환각 신호 검출. 매칭 시 신호 키워드 반환, 없으면 None."""
    answer = str(item.get("답변", ""))

    if case_alias == "엘지생건":
        if "독점금지법" in answer:
            return "독점금지법"

    if case_alias in ("카카오엔터", "네이버"):
        # "광고법" but not part of "표시광고법"
        cleaned = answer.replace("표시광고법", "")
        if re.search(r"광고법", cleaned):
            return "광고법(약칭)"

    if case_alias in ("쿠팡", "삼성전자", "홈플러스"):
        for s in SUSPICIOUS_LAWS:
            if s in answer:
                # 약관법 vs 약관규제법 구분
                if s == "약관법":
                    cleaned = answer.replace("약관규제법", "")
                    if "약관법" in cleaned:
                        return "약관법(약칭)"
                    continue
                return s
        cleaned = answer.replace("표시광고법", "")
        if "광고법" in cleaned and "표시광고법" not in answer:
            return "광고법(약칭)"

    return None


# ============================ 데이터 적재 ============================
def load_locked() -> list[str]:
    rows = []
    with LOCKED_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r["사건키"].strip())
    return rows


def find_case_dir(keyword: str, locked: list[str]) -> Path | None:
    for full in locked:
        if keyword in full:
            d = RAW_DIR / full
            if d.exists():
                return d
    return None


def load_qa_list(case_dir: Path) -> list[dict]:
    p = case_dir / "qa_list.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    items = d if isinstance(d, list) else (d.get("qa_list") or [])
    return items


def walk_get(d, key):
    if isinstance(d, dict):
        if key in d: return d[key]
        for v in d.values():
            r = walk_get(v, key)
            if r is not None: return r
    return None


def load_case_meta(case_dir: Path) -> dict:
    facts = json.loads((case_dir / "facts.json").read_text(encoding="utf-8"))
    legal = json.loads((case_dir / "legal.json").read_text(encoding="utf-8"))
    scope = walk_get(facts, "피해범위") or ""
    m = re.search(r"\[([^\]]+)\]\s*$", scope) if isinstance(scope, str) else None
    return {
        "case_type": (m.group(1).strip() if m else ""),
        "법령": walk_get(legal, "법령") or "",
        "조문": walk_get(legal, "조문") or "",
    }


# ============================ 5건 선정 ============================
def select_5_for_case(items: list[dict], case_alias: str, mandatory_count: int = 2) -> list[tuple[int, dict, str | None]]:
    """5건 선정. (qa_idx, item, hallucination_signal) 리스트 반환.

    1단계: mandatory_count만큼 환각 후보 확보
    2단계: TEMPLATE_5 콤보 중 미사용 콤보로 fill
    3단계: 남은 콤보 무관하게 unused로 채움
    """
    indexed = list(enumerate(items, start=1))  # (idx, item)
    halls = [(idx, it, is_hallucination(it, case_alias)) for idx, it in indexed]
    halls = [t for t in halls if t[2]]  # 환각 신호 있는 것만

    selected: list[tuple[int, dict, str | None]] = []
    used_idx: set[int] = set()
    used_combos: set[tuple[str, str, str]] = set()

    # Stage 1: 환각 후보 우선 (cap = mandatory_count)
    for idx, item, sig in halls[:mandatory_count]:
        selected.append((idx, item, sig))
        used_idx.add(idx)
        used_combos.add((item.get("페르소나"), item.get("난이도"), item.get("질문유형")))
        if len(selected) >= 5:
            return selected

    # Stage 2: TEMPLATE_5 콤보로 fill (이미 매칭된 콤보 제외)
    for combo in TEMPLATE_5:
        if len(selected) >= 5: break
        if combo in used_combos: continue
        for idx, item in indexed:
            if idx in used_idx: continue
            if (item.get("페르소나"), item.get("난이도"), item.get("질문유형")) == combo:
                sig = is_hallucination(item, case_alias)
                selected.append((idx, item, sig))
                used_idx.add(idx)
                used_combos.add(combo)
                break

    # Stage 3: fill 부족 시 — unused index에서 임의
    for idx, item in indexed:
        if len(selected) >= 5: break
        if idx in used_idx: continue
        sig = is_hallucination(item, case_alias)
        selected.append((idx, item, sig))
        used_idx.add(idx)

    return selected[:5]


def select_1_for_case(items: list[dict], case_alias: str) -> tuple[int, dict, str | None]:
    """쿠팡·네이버용 신규 1건. 환각 우선, 없으면 TEMPLATE_5 마지막 콤보(논문/전문가/시장영향)."""
    indexed = list(enumerate(items, start=1))
    halls = [(idx, it, is_hallucination(it, case_alias)) for idx, it in indexed if is_hallucination(it, case_alias)]
    if halls:
        return halls[0]
    # fallback: 시장영향 (기존 4건이 보통 다른 4종 qtype)
    target = ("논문 준비 학생", "전문가", "시장영향")
    for idx, item in indexed:
        if (item.get("페르소나"), item.get("난이도"), item.get("질문유형")) == target:
            return idx, item, None
    return indexed[0][0], indexed[0][1], None


# ============================ 행 빌드 ============================
def build_row(qa_id: str, item: dict, meta: dict) -> list:
    """13컬럼 행. A~G prefill, H~M 빈."""
    return [
        qa_id,
        item.get("페르소나", ""),
        meta["case_type"],
        meta["법령"],
        meta["조문"],
        item.get("질문", ""),
        item.get("답변", ""),
        "", "", "", "", "", "",
    ]


def case_sort_key(case_full_name: str) -> str:
    return case_full_name


def within_case_sort_key(item: dict, qa_idx: int):
    return (
        PERSONA_ORDER.get(item.get("페르소나", ""), 99),
        LEVEL_ORDER.get(item.get("난이도", ""), 99),
        qa_idx,
    )


# ============================ 스타일 ============================
HEADERS = [
    "QA_ID", "페르소나", "사건유형", "적용 법령", "적용 조문",
    "질문", "답변",
    "판단 요건", "본건 적용 이유", "검수자 평가", "보정안", "신뢰도", "메모",
]
HEADER_FILL = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")
HEADER_FONT = Font(name="맑은 고딕", size=10, bold=True, color="000000")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
DATA_FONT  = Font(name="맑은 고딕", size=10)
DATA_ALIGN = Alignment(vertical="top", wrap_text=True)
B_AREA_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
HALL_TINT   = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")  # 환각 행 옅은 빨강
THIN_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"), right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"), bottom=Side(style="thin", color="CCCCCC"),
)
COL_WIDTHS = {1:16, 2:22, 3:12, 4:14, 5:22, 6:50, 7:60, 8:35, 9:35, 10:14, 11:35, 12:10, 13:25}


# ============================ MAIN ============================
def main():
    print("=" * 70)
    print("B prefill 2차 — 환각 우선 6사건 × 5건")
    print("=" * 70)

    if not SRC.exists():
        raise SystemExit(f"입력 파일 없음: {SRC}")

    locked = load_locked()
    print(f"[1] LOCKED 22 사건 로드")

    # 백업
    if BAK.exists():
        BAK.unlink()
    shutil.move(str(SRC), str(BAK))
    print(f"[2] 직전 파일 백업: {BAK.name}")

    # 백업에서 기존 8건 (쿠팡 4 + 네이버 4) 추출
    wb_bak = load_workbook(BAK)
    ws_bak = wb_bak["법리_검수"]
    existing_b8 = []
    for row in ws_bak.iter_rows(min_row=2, values_only=True):
        if row[0] is None: continue
        qa_id = str(row[0])
        if qa_id in {f"QA-쿠팡-00{i}" for i in (1,2,3,4)} | {f"QA-네이버-00{i}" for i in (1,2,3,4)}:
            existing_b8.append(list(row))
    print(f"[3] 기존 B 8건 보존: {len(existing_b8)}/8")

    # 6사건 × 신규 22건 선정
    print(f"\n[4] 6사건 × 5건 선정 (환각 우선)")
    new_picks = []  # (case_full, qa_id, item, meta, sig)
    case_full_map = {}
    case_stats = {}

    for alias, kw, n_existing, n_new in TARGETS:
        case_dir = find_case_dir(kw, locked)
        if case_dir is None:
            print(f"  [WARN] {alias}: 폴더 없음")
            continue
        case_full = case_dir.name
        case_full_map[alias] = case_full
        items = load_qa_list(case_dir)
        meta = load_case_meta(case_dir)

        if n_new == 5:
            picks = select_5_for_case(items, alias, mandatory_count=2)
        elif n_new == 1:
            picks = [select_1_for_case(items, alias)]
        else:
            picks = []

        # 통계
        halls_count = sum(1 for _, _, sig in picks if sig)
        persona_dist = {}
        level_dist = {}
        qtype_dist = {}
        for _, item, _ in picks:
            persona_dist[item.get("페르소나","")] = persona_dist.get(item.get("페르소나",""), 0) + 1
            level_dist[item.get("난이도","")] = level_dist.get(item.get("난이도",""), 0) + 1
            qtype_dist[item.get("질문유형","")] = qtype_dist.get(item.get("질문유형",""), 0) + 1

        case_stats[alias] = {
            "n_existing": n_existing,
            "n_new": n_new,
            "n_total": n_existing + n_new,
            "halls_in_picks": halls_count,
            "persona": persona_dist,
            "level": level_dist,
            "qtype": qtype_dist,
            "picks_meta": [(idx, item.get("페르소나"), item.get("난이도"), item.get("질문유형"), sig) for idx, item, sig in picks],
        }

        for idx, item, sig in picks:
            qa_id = f"QA-{alias}-{idx:03d}"
            new_picks.append((case_full, qa_id, item, meta, sig))
        print(f"  {alias:12s}: 기존 {n_existing} + 신규 {n_new} (환각 매칭 {halls_count}건)")

    # 모든 행을 사건키 가나다 + 사건 내 페르소나·난이도 순으로 정렬
    print(f"\n[5] 정렬 (사건 가나다 → 페르소나 → 난이도 → QA_idx)")
    final_rows = []  # (case_full, persona_order, level_order, qa_idx, row, sig)

    # 기존 8건
    for row in existing_b8:
        qa_id = str(row[0])
        if "쿠팡" in qa_id:
            case_full = case_full_map["쿠팡"]
        elif "네이버" in qa_id:
            case_full = case_full_map["네이버"]
        else:
            case_full = ""
        try:
            qa_idx = int(qa_id.split("-")[2])
        except (IndexError, ValueError):
            qa_idx = 0
        persona = row[1] or ""
        # 난이도 정보가 row에 직접 없음 — 기존 8건은 모두 일반국민·기초 임을 알고 있으니 0으로
        final_rows.append((case_full, PERSONA_ORDER.get(persona, 99), 0, qa_idx, row, None))

    # 신규 22건
    for case_full, qa_id, item, meta, sig in new_picks:
        try:
            qa_idx = int(qa_id.split("-")[2])
        except (IndexError, ValueError):
            qa_idx = 0
        row = build_row(qa_id, item, meta)
        po = PERSONA_ORDER.get(item.get("페르소나",""), 99)
        lo = LEVEL_ORDER.get(item.get("난이도",""), 99)
        final_rows.append((case_full, po, lo, qa_idx, row, sig))

    final_rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    # === 워크북 생성 ===
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

    for r_offset, (case_full, po, lo, qa_idx, row, sig) in enumerate(final_rows):
        r_idx = 2 + r_offset
        for c_idx, val in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = DATA_FONT
            cell.alignment = DATA_ALIGN
            cell.border = THIN_BORDER
            # H~M 빈칸 → 연노랑
            if c_idx >= 8 and (val is None or val == ""):
                cell.fill = B_AREA_FILL
        # 환각 행은 A~G 옅은 빨강 tint
        if sig:
            for c_idx in range(1, 8):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.fill = HALL_TINT
        ws.row_dimensions[r_idx].height = 50

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"[6] 저장: {OUT.relative_to(PROJECT)}")

    # === 검증 ===
    print()
    print("=" * 70)
    print("검증")
    print("=" * 70)

    wb_v = load_workbook(OUT, read_only=True)
    ws_v = wb_v["법리_검수"]
    total = ws_v.max_row - 1
    print(f"\n  총 행: {total} (예상 30) {'✅' if total == 30 else '❌'}")

    # 사건별 행수
    case_count = {}
    qa_ids = []
    for row in ws_v.iter_rows(min_row=2, values_only=True):
        if row[0] is None: continue
        qa_id = str(row[0])
        qa_ids.append(qa_id)
        for alias in ("쿠팡","네이버","카카오엔터","엘지생건","삼성전자","홈플러스"):
            if f"-{alias}-" in qa_id:
                case_count[alias] = case_count.get(alias, 0) + 1
                break

    print(f"\n  [사건별 행 수]")
    expected = {"쿠팡":5,"네이버":5,"카카오엔터":5,"엘지생건":5,"삼성전자":5,"홈플러스":5}
    for alias, exp in expected.items():
        n = case_count.get(alias, 0)
        marker = "✅" if n == exp else "❌"
        print(f"    {marker} {alias:10s}: {n}/{exp}")

    # B 기존 8건
    preserved = sum(1 for q in qa_ids if q in {f"QA-쿠팡-00{i}" for i in (1,2,3,4)} | {f"QA-네이버-00{i}" for i in (1,2,3,4)})
    print(f"\n  기존 B 8건 보존: {preserved}/8 {'✅' if preserved == 8 else '❌'}")

    # 한글 체크
    sample = next(ws_v.iter_rows(min_row=2, max_row=2, values_only=True))
    has_kor = any(isinstance(v, str) and any('가' <= ch <= '힯' for ch in v) for v in sample)
    print(f"  한글 정상: {'✅' if has_kor else '❌'}")

    # 사건별 분포 통계 출력
    print(f"\n  [사건별 신규 분포 통계]")
    for alias in ("쿠팡","네이버","카카오엔터","엘지생건","삼성전자","홈플러스"):
        if alias not in case_stats: continue
        s = case_stats[alias]
        halls_str = ", ".join([f"{idx}({sig})" for idx,_,_,_,sig in s["picks_meta"] if sig]) or "(없음)"
        print(f"\n    {alias} (기존 {s['n_existing']} + 신규 {s['n_new']}):")
        print(f"      페르소나: {s['persona']}")
        print(f"      난이도:   {s['level']}")
        print(f"      질문유형: {s['qtype']}")
        print(f"      환각 매칭 ({s['halls_in_picks']}건): {halls_str}")
        print(f"      신규 picks: {[(idx, p[:6], l, q[:4]) for idx,p,l,q,_ in s['picks_meta']]}")

    # 엘지생건 독점금지법 2건 검증
    el_stats = case_stats.get("엘지생건", {})
    el_halls = [(idx,sig) for idx,_,_,_,sig in el_stats.get("picks_meta",[]) if sig and "독점금지법" in sig]
    print(f"\n  엘지생건 '독점금지법' 환각 포함: {len(el_halls)}/2 {'✅' if len(el_halls) == 2 else '⚠️ 부족 또는 초과'}")
    for idx, sig in el_halls:
        print(f"    - QA-엘지생건-{idx:03d} ({sig})")


if __name__ == "__main__":
    main()
