"""
qa_evaluated_990.csv + dataset_*_22.csv 4종 → 학습데이터_설계서_구조_v3.4.xlsx (12시트)
기존 양식은 백업 후 새 Workbook으로 재생성.
"""
import csv
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
DQ = ROOT / "11_data_quality"
OUT_DIR = ROOT / "05_xlsx"
TARGET = OUT_DIR / "학습데이터_설계서_구조_v3.4.xlsx"
CKPT = OUT_DIR / "checkpoints"

QA_CSV = DQ / "qa_evaluated_990.csv"
SUMMARY_CSV = DQ / "dataset_summary_22.csv"
FACTS_CSV = DQ / "dataset_facts_22.csv"
CLASS_CSV = DQ / "dataset_classification_22.csv"
INFER_CSV = DQ / "dataset_inference_22.csv"

# 서식 (fill_xlsx.py 재사용)
HDR_FILL = PatternFill("solid", fgColor="4472C4")
HDR_FONT = Font(bold=True, color="FFFFFF", name="맑은 고딕", size=10)
CELL_FONT = Font(name="맑은 고딕", size=9)
CELL_ALIGN = Alignment(wrap_text=True, vertical="top")
HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN = Side(border_style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# 시트 폭 프리셋
QA17_WIDTHS = {
    "ID": 30, "사건키": 35, "사건유형": 12, "페르소나": 18, "난이도": 8,
    "질문유형": 10, "질문": 50, "답변": 80, "핵심키워드": 18,
    "적용법령": 18, "적용조문": 16, "처분결과": 30, "근거": 60,
    "Confidence_Score": 14, "검수자_평가": 12, "비고": 16,
    "문제점_및_해결방안": 40,
}
META_WIDTHS = {
    "ID": 14, "사건키": 35, "사건유형": 12, "사건유형_대분류": 14, "사건유형_세분류": 30,
    "적용법령": 18, "처분결과": 30, "summary_short": 70, "의결일": 12, "출처": 22,
    "당사자": 40, "기간": 22, "행위": 50, "피해규모": 30, "피해범위": 30,
    "위반조문": 28, "처분유형": 18, "산업분야": 22, "신뢰도": 10,
    "전제1": 60, "전제2": 60, "결론": 50, "근거": 60, "적용조문": 16,
}


def load_csv(path):
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_table(ws, headers, rows, width_map=None, row_height=60):
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = HDR_ALIGN
        cell.border = BORDER
    ws.row_dimensions[1].height = 24

    for r, row in enumerate(rows, 2):
        for c, h in enumerate(headers, 1):
            v = row.get(h, "")
            if h == "Confidence_Score" and v != "":
                try: v = int(v)
                except (ValueError, TypeError): pass
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = CELL_FONT
            cell.alignment = CELL_ALIGN
            cell.border = BORDER
        ws.row_dimensions[r].height = row_height

    width_map = width_map or {}
    for c, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(c)].width = width_map.get(h, 18)
    ws.freeze_panes = "A2"


def make_qa_sheets(wb, qa_rows):
    headers = list(qa_rows[0].keys()) if qa_rows else []
    sheet_filters = [
        ("전체_QA", lambda r: True),
        ("일반국민", lambda r: r.get("페르소나") == "일반국민"),
        ("기업 컴플라이언스 담당자", lambda r: r.get("페르소나") == "기업 컴플라이언스 담당자"),
        ("논문 준비 학생", lambda r: r.get("페르소나") == "논문 준비 학생"),
    ]
    sheet_counts = {}
    for name, flt in sheet_filters:
        ws = wb.create_sheet(name)
        rs = [r for r in qa_rows if flt(r)]
        write_table(ws, headers, rs, QA17_WIDTHS, row_height=60)
        sheet_counts[name] = len(rs)
    return sheet_counts


def make_meta_sheets(wb, datasets):
    counts = {}
    for sheet, rows in datasets:
        ws = wb.create_sheet(sheet)
        headers = list(rows[0].keys()) if rows else []
        write_table(ws, headers, rows, META_WIDTHS, row_height=80)
        counts[sheet] = len(rows)
    return counts


