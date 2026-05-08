"""
학습데이터_설계서_구조_v3.4.xlsx 확장 — 시트 5~12 추가 + 법리_검수 prefill.

시트 5~8: 데이터셋 (요약/사실관계/분류/추론)  헤더 색 #70AD47 (녹색)
시트 9~12: 검수·메타 (검수_결과표/법리_검수/대시보드/데이터사전) 헤더 색 #FFD966 (노란색)

법리_검수 prefill: 쿠팡 4건 + 네이버 4건 = 8건 (qa_list 인덱스 0~3)
  - 1~5열 자동 입력
  - 6~11열 빈칸 + 배경 #FFF2CC (B 검수자 작성 영역)

기존 파일 백업: 05_xlsx/checkpoints/학습데이터_설계서_구조_v3.4_<TS>.xlsx
"""

from __future__ import annotations
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ============================ 경로 ============================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR      = PROJECT_ROOT / "04_raw_outputs"
XLSX_DIR     = PROJECT_ROOT / "05_xlsx"
XLSX_PATH    = XLSX_DIR / "학습데이터_설계서_구조_v3.4.xlsx"
CKPT_DIR     = XLSX_DIR / "checkpoints"


# ============================ 시트 정의 ============================
NEW_SHEETS: list[tuple[str, list[str]]] = [
    # 시트 5~8 (데이터셋, 녹색 헤더)
    ("요약_데이터셋", [
        "사건키", "의결서명", "사건유형", "summary_short",
        "출처", "추출일자", "검수자", "문제점 및 해결방안",
    ]),
    ("사실관계_데이터셋", [
        "사건키", "의결서명", "당사자", "기간", "행위",
        "피해규모", "피해범위", "출처", "검수자", "문제점 및 해결방안",
    ]),
    ("분류_데이터셋", [
        "사건키", "의결서명", "사건유형_대분류", "사건유형_세분류",
        "위반_조문", "처분_유형", "산업분야", "문제점 및 해결방안",
    ]),
    ("추론_데이터셋", [
        "사건키", "의결서명", "법령확인", "구성요건",
        "근거인용", "결론", "적용_법리", "출처", "검수자", "문제점 및 해결방안",
    ]),
    # 시트 9~12 (검수·메타, 노란색 헤더)
    ("검수_결과표", [
        "항목", "측정방법", "측정값", "조치", "비고",
    ]),
    ("법리_검수", [
        "QA_ID", "페르소나", "사건유형", "적용 법령", "적용 조문",
        "판단 요건", "본건 적용 이유", "검수자 평가", "보정안", "신뢰도", "메모",
    ]),
    ("대시보드", []),  # A1 셀에 타이틀만
    ("데이터사전", [
        "컬럼명", "의미", "예시", "출처 시트",
    ]),
]

GREEN_HEADER_SHEETS  = {"요약_데이터셋", "사실관계_데이터셋", "분류_데이터셋", "추론_데이터셋"}
YELLOW_HEADER_SHEETS = {"검수_결과표", "법리_검수", "대시보드", "데이터사전"}

DASHBOARD_TITLE = "DecisionMiner 통계 대시보드 (Day 9 자동 갱신)"


# ============================ 법리_검수 prefill 대상 ============================
LEGAL_REVIEW_CASES: list[tuple[str, str]] = [
    ("쿠팡",   "쿠팡(주)의 전자상거래소비자보호법 등 위반행위에 대한 건"),
    ("네이버", "네이버(주)의 부당한 광고행위에 대한 건"),
]
PREFILL_PER_CASE = 4   # 인덱스 0~3


# ============================ 스타일 ============================
HEADER_GREEN_FILL  = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")
HEADER_GREEN_FONT  = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
HEADER_YELLOW_FILL = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid")
HEADER_YELLOW_FONT = Font(name="맑은 고딕", size=10, bold=True, color="000000")
HEADER_ALIGN       = Alignment(horizontal="center", vertical="center", wrap_text=True)

DATA_FONT          = Font(name="맑은 고딕", size=10)
DATA_ALIGN         = Alignment(vertical="top", wrap_text=True)

REVIEW_AREA_FILL   = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")  # B 작성 영역

THIN_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)


# ============================ 유틸 ============================
def walk_get(d, key):
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = walk_get(v, key)
            if r is not None:
                return r
    return None


def case_type_from_facts(facts_data) -> str:
    fs = walk_get(facts_data, "facts_structured") or {}
    scope = fs.get("피해범위") or walk_get(facts_data, "피해범위") or ""
    if not isinstance(scope, str):
        return ""
    m = re.search(r"\[([^\]]+)\]\s*$", scope)
    return m.group(1).strip() if m else ""


def load_qa_items(qa_data):
    if isinstance(qa_data, list):
        return qa_data
    if isinstance(qa_data, dict):
        for k in ("qa_list", "qa", "items", "data"):
            v = qa_data.get(k)
            if isinstance(v, list):
                return v
    return []


# ============================ 시트 작성 ============================
def style_for_sheet(name: str) -> tuple[PatternFill, Font]:
    if name in GREEN_HEADER_SHEETS:
        return HEADER_GREEN_FILL, HEADER_GREEN_FONT
    if name in YELLOW_HEADER_SHEETS:
        return HEADER_YELLOW_FILL, HEADER_YELLOW_FONT
    return HEADER_GREEN_FILL, HEADER_GREEN_FONT  # default


