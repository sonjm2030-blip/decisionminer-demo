"""
quality_checker_grounding.py — 오더 #3 작업 1: E3를 grounding 기준으로 교체

웹 데모 v4 (DecisionMiner_web_v4.jsx)의 validate()를 파이썬으로 1:1 포팅한
3단계(적합/검토/부적합) 검수기. 기존 score 기반 quality_checker_v2.py를 대체하지
않고(역사 보존), export_tiers·재채점이 참조하는 '정렬된' 검수 기준을 제공한다.

핵심 변경 (E3):
  - 폐기: 법령·조항을 답변/근거 텍스트에 정규식(제○조·○○법)으로 찾아 없으면 차단.
  - 도입: 구조화 위반조문(legal.json의 조문 = CSV의 '적용조문')·적용법령이 존재하면
          grounded → 통과. 위반조문도 없고 근거 청크 매칭도 없을 때만 차단(E3).
  - 질문유형==법령중심인데 답변에 제○조 표기 없음 → 차단 아님, 주의(검토).

CLI:
  python3 quality_checker_grounding.py                      # 기본 990 CSV 재채점, before/after 출력
  python3 quality_checker_grounding.py --input <csv> --out <csv>
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# ─────────────────────────── enum / 필수필드 (v4 동일) ───────────────────────────
ENUMS = {
    "페르소나": ["일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생"],
    "질문유형": ["제재중심", "법령중심", "유사사례", "통계기반", "시장영향"],
    "난이도": ["기초", "심화", "전문가"],
    "사건유형": ["담합", "하도급", "거래상지위", "표시광고", "전자상거래",
                "사업자단체", "가맹사업", "재판매가격", "부당지원", "부당고객유인"],
}
REQUIRED = ["ID", "페르소나", "질문유형", "난이도", "사건유형", "질문", "답변", "근거"]

_LAW_ART = re.compile(r"제\s?\d+\s?조")
_LAW_OR_ART = re.compile(r"제\s?\d+\s?조|[가-힣]{2,}법")
_PII = re.compile(r"\d{6}-\d{7}|01\d-?\d{3,4}-?\d{4}|[\w.]+@[\w.]+\.[a-z]{2,}", re.I)
_HEDGE_A = re.compile(r"아마|추정되|것으로\s?보|일\s?것|예상되|짐작")
_HEDGE_G = re.compile(r"아마|추정|예상")
_CONTRA_POS = re.compile(r"위반")
_CONTRA_NEG = re.compile(r"무혐의|위반하지\s?않|해당하지\s?않")
_SANCTION = re.compile(r"과징금|시정명령|시정조치|과태료|처분|시정")
_JARGON = re.compile(r"제\s?\d+\s?조|소정의|동법|시행령|구성요건|법리|판시|위법성|귀책")


def _has(pat: re.Pattern, s: str) -> bool:
    return bool(pat.search(s or ""))


# ─────────────────────────── 금액 추출 (v4 extractAmounts 포팅) ───────────────────────────
def extract_amounts(text: str) -> set[int]:
    s: set[int] = set()
    if not text:
        return s
    t = re.sub(r"\s", "", str(text))

    def _digits(g: str) -> int | None:
        d = g.replace(",", "")
        return int(d) if d else None   # JS parseInt("") → NaN: 무시

    for m in re.finditer(r"([\d,]+)억", t):
        d = _digits(m.group(1));  s.add(d * 10**8) if d is not None else None
    for m in re.finditer(r"([\d,]+)백만", t):
        d = _digits(m.group(1));  s.add(d * 10**6) if d is not None else None
    for m in re.finditer(r"([\d,]+)만", t):
        d = _digits(m.group(1))
        if d is not None and d * 10**4 >= 10**4:
            s.add(d * 10**4)
    for m in re.finditer(r"([\d,]{4,})원", t):
        d = _digits(m.group(1));  s.add(d) if d is not None else None
    return s


def _near(a: int, gset: set[int]) -> bool:
    return any(abs(a - g) / max(a, g, 1) < 0.02 for g in gset)


# ─────────────────────────── validate (v4 1:1 포팅) ───────────────────────────
def validate(r: dict, grounding: bool = True) -> dict:
    """v4 validate() 포팅.

    grounding=True  → 신 로직(구조화 위반조문·적용법령 존재 시 통과).
    grounding=False → 구 텍스트매칭(근거 텍스트에 법령·조항 정규식 없으면 차단) — before 비교용.

    record 필드: ID/페르소나/질문유형/난이도/사건유형/질문/답변/근거 (+ 위반조문/적용법령).
    """
    A = r.get("답변") or ""
    G = r.get("근거") or ""
    article = str(r.get("위반조문") or "").strip()   # = legal.json 조문 / CSV 적용조문
    law = str(r.get("적용법령") or "").strip()
    stages = []

    # 1단계 · 원문무결성
    c1 = []
    missing = [k for k in REQUIRED if not r.get(k) or str(r.get(k)).strip() == ""]
    if missing:
        c1.append(("block", "E1", f"필수필드 누락: {', '.join(missing)}"))
    else:
        c1.append(("pass", None, "필수필드 8종 모두 존재"))
    if not G or len(G.strip()) < 10:
        if "근거" not in missing:
            c1.append(("block", "E1", "근거(원문 매칭) 누락"))
    else:
        c1.append(("pass", None, "근거 원문 매칭 존재"))
    stages.append(("1단계·원문무결성", c1))

    # 2단계 · 구조분해 (enum + grounding)
    c2 = []
    enum_bad = False
    for k in ("페르소나", "질문유형", "난이도", "사건유형"):
        if r.get(k) and str(r.get(k)).strip() not in ENUMS[k]:
            enum_bad = True
            c2.append(("block", "E3", f'enum 위반: {k}="{r.get(k)}"'))
    if not enum_bad:
        c2.append(("pass", None, "enum 정합"))
    if grounding:
        is_grounded = bool(article) or bool(law) or _has(_LAW_OR_ART, G)
    else:
        # 구(舊) 텍스트매칭: 근거 텍스트에 법령·조항 정규식이 있어야만 통과
        is_grounded = _has(_LAW_OR_ART, G)
    if is_grounded:
        c2.append(("pass", None, f"법적 근거 확인 (위반조문 {article})" if article else "법적 근거 확인 (텍스트 매칭)"))
    else:
        c2.append(("block", "E3", "법적 근거 없음 (위반조문·법령 미확인)"))
    stages.append(("2단계·구조분해", c2))

    # 3단계 · 메타정합 (조항 grounding + 상반판단)
    c3 = []
    if grounding:
        art_ground = bool(article) or _has(_LAW_ART, G)
    else:
        art_ground = _has(_LAW_ART, G)
    if art_ground:
        c3.append(("pass", None, "조항 정합"))
    else:
        c3.append(("block", "E3", "조항 미확인 (위반조문·근거 없음)"))
    if r.get("질문유형") == "법령중심" and not _has(_LAW_ART, A):
        c3.append(("adv", "E3", "조항 명시 권장 (법령중심 답변에 조문 표기 없음)"))
    if _has(_CONTRA_POS, A) and _has(_CONTRA_NEG, A):
        c3.append(("block", "E4", "상반 판단 동시 출현"))
    else:
        c3.append(("pass", None, "판단 일관성"))
    stages.append(("3단계·메타정합", c3))

    # 4단계 · 사실정합 (환각·금액·분량)
    c4 = []
    if _has(_HEDGE_A, A) and not _has(_HEDGE_G, G):
        c4.append(("block", "E6", "환각 (근거 없는 추론 표현)"))
    else:
        c4.append(("pass", None, "근거 범위 내 응답"))
    a_amt, g_amt = extract_amounts(A), extract_amounts(G)
    mism = [a for a in a_amt if not _near(a, g_amt)]
    if g_amt and mism:
        c4.append(("adv", "E5", "수치 확인 권장"))
    else:
        c4.append(("pass", None, "금액 정합"))
    under = False
    if r.get("질문유형") == "제재중심" and not _has(_SANCTION, A):
        under = True
    if r.get("질문유형") == "법령중심" and not _has(_LAW_ART, A):
        under = True
    if len(re.sub(r"\s", "", A)) < 40:
        under = True
    if under:
        c4.append(("adv", "E8", "분량·필수요소 보강 권장"))
    else:
        c4.append(("pass", None, "분량 충족"))
    stages.append(("4단계·사실정합", c4))

    # 5단계 · 활용성 (개인정보·톤)
    c5 = []
    if _has(_PII, A):
        c5.append(("block", "E10", "개인정보 포함"))
    else:
        c5.append(("pass", None, "개인정보 미포함"))
    jargon = len(_JARGON.findall(A))
    e7 = False
    if r.get("페르소나") == "일반국민" and jargon >= 3:
        e7 = True
    elif r.get("페르소나") in ("논문 준비 학생", "기업 컴플라이언스 담당자") and jargon == 0:
        e7 = True
    elif r.get("난이도") == "전문가" and jargon == 0:
        e7 = True
    if e7:
        c5.append(("adv", "E7", "페르소나 톤 다듬기 권장"))
    else:
        c5.append(("pass", None, "페르소나 톤 적합"))
    stages.append(("5단계·활용성", c5))

    block_n = sum(1 for _, cs in stages for lvl, *_ in cs if lvl == "block")
    adv_n = sum(1 for _, cs in stages for lvl, *_ in cs if lvl == "adv")
    tier = "부적합" if block_n > 0 else ("검토" if adv_n > 0 else "적합")
    block_codes = sorted({code for _, cs in stages for lvl, code, *_ in cs if lvl == "block" and code})
    return {"tier": tier, "blockN": block_n, "advN": adv_n, "block_codes": block_codes, "stages": stages}


# ─────────────────────────── CSV → record 매핑 ───────────────────────────
def csv_to_record(row: dict) -> dict:
    """qa_evaluated_990.csv 행 → validate 입력 record.

    적용조문 → 위반조문(구조화), 적용법령 → 적용법령. 나머지 동명 필드 직결.
    """
    return {
        "ID": row.get("ID", ""),
        "페르소나": row.get("페르소나", ""),
        "질문유형": row.get("질문유형", ""),
        "난이도": row.get("난이도", ""),
        "사건유형": row.get("사건유형", ""),
        "질문": row.get("질문", ""),
        "답변": row.get("답변", ""),
        "근거": row.get("근거", ""),
        "위반조문": row.get("적용조문", ""),
        "적용법령": row.get("적용법령", ""),
    }


def _dist(rows: list[dict], grounding: bool) -> tuple[dict, dict]:
    tally = {"적합": 0, "검토": 0, "부적합": 0}
    codes: dict[str, int] = {}
    for row in rows:
        res = validate(csv_to_record(row), grounding=grounding)
        tally[res["tier"]] += 1
        if res["tier"] == "부적합":
            for c in res["block_codes"]:
                codes[c] = codes.get(c, 0) + 1
    return tally, codes


def _fmt(tally: dict, n: int) -> str:
    return " · ".join(f"{k} {v}건({v/n*100:.1f}%)" for k, v in tally.items())


def main() -> None:
    proj = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(proj / "11_data_quality" / "qa_evaluated_990.csv"))
    ap.add_argument("--out", default=str(proj / "11_data_quality" / "qc_result_grounding_990.csv"))
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.input, encoding="utf-8-sig")))
    n = len(rows)
    print(f"[로드] {a.input} → {n}건\n")

    before, bcodes = _dist(rows, grounding=False)
    after, acodes = _dist(rows, grounding=True)

    print("── 재채점 결과 (E3 텍스트매칭 → grounding) ──")
    print(f"BEFORE (텍스트매칭): {_fmt(before, n)}")
    print(f"  └ 부적합 차단코드: {dict(sorted(bcodes.items()))}")
    print(f"AFTER  (grounding) : {_fmt(after, n)}")
    print(f"  └ 부적합 차단코드: {dict(sorted(acodes.items()))}")
    print(f"\n부적합률: {before['부적합']/n*100:.1f}% → {after['부적합']/n*100:.1f}% "
          f"(Δ {(before['부적합']-after['부적합'])/n*100:+.1f}%p)")
    only_real = set(acodes) <= {"E6", "E10", "E4", "E1"}
    print(f"AFTER 부적합이 환각/개인정보/상반판단/누락에만 걸림: {only_real}")

    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "사건키", "tier_grounding", "block_codes", "blockN", "advN"])
        for row in rows:
            res = validate(csv_to_record(row), grounding=True)
            w.writerow([row.get("ID", ""), row.get("사건키", ""), res["tier"],
                        "|".join(res["block_codes"]), res["blockN"], res["advN"]])
    print(f"\n[저장] {a.out}")


if __name__ == "__main__":
    main()
