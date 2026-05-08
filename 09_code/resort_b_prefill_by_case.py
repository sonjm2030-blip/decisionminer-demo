"""
B prefill 2차 — 사건별 묶기 재정렬.

입력: 학습데이터_설계서_구조_v3.4_B용_2차.xlsx (색상별 정렬)
출력: 학습데이터_설계서_구조_v3.4_B용_2차_사건별.xlsx (사건 알파벳 묶음)
백업: 기존 _2차.xlsx → _2차_색상별.xlsx (이름 변경)

변경:
  - 행 정렬: 색상(RED→YELLOW→GREEN) → 사건키 알파벳 순
  - 같은 사건 내 정렬: QA_ID 오름차순 (자연스럽게 페르소나·난이도 순)
  - A~G 색상 tint 제거 (균일 흰색)
  - H~M 빈칸은 연노랑 (#FFF2CC) 유지 — B 작성 영역 표시
"""

from __future__ import annotations
import csv
import shutil
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


PROJECT = Path(__file__).resolve().parent.parent
SRC = PROJECT / "05_xlsx" / "학습데이터_설계서_구조_v3.4_B용_2차.xlsx"
OUT = PROJECT / "05_xlsx" / "학습데이터_설계서_구조_v3.4_B용_2차_사건별.xlsx"
BAK = PROJECT / "05_xlsx" / "학습데이터_설계서_구조_v3.4_B용_2차_색상별.xlsx"
LOCKED_CSV = PROJECT / "01_data_inventory" / "22_LOCKED_v1.csv"

# QA_ID 약어 → 사건키 키워드
ALIAS_TO_KW = {
    "쿠팡":            "쿠팡",
    "네이버":          "네이버",
    "남양유업":        "남양유업",
    "삼성전자":        "삼성전자",
    "신세계":          "신세계",
    "에스피피조선":    "에스피피조선",
    "새마을금고":      "새마을금고",
    "조달청":          "조달청",
    "경북교육청":      "경상북도교육청",
    "글락소":          "글락소",
    "평화이엔지":      "평화이엔지",
    "케이티디에스":    "케이티디에스",
    "동원건설":        "동원건설",
    "홈플러스":        "홈플러스",
    "카카오엔터":      "카카오엔터",
    "경북택시":        "경상북도개인택시",
    "과수종묘":        "한국과수종묘",
    "엘지생건":        "엘지생활건강",
    "비에이치씨":      "비에이치씨",
    "금호아시아나":    "금호아시아나",
    "아모레":          "아모레퍼시픽",
    "롯데쇼핑":        "롯데쇼핑",
}


# ============================ 사건키 매핑 ============================
def load_locked_full_names() -> list[str]:
    full_names = []
    with LOCKED_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            full_names.append(r["사건키"].strip())
    return full_names


def alias_to_full(alias: str, full_names: list[str]) -> str:
    """약어 → 전체 사건키. 매칭 실패 시 약어 그대로 반환."""
    kw = ALIAS_TO_KW.get(alias, alias)
    for full in full_names:
        if kw in full:
            return full
    return alias


# ============================ 정렬 ============================
def parse_qa_id(qa_id: str) -> tuple[str, int]:
    """'QA-쿠팡-001' → ('쿠팡', 1)"""
    parts = str(qa_id).split("-")
    alias = parts[1] if len(parts) >= 2 else ""
    try:
        idx = int(parts[2]) if len(parts) >= 3 else 0
    except ValueError:
        idx = 0
    return alias, idx


def sort_key(row: list, full_names: list[str]):
    """정렬 키: (전체사건키 가나다순, QA_ID 인덱스 오름차순)"""
    alias, idx = parse_qa_id(row[0])
    full = alias_to_full(alias, full_names)
    return (full, idx)


# ============================ 빌드 ============================
HEADERS = [
    "QA_ID", "페르소나", "사건유형", "적용 법령", "적용 조문",
    "질문", "답변",
    "판단 요건", "본건 적용 이유", "검수자 평가", "보정안", "신뢰도", "메모",
]

HEADER_FILL  = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")
HEADER_FONT  = Font(name="맑은 고딕", size=10, bold=True, color="000000")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
DATA_FONT    = Font(name="맑은 고딕", size=10)
DATA_ALIGN   = Alignment(vertical="top", wrap_text=True)
B_AREA_FILL  = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
THIN_BORDER  = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)
COL_WIDTHS = {1:16, 2:22, 3:12, 4:14, 5:22, 6:50, 7:60, 8:35, 9:35, 10:14, 11:35, 12:10, 13:25}


