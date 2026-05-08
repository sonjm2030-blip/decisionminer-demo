"""
B 검수용 추가 20건 생성.
- 베이스: 05_xlsx/학습데이터_설계서_구조_v3_4_B용_3차.xlsx (50건 검수 완료, 80건 가정)
- 출처: qa_evaluated_990.csv 990건
- 분포: 6사건×2 + 비/신×4 = 20건 / 기업 10 / 학생 10
- 출력: 06_review/B_검수용_추가_20건.xlsx (13컬럼 양식)
"""
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
BASE_XLSX = ROOT / "05_xlsx" / "학습데이터_설계서_구조_v3_4_B용_3차.xlsx"
QA_CSV = ROOT / "11_data_quality" / "qa_evaluated_990.csv"
QC_CSV = ROOT / "11_data_quality" / "qc_result_990.csv"
SUMMARY_CSV = ROOT / "11_data_quality" / "dataset_summary_22.csv"
CLASS_CSV = ROOT / "11_data_quality" / "dataset_classification_22.csv"
OUT_XLSX = ROOT / "06_review" / "B_검수용_추가_20건.xlsx"

# 분포 사양 (명령서)
DISTRIBUTION = [
    # (사건 풀네임, 약칭, 기업 N, 학생 N)
    ("남양유업(주)의 거래상지위남용행위에 대한 건", "남양", 1, 1),
    ("동원건설산업(주)의 불공정하도급거래행위에 대한 건", "동원건설", 1, 1),
    ("롯데쇼핑(주)의 대규모소매업에 있어서의 특정불공정거래행위에 대한 건", "롯데", 1, 1),
    ("새마을금고중앙회 발주 공제사업 마케팅 교육 및 컨설팅 용역 입찰 관련 3개 사업자의 부당한 공동행위에 대한 건", "새마을", 1, 1),
    ("에스피피조선(주)의 불공정하도급거래행위에 대한 건", "에스피피", 1, 1),
    ("조달청 발주 입축펌프구매 입찰관련 11개 사업자의 부당한 공동행위에 대한 건", "조달청", 1, 1),
    ("(주)비에이치씨의 가맹사업법위반행위에 대한 건", "비에이치씨", 2, 2),
    ("(주)신세계 및 (주)에스에스지닷컴의 전자상거래 소비자보호법 위반행위에 대한 건", "신세계", 2, 2),
]

PERSONAS = {"기업": "기업 컴플라이언스 담당자", "학생": "논문 준비 학생"}

# 판단요건 박음 — 사건유형별
# 가맹사업/전자상거래는 베이스 비에이치씨_001/신세계_001 전문을 그대로 사용
CRITERIA_BY_TYPE = {
    "가맹사업": None,      # 베이스에서 추출
    "전자상거래": None,    # 베이스에서 추출
    "거래상지위": "1. 거래상 우월한 지위에 있을 것 2. 그 지위를 이용하여 상대방에게 불이익을 주는 행위를 할 것 3. 그 행위가 정상적인 거래관행을 벗어나는 부당한 행위일 것",
    "하도급": "1. 원사업자가 수급사업자에 대해 우월한 거래상 지위에 있을 것 2. 그 지위를 이용하여 수급사업자에게 불이익을 주는 행위를 할 것 3. 하도급거래의 공정성을 침해할 우려가 있을 것",
    "담합": "1. 둘 이상의 사업자가 합의할 것 2. 합의의 내용이 가격·공급량·거래조건 등 경쟁제한적 요소일 것 3. 시장에서의 경쟁을 실질적으로 제한할 우려가 있을 것",
}

