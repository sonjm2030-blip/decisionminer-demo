"""
Tier 2 정밀화 대상 35건 선정 + 정밀화 템플릿 생성기.

입력
  - 11_data_quality/tier1_ai_auto/_combined.json  (Tier 1 AI 자동 검수 결과)
  - 04_raw_outputs/{사건키}/qa_list.json          (원본 QA 메타)

출력
  - 11_data_quality/tier2_human_polish/Day6_35건_정밀화.md
  - 11_data_quality/tier2_human_polish/Day6_35건_선정.csv

선정 규칙
  사건유형 7종(담합/하도급/거래상지위/표시광고/전자상거래/사업자단체/가맹사업) × 5건 = 35건
  각 5건 배분
    - 페르소나 : 일반국민 2 / 기업 컴플라이언스 담당자 2 / 논문 준비 학생 1
    - 난이도   : 기초 2 / 심화 2 / 전문가 1
    - 색상     : GREEN 2 / YELLOW 2 / RED 1   (RED 부족 시 YELLOW 로 대체, GREEN 부족 시 YELLOW 로 대체)

Confidence 색상 도출 규칙(Tier 1 문제점 텍스트 기반)
  GREEN  : "특이사항 없음"/"해당 없음" 또는 긍정 평가('적절','양호','타당','잘 설명') 로 시작하는 짧은 문제점
  RED    : 사실 오류·왜곡·부정확·누락·잘못 등 명백한 결함 키워드 포함
  YELLOW : 그 외(보통 수준의 보완 권고)

작성: 17열 Tier 2
"""

from __future__ import annotations
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
COMBINED = ROOT / "11_data_quality" / "tier1_ai_auto" / "_combined.json"
RAW_DIR = ROOT / "04_raw_outputs"
OUT_DIR = ROOT / "11_data_quality" / "tier2_human_polish"
OUT_MD = OUT_DIR / "Day6_35건_정밀화.md"
OUT_CSV = OUT_DIR / "Day6_35건_선정.csv"

TARGET_TYPES = ["담합", "하도급", "거래상지위", "표시광고", "전자상거래", "사업자단체", "가맹사업"]
PERSONA_QUOTA = {"일반국민": 2, "기업 컴플라이언스 담당자": 2, "논문 준비 학생": 1}
DIFF_QUOTA = {"기초": 2, "심화": 2, "전문가": 1}
COLOR_QUOTA = {"GREEN": 2, "YELLOW": 2, "RED": 1}
COLOR_FALLBACK = {"RED": "YELLOW", "GREEN": "YELLOW"}


def classify_color(prob: str) -> str:
    p = (prob or "").strip()
    if any(k in p for k in ("특이사항 없음", "해당 없음")) and len(p) < 40:
        return "GREEN"
    red_kw = (
        "사실 오류", "내용 오류", "불일치", "왜곡", "잘못 기재", "잘못된",
        "부정확", "누락", "심각", "치명적", "명백히 다르", "실제와 다르",
        "과대", "과장", "허위",
    )
    if any(k in p for k in red_kw):
        return "RED"
    pos_kw = ("적절하", "양호", "타당", "잘 설명", "잘 반영", "전반적으로", "대체로", "문제없", "이상 없")
    if any(k in p[:80] for k in pos_kw) and ("다만" in p or "추가" in p or len(p) < 200):
        return "GREEN"
    return "YELLOW"


