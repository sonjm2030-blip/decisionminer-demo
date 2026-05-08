"""
공모전 빈 양식(05_xlsx/학습데이터 설계서.xlsx)을 베이스로 12시트 통합 xlsx 생성.

- QA 4시트: 양식의 1·2·3행 보존, 4행부터 데이터 입력
- 메타 4시트: 신규 추가 (요약/사실관계/분류/추론)
- 검수·관리 4시트: 검수_결과표·법리_검수 신규, 대시보드·데이터사전 덮어쓰기
- 16번 컬럼은 시트별 양식 헤더 그대로 (전체_QA=근거, 페르소나=주의사항/비고)
- 17번 컬럼은 4요소 형식 (자동검수/보정지침/유의사항/학습권장)
"""
import csv
import re
import shutil
from collections import Counter
from copy import copy
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "05_xlsx" / "학습데이터 설계서.xlsx"
OUT = ROOT / "제출_패키지" / "학습데이터_설계서_DecisionMiner_v2_4.xlsx"

DQ = ROOT / "11_data_quality"
QA_CSV = DQ / "qa_evaluated_990.csv"
QC_CSV = DQ / "qc_result_990.csv"
SUMMARY_CSV = DQ / "dataset_summary_22.csv"
FACTS_CSV = DQ / "dataset_facts_22.csv"
CLASS_CSV = DQ / "dataset_classification_22.csv"
INFER_CSV = DQ / "dataset_inference_22.csv"

# 양식 17열 헤더 매핑 (양식 그대로)
QA_COL_HEADERS_BASE = [
    "ID", "페르소나", "질문유형", "난이도", "주제", "질문", "답변", "근거",
    "주제별·수준별 의결서 요약", "사실(Facts)", "법리 해석",
    "기본 시나리오", "추가 시나리오", "응답 설계 포인트", "의도된 설명 스타일",
    "_SHEET_DEPENDENT_", "문제점 및 해결방안",
]
COL16_BY_SHEET = {
    "전체_QA": "근거",
    "일반국민": "주의사항",
    "기업 컴플라이언스 담당자": "주의사항",
    "논문 준비 학생": "비고",
}