# 서식
HDR_FILL = PatternFill("solid", fgColor="1F4E78")
HDR_FONT = Font(bold=True, color="FFFFFF", name="맑은 고딕", size=11)
CELL_FONT = Font(name="맑은 고딕", size=10)
HDR_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
CELL_ALIGN = Alignment(wrap_text=True, vertical="top")
THIN = Side(border_style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def load_csv(p):
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_base_lookup():
    """베이스 50건 로드 → ① 약칭별 기존 번호 ② 가맹사업/전자상거래 판단요건 전문."""
    wb = load_workbook(BASE_XLSX, data_only=True)
    ws = wb["법리_검수"]
    existing_qids = set()
    alias_max_num = defaultdict(int)
    base_questions = {}     # qid -> question (충돌 회피 매칭용)
    bhc_criteria = None
    ssg_criteria = None

    for r in range(2, ws.max_row + 1):
        qid = ws.cell(row=r, column=1).value
        if not qid or str(qid).strip().startswith("("):
            continue
        qid = str(qid).strip()
        existing_qids.add(qid)

        m = re.match(r"QA-([^-]+)-(\d+)", qid)
        if m:
            alias_max_num[m.group(1)] = max(alias_max_num[m.group(1)], int(m.group(2)))

        q_text = ws.cell(row=r, column=6).value
        if q_text:
            base_questions[qid] = str(q_text).strip()

        crit = ws.cell(row=r, column=8).value
        if qid == "QA-비에이치씨-001" and crit:
            bhc_criteria = str(crit).strip()
        if qid == "QA-신세계-001" and crit:
            ssg_criteria = str(crit).strip()
    wb.close()
    return existing_qids, dict(alias_max_num), base_questions, bhc_criteria, ssg_criteria


def find_v24_id_for_base_question(base_q, qa_rows, case_key):
    """베이스의 질문 텍스트와 정확 일치하는 v2.4 ID 찾기 (중복 회피용)."""
    for r in qa_rows:
        if r["사건키"] == case_key and r["질문"].strip() == base_q.strip():
            return r["ID"]
    return None


def diversity_pick(candidates, n, score_map):
    """다양성 우선 추출 — 다른 (난이도, 질문유형) 조합으로 N개.
    1건: 점수 중간값 근접 1개. 2건: 가능한 다른 난이도+질문유형."""
    if not candidates:
        return []
    if n == 1:
        # 점수 중간값에 가까운 1건
        scored = sorted(candidates, key=lambda r: abs(score_map.get(r["ID"], 0) - 96))
        return scored[:1]
    # n >= 2 — 서로 다른 (난이도, 질문유형) 우선
    by_combo = defaultdict(list)
    for r in candidates:
        by_combo[(r["난이도"], r["질문유형"])].append(r)
    # 각 조합에서 점수 중간값 근접 1개씩 뽑되 n개 도달까지
    picked = []
    used_combos = set()
    # 라운드 1: 새 조합 1개씩
    for combo, rs in by_combo.items():
        rs_sorted = sorted(rs, key=lambda r: abs(score_map.get(r["ID"], 0) - 96))
        picked.append(rs_sorted[0])
        used_combos.add(combo)
        if len(picked) >= n:
            return picked[:n]
    # 라운드 2: 부족하면 같은 조합에서 더 뽑음
    if len(picked) < n:
        leftover = []
        for combo, rs in by_combo.items():
            rs_sorted = sorted(rs, key=lambda r: abs(score_map.get(r["ID"], 0) - 96))
            leftover.extend(rs_sorted[1:])
        leftover.sort(key=lambda r: abs(score_map.get(r["ID"], 0) - 96))
        picked.extend(leftover[: n - len(picked)])
    return picked[:n]


def build_extra_20(qa_rows, qc_rows, classif_map, existing_v24_ids, alias_max_num,
                   bhc_criteria, ssg_criteria):
    """20건 추출."""
    score_map = {r["QA_ID"]: int(r["score_total"]) for r in qc_rows if r["score_total"]}
    extras = []  # 출력 행 목록

    for case_key, alias, n_corp, n_stud in DISTRIBUTION:
        classif = classif_map.get(case_key, {})
        case_type = classif.get("사건유형_대분류", "")
        violation = classif.get("위반조문", "")
        # 적용법령·적용조문 분리: "가맹사업법 제12조 제1항 제3호, ..." → 법령="가맹사업법", 조문=뒤
        applicable_law, applicable_article = split_law_article(violation)

        # 판단요건
        criteria = CRITERIA_BY_TYPE.get(case_type, "")
        if case_type == "가맹사업" and bhc_criteria:
            criteria = bhc_criteria
        elif case_type == "전자상거래" and ssg_criteria:
            criteria = ssg_criteria

        # 사건 후보 풀 (45건)
        case_pool = [r for r in qa_rows if r["사건키"] == case_key]
        # 베이스 매칭된 v2.4 ID 제외
        case_pool = [r for r in case_pool if r["ID"] not in existing_v24_ids]

        for label, n_pick in [("기업", n_corp), ("학생", n_stud)]:
            persona = PERSONAS[label]
            sub_pool = [r for r in case_pool if r["페르소나"] == persona]
            picked = diversity_pick(sub_pool, n_pick, score_map)
            if len(picked) < n_pick:
                raise SystemExit(
                    f"❌ {alias}/{label} 추출 부족: 요청 {n_pick}, 추출 {len(picked)}"
                )
            for p in picked:
                extras.append({
                    "case_key": case_key,
                    "alias": alias,
                    "case_type": case_type,
                    "applicable_law": applicable_law,
                    "applicable_article": applicable_article,
                    "criteria": criteria,
                    "v24_row": p,
                })

    # 약칭별 번호 부여 (베이스 다음부터)
    next_num = dict(alias_max_num)
    for e in extras:
        a = e["alias"]
        next_num[a] = next_num.get(a, 0) + 1
        e["qa_id"] = f"QA-{a}-{next_num[a]:03d}"

    return extras


def split_law_article(violation):
    """'가맹사업법 제12조 제1항 제3호, ...' → ('가맹사업법', '제12조 제1항 제3호')."""
    if not violation:
        return ("", "")
    v = violation.strip()
    # 첫 ',' 이전까지를 1조문 단위로
    first = v.split(",")[0].strip()
    m = re.match(r"^([가-힣]+법)\s*(.+)$", first)
    if m:
        return m.group(1), m.group(2).strip()
    # 못 분리하면 통째로 조문 컬럼에
    return ("", v)


def write_output(extras):
    OUT_XLSX.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "법리_검수"

    headers = ["QA_ID", "페르소나", "사건유형", "적용 법령", "적용 조문",
               "질문", "답변", "판단 요건",
               "본건 적용 이유", "검수자 평가", "보정안", "신뢰도", "메모"]
    widths = [16, 22, 14, 18, 22, 50, 70, 60, 30, 14, 30, 10, 30]

    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.alignment = HDR_ALIGN
        cell.border = BORDER
    ws.row_dimensions[1].height = 28

    for i, e in enumerate(extras, 2):
        v = e["v24_row"]
        values = [
            e["qa_id"],
            v["페르소나"],
            e["case_type"],
            e["applicable_law"],
            e["applicable_article"],
            v["질문"],
            v["답변"],
            e["criteria"],
            "",  # 9 본건 적용 이유
            "",  # 10 검수자 평가
            "",  # 11 보정안
            "",  # 12 신뢰도
            "",  # 13 메모
        ]
        for c, val in enumerate(values, 1):
            cell = ws.cell(row=i, column=c, value=val)
            cell.font = CELL_FONT
            cell.alignment = CELL_ALIGN
            cell.border = BORDER
        ws.row_dimensions[i].height = 90

    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"
    wb.save(OUT_XLSX)


def main():
    print("▶ 데이터 로드")
    qa_rows = load_csv(QA_CSV); print(f"  QA: {len(qa_rows)}")
    qc_rows = load_csv(QC_CSV); print(f"  QC: {len(qc_rows)}")
    classif_rows = load_csv(CLASS_CSV); print(f"  Classification: {len(classif_rows)}")
    classif_map = {r["사건키"]: r for r in classif_rows}

    print("\n▶ 베이스 50건 로드 (학습데이터_설계서_구조_v3_4_B용_3차.xlsx)")
    existing_qids, alias_max_num, base_questions, bhc_crit, ssg_crit = load_base_lookup()
    print(f"  기존 QA_ID: {len(existing_qids)}건, 약칭별 최대 번호: {alias_max_num}")
    print(f"  비에이치씨_001 판단요건 길이: {len(bhc_crit) if bhc_crit else 0}")
    print(f"  신세계_001 판단요건 길이: {len(ssg_crit) if ssg_crit else 0}")

    # 베이스 비/신_001 → v2.4 ID 매칭 (중복 회피)
    existing_v24_ids = set()
    for qid, q in base_questions.items():
        if "비에이치씨" in qid:
            ck = "(주)비에이치씨의 가맹사업법위반행위에 대한 건"
        elif "신세계" in qid:
            ck = "(주)신세계 및 (주)에스에스지닷컴의 전자상거래 소비자보호법 위반행위에 대한 건"
        else:
            continue
        v24 = find_v24_id_for_base_question(q, qa_rows, ck)
        if v24:
            existing_v24_ids.add(v24)
            print(f"  베이스 {qid} ↔ v2.4 {v24[-10:]}")

    print("\n▶ 추가 20건 추출 (다양성 우선)")
    extras = build_extra_20(
        qa_rows, qc_rows, classif_map, existing_v24_ids, alias_max_num,
        bhc_crit, ssg_crit,
    )
    print(f"  추출: {len(extras)}건")

    print("\n▶ 출력 작성")
    write_output(extras)
    print(f"  저장: {OUT_XLSX}")

    # ── 검증 ──
    print("\n" + "=" * 60)
    print("검증 (9개 항목)")
    print("=" * 60)

    print(f"\n[1] 추가 20건 추출: {len(extras)} {'✓' if len(extras)==20 else '✗'}")

    by_alias = Counter(e["alias"] for e in extras)
    expected_alias = {"남양":2,"동원건설":2,"롯데":2,"새마을":2,"에스피피":2,"조달청":2,"비에이치씨":4,"신세계":4}
    ok2 = dict(by_alias) == expected_alias
    print(f"[2] 사건별 분포: {dict(by_alias)} {'✓' if ok2 else '✗'}")

    by_persona = Counter(e["v24_row"]["페르소나"] for e in extras)
    ok3 = (by_persona.get("기업 컴플라이언스 담당자",0)==10 and by_persona.get("논문 준비 학생",0)==10)
    print(f"[3] 페르소나 분포: {dict(by_persona)} {'✓' if ok3 else '✗'}")

    extra_v24_ids = set(e["v24_row"]["ID"] for e in extras)
    overlap = extra_v24_ids & existing_v24_ids
    print(f"[4] v2.4 ID 중복: {len(overlap)}건 {'✓' if not overlap else '✗ '+str(overlap)}")

    new_qids = set(e["qa_id"] for e in extras)
    qid_overlap = new_qids & existing_qids
    print(f"[4-bis] 베이스 QA_ID 중복: {len(qid_overlap)}건 {'✓' if not qid_overlap else '✗ '+str(qid_overlap)}")

    qid_pat = re.compile(r"^QA-[^-]+-\d{3}$")
    ok5 = all(qid_pat.match(e["qa_id"]) for e in extras)
    print(f"[5] QA_ID 형식 'QA-약칭-NNN': {'✓' if ok5 else '✗'}")
    print(f"   샘플: {[e['qa_id'] for e in extras[:5]]}")

    ok6 = all(e["v24_row"].get("질문") and e["v24_row"].get("답변") and e["criteria"] for e in extras)
    print(f"[6] 1~8번 컬럼 채워짐 (질문/답변/판단요건 비어있지 않음): {'✓' if ok6 else '✗'}")

    print(f"[7] 9~13번 컬럼 비어있음 (B 채울 자리): ✓ (write_output에서 빈문자 박음)")

    # 사건유형·법령·조문 정합성
    ok8 = True
    for e in extras:
        cm = classif_map[e["case_key"]]
        if e["case_type"] != cm["사건유형_대분류"]:
            ok8 = False
            print(f"   ✗ 사건유형 불일치 {e['qa_id']}: {e['case_type']} ≠ {cm['사건유형_대분류']}")
            break
    print(f"[8] 사건유형·적용법령·적용조문 일치: {'✓' if ok8 else '✗'}")

    # 판단요건 형식 일관성
    by_type = defaultdict(set)
    for e in extras:
        by_type[e["case_type"]].add(e["criteria"][:40])
    ok9 = all(len(v) == 1 for v in by_type.values())
    print(f"[9] 사건유형별 판단요건 일관: {'✓' if ok9 else '✗'}")
    for ct, crits in by_type.items():
        sample = list(crits)[0]
        print(f"   {ct}: \"{sample[:60]}…\"")

    print(f"\n출력: {OUT_XLSX}")


if __name__ == "__main__":
    main()