def load_qa_list(case_key: str) -> list[dict]:
    path = RAW_DIR / case_key / "qa_list.json"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def join_records() -> list[dict]:
    """Tier 1 결과 + qa_list 메타를 qa_id 순서로 조인."""
    with COMBINED.open(encoding="utf-8") as f:
        combined = json.load(f)

    rows: list[dict] = []
    for case in combined["cases"]:
        case_key = case["case_key"]
        case_type = case["case_type"]
        qa_meta = load_qa_list(case_key)
        results_by_id = {r["qa_id"]: r for r in case["results"]}

        for idx, meta in enumerate(qa_meta, start=1):
            qa_id = f"{idx:03d}"
            tier1 = results_by_id.get(qa_id, {})
            problem = tier1.get("문제점", "")
            solution = tier1.get("해결방안", "")
            color = classify_color(problem)
            rows.append({
                "case_key": case_key,
                "case_type": case_type,
                "qa_id": qa_id,
                "페르소나": meta.get("페르소나", ""),
                "난이도": meta.get("난이도", ""),
                "질문유형": meta.get("질문유형", ""),
                "질문": meta.get("질문", ""),
                "답변": meta.get("답변", ""),
                "근거_short": meta.get("근거_short", ""),
                "tier1_문제점": problem,
                "tier1_해결방안": solution,
                "color": color,
            })
    return rows


# 5건 슬롯 사양: (페르소나, 난이도, 색상)
# 페르소나 2-2-1, 난이도 2-2-1, 색상 2-2-1 모두 동시 충족하는 한 가지 균형 배치.
SLOT_SPECS: list[tuple[str, str, str]] = [
    ("일반국민",            "기초",   "GREEN"),
    ("일반국민",            "심화",   "YELLOW"),
    ("기업 컴플라이언스 담당자", "심화",   "RED"),
    ("기업 컴플라이언스 담당자", "전문가", "GREEN"),
    ("논문 준비 학생",       "기초",   "YELLOW"),
]


def _pick(pool: list[dict], used: set[int], *,
          persona: str | None, diff: str | None, color: str | None) -> int | None:
    for i, row in enumerate(pool):
        if i in used:
            continue
        if persona is not None and row["페르소나"] != persona:
            continue
        if diff is not None and row["난이도"] != diff:
            continue
        if color is not None and row["color"] != color:
            continue
        return i
    return None