# 서식 (양식 행 1·2·3은 보존되므로 신규 시트만 적용)
HDR_FILL = PatternFill("solid", fgColor="1F4E78")
HDR_FONT = Font(bold=True, color="FFFFFF", name="맑은 고딕", size=11)
CELL_FONT = Font(name="맑은 고딕", size=10)
HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGN = Alignment(wrap_text=True, vertical="top")
THIN = Side(border_style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ─── 데이터 로드 ──────────────────────────────────
def load_csv(path):
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ─── 17열 행 빌드 ──────────────────────────────────
def short_keyword(case_key, summary_short):
    """주제 컬럼용: 사건 핵심 키워드 추출."""
    text = summary_short or case_key
    # 첫 1~2 절(어절 단위 4~6개)을 핵심 키워드로
    cleaned = re.sub(r"\([^)]*\)", "", case_key)
    if "에 대한 건" in cleaned:
        cleaned = cleaned.split("에 대한 건")[0]
    cleaned = cleaned.replace("의 ", " ").strip()
    # summary_short의 첫 문장에서 핵심 동작
    first = (summary_short or "").split(".")[0]
    if first and len(first) > 10:
        return f"{cleaned}".strip()
    return cleaned


def build_topic(case_type, case_key, summary_short):
    """5번 컬럼 — 사건유형 / 사건 키워드."""
    kw = short_keyword(case_key, summary_short)
    return f"{case_type} / {kw}" if case_type else kw


def build_summary_by_level(level, summary_short, case_type):
    """9번 — 난이도별 의결서 요약."""
    if not summary_short:
        return f"{case_type} 사건 요약 (정보 없음)"
    if level == "기초":
        return f"[기초 요약] {summary_short[:120]}{'…' if len(summary_short) > 120 else ''}"
    elif level == "심화":
        return f"[심화 요약] {summary_short}"
    else:  # 전문가
        return f"[전문가 요약] {summary_short} (사건유형: {case_type}, 의결서 본문 § 1~4 참조)"


def build_facts_block(facts_row):
    """10번 — 사실관계 결합."""
    parts = []
    for k in ("당사자", "기간", "행위", "피해규모", "피해범위"):
        v = (facts_row.get(k) or "").strip()
        if v:
            parts.append(f"{k}: {v}")
    return " | ".join(parts) or "사실관계 정보 없음"


def build_inference_block(infer_row):
    """11번 — 법리 해석 (전제→결론)."""
    p1 = (infer_row.get("전제1") or "").strip()
    p2 = (infer_row.get("전제2") or "").strip()
    cn = (infer_row.get("결론") or "").strip()
    parts = []
    if p1: parts.append(f"전제1: {p1[:200]}")
    if p2: parts.append(f"전제2: {p2[:200]}")
    if cn: parts.append(f"결론: {cn[:150]}")
    return " ▸ ".join(parts) or "법리 해석 정보 없음"


def build_basic_scenario(classif_row, persona):
    """12번 — 기본 시나리오."""
    industry = (classif_row.get("산업분야") or "").strip()
    sub = (classif_row.get("사건유형_세분류") or "").strip()
    if persona == "일반국민":
        return f"소비자가 {industry or '관련 시장'}에서 {sub or '본 사건 유형'} 피해를 인지하고 신고·구제 절차를 검토하는 상황"
    elif persona == "기업 컴플라이언스 담당자":
        return f"{industry or '해당 산업'} 기업의 컴플라이언스 담당자가 {sub or '본 사건 유형'} 위반 리스크를 점검하는 상황"
    else:
        return f"법학·정책 연구자가 {industry or '관련 산업'}의 {sub or '본 사건 유형'} 사례를 학술 분석하는 상황"


def build_extra_scenario(classif_row, persona):
    """13번 — 추가 시나리오."""
    laws = (classif_row.get("위반조문") or "").strip()
    if persona == "일반국민":
        return f"유사 피해 사례 검색 / 집단분쟁조정 신청 검토 / {laws} 적용 여부 확인"
    elif persona == "기업 컴플라이언스 담당자":
        return f"내부 거래·약관 점검 / 임직원 교육 자료 작성 / {laws} 위반 사전예방"
    else:
        return f"공정거래법·{laws} 비교 연구 / 학회 발표·논문 인용 / 정책 제언 검토"


PERSONA_DESIGN = {
    "일반국민": "쉬운 어휘·일상 표현 우선, 신고·구제 가이드 포함",
    "기업 컴플라이언스 담당자": "조문·판단요건 정확 인용, 내부통제 시사점 제시",
    "논문 준비 학생": "법리 분석·선례 비교, 인용 가능 형식의 서술",
}

LENGTH_GUIDE = {
    ("일반국민", "기초"): "200~400자, 평이한 표현",
    ("일반국민", "심화"): "300~600자, 사례 비교 포함",
    ("일반국민", "전문가"): "400~800자, 일부 법령 명시",
    ("기업 컴플라이언스 담당자", "기초"): "300~500자, 조문 1~2개 인용",
    ("기업 컴플라이언스 담당자", "심화"): "400~700자, 판단요건 명시",
    ("기업 컴플라이언스 담당자", "전문가"): "600~1000자, 다중 조문·실무 시사점",
    ("논문 준비 학생", "기초"): "300~500자, 학술 용어 도입",
    ("논문 준비 학생", "심화"): "500~800자, 법리 분석 + 선례",
    ("논문 준비 학생", "전문가"): "700~1200자, 정밀 인용·비교법",
}


def build_response_design(persona):
    return PERSONA_DESIGN.get(persona, "")


def build_style(persona, level):
    g = LENGTH_GUIDE.get((persona, level), "")
    return f"{persona}·{level}: {g}" if g else f"{persona}·{level}"


def build_col16(sheet_name, qa_row, classif_row):
    case_type = (classif_row.get("사건유형_대분류") or "").strip()
    level = qa_row.get("난이도", "")
    if sheet_name == "전체_QA":
        return qa_row.get("근거", "")
    elif sheet_name == "논문 준비 학생":
        return (
            f"본 QA의 학술 활용 시 보충 참조: {case_type} 분야 인접 의결서 또는 판례 비교 검토. "
            f"확장 연구 방향: 페르소나·난이도({level}) 매트릭스 기반 학습데이터 효용 측정."
        )
    else:
        # 일반국민 / 기업 컴플라이언스 담당자 — 주의사항
        if sheet_name == "일반국민":
            return (
                f"실의결서 전환 시 검증 유의사항: {case_type}·{level} 단계에서는 "
                f"① 처분결과 금액·과징금 표기 정확성, ② 일반국민 이해도 적합성을 우선 점검."
            )
        else:  # 기업 컴플라이언스
            return (
                f"실의결서 전환 시 검증 유의사항: {case_type}·{level} 단계에서는 "
                f"① 적용 조문 정확성, ② 내부 컴플라이언스 시사점 명시 여부를 우선 점검."
            )


def build_col17(qa_row, qc_row):
    """17번 — 4요소 형식 (자동검수/보정지침/유의사항/학습권장)."""
    persona = qa_row.get("페르소나", "")
    level = qa_row.get("난이도", "")
    qtype = qa_row.get("질문유형", "")
    score = qa_row.get("Confidence_Score", "")
    judgment = qa_row.get("검수자_평가", "")

    err = qc_row.get("error_codes", "") if qc_row else ""
    warn = qc_row.get("warning_flags", "") if qc_row else ""
    note = qc_row.get("correction_note", "") if qc_row else ""
    details = qc_row.get("error_details", "") if qc_row else ""
    err_short = (details[:80] + "…") if len(details) > 80 else details

    # [자동 검수 결과]
    parts = []
    line1 = (
        f"[자동 검수 결과] 본 QA는 5단계 자동 검수에서 {score}점({judgment} 판정)으로 분류되었으며, "
    )
    if err:
        line1 += f"오류코드 {err}({err_short}) "
        if warn:
            line1 += f"및 확인필요 플래그 {warn}이(가) 식별됨."
        else:
            line1 += "이 식별됨."
    elif warn:
        line1 += f"오류코드는 없으며 확인필요 플래그 {warn}이(가) 식별됨."
    else:
        line1 += "오류코드·확인필요 플래그 없이 통과."
    parts.append(line1)

    # [보정 지침]
    if judgment == "Gold":
        parts.append("[보정 지침] 본 QA는 5단계 검수 무결점 통과. 활용 시 별도 보정 불필요.")
    elif note:
        parts.append(f"[보정 지침] {note}")
    else:
        parts.append("[보정 지침] 자동 보정 지침은 도출되지 않음. 인간 검수자 판단 권장.")

    # [활용 시 유의사항]
    caveat_map = {
        "일반국민": "전문 법률용어 사용을 자제하고 신고·구제 안내 중심으로 답변 검증",
        "기업 컴플라이언스 담당자": "조문 인용 정확성과 내부통제 시사점 제시 여부를 추가 검토",
        "논문 준비 학생": "법리 분석 깊이와 선례·비교법 인용의 적정성을 학술적 기준으로 점검",
    }
    parts.append(
        f"[활용 시 유의사항] {persona}·{level} 페르소나·난이도 조합에서는 "
        f"{caveat_map.get(persona, '페르소나 적합성 검토')}."
    )

    # [학습 권장 패턴]
    qtype_rec = {
        "제재중심": "처분결과·과징금 수치 정확성 강화 학습",
        "법령중심": "조문·판단요건 정확 인용 학습",
        "유사사례": "사건유형 간 유사도 변별 학습",
        "통계기반": "수치·비율 근거 매핑 학습",
        "시장영향": "근거 외 과잉추론 억제 학습",
    }
    parts.append(
        f"[학습 권장 패턴] 후속 모델 학습 시 {qtype_rec.get(qtype, '질문유형 적합 답변 패턴')} 권장."
    )

    return " ".join(parts)


def build_qa_data_row(sheet_name, qa_row, qc_row, summary_map, facts_map, classif_map, infer_map):
    """양식 17열에 맞는 데이터 행 1개 생성."""
    case_key = qa_row.get("사건키", "")
    persona = qa_row.get("페르소나", "")
    level = qa_row.get("난이도", "")
    qtype = qa_row.get("질문유형", "")

    summary_row = summary_map.get(case_key, {})
    facts_row = facts_map.get(case_key, {})
    classif_row = classif_map.get(case_key, {})
    infer_row = infer_map.get(case_key, {})

    case_type = (classif_row.get("사건유형_대분류") or qa_row.get("사건유형") or "").strip()
    summary_short = summary_row.get("summary_short", "")

    return [
        qa_row.get("ID", ""),                                     # 1 ID
        persona,                                                  # 2 페르소나
        qtype,                                                    # 3 질문유형
        level,                                                    # 4 난이도
        build_topic(case_type, case_key, summary_short),          # 5 주제
        qa_row.get("질문", ""),                                    # 6 질문
        qa_row.get("답변", ""),                                    # 7 답변
        qa_row.get("근거", ""),                                    # 8 근거
        build_summary_by_level(level, summary_short, case_type),   # 9 의결서 요약
        build_facts_block(facts_row),                              # 10 사실(Facts)
        build_inference_block(infer_row),                          # 11 법리 해석
        build_basic_scenario(classif_row, persona),                # 12 기본 시나리오
        build_extra_scenario(classif_row, persona),                # 13 추가 시나리오
        build_response_design(persona),                            # 14 응답 설계 포인트
        build_style(persona, level),                               # 15 의도된 설명 스타일
        build_col16(sheet_name, qa_row, classif_row),              # 16 시트별
        build_col17(qa_row, qc_row),                               # 17 문제점 및 해결방안
    ]


# ─── QA 4시트 채우기 ──────────────────────────────────
def fill_qa_sheet(ws, sheet_name, qa_rows, qc_index, summary_map, facts_map, classif_map, infer_map):
    """양식의 1·2·3행을 보존하고 4행부터 데이터 입력."""
    # 데이터 영역 클리어 (4행 이후)
    if ws.max_row >= 4:
        for r in range(4, ws.max_row + 1):
            for c in range(1, 18):
                ws.cell(row=r, column=c).value = None

    # 행 입력
    template_cell = ws.cell(row=2, column=1)  # 헤더 셀 (참고용 — 셀 서식은 새로 설정)
    for i, qa_row in enumerate(qa_rows):
        r = 4 + i
        qc_row = qc_index.get(qa_row.get("ID", ""), {})
        values = build_qa_data_row(
            sheet_name, qa_row, qc_row, summary_map, facts_map, classif_map, infer_map
        )
        for c, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = CELL_FONT
            cell.alignment = CELL_ALIGN
            cell.border = BORDER
        ws.row_dimensions[r].height = 80


# ─── 메타·검수·관리 시트 ──────────────────────────────
def write_table(ws, headers, rows, width_map=None, row_height=70):
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = HDR_ALIGN
        cell.border = BORDER
    ws.row_dimensions[1].height = 26
    for r, row in enumerate(rows, 2):
        for c, h in enumerate(headers, 1):
            v = row.get(h, "") if isinstance(row, dict) else (row[c-1] if c-1 < len(row) else "")
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = CELL_FONT
            cell.alignment = CELL_ALIGN
            cell.border = BORDER
        ws.row_dimensions[r].height = row_height
    width_map = width_map or {}
    for c, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(c)].width = width_map.get(h, 22)
    ws.freeze_panes = "A2"


