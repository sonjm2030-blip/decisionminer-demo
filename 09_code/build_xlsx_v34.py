"""
6건 사건의 5단 분해 결과(JSON) → 학습데이터_설계서_구조_v3.4.xlsx 자동 채움.

읽기 대상:
  04_raw_outputs/<case_dir>/{qa_list,facts,legal,sanction}.json
출력:
  05_xlsx/학습데이터_설계서_구조_v3.4.xlsx (4시트: 전체_QA + 페르소나 3종)

기존 파일 백업: 05_xlsx/checkpoints/학습데이터_설계서_구조_v3.4_<YYYYMMDD_HHMMSS>.xlsx
"""

from __future__ import annotations
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ============================ 설정 ============================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR      = PROJECT_ROOT / "04_raw_outputs"
XLSX_DIR     = PROJECT_ROOT / "05_xlsx"
XLSX_PATH    = XLSX_DIR / "학습데이터_설계서_구조_v3.4.xlsx"
CKPT_DIR     = XLSX_DIR / "checkpoints"

# 폴더명 → 사건키 약어
CASE_KEY_MAP: dict[str, str] = {
    "쿠팡(주)의 전자상거래소비자보호법 등 위반행위에 대한 건":                                   "쿠팡",
    "네이버(주)의 부당한 광고행위에 대한 건":                                                "네이버",
    "남양유업(주)의 거래상지위남용행위에 대한 건":                                              "남양유업",
    "삼성전자(주)의 부당한 고객유인행위에 대한 건":                                              "삼성전자",
    "(주)신세계 및 (주)에스에스지닷컴의 전자상거래 소비자보호법 위반행위에 대한 건":              "신세계",
    "에스피피조선(주)의 불공정하도급거래행위에 대한 건":                                        "에스피피조선",
}

# 시트별 16번 컬럼 정책
SHEET_POLICY: dict[str, dict] = {
    "전체_QA": {
        "header_16": "근거(원문)",
        "value_16": lambda item, ctx: item.get("근거_short", ""),
        "filter":   lambda item: True,
    },
    "일반국민": {
        "header_16": "주의사항",
        "value_16": lambda item, ctx: "소비자 권리 침해 시 공정위 신고센터 활용 가능.",
        "filter":   lambda item: item.get("페르소나") == "일반국민",
    },
    "기업 컴플라이언스 담당자": {
        "header_16": "주의사항",
        "value_16": lambda item, ctx: "해당 조문 준수 여부 사전 점검 및 법무팀 보고 체계 구축 권고.",
        "filter":   lambda item: item.get("페르소나") == "기업 컴플라이언스 담당자",
    },
    "논문 준비 학생": {
        "header_16": "비고",
        "value_16": lambda item, ctx: "적용 법령+조문 인용 및 유사 선례 비교 분석 권장.",
        "filter":   lambda item: item.get("페르소나") == "논문 준비 학생",
    },
}

SHEET_ORDER = ["전체_QA", "일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생"]
CONFIDENCE_FIXED = 0.85