def select_for_type(pool: list[dict]) -> list[dict]:
    """단일 사건유형 풀에서 슬롯 사양에 맞춰 5건 선정.

    각 슬롯에 대해 우선순위(페르소나·난이도 동시 만족이 최우선)로 후보를 탐색.
        1) 페르소나·난이도·색상 모두 매칭
        2) 색상 폴백(RED→YELLOW, GREEN→YELLOW)
        3) 색상 무시, 페르소나·난이도 매칭
        4) 페르소나만 매칭
        5) 난이도만 매칭
        6) 아무거나
    """
    chosen: list[int] = []
    used: set[int] = set()

    for persona, diff, color in SLOT_SPECS:
        idx = _pick(pool, used, persona=persona, diff=diff, color=color)
        if idx is None:
            fb = COLOR_FALLBACK.get(color)
            if fb:
                idx = _pick(pool, used, persona=persona, diff=diff, color=fb)
        if idx is None:
            idx = _pick(pool, used, persona=persona, diff=diff, color=None)
        if idx is None:
            idx = _pick(pool, used, persona=persona, diff=None, color=None)
        if idx is None:
            idx = _pick(pool, used, persona=None, diff=diff, color=None)
        if idx is None:
            idx = _pick(pool, used, persona=None, diff=None, color=None)
        if idx is not None:
            chosen.append(idx)
            used.add(idx)

    return [pool[i] for i in chosen]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = join_records()
    print(f"[load] 전체 QA = {len(rows)}건 / 사건 = {len({r['case_key'] for r in rows})}")

    selections: dict[str, list[dict]] = {}
    for ct in TARGET_TYPES:
        pool = [r for r in rows if r["case_type"] == ct]
        print(f"[pool] {ct}: {len(pool)}건  (색상 {Counter(r['color'] for r in pool)})")
        selections[ct] = select_for_type(pool)

    # ── CSV 저장
    fieldnames = [
        "no", "case_type", "case_key", "qa_id", "페르소나", "난이도", "질문유형",
        "color", "질문", "답변", "근거_short", "tier1_문제점", "tier1_해결방안",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        no = 0
        for ct in TARGET_TYPES:
            for r in selections[ct]:
                no += 1
                w.writerow({"no": no, **{k: r.get(k, "") for k in fieldnames if k != "no"}})

    # ── Markdown 정밀화 템플릿 저장
    lines: list[str] = []
    lines.append("# Day 6 — Tier 2 사람 정밀화 작업지 (35건)")
    lines.append("")
    lines.append(f"- 입력: `11_data_quality/tier1_ai_auto/_combined.json` ({len(rows)} QA)")
    lines.append(f"- 산출: 본 파일 + `Day6_35건_선정.csv`")
    lines.append(f"- 사건유형 7종 × 5건 = 35건 (각 5건: 페르소나 2·2·1 / 난이도 2·2·1 / 색상 2·2·1)")
    lines.append("")
    lines.append("## 선정 분포 요약")
    lines.append("")
    persona_total: Counter = Counter()
    diff_total: Counter = Counter()
    color_total: Counter = Counter()
    for ct in TARGET_TYPES:
        sel = selections[ct]
        persona_total.update(r["페르소나"] for r in sel)
        diff_total.update(r["난이도"] for r in sel)
        color_total.update(r["color"] for r in sel)
    lines.append(f"- 페르소나: {dict(persona_total)}")
    lines.append(f"- 난이도: {dict(diff_total)}")
    lines.append(f"- 색상: {dict(color_total)}")
    lines.append("")
    lines.append("| 사건유형 | 일반국민 | 기업컴플 | 논문학생 | 기초 | 심화 | 전문가 | GREEN | YELLOW | RED |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for ct in TARGET_TYPES:
        sel = selections[ct]
        pp = Counter(r["페르소나"] for r in sel)
        dd = Counter(r["난이도"] for r in sel)
        cc = Counter(r["color"] for r in sel)
        lines.append(
            f"| {ct} | {pp.get('일반국민',0)} | {pp.get('기업 컴플라이언스 담당자',0)} | "
            f"{pp.get('논문 준비 학생',0)} | {dd.get('기초',0)} | {dd.get('심화',0)} | "
            f"{dd.get('전문가',0)} | {cc.get('GREEN',0)} | {cc.get('YELLOW',0)} | {cc.get('RED',0)} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    no = 0
    for ct in TARGET_TYPES:
        lines.append(f"# ▶ 사건유형: {ct}")
        lines.append("")
        for r in selections[ct]:
            no += 1
            lines.append("---")
            lines.append(
                f"### [{no:02d}] {r['qa_id']} | {ct} | {r['페르소나']} | {r['난이도']} | {r['color']}"
            )
            lines.append("")
            lines.append(f"**질문**: {r['질문']}")
            ans = r["답변"] or ""
            lines.append(f"**답변**: {ans[:200]}{'…' if len(ans) > 200 else ''}")
            lines.append("")
            lines.append("**Tier 1 AI 초안**:")
            lines.append(f"- 문제점: {r['tier1_문제점'] or '(Tier 1 결과 없음)'}")
            lines.append(f"- 해결방안: {r['tier1_해결방안'] or '(Tier 1 결과 없음)'}")
            lines.append("")
            lines.append("**→ Tier 2 정밀화** (여기를 직접 작성):")
            lines.append("- 문제점: ")
            lines.append("- 해결방안: ")
            lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    # ── 콘솔 요약
    print()
    print(f"[save] {OUT_CSV.relative_to(ROOT)}")
    print(f"[save] {OUT_MD.relative_to(ROOT)}")
    print()
    print("== 분포 ==")
    print("페르소나:", dict(persona_total))
    print("난이도:", dict(diff_total))
    print("색상:", dict(color_total))
    print()
    print("== 사건유형별 ==")
    for ct in TARGET_TYPES:
        sel = selections[ct]
        pp = Counter(r["페르소나"] for r in sel)
        dd = Counter(r["난이도"] for r in sel)
        cc = Counter(r["color"] for r in sel)
        print(f"  {ct:6s} | 페르소나={dict(pp)} 난이도={dict(dd)} 색상={dict(cc)}")


if __name__ == "__main__":
    main()