def add_meta_sheets(wb, summary_rows, facts_rows, classif_rows, infer_rows):
    META_W = {
        "ID": 14, "사건키": 38, "사건유형": 14, "사건유형_대분류": 14, "사건유형_세분류": 30,
        "적용법령": 18, "처분결과": 32, "summary_short": 70, "의결일": 12, "출처": 22,
        "당사자": 40, "기간": 22, "행위": 50, "피해규모": 30, "피해범위": 30,
        "위반조문": 30, "처분유형": 18, "산업분야": 22, "신뢰도": 10,
        "전제1": 60, "전제2": 60, "결론": 50, "근거": 60, "적용조문": 16,
    }
    for sheet_name, rows in [
        ("요약_데이터셋", summary_rows),
        ("사실관계_데이터셋", facts_rows),
        ("분류_데이터셋", classif_rows),
        ("추론_데이터셋", infer_rows),
    ]:
        if sheet_name in wb.sheetnames:
            del wb[sheet_name]
        ws = wb.create_sheet(sheet_name)
        if rows:
            headers = list(rows[0].keys())
            write_table(ws, headers, rows, META_W, row_height=70)


def add_inspection_sheet(wb, qa_rows, qc_rows):
    """검수_결과표 — 사건별 22행 + 전체 통계 1행."""
    if "검수_결과표" in wb.sheetnames:
        del wb["검수_결과표"]
    ws = wb.create_sheet("검수_결과표")

    # 사건별 집계
    by_case = {}
    for r in qc_rows:
        ck = r["사건키"]
        by_case.setdefault(ck, []).append(r)

    case_summary = []
    for ck, rs in sorted(by_case.items()):
        scores = [int(x["score_total"]) for x in rs if x["score_total"]]
        judg = Counter(x["judgment"] for x in rs)
        err_codes = []
        warn_codes = []
        for x in rs:
            if x.get("error_codes"):
                err_codes.extend(c.strip() for c in x["error_codes"].split(",") if c.strip())
            if x.get("warning_flags"):
                warn_codes.extend(c.strip() for c in x["warning_flags"].split(",") if c.strip())
        top_err = ", ".join(f"{c}({n})" for c, n in Counter(err_codes).most_common(3))
        top_warn = ", ".join(f"{c}({n})" for c, n in Counter(warn_codes).most_common(3))
        case_summary.append({
            "사건키": ck,
            "총 QA수": len(rs),
            "평균점수": round(sum(scores)/len(scores), 1) if scores else 0,
            "Gold": judg.get("Gold", 0),
            "보정필요": judg.get("보정필요", 0),
            "탈락": judg.get("탈락", 0),
            "주요 오류": top_err or "—",
            "주요 경고": top_warn or "—",
        })

    # Section 1
    headers = ["사건키", "총 QA수", "평균점수", "Gold", "보정필요", "탈락", "주요 오류", "주요 경고"]
    width_map = {"사건키": 38, "총 QA수": 10, "평균점수": 10, "Gold": 8, "보정필요": 10,
                 "탈락": 8, "주요 오류": 30, "주요 경고": 35}
    write_table(ws, headers, case_summary, width_map, row_height=30)

    # Section 2 — 전체 통계
    n = len(qc_rows)
    scores = [int(x["score_total"]) for x in qc_rows if x["score_total"]]
    avg = sum(scores)/n if scores else 0
    judg = Counter(x["judgment"] for x in qc_rows)
    err_codes, warn_codes = [], []
    for x in qc_rows:
        if x.get("error_codes"):
            err_codes.extend(c.strip() for c in x["error_codes"].split(",") if c.strip())
        if x.get("warning_flags"):
            warn_codes.extend(c.strip() for c in x["warning_flags"].split(",") if c.strip())
    top_err = ", ".join(f"{c} {n_}" for c, n_ in Counter(err_codes).most_common(4))
    top_warn = ", ".join(f"{c} {n_}" for c, n_ in Counter(warn_codes).most_common(5))

    blank_r = len(case_summary) + 3
    ws.cell(row=blank_r, column=1, value="── 전체 통계 ──").font = HDR_FONT
    ws.cell(row=blank_r, column=1).fill = PatternFill("solid", fgColor="DCE6F1")

    overall = blank_r + 1
    ws.cell(row=overall, column=1, value=f"총 {n}건 / 평균 {round(avg,1)}점")
    ws.cell(row=overall, column=2, value=f"Gold {judg.get('Gold',0)} ({judg.get('Gold',0)/n*100:.1f}%)")
    ws.cell(row=overall, column=3, value=f"보정필요 {judg.get('보정필요',0)} ({judg.get('보정필요',0)/n*100:.1f}%)")
    ws.cell(row=overall, column=4, value=f"탈락 {judg.get('탈락',0)} ({judg.get('탈락',0)/n*100:.1f}%)")
    ws.cell(row=overall+1, column=1, value=f"오류 TOP: {top_err}")
    ws.merge_cells(start_row=overall+1, start_column=1, end_row=overall+1, end_column=4)
    ws.cell(row=overall+2, column=1, value=f"확인필요 TOP: {top_warn}")
    ws.merge_cells(start_row=overall+2, start_column=1, end_row=overall+2, end_column=4)
    for r in range(overall, overall+3):
        for c in range(1, 9):
            cell = ws.cell(row=r, column=c)
            cell.font = CELL_FONT
            cell.alignment = CELL_ALIGN