def make_inspection_summary(wb, qa_rows):
    ws = wb.create_sheet("검수_결과표")
    judg = Counter(r.get("검수자_평가", "") for r in qa_rows)
    n = len(qa_rows)
    gold = judg.get("Gold", 0)
    corr = judg.get("보정필요", 0)
    rej = judg.get("탈락", 0)
    scores = [int(r["Confidence_Score"]) for r in qa_rows if r.get("Confidence_Score","").strip()]
    avg = sum(scores) / len(scores) if scores else 0.0

    case_types = set(r.get("사건유형", "") for r in qa_rows if r.get("사건유형", "").strip())
    cov = len(case_types - {"기타"})

    headers = ["항목", "측정값", "기준", "달성", "비고"]
    rows = [
        {"항목": "평균 점수", "측정값": f"{avg:.1f}", "기준": "80점 이상", "달성": "달성" if avg >= 80 else "미달", "비고": "정부 표준 5단계"},
        {"항목": "Gold 비율", "측정값": f"{gold}건 ({gold/n*100:.1f}%)", "기준": "-", "달성": "-", "비고": "즉시 활용 가능"},
        {"항목": "보정필요 비율", "측정값": f"{corr}건 ({corr/n*100:.1f}%)", "기준": "-", "달성": "-", "비고": "인간 검수 필요"},
        {"항목": "탈락 비율", "측정값": f"{rej}건 ({rej/n*100:.1f}%)", "기준": "5% 이하", "달성": "달성" if rej/n <= 0.05 else "미달", "비고": "재생성 권장"},
        {"항목": "사건유형 커버리지", "측정값": f"{cov}/11 ({cov/11*100:.1f}%)", "기준": "다양성 확보", "달성": "달성" if cov >= 8 else "미달", "비고": "기타 enum 제외"},
    ]
    write_table(ws, headers, rows, {"항목":18,"측정값":24,"기준":18,"달성":12,"비고":28}, row_height=28)


def make_legal_review(wb):
    ws = wb.create_sheet("법리_검수")
    headers = ["QA_ID","페르소나","사건유형","적용법령","적용조문","판단요건","본건 적용 이유","검수자 평가","신뢰도","환각 유형","보정 메모"]
    write_table(ws, headers, [], {"QA_ID":30,"페르소나":18,"사건유형":12,"적용법령":18,"적용조문":16,"판단요건":40,"본건 적용 이유":50,"검수자 평가":14,"신뢰도":10,"환각 유형":18,"보정 메모":40}, row_height=24)


def make_dashboard(wb, qa_rows, meta_counts):
    ws = wb.create_sheet("대시보드")
    n = len(qa_rows)
    judg = Counter(r.get("검수자_평가", "") for r in qa_rows)
    persona = Counter(r.get("페르소나", "") for r in qa_rows)
    level = Counter(r.get("난이도", "") for r in qa_rows)
    qtype = Counter(r.get("질문유형", "") for r in qa_rows)

    headers = ["구분", "값", "비율"]
    rows = []

    def add(group, key, count, denom=n):
        rows.append({"구분": f"{group}: {key}", "값": count, "비율": f"{count/denom*100:.1f}%" if denom else ""})

    rows.append({"구분": "[전체 QA]", "값": n, "비율": "100.0%"})
    add("판정", "Gold", judg.get("Gold", 0))
    add("판정", "보정필요", judg.get("보정필요", 0))
    add("판정", "탈락", judg.get("탈락", 0))
    rows.append({"구분": "", "값": "", "비율": ""})

    rows.append({"구분": "[페르소나]", "값": "", "비율": ""})
    for p in ["일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생"]:
        add("페르소나", p, persona.get(p, 0))
    rows.append({"구분": "", "값": "", "비율": ""})

    rows.append({"구분": "[난이도]", "값": "", "비율": ""})
    for l in ["기초", "심화", "전문가"]:
        add("난이도", l, level.get(l, 0))
    rows.append({"구분": "", "값": "", "비율": ""})

    rows.append({"구분": "[질문유형]", "값": "", "비율": ""})
    for q in ["제재중심", "법령중심", "유사사례", "통계기반", "시장영향"]:
        add("질문유형", q, qtype.get(q, 0))
    rows.append({"구분": "", "값": "", "비율": ""})

    rows.append({"구분": "[메타 데이터셋]", "값": "", "비율": ""})
    meta_total = sum(meta_counts.values())
    for k, v in meta_counts.items():
        rows.append({"구분": f"메타: {k}", "값": v, "비율": ""})
    rows.append({"구분": "메타 합계", "값": meta_total, "비율": ""})
    rows.append({"구분": "", "값": "", "비율": ""})

    rows.append({"구분": "[총 학습데이터]", "값": n + meta_total, "비율": ""})

    write_table(ws, headers, rows, {"구분": 30, "값": 14, "비율": 12}, row_height=22)


