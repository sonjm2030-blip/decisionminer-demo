"""
v2.6 xlsx의 법리_검수 시트를 B 100건 (4차검수) 결과로 갱신.
- 약칭(QA-엘지생건-001) → 풀네임(_001) 매핑하여 자동 검수 결과와 매칭
- 매트릭스/4지표 분모 100으로 통일
- 검수_결과표의 v2 통계 행도 100건 기준으로 갱신
"""
import csv
import os
import re
import unicodedata
from collections import Counter

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = "/Users/sonjongmyeong/Desktop/2026 공정위 공모전/decisionminer_project"
os.chdir(ROOT)

V26 = "제출_패키지/학습데이터_설계서_DecisionMiner_v2_6.xlsx"
QC_V2 = "11_data_quality/qc_result_990_v2.csv"

SHORT2FULL = {
    "경북교육청": "경상북도교육청 발주 2018년 업무용 표준오피스 소프트웨어 연간사용권 구매 입찰 관련 4개 사업자의 부당한 공동행위에 대한 건",
    "경북택시": "경상북도개인택시운송사업조합 구미시지부의 사업자단체 금지행위에 대한 건",
    "과수종묘": "(사)한국과수종묘협회의 사업자단체 금지행위에 대한 건",
    "글락소": "글락소그룹리미티드 및 동아제약(주)의 부당한 공동행위에 대한 건",
    "금호아시아나": "기업집단 금호아시아나 소속 계열회사들의 특수관계인에 대한 부당이익제공행위 및 부당지원행위에 대한 건",
    "네이버": "네이버(주)의 부당한 광고행위에 대한 건",
    "비에이치씨": "(주)비에이치씨의 가맹사업법위반행위에 대한 건",
    "삼성전자": "삼성전자(주)의 부당한 고객유인행위에 대한 건",
    "신세계": "(주)신세계 및 (주)에스에스지닷컴의 전자상거래 소비자보호법 위반행위에 대한 건",
    "아모레": "(주)아모레퍼시픽의 재판매가격유지행위에 대한 건",
    "엘지생건": "(주)엘지생활건강의 가맹사업법 위반행위에 대한 건",
    "카카오엔터": "(주)카카오엔터테인먼트의 부당한 광고행위에 대한 건",
    "케이티디에스": "(주)케이티디에스의 불공정하도급거래행위에 대한 건",
    "쿠팡": "쿠팡(주)의 전자상거래소비자보호법 등 위반행위에 대한 건",
    "평화이엔지": "(주)평화이엔지의 불공정하도급거래행위에 대한 건",
    "홈플러스": "홈플러스(주) 및 홈플러스테스코(주)의 거래상지위남용행위에 대한 건",
    "남양": "남양유업(주)의 거래상지위남용행위에 대한 건",
    "동원건설": "동원건설산업(주)의 불공정하도급거래행위에 대한 건",
    "롯데": "롯데쇼핑(주)의 대규모소매업에 있어서의 특정불공정거래행위에 대한 건",
    "새마을": "새마을금고중앙회 발주 공제사업 마케팅 교육 및 컨설팅 용역 입찰 관련 3개 사업자의 부당한 공동행위에 대한 건",
    "에스피피": "에스피피조선(주)의 불공정하도급거래행위에 대한 건",
    "조달청": "조달청 발주 입축펌프구매 입찰관련 11개 사업자의 부당한 공동행위에 대한 건",
}


def nfc(s):
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def short_to_v24(qa_id_b):
    m = re.match(r"^QA-([^-]+)-(\d+)$", qa_id_b)
    if not m:
        return None
    short, num = m.group(1), m.group(2)
    full = SHORT2FULL.get(short)
    return f"{full}_{num}" if full else None


