"""
build_static_labels.py — 오더 #4: 설계서 xlsx → 정적 990건 신뢰등급 라벨맵 생성

단일 진실(핸드오프 §4): 정적 990건의 신뢰등급은 설계서 xlsx '전체_QA' 시트의
17번째 컬럼 '자동 검수 결과 및 활용 유의' 텍스트에서 도출(2차 설계서 재생성과 동일 규칙).
  - 차단결함 E6·E10·E4·E3 중 하나라도 포함 → 부적합
  - 차단 없이 주의신호 E5·E7·E8 또는 '확인필요:' 플래그 → 검토
  - 둘 다 없음 → 적합

산출: 11_data_quality/static_labels_990.json  ({ "<ID>": "<신뢰등급>" }, ID = {사건키}_{NNN})
이 맵을 export_tiers가 로드해 정적 22사건 라벨로 사용한다(grounding 재채점 금지).

사용: python3 build_static_labels.py [설계서.xlsx]
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = PROJECT_ROOT / "학습데이터_설계서_DecisionMiner_v2_7.xlsx"
OUT_JSON = PROJECT_ROOT / "11_data_quality" / "static_labels_990.json"

_BLOCK = re.compile(r"\bE6\b|\bE10\b|\bE4\b|\bE3\b")
_ADV = re.compile(r"\bE5\b|\bE7\b|\bE8\b|확인필요")


def nfc(s) -> str:
    return unicodedata.normalize("NFC", str(s).strip())


def tier_from_audit(text: str) -> str:
    t = str(text or "")
    if _BLOCK.search(t):
        return "부적합"
    if _ADV.search(t):
        return "검토"
    return "적합"


def build(xlsx_path: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["전체_QA"]
    allrows = list(ws.iter_rows(values_only=True))
    wb.close()
    # 1행=제목 배너, 2행=헤더, 3행~=데이터. 헤더에서 ID/검수컬럼 위치 확인.
    header = [nfc(c) if c is not None else "" for c in allrows[1]]
    id_col = header.index("ID")
    audit_col = header.index("자동 검수 결과 및 활용 유의")
    data = [r for r in allrows[2:] if any(c is not None and str(c).strip() for c in r)]

    labels = {}
    for r in data:
        rid = nfc(r[id_col])
        if rid:
            labels[rid] = tier_from_audit(r[audit_col])
    return labels


def main() -> None:
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    labels = build(xlsx)
    OUT_JSON.write_text(json.dumps(labels, ensure_ascii=False, indent=0), encoding="utf-8")
    dist = Counter(labels.values())
    print(f"[build_static_labels] {xlsx.name} → {OUT_JSON}")
    print(f"  항목수: {len(labels)}  분포: {dict(dist)}  사용가능(적합+검토): {dist['적합']+dist['검토']}")


if __name__ == "__main__":
    main()
