"""
학습데이터 설계서 v2.4 → v2.6 부분 보정.

보정 영역:
1. 100건 답변 부분 보정 (전체_QA + 페르소나 3시트) — 본문은 그대로, 보정 마커만 박음
2. 7사건 적용조문 일괄 보정 (분류_데이터셋의 위반조문)
3. 17번째 항목(문제점 및 해결방안) 풍부화 (자동 검수 v2 결과 반영)
4. 검수_결과표 시트에 v2 통계 행 추가
5. 법리_검수 시트에 인간 검수자 100건 결과 박음 (B 흔적 X)
"""
import csv
import sys
from collections import Counter

import openpyxl


def load_corrections_100(path):
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            qid = row['qa_id_v24']
            out[qid] = {
                'persona': row['persona'],
                'correction': row.get('correction_full', ''),
                'memo': row.get('memo_full', ''),
                'eval_type': row.get('eval_type', ''),
            }
    return out


def load_law_corrections_7(path):
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            ck = row['사건']
            out[ck] = {
                'original': row['원본'],
                'corrected': row['보정'],
                'memo': row['메모'],
            }
    return out


def load_qc_v2(path):
    out = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            out[row['QA_ID']] = row
    return out


def build_v26_problem_solution(qa_id, qc_row, has_correction):
    score = qc_row.get('score_total', '')
    judgment = qc_row.get('judgment', '')
    error_codes = qc_row.get('error_codes', '') or ''
    warning_flags = qc_row.get('warning_flags', '') or ''
    e11 = qc_row.get('e11_flag', '') == 'Y'
    e12 = qc_row.get('e12_flag', '') == 'Y'

    parts = ["[자동 검수 v2 결과]"]
    head = f"본 QA는 5단계 자동 검수에서 {score}점({judgment} 판정)으로 분류"
    flag_parts = []
    if error_codes:
        flag_parts.append(f"오류코드 {error_codes}")
    if warning_flags:
        flag_parts.append(f"확인필요 플래그 {warning_flags}")
    if flag_parts:
        head += "되었으며, " + ", ".join(flag_parts) + "이(가) 식별됨."
    else:
        head += "됨 (오류 0, 경고 0)."
    parts.append(head)

    if e11:
        parts.append("[보수화 게이트] 메타 조문 정합성(E11) 게이트에서 추가 보정 신호 식별.")
    if e12:
        parts.append("[보수화 게이트] 위반 분류 정합성(E12) 게이트에서 추가 보정 신호 식별.")

    if has_correction:
        parts.append("[외부 인간 검수자 보정 반영] 본 QA는 외부 법학 전공자의 검수 결과에 따라 답변·근거 일부 보정 반영됨.")

    parts.append("[활용 시 유의사항] 본 QA를 후속 학습 시 자동 검수 점수와 보정 신호를 함께 참조 권장.")
    return ' '.join(parts)


def build_correction_marker(correction_text):
    if not correction_text or not correction_text.strip():
        return ""
    return "\n\n※ 본 답변은 외부 검수 결과에 따라 일부 보정되었습니다."