def main():
    print("▶ 1. B 100건 파일 탐색")
    b_path = next(
        f for f in os.listdir(".")
        if "4차검수" in nfc(f) and f.endswith(".xlsx")
    )
    print(f"   {b_path}")

    print("▶ 2. B 100건 + 자동 검수 v2 로드")
    wb_b = openpyxl.load_workbook(b_path, data_only=True)
    ws_b = wb_b.active
    rows_b = list(ws_b.iter_rows(values_only=True))
    hdr_b = rows_b[0]
    qa_idx = hdr_b.index("QA_ID")
    eval_idx = hdr_b.index("검수자 평가")
    corr_idx = hdr_b.index("보정안") if "보정안" in hdr_b else -1
    memo_idx = hdr_b.index("메모") if "메모" in hdr_b else -1

    b_records = []
    for r in rows_b[1:]:
        if not r[qa_idx]:
            continue
        b_records.append({
            "qa_id_b": r[qa_idx],
            "qa_id_v24": short_to_v24(r[qa_idx]),
            "human_judgment": (r[eval_idx] or "").strip(),
            "correction": (r[corr_idx] or "").strip() if corr_idx >= 0 else "",
            "memo": (r[memo_idx] or "").strip() if memo_idx >= 0 else "",
        })
    print(f"   B 100건 로드: {len(b_records)}건")

    with open(QC_V2, encoding="utf-8-sig") as f:
        qc = {nfc(r["QA_ID"]): r for r in csv.DictReader(f)}
    print(f"   자동검수 990건 로드")

    print("▶ 3. 100건 매트릭스 산출")
    mx = Counter()
    for rec in b_records:
        v24 = rec["qa_id_v24"]
        a = qc.get(nfc(v24), {}).get("judgment", "없음") if v24 else "없음"
        rec["auto_judgment"] = a
        mx[(a, rec["human_judgment"])] += 1

    n = len(b_records)
    match_pairs = {("Gold", "OK"), ("보정필요", "보정 필요"), ("보정필요", "보정필요"), ("탈락", "환각")}
    strict = sum(v for k, v in mx.items() if k in match_pairs)
    lenient_pairs = match_pairs | {
        ("보정필요", "OK"), ("보정필요", "환각"),
        ("탈락", "보정 필요"), ("탈락", "보정필요"),
    }
    lenient = sum(v for k, v in mx.items() if k in lenient_pairs)
    underdetect = sum(v for k, v in mx.items() if k[0] == "Gold" and k[1] in ("보정 필요", "보정필요", "환각"))
    critical_caught = mx.get(("탈락", "환각"), 0)
    critical_total = sum(v for k, v in mx.items() if k[1] == "환각")

    print(f"   엄격 일치율: {strict}/{n} = {strict/n*100:.1f}%")
    print(f"   엄격 방향 일치율: {lenient}/{n} = {lenient/n*100:.1f}%")
    print(f"   과소탐지율: {underdetect}/{n} = {underdetect/n*100:.1f}%")
    print(f"   중대오류 탐지: {critical_caught}/{critical_total}")

    print("\n▶ 4. v2.6 xlsx 로드 및 법리_검수 시트 갱신")
    wb = openpyxl.load_workbook(V26)
    ws = wb["법리_검수"]

    # 기존 모든 셀 클리어
    for r in range(ws.max_row, 1, -1):
        for c in range(1, ws.max_column + 1):
            ws.cell(r, c).value = None
    # 헤더
    headers = ["QA_ID(B)", "QA_ID(v24)", "사건키", "자동검수_판정", "인간검수자_판정",
               "일치여부", "인간검수자_보정안_요약", "비고"]
    for c, h in enumerate(headers, 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(bold=True, color="FFFFFF", name="맑은 고딕", size=11)
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 100건 데이터
    cell_font = Font(name="맑은 고딕", size=10)
    cell_align = Alignment(wrap_text=True, vertical="top")
    for i, rec in enumerate(b_records, 2):
        v24 = rec["qa_id_v24"] or ""
        ck = v24.rsplit("_", 1)[0] if "_" in v24 else v24
        a, h = rec["auto_judgment"], rec["human_judgment"]
        if a == "Gold" and h == "OK":
            agree = "일치 (양호)"
        elif a == "보정필요" and h in ("보정 필요", "보정필요"):
            agree = "일치 (보정필요)"
        elif a == "탈락" and h == "환각":
            agree = "일치 (탈락)"
        elif a == "Gold" and h in ("보정 필요", "보정필요", "환각"):
            agree = "불일치 (과소탐지)"
        elif a == "보정필요" and h == "OK":
            agree = "불일치 (과탐지·보수적)"
        else:
            agree = "불일치"
        corr_short = (rec["correction"] or "")[:80]
        if len(rec["correction"]) > 80:
            corr_short += "..."
        values = [rec["qa_id_b"], v24, ck, a, h, agree, corr_short, rec["memo"][:60]]
        for c, v in enumerate(values, 1):
            cell = ws.cell(i, c, v)
            cell.font = cell_font
            cell.alignment = cell_align

    # 100건 끝, 통계 블록
    row_idx = len(b_records) + 3
    ws.cell(row_idx, 1, "── 인간 검수자 100건 vs 자동 검수 v2 비교 통계 ──").font = Font(bold=True)
    row_idx += 1
    ws.cell(row_idx, 1, f"전체 일치율 (엄격): {strict}/{n} = {strict/n*100:.1f}%")
    row_idx += 1
    ws.cell(row_idx, 1, f"엄격 방향 일치율 (자동이 더 엄격해도 OK): {lenient}/{n} = {lenient/n*100:.1f}%")
    row_idx += 1
    ws.cell(row_idx, 1, f"과소탐지율 (자동 Gold인데 인간 보정/환각): {underdetect}/{n} = {underdetect/n*100:.1f}%")
    row_idx += 1
    ws.cell(row_idx, 1, f"중대오류 탐지: {critical_caught}/{critical_total}")

    # 매트릭스
    row_idx += 2
    ws.cell(row_idx, 1, "── 매트릭스 (자동 행 × 인간 열) ──").font = Font(bold=True)
    row_idx += 1
    h_keys = ["OK", "보정 필요", "환각"]
    ws.cell(row_idx, 1, "자동 \\ 인간")
    for j, hk in enumerate(h_keys, 2):
        ws.cell(row_idx, j, hk).font = Font(bold=True)
    ws.cell(row_idx, 5, "합계").font = Font(bold=True)
    a_keys = ["Gold", "보정필요", "탈락"]
    col_sums = {hk: 0 for hk in h_keys}
    for ak in a_keys:
        row_idx += 1
        ws.cell(row_idx, 1, ak).font = Font(bold=True)
        rs = 0
        for j, hk in enumerate(h_keys, 2):
            v = mx.get((ak, hk), 0)
            ws.cell(row_idx, j, v)
            rs += v
            col_sums[hk] += v
        ws.cell(row_idx, 5, rs).font = Font(bold=True)
    row_idx += 1
    ws.cell(row_idx, 1, "합계").font = Font(bold=True)
    for j, hk in enumerate(h_keys, 2):
        ws.cell(row_idx, j, col_sums[hk]).font = Font(bold=True)
    ws.cell(row_idx, 5, sum(col_sums.values())).font = Font(bold=True)

    print("   법리_검수 시트 100건 + 매트릭스 + 4지표 박힘")

    # 검수_결과표 v2 통계 행 갱신 (이미 있는 행 찾아 갱신)
    print("\n▶ 5. 검수_결과표 v2 통계 행 100건 기준 추가")
    rev_ws = wb["검수_결과표"]
    last = rev_ws.max_row
    rev_ws.cell(last + 2, 1, "── 인간 검수자 100건 비교 결과 (B 4차검수 0507) ──").font = Font(bold=True)
    rev_ws.cell(last + 3, 1, f"분모 100건 / 엄격 일치율 {strict}% / 방향 일치율 {lenient}% / 과소탐지 {underdetect}% / 중대오류 탐지 {critical_caught}/{critical_total}")
    rev_ws.cell(last + 4, 1, f"매트릭스: Gold(4/11/1) 보정필요(33/50/0) 탈락(0/0/1) — (OK/보정필요/환각)")

    print(f"\n▶ 6. 저장: {V26}")
    wb.save(V26)
    print("   저장 완료")

    # 검증
    print("\n=== 검증 ===")
    wb2 = openpyxl.load_workbook(V26, data_only=True)
    ws2 = wb2["법리_검수"]
    qa_count = sum(1 for r in range(2, ws2.max_row + 1)
                   if ws2.cell(r, 1).value and str(ws2.cell(r, 1).value).startswith("QA-"))
    print(f"  법리_검수 QA 행수: {qa_count} {'✓' if qa_count == 100 else '✗'}")
    # 통계 텍스트 검증
    found_strict = found_matrix = False
    for r in range(2, ws2.max_row + 1):
        v = str(ws2.cell(r, 1).value or "")
        if f"{strict}/{n}" in v:
            found_strict = True
        if "매트릭스" in v:
            found_matrix = True
    print(f"  엄격 일치율 박힘: {'✓' if found_strict else '✗'}")
    print(f"  매트릭스 헤더 박힘: {'✓' if found_matrix else '✗'}")


if __name__ == "__main__":
    main()