def make_data_dictionary(wb):
    ws = wb.create_sheet("데이터사전")
    headers = ["컬럼명", "의미", "예시", "출처 시트"]

    qa17 = [
        ("ID", "QA 식별자 (사건키_001~045)", "(주)비에이치씨..._001", "전체_QA"),
        ("사건키", "사건 폴더명 (의결서 단위)", "(주)비에이치씨의 가맹사업법위반행위에 대한 건", "전체_QA"),
        ("사건유형", "11종 enum 분류", "가맹사업", "전체_QA"),
        ("페르소나", "응답 대상 (3종)", "일반국민 / 기업 컴플라이언스 담당자 / 논문 준비 학생", "전체_QA"),
        ("난이도", "3단계", "기초 / 심화 / 전문가", "전체_QA"),
        ("질문유형", "5종", "제재중심 / 법령중심 / 유사사례 / 통계기반 / 시장영향", "전체_QA"),
        ("질문", "QA 질문 텍스트", "BHC가 이번에 어떤 처벌을 받은 거예요?", "전체_QA"),
        ("답변", "QA 답변 텍스트 (페르소나별 길이 매트릭스 적용)", "공정거래위원회가 BHC에 시정명령과 과징금 5억 원...", "전체_QA"),
        ("핵심키워드", "facts에서 추출 (선택값)", "", "전체_QA"),
        ("적용법령", "법령명 (약칭 허용)", "가맹사업법", "전체_QA"),
        ("적용조문", "조문 번호", "제12조 제1항 제3호", "전체_QA"),
        ("처분결과", "처분유형 + 과징금 + 시정명령 결합", "시정명령, 과징금 | 과징금 500,000,000원 부과", "전체_QA"),
        ("근거", "evidence.json에서 질문유형별로 결합한 근거 텍스트 (≤1500자)", "주된 광고에는 '최대 5%까지...' 제한사항을 1~3회 클릭해야 확인...", "전체_QA"),
        ("Confidence_Score", "quality_checker 5단계 합산 점수 (0~100)", "97", "전체_QA"),
        ("검수자_평가", "자동 판정", "Gold / 보정필요 / 탈락", "전체_QA"),
        ("비고", "오류 코드 요약 (E1~E10)", "E5,E6", "전체_QA"),
        ("문제점_및_해결방안", "보정 지침 (탈락은 [재생성 권장] 프리픽스)", "[재생성 권장] 과잉추론 표현 삭제 / 질문-근거 연결성 검토", "전체_QA"),
    ]

    summary8 = [
        ("ID", "요약 행 식별자", "summary_001", "요약_데이터셋"),
        ("사건키", "사건 폴더명", "(사)한국과수종묘협회...", "요약_데이터셋"),
        ("사건유형", "11종 enum 분류", "사업자단체", "요약_데이터셋"),
        ("적용법령", "법령명", "공정거래법", "요약_데이터셋"),
        ("처분결과", "처분 결합 텍스트", "시정명령, 과징금 | 과징금 18,000,000원 부과", "요약_데이터셋"),
        ("summary_short", "사건 1~2문장 요약", "과수종묘협회가 7년간 매년 이사회에서 가격을 협정...", "요약_데이터셋"),
        ("의결일", "의결 날짜 (현재 비어있음)", "", "요약_데이터셋"),
        ("출처", "데이터 출처", "공정거래위원회 의결서", "요약_데이터셋"),
    ]

    facts10 = [
        ("ID", "사실관계 행 식별자", "facts_001", "사실관계_데이터셋"),
        ("사건키", "사건 폴더명", "(주)비에이치씨...", "사실관계_데이터셋"),
        ("사건유형", "11종 enum 분류", "가맹사업", "사실관계_데이터셋"),
        ("적용법령", "법령명", "가맹사업법", "사실관계_데이터셋"),
        ("당사자", "피심인/피해자 list (; 결합)", "주식회사 비에이치씨(피심인); 가맹점협의회 회장 7명...", "사실관계_데이터셋"),
        ("기간", "행위 기간", "2018.10~2019.8", "사실관계_데이터셋"),
        ("행위", "위반 행위 요약", "수수료 부담 E쿠폰 취급 강제 및 부당 계약해지", "사실관계_데이터셋"),
        ("피해규모", "피해 규모 (수치)", "7개 가맹점 계약해지, 과징금 5억 원", "사실관계_데이터셋"),
        ("피해범위", "피해 범위 (대상)", "가맹점주 7명 및 1,469개 전체 가맹점 [가맹사업]", "사실관계_데이터셋"),
        ("처분결과", "처분 결합 텍스트", "시정명령, 과징금 | 과징금 500,000,000원 부과", "사실관계_데이터셋"),
    ]

    classif8 = [
        ("ID", "분류 행 식별자", "class_001", "분류_데이터셋"),
        ("사건키", "사건 폴더명", "(주)비에이치씨...", "분류_데이터셋"),
        ("사건유형_대분류", "11종 enum 매핑", "가맹사업", "분류_데이터셋"),
        ("사건유형_세분류", "사건별 세부 분류", "E쿠폰 취급 강제 및 가맹점협의회 활동 이유 부당 계약해지", "분류_데이터셋"),
        ("위반조문", "위반된 조문 풀텍스트", "가맹사업법 제12조 제1항 제1호·제3호, 제14조의2 제5항", "분류_데이터셋"),
        ("처분유형", "처분 list (, 결합)", "시정명령, 과징금", "분류_데이터셋"),
        ("산업분야", "사업 영역", "치킨 가맹사업", "분류_데이터셋"),
        ("신뢰도", "분류 신뢰도 (현재 비어있음)", "", "분류_데이터셋"),
    ]

    infer10 = [
        ("ID", "추론 행 식별자", "infer_001", "추론_데이터셋"),
        ("사건키", "사건 폴더명", "(주)비에이치씨...", "추론_데이터셋"),
        ("사건유형", "11종 enum 분류", "가맹사업", "추론_데이터셋"),
        ("전제1", "inference_chain 1단계 (법령확인)", "가맹사업법 제12조 제1항 제3호: 거래상 지위 남용...", "추론_데이터셋"),
        ("전제2", "inference_chain 2단계 (구성요건)", "본 사건은 ① 거래상 지위 보유 ② 사전 협의 없이 비용 강제 ③ 통지절차 미준수...", "추론_데이터셋"),
        ("결론", "inference_chain 4단계 (결론)", "가맹사업법 제12조 제1항 제3호 위반", "추론_데이터셋"),
        ("근거", "inference_chain 3단계 (근거인용)", "주문 1·2·3항: '수수료 부담이 있는 E쿠폰 취급을 강제...'", "추론_데이터셋"),
        ("적용법령", "법령명", "가맹사업법", "추론_데이터셋"),
        ("적용조문", "조문 번호", "제12조 제1항 제3호", "추론_데이터셋"),
        ("처분결과", "처분 결합 텍스트", "시정명령, 과징금 | 과징금 500,000,000원 부과", "추론_데이터셋"),
    ]

    rows = [{"컬럼명": c, "의미": m, "예시": e, "출처 시트": s}
            for blk in [qa17, summary8, facts10, classif8, infer10]
            for c, m, e, s in blk]
    write_table(ws, headers, rows, {"컬럼명": 22, "의미": 36, "예시": 60, "출처 시트": 18}, row_height=30)