def write_header(ws, headers: list[str], name: str):
    fill, font = style_for_sheet(name)
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.fill = fill
        cell.font = font
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        col_letter = ws.cell(row=1, column=c_idx).column_letter
        # 컬럼 폭 휴리스틱 (글자 길이 기반 + 최소 14)
        ws.column_dimensions[col_letter].width = max(14, min(40, len(h) * 2 + 4))
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


def write_dashboard(ws):
    fill, font = style_for_sheet("대시보드")
    cell = ws.cell(row=1, column=1, value=DASHBOARD_TITLE)
    cell.fill = fill
    cell.font = Font(name="맑은 고딕", size=12, bold=True, color="000000")
    cell.alignment = Alignment(horizontal="left", vertical="center")
    cell.border = THIN_BORDER
    ws.column_dimensions["A"].width = 60
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"


# ============================ 법리_검수 prefill ============================
def prefill_legal_review(ws) -> list[str]:
    """8건 prefill: 쿠팡 4 + 네이버 4. cols 1~5 채움, 6~11 빈칸 + 배경색."""
    qa_ids: list[str] = []
    row_idx = 2

    for case_short, case_full in LEGAL_REVIEW_CASES:
        case_dir = RAW_DIR / case_full
        qa_data    = json.loads((case_dir / "qa_list.json").read_text(encoding="utf-8"))
        facts_data = json.loads((case_dir / "facts.json").read_text(encoding="utf-8"))
        legal_data = json.loads((case_dir / "legal.json").read_text(encoding="utf-8"))

        items   = load_qa_items(qa_data)
        ctype   = case_type_from_facts(facts_data)
        law     = walk_get(legal_data, "법령") or ""
        article = walk_get(legal_data, "조문") or ""

        for i in range(min(PREFILL_PER_CASE, len(items))):
            item = items[i]
            qa_id = f"QA-{case_short}-{i+1:03d}"
            persona = item.get("페르소나", "")

            row_values = [
                qa_id,        # 1. QA_ID
                persona,      # 2. 페르소나
                ctype,        # 3. 사건유형
                law,          # 4. 적용 법령
                article,      # 5. 적용 조문
                "", "", "", "", "", "",   # 6~11. B 빈칸
            ]
            for c_idx, val in enumerate(row_values, start=1):
                cell = ws.cell(row=row_idx, column=c_idx, value=val)
                cell.font = DATA_FONT
                cell.alignment = DATA_ALIGN
                cell.border = THIN_BORDER
                if c_idx >= 6:
                    cell.fill = REVIEW_AREA_FILL  # B 작성 영역 표시

            ws.row_dimensions[row_idx].height = 50
            qa_ids.append(qa_id)
            row_idx += 1

    return qa_ids


# ============================ 백업 ============================
def backup_existing(xlsx: Path) -> Path | None:
    if not xlsx.exists():
        return None
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CKPT_DIR / f"{xlsx.stem}_{ts}{xlsx.suffix}"
    shutil.copy2(xlsx, bak)
    return bak


# ============================ 메인 ============================
def main():
    print("=" * 70)
    print("학습데이터 설계서 확장 — 시트 5~12 추가 + 법리_검수 prefill")
    print("=" * 70)

    bak = backup_existing(XLSX_PATH)
    if bak:
        print(f"[BACKUP] {bak.relative_to(PROJECT_ROOT)}")
    if not XLSX_PATH.exists():
        raise SystemExit(f"[FATAL] 기준 파일 없음: {XLSX_PATH}")

    wb = load_workbook(XLSX_PATH)

    # 1) 신규 시트 8개 추가 (이미 있으면 삭제 후 재생성)
    legal_qa_ids: list[str] = []
    for sheet_name, headers in NEW_SHEETS:
        if sheet_name in wb.sheetnames:
            del wb[sheet_name]
        ws = wb.create_sheet(title=sheet_name)

        if sheet_name == "대시보드":
            write_dashboard(ws)
        else:
            write_header(ws, headers, sheet_name)

        # 법리_검수 prefill 실행
        if sheet_name == "법리_검수":
            legal_qa_ids = prefill_legal_review(ws)

    wb.save(XLSX_PATH)
    print(f"[SAVE] {XLSX_PATH.relative_to(PROJECT_ROOT)}")

    # 2) 검증
    print()
    print("=" * 70)
    print("검증")
    print("=" * 70)
    wb2 = load_workbook(XLSX_PATH, read_only=True)
    print(f"\n[전체 시트 목록] ({len(wb2.sheetnames)}개)")
    for i, n in enumerate(wb2.sheetnames, 1):
        ws = wb2[n]
        print(f"  {i:2d}. {n:<28} ({ws.max_row} 행 × {ws.max_column} 열)")

    print(f"\n[법리_검수 시트 8행 QA_ID 목록]")
    for q in legal_qa_ids:
        print(f"  - {q}")
    print(f"  총 {len(legal_qa_ids)}건")


if __name__ == "__main__":
    main()