def add_legal_review_sheet(wb):
    """법리_검수 — 양식만 (06_review에 데이터 CSV 없음)."""
    if "법리_검수" in wb.sheetnames:
        del wb["법리_검수"]
    ws = wb.create_sheet("법리_검수")
    headers = ["QA_ID", "사건키", "자동검수_판정", "인간_판정", "일치여부",
               "인간_식별_위험요소", "인간_검수자_메모"]
    width_map = {"QA_ID": 30, "사건키": 38, "자동검수_판정": 14, "인간_판정": 14,
                 "일치여부": 10, "인간_식별_위험요소": 30, "인간_검수자_메모": 40}
    write_table(ws, headers, [], width_map, row_height=24)
    # 안내문
    ws.cell(row=2, column=1, value="(06_review/B_*.csv 도착 후 30건 입력 예정)")
    ws.cell(row=2, column=1).font = Font(italic=True, color="888888", name="맑은 고딕")


def fill_dashboard(wb, qa_rows, qc_rows):
    """양식 시트 '대시보드' 덮어쓰기."""
    ws = wb["대시보드"]
    # 1행 제목 머지(A1:I1)는 보존, 그 외 모든 머지는 해제
    for mr in list(ws.merged_cells.ranges):
        if str(mr) != "A1:I1":
            ws.unmerge_cells(str(mr))
    # 기존 셀 클리어 (1행 제목 머지셀 보존)
    for r in range(2, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            try:
                ws.cell(row=r, column=c).value = None
            except AttributeError:
                pass

    # 1행 제목 갱신 (머지 보존)
    ws.cell(row=1, column=1, value="페르소나 기반 QA 데이터셋 대시보드 (990건)")

    n = len(qa_rows)
    persona = Counter(r["페르소나"] for r in qa_rows)
    level = Counter(r["난이도"] for r in qa_rows)
    qtype = Counter(r["질문유형"] for r in qa_rows)
    judg = Counter(r["검수자_평가"] for r in qa_rows)
    scores = [int(r["Confidence_Score"]) for r in qa_rows if r.get("Confidence_Score","").strip()]
    avg = sum(scores)/len(scores) if scores else 0

    # Layout
    ws.cell(row=3, column=1, value="전체 건수")
    ws.cell(row=3, column=2, value=n)

    ws.cell(row=5, column=1, value="페르소나"); ws.cell(row=5, column=2, value="건수")
    ws.cell(row=5, column=4, value="질문유형"); ws.cell(row=5, column=5, value="건수")
    for i, p in enumerate(["일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생"]):
        ws.cell(row=6+i, column=1, value=p)
        ws.cell(row=6+i, column=2, value=persona.get(p, 0))
    for i, q in enumerate(["제재중심", "법령중심", "유사사례", "통계기반", "시장영향"]):
        ws.cell(row=6+i, column=4, value=q)
        ws.cell(row=6+i, column=5, value=qtype.get(q, 0))

    ws.cell(row=11, column=1, value="난이도"); ws.cell(row=11, column=2, value="건수")
    for i, l in enumerate(["기초", "심화", "전문가"]):
        ws.cell(row=12+i, column=1, value=l)
        ws.cell(row=12+i, column=2, value=level.get(l, 0))

    ws.cell(row=15, column=1, value="자동 검수 결과"); ws.cell(row=15, column=2, value="건수")
    ws.cell(row=16, column=1, value="Gold");      ws.cell(row=16, column=2, value=f"{judg.get('Gold',0)}건 ({judg.get('Gold',0)/n*100:.1f}%)")
    ws.cell(row=17, column=1, value="보정필요");   ws.cell(row=17, column=2, value=f"{judg.get('보정필요',0)}건 ({judg.get('보정필요',0)/n*100:.1f}%)")
    ws.cell(row=18, column=1, value="탈락");      ws.cell(row=18, column=2, value=f"{judg.get('탈락',0)}건 ({judg.get('탈락',0)/n*100:.1f}%)")
    ws.cell(row=19, column=1, value="평균 점수");  ws.cell(row=19, column=2, value=f"{round(avg,1)}점")

    # 주요 안내
    ws.cell(row=12, column=4, value="주요 안내")
    notes = [
        "본 데이터셋은 공정거래위원회 의결서 22건 기반 합성 학습데이터입니다.",
        "자동 검수 + 인간 교차검증 30건으로 품질을 측정·문서화하였습니다.",
        "17번째 컬럼은 5단계 자동 검수 + 인간 교차검증 결과를 종합한 품질관리 컬럼입니다.",
    ]
    for i, t in enumerate(notes):
        ws.cell(row=13+i, column=4, value=t)

    # 폰트
    for r in range(2, 25):
        for c in range(1, 10):
            cell = ws.cell(row=r, column=c)
            if cell.value is not None:
                cell.font = CELL_FONT
                cell.alignment = Alignment(vertical="center", wrap_text=True)


def fill_data_dictionary(wb):
    ws = wb["데이터사전"]
    # 기존 데이터 클리어 (1행 제목 머지 보존)
    for r in range(3, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            try:
                ws.cell(row=r, column=c).value = None
            except AttributeError:
                pass

    # 헤더 (양식과 동일)
    ws.cell(row=2, column=1, value="항목")
    ws.cell(row=2, column=2, value="설명")

    items = [
        ("ID", "QA 레코드 식별자 (사건키_001~045)"),
        ("페르소나", "일반국민 / 기업 컴플라이언스 담당자 / 논문 준비 학생"),
        ("질문유형", "제재중심 / 법령중심 / 유사사례 / 통계기반 / 시장영향"),
        ("난이도", "기초 / 심화 / 전문가"),
        ("주제", "사건유형 / 사건 핵심 키워드 결합"),
        ("질문", "페르소나·난이도 맞춤 질의"),
        ("답변", "페르소나·난이도 맞춤 응답"),
        ("근거", "evidence.json 매핑 근거 텍스트 (≤1500자)"),
        ("주제별·수준별 의결서 요약", "난이도별 길이·표현 분기된 사건 요약"),
        ("사실(Facts)", "당사자·기간·행위·피해규모·피해범위 결합"),
        ("법리 해석", "전제1(법령확인) → 전제2(구성요건) → 결론(위반)"),
        ("기본 시나리오", "페르소나 대표 사용 시나리오"),
        ("추가 시나리오", "페르소나 확장 시나리오"),
        ("응답 설계 포인트", "페르소나별 답변 원칙"),
        ("의도된 설명 스타일", "페르소나·난이도별 톤·길이 가이드"),
        ("16번 컬럼 (시트별)", "전체_QA=근거(재인용) / 일반국민·기업컴플=주의사항 / 학생=비고"),
        ("문제점 및 해결방안", "[자동검수][보정지침][활용유의][학습권장] 4요소 형식"),
        ("", ""),
        ("── 시트 정의 ──", ""),
        ("전체_QA", "990건 — 모든 QA 학습데이터 (17열)"),
        ("일반국민", "330건 — 일반국민 페르소나 (16번=주의사항)"),
        ("기업 컴플라이언스 담당자", "330건 — 기업 페르소나 (16번=주의사항)"),
        ("논문 준비 학생", "330건 — 학생 페르소나 (16번=비고)"),
        ("요약_데이터셋", "22건 — 사건 단위 요약"),
        ("사실관계_데이터셋", "22건 — 사건 단위 사실관계"),
        ("분류_데이터셋", "22건 — 사건 단위 분류"),
        ("추론_데이터셋", "22건 — 사건 단위 추론"),
        ("검수_결과표", "사건별 22행 + 전체 통계 — 자동 검수 요약"),
        ("법리_검수", "최대 30건 — 인간 교차검증 결과 (06_review/ 도착 후 입력)"),
        ("대시보드", "990건 분포 통계"),
        ("데이터사전", "본 시트"),
    ]
    for i, (k, v) in enumerate(items, start=3):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
        for c in (1, 2):
            cell = ws.cell(row=i, column=c)
            cell.font = CELL_FONT
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 70


def reorder_sheets(wb):
    """시트 순서: 전체_QA → 페르소나 3 → 메타 4 → 검수_결과표 → 법리_검수 → 대시보드 → 데이터사전."""
    desired = [
        "전체_QA", "일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생",
        "요약_데이터셋", "사실관계_데이터셋", "분류_데이터셋", "추론_데이터셋",
        "검수_결과표", "법리_검수", "대시보드", "데이터사전",
    ]
    # openpyxl 순서 변경
    wb._sheets = [wb[name] for name in desired if name in wb.sheetnames]


# ─── 메인 ─────────────────────────────────────────────
def main():
    print("▶ 빈 양식 복사")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATE, OUT)

    print("▶ CSV 로드")
    qa_rows = load_csv(QA_CSV); print(f"  QA: {len(qa_rows)}행")
    qc_rows = load_csv(QC_CSV); print(f"  QC: {len(qc_rows)}행")
    summary_rows = load_csv(SUMMARY_CSV); print(f"  Summary: {len(summary_rows)}행")
    facts_rows = load_csv(FACTS_CSV); print(f"  Facts: {len(facts_rows)}행")
    classif_rows = load_csv(CLASS_CSV); print(f"  Classification: {len(classif_rows)}행")
    infer_rows = load_csv(INFER_CSV); print(f"  Inference: {len(infer_rows)}행")

    qc_index = {r["QA_ID"]: r for r in qc_rows}
    summary_map = {r["사건키"]: r for r in summary_rows}
    facts_map = {r["사건키"]: r for r in facts_rows}
    classif_map = {r["사건키"]: r for r in classif_rows}
    infer_map = {r["사건키"]: r for r in infer_rows}

    print("\n▶ 양식 열기 (1·2·3행 보존 모드)")
    wb = load_workbook(OUT)
    print(f"  베이스 시트: {wb.sheetnames}")

    # QA 4시트 채우기
    print("\n▶ QA 4시트 데이터 입력 (4행부터)")
    for sheet_name in ["전체_QA", "일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생"]:
        if sheet_name == "전체_QA":
            rows = qa_rows
        elif sheet_name == "논문 준비 학생":
            rows = [r for r in qa_rows if r["페르소나"] == "논문 준비 학생"]
        else:
            rows = [r for r in qa_rows if r["페르소나"] == sheet_name]
        ws = wb[sheet_name]
        # 16번 컬럼 헤더 검증 (양식 그대로)
        actual_h16 = ws.cell(row=2, column=16).value
        expected = COL16_BY_SHEET[sheet_name]
        if actual_h16 != expected:
            raise SystemExit(f"❌ {sheet_name} 16번 헤더 불일치: 양식 '{actual_h16}' ≠ 기대 '{expected}'")
        fill_qa_sheet(ws, sheet_name, rows, qc_index, summary_map, facts_map, classif_map, infer_map)
        print(f"  ✓ {sheet_name}: {len(rows)}행 (R{4}~R{4+len(rows)-1})  16번='{actual_h16}'")

    # 메타 4시트
    print("\n▶ 메타 4시트 신규 추가")
    add_meta_sheets(wb, summary_rows, facts_rows, classif_rows, infer_rows)
    print(f"  ✓ 요약/사실관계/분류/추론 각 22행")

    # 검수 시트
    print("\n▶ 검수_결과표 신규 추가")
    add_inspection_sheet(wb, qa_rows, qc_rows)
    print(f"  ✓ 사건별 22행 + 전체 통계")

    # 법리_검수
    print("\n▶ 법리_검수 신규 추가 (헤더만)")
    add_legal_review_sheet(wb)
    print(f"  ✓ 7열 헤더 + 안내")

    # 대시보드 덮어쓰기
    print("\n▶ 대시보드 덮어쓰기 (990건 실측치)")
    fill_dashboard(wb, qa_rows, qc_rows)
    print(f"  ✓ 페르소나/질문유형/난이도/검수결과 박음")

    # 데이터사전 덮어쓰기
    print("\n▶ 데이터사전 덮어쓰기 (난이도 enum 갱신 + 12시트 정의 추가)")
    fill_data_dictionary(wb)
    print(f"  ✓ 항목 31개 박음")

    # 시트 순서
    reorder_sheets(wb)
    print(f"\n▶ 시트 순서: {wb.sheetnames}")

    print(f"\n▶ 저장: {OUT}")
    wb.save(OUT)

    # ─── 검증 ─────
    print("\n" + "=" * 60)
    print("검증 (11개 항목)")
    print("=" * 60)

    wb2 = load_workbook(OUT)
    sheets = wb2.sheetnames

    print(f"\n[1] 12시트 모두 채워짐: {len(sheets)}개")
    expected_order = ["전체_QA","일반국민","기업 컴플라이언스 담당자","논문 준비 학생",
                      "요약_데이터셋","사실관계_데이터셋","분류_데이터셋","추론_데이터셋",
                      "검수_결과표","법리_검수","대시보드","데이터사전"]
    print(f"[10] 시트 순서: {'✓' if sheets == expected_order else '✗'}")
    for i, s in enumerate(sheets, 1):
        n_rows = wb2[s].max_row
        print(f"   {i:2}. {s}: max_row={n_rows}")

    # 헤더 검증
    print(f"\n[2] QA 4시트 17열 헤더 (2행 기준)")
    for s in ["전체_QA","일반국민","기업 컴플라이언스 담당자","논문 준비 학생"]:
        ws = wb2[s]
        h16 = ws.cell(row=2, column=16).value
        ok = h16 == COL16_BY_SHEET[s]
        print(f"  {s}: 16번='{h16}' {'✓' if ok else '✗'}")

    # 데이터 4행부터
    print(f"\n[3] QA 4시트 데이터 4행부터 입력")
    for s in ["전체_QA","일반국민","기업 컴플라이언스 담당자","논문 준비 학생"]:
        ws = wb2[s]
        r3_q = ws.cell(row=3, column=17).value
        r4_a = ws.cell(row=4, column=1).value
        r4_q = ws.cell(row=4, column=17).value
        ok = r4_a is not None and r4_q is not None and r3_q is not None
        print(f"  {s}: R3Q존재={r3_q is not None}, R4A존재={r4_a is not None}, R4Q존재={r4_q is not None} {'✓' if ok else '✗'}")

    # enum 검증
    print(f"\n[5] enum 일치 (난이도)")
    ws = wb2["전체_QA"]
    levels_in_data = set()
    for r in range(4, ws.max_row + 1):
        v = ws.cell(row=r, column=4).value
        if v: levels_in_data.add(v)
    expected_levels = {"기초", "심화", "전문가"}
    print(f"  사용된 난이도: {levels_in_data} {'✓' if levels_in_data == expected_levels else '✗'}")

    # 데이터사전 난이도 체크
    print(f"\n[6] 데이터사전 난이도 정의")
    ws = wb2["데이터사전"]
    for r in range(3, 8):
        a = ws.cell(row=r, column=1).value
        b = ws.cell(row=r, column=2).value
        if a == "난이도":
            ok = "기초" in str(b) and "심화" in str(b) and "전문가" in str(b)
            print(f"  난이도 정의: '{b}' {'✓' if ok else '✗'}")
            break

    # 대시보드 990건
    print(f"\n[7] 대시보드 990건 박힘")
    ws = wb2["대시보드"]
    title = ws.cell(row=1, column=1).value
    total = ws.cell(row=3, column=2).value
    print(f"  제목: '{title}'")
    print(f"  전체 건수: {total} {'✓' if total == 990 else '✗'}")

    # 17번 컬럼 빈값 없음
    print(f"\n[8] 17번 컬럼 모든 990건 채워짐")
    for s in ["전체_QA","일반국민","기업 컴플라이언스 담당자","논문 준비 학생"]:
        ws = wb2[s]
        n_data = ws.max_row - 3  # 데이터는 4행부터
        n_filled = sum(1 for r in range(4, ws.max_row + 1)
                       if ws.cell(row=r, column=17).value)
        ok = n_filled == n_data
        print(f"  {s}: {n_filled}/{n_data} {'✓' if ok else '✗'}")

    # 17번 4요소 형식
    print(f"\n[9] 17번 컬럼 4요소 형식")
    ws = wb2["전체_QA"]
    sample = ws.cell(row=4, column=17).value or ""
    elements = ["[자동 검수 결과]", "[보정 지침]", "[활용 시 유의사항]", "[학습 권장 패턴]"]
    has_all = all(e in sample for e in elements)
    print(f"  R4 4요소 모두 포함: {'✓' if has_all else '✗'}")
    print(f"  샘플 (앞 200자): {sample[:200]}…")

    # 1·2·3행 보존
    print(f"\n[11] 1·2·3행 보존 검증")
    for s in ["전체_QA","일반국민","기업 컴플라이언스 담당자","논문 준비 학생"]:
        ws = wb2[s]
        r1 = ws.cell(row=1, column=1).value
        r2_a = ws.cell(row=2, column=1).value
        r3_q = ws.cell(row=3, column=17).value
        ok = r1 is not None and r2_a == "ID" and r3_q is not None
        print(f"  {s}: R1='{str(r1)[:40]}' R2A='{r2_a}' R3Q존재={r3_q is not None} {'✓' if ok else '✗'}")

    print(f"\n출력: {OUT}")


if __name__ == "__main__":
    main()