def main():
    print("▶ CSV 로드")
    qa = load_csv(QA_CSV); print(f"  qa_evaluated_990: {len(qa)}행, {len(qa[0])}컬럼")
    summary = load_csv(SUMMARY_CSV); print(f"  dataset_summary_22: {len(summary)}행")
    facts = load_csv(FACTS_CSV); print(f"  dataset_facts_22: {len(facts)}행")
    classif = load_csv(CLASS_CSV); print(f"  dataset_classification_22: {len(classif)}행")
    infer = load_csv(INFER_CSV); print(f"  dataset_inference_22: {len(infer)}행")

    print("\n▶ 백업")
    CKPT.mkdir(parents=True, exist_ok=True)
    backup_path = ""
    if TARGET.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = CKPT / f"v34_backup_{ts}.xlsx"
        shutil.copy2(TARGET, backup_path)
        print(f"  → {backup_path}")
    else:
        print("  (기존 파일 없음, 백업 생략)")

    print("\n▶ Workbook 신규 생성")
    wb = Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    print("  - QA 4시트 작성 중...")
    qa_counts = make_qa_sheets(wb, qa)

    print("  - 메타 4시트 작성 중...")
    meta_counts = make_meta_sheets(wb, [
        ("요약_데이터셋", summary),
        ("사실관계_데이터셋", facts),
        ("분류_데이터셋", classif),
        ("추론_데이터셋", infer),
    ])

    print("  - 검수_결과표 작성 중...")
    make_inspection_summary(wb, qa)

    print("  - 법리_검수 헤더 작성 중...")
    make_legal_review(wb)

    print("  - 대시보드 작성 중...")
    make_dashboard(wb, qa, meta_counts)

    print("  - 데이터사전 작성 중...")
    make_data_dictionary(wb)

    print(f"\n▶ 저장: {TARGET}")
    wb.save(TARGET)

    # 검증
    print("\n" + "=" * 60)
    print("검증")
    print("=" * 60)

    from openpyxl import load_workbook
    wb2 = load_workbook(TARGET, read_only=True)
    sheets = wb2.sheetnames
    print(f"\n[1] 시트 수: {len(sheets)}/12")
    for i, s in enumerate(sheets, 1):
        ws = wb2[s]
        rows_n = ws.max_row - 1  # 헤더 제외
        print(f"  {i:2}. {s}: {rows_n}행")
    wb2.close()

    print("\n[2] QA 17컬럼 시트 (1~4)")
    for name, cnt in qa_counts.items():
        print(f"  {name}: {cnt}행")

    print("\n[3] qa_evaluated_990 4컬럼 충실도")
    cs_n = sum(1 for r in qa if r.get("Confidence_Score","").strip())
    je_n = sum(1 for r in qa if r.get("검수자_평가","").strip())
    bg_n = sum(1 for r in qa if r.get("비고","").strip())
    pn_n = sum(1 for r in qa if r.get("문제점_및_해결방안","").strip())
    n = len(qa)
    print(f"  Confidence_Score: {cs_n}/{n} {'✓' if cs_n==n else '✗'}")
    print(f"  검수자_평가:     {je_n}/{n} {'✓' if je_n==n else '✗'}")
    print(f"  비고:            {bg_n}/{n} (빈값 허용)")
    print(f"  문제점_및_해결방안: {pn_n}/{n} (빈값 허용)")

    print("\n[4] 메타 시트 4종 (5~8)")
    for k, v in meta_counts.items():
        mark = "✓" if v == 22 else "✗"
        print(f"  {k}: {v}행 {mark}")

    print(f"\n[5] 백업: {backup_path or '(생략)'}")
    print(f"[5] 출력: {TARGET}")


if __name__ == "__main__":
    main()
