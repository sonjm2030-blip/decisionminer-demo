import json, re, shutil
from pathlib import Path
from datetime import datetime
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

PROJECT = Path.home() / "Desktop/2026 공정위 공모전/decisionminer_project"
OUTPUT_DIR = PROJECT / "05_xlsx"
OUTPUT_DIR.mkdir(exist_ok=True)
TARGET = OUTPUT_DIR / "학습데이터_설계서_구조_v3.4.xlsx"
CKPT = OUTPUT_DIR / "checkpoints"
CKPT.mkdir(exist_ok=True)

CASES = {
    "쿠팡": "쿠팡(주)의 전자상거래소비자보호법 등 위반행위에 대한 건",
    "네이버": "네이버(주)의 부당한 광고행위에 대한 건",
    "남양유업": "남양유업(주)의 거래상지위남용행위에 대한 건",
    "삼성전자": "삼성전자(주)의 부당한 고객유인행위에 대한 건",
    "신세계": "(주)신세계 및 (주)에스에스지닷컴의 전자상거래 소비자보호법 위반행위에 대한 건",
    "에스피피조선": "에스피피조선(주)의 불공정하도급거래행위에 대한 건",
}

HEADERS = ["ID","사건키","사건유형","페르소나","난이도","질문유형","질문","답변","핵심키워드","적용법령","적용조문","처분결과","근거(chunk)","Confidence","검수자 평가","주의사항/비고","문제점 및 해결방안"]
HDR_FILL = PatternFill("solid", fgColor="4472C4")
HDR_FONT = Font(bold=True, color="FFFFFF", name="맑은 고딕", size=10)
CELL_FONT = Font(name="맑은 고딕", size=9)
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Side(border_style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
COL_WIDTHS = [18,14,14,16,8,12,40,60,20,20,16,24,28,12,12,30,50]

def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except:
        return {}

def extract_case_type(facts):
    try:
        pr = facts["facts_structured"]["피해범위"]
        m = re.search(r'\[(.+?)\]', pr)
        return m.group(1) if m else "기타"
    except:
        return "기타"

def sanction_str(s):
    parts = []
    t = s.get("처분유형","")
    if t: parts.append(t)
    a = s.get("과징금액","")
    if a: parts.append(f"과징금 {a}")
    return " / ".join(parts) if parts else "정보 없음"

def col16_value(persona, legal):
    if persona == "일반국민":
        return "해당 사건의 처분 결과를 숙지하고 소비자 권리 침해 시 신고 가능(공정거래위원회 신고센터)."
    elif persona == "기업 컴플라이언스 담당자":
        조문 = legal.get("조문","관련 조문")
        return f"내부 거래 조건·약관 점검 필요. {조문} 준수 여부 사전 확인 권고. 유사 행위 발견 시 즉시 법무팀 보고."
    elif persona == "논문 준비 학생":
        return f"참고 법령: {legal.get('법령','')} {legal.get('조문','')}. 유사 선례 검토 권장. 판단요건 비교 분석 가능."
    return ""

def tier1_col17(qa):
    chunk = qa.get("근거_short","N/A")
    return f"AI 자동 생성 답변으로 법령 조문 인용 정확도 검수 필요. 근거 chunk [{chunk}] 원문 대조 권고. 페르소나 톤 적합성 B 검수자 최종 확인 대상."

print("▶ 데이터 로드 중...")
rows = []
for key, folder in CASES.items():
    base = PROJECT / "04_raw_outputs" / folder
    qa_list = load_json(base / "qa_list.json")
    facts = load_json(base / "facts.json")
    legal = load_json(base / "legal.json")
    sanction = load_json(base / "sanction.json")
    case_type = extract_case_type(facts)
    법령 = legal.get("법령","정보 없음")
    조문 = legal.get("조문","정보 없음")
    처분 = sanction_str(sanction)
    키워드 = facts.get("행위","")[:30] if facts.get("행위") else "정보 없음"
    for i, qa in enumerate(qa_list, 1):
        persona = qa.get("페르소나","")
        rows.append({"ID":f"QA-{key}-{i:03d}","사건키":key,"사건유형":case_type,"페르소나":persona,"난이도":qa.get("난이도",""),"질문유형":qa.get("질문유형",""),"질문":qa.get("질문",""),"답변":qa.get("답변",""),"핵심키워드":키워드,"적용법령":법령,"적용조문":조문,"처분결과":처분,"근거(chunk)":qa.get("근거_short",""),"Confidence":0.85,"검수자 평가":"","주의사항/비고":col16_value(persona,legal),"문제점 및 해결방안":tier1_col17(qa)})

print(f"  총 {len(rows)}건 로드 완료")

if TARGET.exists():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bk = CKPT / f"Day4_backup_{ts}.xlsx"
    shutil.copy2(TARGET, bk)
    print(f"  백업 → {bk.name}")

def write_sheet(ws, sheet_rows, col16_label):
    headers = HEADERS.copy()
    headers[15] = col16_label
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[1].height = 22
    for r, row in enumerate(sheet_rows, 2):
        vals = [row["ID"],row["사건키"],row["사건유형"],row["페르소나"],row["난이도"],row["질문유형"],row["질문"],row["답변"],row["핵심키워드"],row["적용법령"],row["적용조문"],row["처분결과"],row["근거(chunk)"],row["Confidence"],row["검수자 평가"],row["주의사항/비고"],row["문제점 및 해결방안"]]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = CELL_FONT
            cell.alignment = WRAP
            cell.border = BORDER
        ws.row_dimensions[r].height = 60
    for c, w in enumerate(COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"

print("▶ xlsx 작성 중...")
wb = load_workbook(TARGET) if TARGET.exists() else Workbook()
if "Sheet" in wb.sheetnames:
    del wb["Sheet"]

SHEET_DEFS = [
    ("전체_QA", rows, "근거(원문)"),
    ("일반국민", [r for r in rows if r["페르소나"]=="일반국민"], "주의사항"),
    ("기업 컴플라이언스 담당자", [r for r in rows if r["페르소나"]=="기업 컴플라이언스 담당자"], "주의사항"),
    ("논문 준비 학생", [r for r in rows if r["페르소나"]=="논문 준비 학생"], "비고"),
]

for sheet_name, sheet_rows, col16_label in SHEET_DEFS:
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)
    write_sheet(ws, sheet_rows, col16_label)
    print(f"  ✅ {sheet_name}: {len(sheet_rows)}행")

wb.save(TARGET)
print(f"\n✅ 저장 완료 → {TARGET}")
print("\n완료.")