def main():
    print("=" * 70)
    print("B prefill 2차 — 사건별 재정렬")
    print("=" * 70)

    if not SRC.exists():
        raise SystemExit(f"입력 파일 없음: {SRC}")

    full_names = load_locked_full_names()
    print(f"[1] LOCKED 22 사건키 로드: {len(full_names)}")

    # 백업 — 기존 _2차.xlsx → _2차_색상별.xlsx (rename)
    if BAK.exists():
        BAK.unlink()
        print(f"[2] 기존 백업 삭제: {BAK.name}")
    shutil.move(str(SRC), str(BAK))
    print(f"[2] 색상별 백업: {BAK.relative_to(PROJECT)}")

    # 백업에서 행 로드
    wb_src = load_workbook(BAK)
    ws_src = wb_src["법리_검수"]
    rows = []
    for row in ws_src.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        rows.append(list(row))
    print(f"[3] 30행 로드: 실제 {len(rows)}")

    # 사건별 묶음 정렬
    rows.sort(key=lambda r: sort_key(r, full_names))
    print(f"[4] 사건키 가나다순 정렬 완료")

    # 빌드 — 색상 tint 없음
    wb_out = Workbook()
    wb_out.remove(wb_out.active)
    ws_out = wb_out.create_sheet("법리_검수")

    for c_idx, h in enumerate(HEADERS, start=1):
        cell = ws_out.cell(row=1, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws_out.column_dimensions[cell.column_letter].width = COL_WIDTHS.get(c_idx, 15)
    ws_out.row_dimensions[1].height = 32
    ws_out.freeze_panes = "A2"

    for r_offset, row in enumerate(rows):
        r_idx = 2 + r_offset
        for c_idx, val in enumerate(row, start=1):
            cell = ws_out.cell(row=r_idx, column=c_idx, value=val)
            cell.font = DATA_FONT
            cell.alignment = DATA_ALIGN
            cell.border = THIN_BORDER
            # H~M (col 8~13) 빈칸 → 연노랑 (B 작성 영역)
            if c_idx >= 8 and (val is None or val == ""):
                cell.fill = B_AREA_FILL
            # A~G는 색상 tint 제거 (기본 흰색)
        ws_out.row_dimensions[r_idx].height = 50

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb_out.save(OUT)
    print(f"[5] 저장: {OUT.relative_to(PROJECT)}")

    # === 검증 ===
    print()
    print("=" * 70)
    print("검증")
    print("=" * 70)
    wb_v = load_workbook(OUT, read_only=True)
    ws_v = wb_v["법리_검수"]
    total = ws_v.max_row - 1
    print(f"\n  총 행: {total} (예상 30) {'✅' if total == 30 else '❌'}")

    # 사건별 묶음 순서 + 카운트
    print(f"\n  [사건별 묶음 순서]")
    prev_full = None
    case_count = {}
    case_order = []
    for row in ws_v.iter_rows(min_row=2, values_only=True):
        if row[0] is None: continue
        alias, _ = parse_qa_id(row[0])
        full = alias_to_full(alias, full_names)
        case_count[full] = case_count.get(full, 0) + 1
        if full != prev_full:
            case_order.append(full)
            prev_full = full

    consecutive_ok = True
    for i, full in enumerate(case_order, 1):
        n = case_count[full]
        marker = "✅" if (("쿠팡" in full or "네이버" in full) and n == 5) or (("쿠팡" not in full and "네이버" not in full) and n == 1) else "❌"
        if marker == "❌": consecutive_ok = False
        print(f"    {i:2d}. {marker} {n}건  {full[:48]}")

    # 사건별 묶임 검증 (같은 사건이 인접)
    appeared = set()
    inline_issues = 0
    seen_full = None
    for row in ws_v.iter_rows(min_row=2, values_only=True):
        if row[0] is None: continue
        alias, _ = parse_qa_id(row[0])
        full = alias_to_full(alias, full_names)
        if full != seen_full:
            if full in appeared:
                inline_issues += 1
            appeared.add(full)
            seen_full = full
    print(f"\n  사건별 묶임 (재출현 0건): {'✅' if inline_issues == 0 else f'❌ {inline_issues}건 중복'}")

    # B 기존 8건 H~M 보존 검증 (쿠팡 4 + 네이버 4 → H~M 모두 빈값일 것)
    preserved = 0
    for row in ws_v.iter_rows(min_row=2, values_only=True):
        if row[0] is None: continue
        qa_id = str(row[0])
        if qa_id in {f"QA-쿠팡-00{i}" for i in (1,2,3,4)} | {f"QA-네이버-00{i}" for i in (1,2,3,4)}:
            preserved += 1
    print(f"  기존 8건 (쿠팡 4 + 네이버 4) 존재: {preserved}/8 {'✅' if preserved == 8 else '❌'}")

    # 한글 체크 (행 1개 샘플)
    sample = next(ws_v.iter_rows(min_row=2, max_row=2, values_only=True))
    has_korean = any(isinstance(v, str) and any('가' <= ch <= '힯' for ch in v) for v in sample)
    print(f"  한글 정상: {'✅' if has_korean else '❌'}  (예: {str(sample[1])[:20]}...)")

    print(f"\n  출력: {OUT.name}")
    print(f"  백업: {BAK.name}")


if __name__ == "__main__":
    main()