# ============================ 유틸 ============================
def walk_get(d, key):
    """nested dict에서 key를 첫 매치로 찾아 반환."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = walk_get(v, key)
            if r is not None:
                return r
    return None


def load_qa_items(qa_data):
    if isinstance(qa_data, list):
        return qa_data
    if isinstance(qa_data, dict):
        for k in ("qa_list", "qa", "items", "data"):
            v = qa_data.get(k)
            if isinstance(v, list):
                return v
    return []


def extract_case_type_tag(damage_scope: str) -> str:
    """facts_structured.피해범위 끝의 [태그] 추출."""
    if not isinstance(damage_scope, str):
        return ""
    m = re.search(r"\[([^\]]+)\]\s*$", damage_scope)
    return m.group(1).strip() if m else ""


def core_keyword(action: str, n: int = 30) -> str:
    """facts.행위 앞 n자."""
    if not isinstance(action, str):
        return ""
    s = action.strip()
    return s[:n] + ("…" if len(s) > n else "")


def format_sanction(sanction_types, fine_amount) -> str:
    """처분유형 리스트 + 과징금액 → '시정명령, 과태료 / 과징금 0원' 형태."""
    if isinstance(sanction_types, list):
        st = ", ".join(str(x) for x in sanction_types)
    else:
        st = str(sanction_types or "")
    try:
        amount = int(fine_amount) if fine_amount not in (None, "") else 0
    except (TypeError, ValueError):
        amount = 0
    if amount == 0:
        amount_str = "0원"
    else:
        amount_str = f"{amount:,}원"
    return f"{st} / 과징금 {amount_str}"


# ============================ 데이터 적재 ============================
def load_case_data(case_dir: Path) -> dict:
    """1건 사건의 4개 JSON 통합 적재."""
    qa_path      = case_dir / "qa_list.json"
    facts_path   = case_dir / "facts.json"
    legal_path   = case_dir / "legal.json"
    sanction_path = case_dir / "sanction.json"

    qa_data    = json.loads(qa_path.read_text(encoding="utf-8"))
    facts_data = json.loads(facts_path.read_text(encoding="utf-8"))
    legal_data = json.loads(legal_path.read_text(encoding="utf-8"))
    sanc_data  = json.loads(sanction_path.read_text(encoding="utf-8"))

    qa_items = load_qa_items(qa_data)
    facts_structured = walk_get(facts_data, "facts_structured") or {}

    return {
        "qa_items":     qa_items,
        "행위":         walk_get(facts_data, "행위") or "",
        "피해범위":     facts_structured.get("피해범위") or walk_get(facts_data, "피해범위") or "",
        "법령":         walk_get(legal_data, "법령") or "",
        "조문":         walk_get(legal_data, "조문") or "",
        "처분유형":     walk_get(sanc_data, "처분유형") or [],
        "과징금액":     walk_get(sanc_data, "과징금액"),
    }


# ============================ 행 생성 ============================
def build_row(item: dict, case_short: str, ctx: dict, qa_index: int, sheet_policy: dict) -> list:
    """1개 Q&A → 17열 행."""
    case_type = extract_case_type_tag(ctx["피해범위"])
    keyword   = core_keyword(ctx["행위"], 30)
    qa_id     = f"QA-{case_short}-{qa_index:03d}"

    persona  = item.get("페르소나", "")
    level    = item.get("난이도", "")
    qtype    = item.get("질문유형", "")
    question = item.get("질문", "")
    answer   = item.get("답변", "")
    chunk    = item.get("근거_short", "")

    sanction_str = format_sanction(ctx["처분유형"], ctx["과징금액"])
    persona_value = sheet_policy["value_16"](item, ctx)

    issue_solution = (
        "AI 자동 생성 답변으로 법령 조문 인용 정확도 검수 필요. "
        f"근거 chunk [{chunk}] 원문 대조 권고. "
        "페르소나 톤 적합성 B 검수자 최종 확인 대상."
    )

    return [
        qa_id,                      # 1.  ID
        case_short,                 # 2.  사건키
        case_type,                  # 3.  사건유형
        persona,                    # 4.  페르소나
        level,                      # 5.  난이도
        qtype,                      # 6.  질문유형
        question,                   # 7.  질문
        answer,                     # 8.  답변
        keyword,                    # 9.  핵심키워드
        ctx["법령"],                # 10. 적용법령
        ctx["조문"],                # 11. 적용조문
        sanction_str,               # 12. 처분결과
        chunk,                      # 13. 근거(chunk)
        CONFIDENCE_FIXED,           # 14. Confidence
        "",                         # 15. 검수자 평가
        persona_value,              # 16. 시트별 동적 (주의사항/비고/근거(원문))
        issue_solution,             # 17. 문제점 및 해결방안
    ]


# ============================ 워크북 빌드 ============================
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
DATA_FONT = Font(name="맑은 고딕", size=9)
DATA_ALIGN = Alignment(vertical="top", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)

BASE_HEADERS_1_15 = [
    "ID", "사건키", "사건유형", "페르소나", "난이도",
    "질문유형", "질문", "답변", "핵심키워드",
    "적용법령", "적용조문", "처분결과", "근거(chunk)",
    "Confidence", "검수자 평가",
]
HEADER_17 = "문제점 및 해결방안"

COL_WIDTHS = {
    1: 18, 2: 12, 3: 12, 4: 22, 5: 10,
    6: 12, 7: 50, 8: 70, 9: 32,
    10: 14, 11: 22, 12: 36, 13: 28,
    14: 12, 15: 14, 16: 28, 17: 60,
}


def write_sheet(ws, sheet_name: str, rows: list[list]):
    policy = SHEET_POLICY[sheet_name]
    headers = BASE_HEADERS_1_15 + [policy["header_16"]] + [HEADER_17]

    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col_idx, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = HEADER_ALIGN
        c.border = THIN_BORDER

    for col_idx, w in COL_WIDTHS.items():
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = w
    ws.row_dimensions[1].height = 32

    for r_idx, row in enumerate(rows, start=2):
        for c_idx, val in enumerate(row, start=1):
            c = ws.cell(row=r_idx, column=c_idx, value=val)
            c.font = DATA_FONT
            c.alignment = DATA_ALIGN
            c.border = THIN_BORDER
        ws.row_dimensions[r_idx].height = 60

    ws.freeze_panes = "A2"


# ============================ 백업 ============================
def backup_existing(xlsx_path: Path) -> Path | None:
    if not xlsx_path.exists():
        return None
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = CKPT_DIR / f"{xlsx_path.stem}_{ts}{xlsx_path.suffix}"
    shutil.copy2(xlsx_path, bak)
    return bak


# ============================ 메인 ============================
def main():
    print("=" * 70)
    print("학습데이터 설계서 자동 빌드 v3.4")
    print("=" * 70)

    # 1) 백업
    bak = backup_existing(XLSX_PATH)
    if bak:
        print(f"[BACKUP] 기존 파일 → {bak.relative_to(PROJECT_ROOT)}")
    else:
        print("[BACKUP] 기존 파일 없음 — 신규 생성")

    # 2) 6건 사건 데이터 적재 + 행 빌드
    all_rows: list[list] = []   # 전체_QA 행
    persona_rows: dict[str, list] = {p: [] for p in ["일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생"]}

    for folder, case_short in CASE_KEY_MAP.items():
        case_dir = RAW_DIR / folder
        if not case_dir.exists():
            print(f"[SKIP] {case_short}: 폴더 없음 {case_dir}")
            continue
        ctx = load_case_data(case_dir)
        items = ctx["qa_items"]
        print(f"[LOAD] {case_short}: qa={len(items)}, 법령={ctx['법령']}, 처분={ctx['처분유형']}")

        for i, item in enumerate(items, start=1):
            # 전체_QA용 행 (정책 = 전체_QA)
            row_full = build_row(item, case_short, ctx, i, SHEET_POLICY["전체_QA"])
            all_rows.append(row_full)

            # 페르소나별 시트 행 (정책 = 해당 페르소나)
            persona = item.get("페르소나")
            if persona in persona_rows:
                row_persona = build_row(item, case_short, ctx, i, SHEET_POLICY[persona])
                persona_rows[persona].append(row_persona)

    print()
    print(f"[BUILD] 전체 행 수: {len(all_rows)}")
    for p, rs in persona_rows.items():
        print(f"        {p}: {len(rs)}")

    # 3) Workbook 생성
    wb = Workbook()
    wb.remove(wb.active)

    sheet_data = {
        "전체_QA": all_rows,
        "일반국민": persona_rows["일반국민"],
        "기업 컴플라이언스 담당자": persona_rows["기업 컴플라이언스 담당자"],
        "논문 준비 학생": persona_rows["논문 준비 학생"],
    }

    for name in SHEET_ORDER:
        ws = wb.create_sheet(title=name)
        write_sheet(ws, name, sheet_data[name])

    # 4) 저장
    XLSX_DIR.mkdir(parents=True, exist_ok=True)
    wb.save(XLSX_PATH)
    print()
    print(f"[SAVE] {XLSX_PATH.relative_to(PROJECT_ROOT)}")

    # 5) 검증
    print()
    print("=" * 70)
    print("검증")
    print("=" * 70)
    counts = {n: len(sheet_data[n]) for n in SHEET_ORDER}
    for n in SHEET_ORDER:
        print(f"  {n:<28} : {counts[n]} 행")
    persona_sum = counts["일반국민"] + counts["기업 컴플라이언스 담당자"] + counts["논문 준비 학생"]
    ok = (persona_sum == counts["전체_QA"])
    print()
    print(f"  페르소나 3종 합계  : {persona_sum}")
    print(f"  전체_QA           : {counts['전체_QA']}")
    print(f"  검증 결과         : {'✅ PASS' if ok else '❌ FAIL'} (전체_QA == 페르소나 합계)")


if __name__ == "__main__":
    main()