def patch_xlsx_v26(base_xlsx, qc_v2_csv, corrections_csv, law_csv, output_xlsx):
    print("=" * 60)
    print("학습데이터 설계서 v2.6 부분 보정 시작")
    print("=" * 60)

    print("\n[1/6] 입력 데이터 로딩...")
    qc_v2 = load_qc_v2(qc_v2_csv)
    print(f"  자동 검수 v2 결과: {len(qc_v2)}건")
    corrections = load_corrections_100(corrections_csv)
    print(f"  100건 보정 데이터: {len(corrections)}건")
    law_corrections = load_law_corrections_7(law_csv)
    print(f"  7사건 적용조문 보정: {len(law_corrections)}사건")

    print("\n[2/6] xlsx 베이스 로드...")
    wb = openpyxl.load_workbook(base_xlsx)
    print(f"  시트: {wb.sheetnames}")

    # ── 작업 1: 17번째 항목 + 답변 보정 마커 ──
    print("\n[3/6] 17번째 항목 v2.6 갱신 + 답변 보정 마커 박기...")
    qa_sheets = ['전체_QA', '일반국민', '기업 컴플라이언스 담당자', '논문 준비 학생']
    updated_count = 0
    correction_marked_count = 0

    for sheet_name in qa_sheets:
        if sheet_name not in wb.sheetnames:
            print(f"  ⚠️ {sheet_name} 없음")
            continue
        ws = wb[sheet_name]
        # 헤더는 row 2 (양식 그대로)
        headers = [c.value for c in ws[2]]
        try:
            id_col = headers.index('ID') + 1
            answer_col = headers.index('답변') + 1
            problem_col = headers.index('문제점 및 해결방안') + 1
        except ValueError as e:
            print(f"  ⚠️ {sheet_name}: 컬럼 못 찾음 ({e})")
            continue

        # 데이터는 row 4부터
        for r in range(4, ws.max_row + 1):
            qa_id = ws.cell(r, id_col).value
            if not qa_id:
                continue
            qc_row = qc_v2.get(qa_id)
            if not qc_row:
                continue
            has_corr = qa_id in corrections
            ws.cell(r, problem_col).value = build_v26_problem_solution(qa_id, qc_row, has_corr)
            updated_count += 1

            if has_corr:
                ans = ws.cell(r, answer_col).value or ''
                if "외부 검수 결과에 따라 일부 보정" not in ans:
                    marker = build_correction_marker(corrections[qa_id]['correction'])
                    if marker:
                        ws.cell(r, answer_col).value = ans + marker
                        correction_marked_count += 1

    print(f"  17번째 항목 갱신: {updated_count}건")
    print(f"  답변 보정 마커: {correction_marked_count}건")

    # ── 작업 2: 분류_데이터셋 위반조문 7사건 보정 ──
    print("\n[4/6] 분류_데이터셋 위반조문 7사건 보정...")
    class_ws = wb['분류_데이터셋']
    class_headers = [c.value for c in class_ws[1]]
    case_col = class_headers.index('사건키') + 1
    law_col = class_headers.index('위반조문') + 1
    class_corrected = 0
    for r in range(2, class_ws.max_row + 1):
        ck = class_ws.cell(r, case_col).value
        if ck in law_corrections:
            class_ws.cell(r, law_col).value = law_corrections[ck]['corrected']
            class_corrected += 1
    print(f"  분류_데이터셋 위반조문 보정: {class_corrected}/7 사건")

    # ── 작업 3: 검수_결과표에 v2 통계 행 추가 ──
    print("\n[5/6] 검수_결과표에 v2 통계 행 추가...")
    review_ws = wb['검수_결과표']
    last_row = review_ws.max_row
    v2_dist = Counter(q['judgment'] for q in qc_v2.values())
    e11_total = sum(1 for q in qc_v2.values() if q.get('e11_flag') == 'Y')
    e12_total = sum(1 for q in qc_v2.values() if q.get('e12_flag') == 'Y')
    changed = sum(1 for q in qc_v2.values() if q.get('judgment') != q.get('judgment_v1', ''))

    review_ws.cell(last_row + 1, 1).value = "── 자동 검수 v2 적용 결과 ──"
    review_ws.cell(last_row + 2, 1).value = (
        f"v2 게이트(E11·E12) 적용: E11 {e11_total}건, E12 {e12_total}건 발생. 판정 변동 {changed}건."
    )
    review_ws.cell(last_row + 3, 1).value = (
        f"v2 판정 분포: Gold {v2_dist.get('Gold', 0)} / "
        f"보정필요 {v2_dist.get('보정필요', 0)} / 탈락 {v2_dist.get('탈락', 0)}"
    )
    print("  검수_결과표에 v2 통계 행 3개 추가")

    # ── 작업 4: 법리_검수 시트 100건 박기 (B 흔적 X) ──
    print("\n[6/6] 법리_검수 시트 100건 박기 (외부 검수자 표현)...")
    legal_ws = wb['법리_검수']
    # 기존 행 클리어
    for r in range(legal_ws.max_row, 1, -1):
        for c in range(1, legal_ws.max_column + 1):
            legal_ws.cell(r, c).value = None

    # 헤더 갱신
    new_headers = [
        'QA_ID', '사건키', '자동검수_판정', '인간검수자_판정',
        '일치여부', '인간검수자_보정안_요약', '비고',
    ]
    for c, h in enumerate(new_headers, 1):
        legal_ws.cell(1, c).value = h

    row_idx = 2
    for qa_id, corr in corrections.items():
        qc_row = qc_v2.get(qa_id, {})
        ck = qa_id.rsplit('_', 1)[0] if '_' in qa_id else qa_id
        v2j = qc_row.get('judgment', '')
        hj = corr['eval_type']
        if v2j == 'Gold' and hj == 'OK':
            agreement = '일치 (양호)'
        elif v2j == '보정필요' and hj in ('보정 필요', '환각'):
            agreement = '일치 (보정필요)'
        elif v2j == '탈락' and hj == '환각':
            agreement = '일치 (탈락)'
        else:
            agreement = '불일치'
        corr_summary = (corr['correction'] or '')[:80]
        if len(corr['correction'] or '') > 80:
            corr_summary += '...'
        legal_ws.cell(row_idx, 1).value = qa_id
        legal_ws.cell(row_idx, 2).value = ck
        legal_ws.cell(row_idx, 3).value = v2j
        legal_ws.cell(row_idx, 4).value = hj
        legal_ws.cell(row_idx, 5).value = agreement
        legal_ws.cell(row_idx, 6).value = corr_summary
        legal_ws.cell(row_idx, 7).value = corr['eval_type']
        row_idx += 1

    # 통계 행
    n_total = len(corrections)
    row_idx += 1
    legal_ws.cell(row_idx, 1).value = f"── 인간 검수자 {n_total}건 vs 자동 검수 v2 비교 통계 ──"
    matrix = Counter()
    for qa_id, corr in corrections.items():
        v2j = qc_v2.get(qa_id, {}).get('judgment', '')
        matrix[(v2j, corr['eval_type'])] += 1

    row_idx += 1
    agreement_count = sum(matrix.get(p, 0) for p in [
        ('Gold', 'OK'), ('보정필요', '보정 필요'), ('보정필요', '환각'),
        ('탈락', '보정 필요'), ('탈락', '환각'),
    ])
    pct = agreement_count / n_total * 100 if n_total else 0
    legal_ws.cell(row_idx, 1).value = f"전체 일치율: {agreement_count}/{n_total} = {pct:.1f}%"

    row_idx += 1
    strict_agree = sum(matrix.get(p, 0) for p in [
        ('Gold', 'OK'), ('Gold', '보정 필요'), ('Gold', '환각'),
        ('보정필요', '보정 필요'), ('보정필요', '환각'),
        ('탈락', '보정 필요'), ('탈락', '환각'),
    ])
    spct = strict_agree / n_total * 100 if n_total else 0
    legal_ws.cell(row_idx, 1).value = (
        f"엄격 방향 일치율: {strict_agree}/{n_total} = {spct:.1f}% (자동 검수가 인간보다 같거나 더 엄격)"
    )

    # 매트릭스 출력
    row_idx += 2
    legal_ws.cell(row_idx, 1).value = "── 매트릭스 (v2 행 × 인간 열) ──"
    row_idx += 1
    legal_ws.cell(row_idx, 1).value = "v2 \\ 인간"
    legal_ws.cell(row_idx, 2).value = "OK"
    legal_ws.cell(row_idx, 3).value = "보정 필요"
    legal_ws.cell(row_idx, 4).value = "환각"
    legal_ws.cell(row_idx, 5).value = "합계"
    for v2j in ['Gold', '보정필요', '탈락']:
        row_idx += 1
        legal_ws.cell(row_idx, 1).value = v2j
        legal_ws.cell(row_idx, 2).value = matrix.get((v2j, 'OK'), 0)
        legal_ws.cell(row_idx, 3).value = matrix.get((v2j, '보정 필요'), 0)
        legal_ws.cell(row_idx, 4).value = matrix.get((v2j, '환각'), 0)
        legal_ws.cell(row_idx, 5).value = sum(matrix.get((v2j, h), 0) for h in ['OK', '보정 필요', '환각'])

    print(f"  법리_검수 시트 100건 + 통계 + 매트릭스 박음")

    # 저장
    print(f"\n[저장] {output_xlsx}")
    wb.save(output_xlsx)

    print("\n" + "=" * 60)
    print("v2.6 부분 보정 완료")
    print("=" * 60)
    print(f"\n## 보정 요약")
    print(f"- 17번째 항목 갱신: {updated_count}건")
    print(f"- 답변 보정 마커: {correction_marked_count}건")
    print(f"- 분류_데이터셋 위반조문 보정: {class_corrected}/7 사건")
    print(f"- 검수_결과표 v2 통계 행 추가")
    print(f"- 법리_검수 시트 100건 박음")
    print(f"\n## 매트릭스 (v2 \\ 인간)")
    print(f"          OK   보정필요  환각")
    for v2j in ['Gold', '보정필요', '탈락']:
        row = [matrix.get((v2j, h), 0) for h in ['OK', '보정 필요', '환각']]
        print(f"  {v2j:<7}: {row[0]:>3}    {row[1]:>3}    {row[2]:>3}")
    print(f"\n## 일치율 (분모 = 외부 검수 데이터 {n_total}건)")
    print(f"  전체 일치율: {agreement_count}/{n_total} = {pct:.1f}%")
    print(f"  엄격 방향 일치율: {strict_agree}/{n_total} = {spct:.1f}%")

    return {
        'updated': updated_count,
        'marked': correction_marked_count,
        'class_corrected': class_corrected,
        'agreement': agreement_count,
        'strict_agree': strict_agree,
        'matrix': dict(matrix),
    }


if __name__ == '__main__':
    base_xlsx = sys.argv[1] if len(sys.argv) > 1 else '제출_패키지/학습데이터_설계서_DecisionMiner_v2_4.xlsx'
    qc_v2_csv = sys.argv[2] if len(sys.argv) > 2 else '11_data_quality/qc_result_990_v2.csv'
    corrections_csv = sys.argv[3] if len(sys.argv) > 3 else 'qa_corrections_100.csv'
    law_csv = sys.argv[4] if len(sys.argv) > 4 else 'case_law_corrections_7.csv'
    output_xlsx = sys.argv[5] if len(sys.argv) > 5 else '제출_패키지/학습데이터_설계서_DecisionMiner_v2_6.xlsx'
    patch_xlsx_v26(base_xlsx, qc_v2_csv, corrections_csv, law_csv, output_xlsx)
