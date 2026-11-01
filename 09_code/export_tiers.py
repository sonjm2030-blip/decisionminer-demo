"""
export_tiers.py — 오더 #3 작업 3: 04_raw_outputs/{사건키} → 사용처별 3티어 산출

웹 데모 v4의 buildContent/trainContent/evalContent를 1:1 포팅.
신뢰등급은 작업 1의 grounding 검수기(quality_checker_grounding.validate)를 사용하며,
Train(학습)은 '부적합'을 제외한다.

산출 (case_dir에 저장):
  - {사건키}_build.json : facts·legal·sanction·evidence·qa 전체 + chunk_id (가공 원본)
  - {사건키}_train.jsonl: QA 1행 = {"messages":[{user:질문},{assistant:답변}],
                          "meta":{사건유형,페르소나,난이도,질문유형,신뢰등급}}  ※ 부적합 제외
  - eval_gold.json      : {질문,정답,근거,위반조문,난이도,질문유형,신뢰등급}

CLI:
  python3 export_tiers.py "<04_raw_outputs/사건키 경로>"
  python3 export_tiers.py --all          # 04_raw_outputs 전체 사건
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_checker_grounding import validate  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "04_raw_outputs"
STATIC_LABELS_JSON = PROJECT_ROOT / "11_data_quality" / "static_labels_990.json"
STEP_FILES = {
    "facts": "facts.json",
    "legal": "legal.json",
    "sanction": "sanction.json",
    "evidence": "evidence.json",
    "qa": "qa_list.json",
}


def _nfc(s) -> str:
    return unicodedata.normalize("NFC", str(s).strip())


_STATIC_LABELS_CACHE = None


def load_static_labels() -> dict:
    """정적 990건 신뢰등급 라벨맵 {NFC(ID): 등급} 로드 (1회 캐시).

    오더 #4: 정적 22사건은 설계서 xlsx 17번째 컬럼 기반 라벨(195/768/27)을 사용하고
    grounding 재채점을 하지 않는다. 파일이 없으면 build_static_labels.py 실행 안내.
    """
    global _STATIC_LABELS_CACHE
    if _STATIC_LABELS_CACHE is None:
        if STATIC_LABELS_JSON.exists():
            raw = json.loads(STATIC_LABELS_JSON.read_text(encoding="utf-8"))
            _STATIC_LABELS_CACHE = {_nfc(k): v for k, v in raw.items()}
        else:
            print(f"[WARN] {STATIC_LABELS_JSON} 없음 — `python3 09_code/build_static_labels.py` 먼저 실행. "
                  f"정적 라벨 없이 grounding으로 진행.")
            _STATIC_LABELS_CACHE = {}
    return _STATIC_LABELS_CACHE


def _load(case_dir: Path) -> dict:
    out = {}
    for key, fname in STEP_FILES.items():
        p = case_dir / fname
        out[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return out


def _case_meta(data: dict, case_key: str) -> dict:
    """사건 단위 메타(사건유형·위반조문·적용법령) — legal.json에서 추출."""
    legal = data.get("legal") or {}
    tags = legal.get("classification_tags") or {}
    article = (str(legal.get("조문", "")).strip()
               or str(tags.get("위반_조문", "")).strip())
    law = str(legal.get("법령", "")).strip()
    case_type = (str(tags.get("사건유형_대분류", "")).strip()
                 or str(legal.get("사건유형_대분류", "")).strip())
    return {"사건키": case_key, "사건유형": case_type, "위반조문": article, "적용법령": law}


def _qa_record(q: dict, meta: dict, idx: int) -> dict:
    """qa_list 항목 → validate 입력 record (v4 recOf 대응)."""
    return {
        "ID": f"{meta['사건키']}_{idx:03d}",
        "페르소나": q.get("페르소나", ""),
        "질문유형": q.get("질문유형", ""),
        "난이도": q.get("난이도", ""),
        "사건유형": meta["사건유형"],
        "질문": q.get("질문", ""),
        "답변": q.get("답변", ""),
        "근거": q.get("근거_short") or q.get("근거", ""),
        "위반조문": meta["위반조문"],
        "적용법령": meta["적용법령"],
    }


def export_tiers(case_dir, out_dir=None, label_source="auto") -> dict:
    """case_dir(04_raw_outputs/{사건키}) → build/train/eval 3파일 생성.

    신뢰등급 소스 (오더 #4):
      - label_source="auto"(기본): 정적 라벨맵에 ID가 있으면 원본 라벨(설계서 195/768/27 기준),
        없으면(신규 PDF) grounding 검수기로 자동 분기 — QA별로 결정.
      - "static"  : 원본 라벨 강제(없으면 grounding 폴백 + 경고).
      - "grounding": v4 라이브 검수기 강제(신규 PDF·재채점 검증용).

    반환: {build, train, eval, counts, label_source_used:{static,grounding}} 경로·집계.
    """
    case_dir = Path(case_dir)
    out_dir = Path(out_dir) if out_dir else case_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    case_key = case_dir.name

    data = _load(case_dir)
    if not data.get("qa"):
        raise FileNotFoundError(f"{case_dir}/qa_list.json 없음 — 5단 분해 먼저 필요")
    meta = _case_meta(data, case_key)
    qa_items = data["qa"] if isinstance(data["qa"], list) else []

    static_labels = load_static_labels() if label_source in ("auto", "static") else {}

    rows = []
    tally = {"적합": 0, "검토": 0, "부적합": 0}
    src_used = {"static": 0, "grounding": 0}
    for i, q in enumerate(qa_items, 1):
        rec = _qa_record(q, meta, i)
        static_tier = static_labels.get(_nfc(rec["ID"]))
        if static_tier is not None and label_source != "grounding":
            tier = static_tier
            src_used["static"] += 1
        else:
            tier = validate(rec, grounding=True)["tier"]
            src_used["grounding"] += 1
        tally[tier] += 1
        rows.append((rec, tier))

    # ── Build: 가공 원본 전체 (chunk_id 포함된 evidence 그대로) ──
    build = {
        "사건키": case_key,
        "사건유형": meta["사건유형"],
        "적용법령": meta["적용법령"],
        "위반조문": meta["위반조문"],
        "facts": data.get("facts"),
        "legal": data.get("legal"),
        "sanction": data.get("sanction"),
        "evidence": data.get("evidence"),
        "qa": qa_items,
    }
    build_path = out_dir / f"{case_key}_build.json"
    build_path.write_text(json.dumps(build, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Train: 부적합 제외, 1행 1 QA (jsonl) ──
    train_path = out_dir / f"{case_key}_train.jsonl"
    train_lines = []
    for rec, tier in rows:
        if tier == "부적합":
            continue
        train_lines.append(json.dumps({
            "messages": [
                {"role": "user", "content": rec["질문"]},
                {"role": "assistant", "content": rec["답변"]},
            ],
            "meta": {
                "사건유형": rec["사건유형"],
                "페르소나": rec["페르소나"],
                "난이도": rec["난이도"],
                "질문유형": rec["질문유형"],
                "신뢰등급": tier,
            },
        }, ensure_ascii=False))
    train_path.write_text("\n".join(train_lines) + ("\n" if train_lines else ""), encoding="utf-8")

    # ── Eval: 전체 QA + 정답·근거·위반조문·신뢰등급 ──
    eval_rows = [{
        "id": rec["ID"],
        "질문": rec["질문"],
        "정답": rec["답변"],
        "근거": rec["근거"],
        "위반조문": meta["위반조문"],
        "난이도": rec["난이도"],
        "질문유형": rec["질문유형"],
        "신뢰등급": tier,
    } for rec, tier in rows]
    eval_path = out_dir / "eval_gold.json"
    eval_path.write_text(json.dumps(eval_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = {**tally, "train_lines": len(train_lines)}
    src = "정적라벨" if src_used["grounding"] == 0 else ("grounding" if src_used["static"] == 0 else "혼합")
    print(f"[export] {case_key}: {tally} → train {len(train_lines)}행 "
          f"(부적합 {tally['부적합']}건 제외 · 등급출처={src} {src_used})")
    return {"build": str(build_path), "train": str(train_path), "eval": str(eval_path),
            "counts": counts, "label_source_used": src_used}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_dir", nargs="?", help="04_raw_outputs/{사건키} 경로")
    ap.add_argument("--all", action="store_true", help="04_raw_outputs 전체 사건")
    ap.add_argument("--label-source", default="auto", choices=["auto", "static", "grounding"],
                    help="신뢰등급 소스 (기본 auto: 정적라벨 우선, 신규는 grounding)")
    a = ap.parse_args()

    if a.all:
        dirs = [d for d in sorted(OUTPUT_DIR.iterdir())
                if d.is_dir() and (d / "qa_list.json").exists()]
    elif a.case_dir:
        dirs = [Path(a.case_dir)]
    else:
        ap.error("case_dir 또는 --all 필요")

    total = 0
    agg = {"적합": 0, "검토": 0, "부적합": 0}
    bad_by_case = {}
    for d in dirs:
        try:
            r = export_tiers(d, label_source=a.label_source)
            total += r["counts"]["train_lines"]
            for k in agg:
                agg[k] += r["counts"][k]
            if r["counts"]["부적합"]:
                bad_by_case[d.name] = r["counts"]["부적합"]
        except Exception as e:
            print(f"[SKIP] {d.name}: {type(e).__name__}: {e}")
    print(f"\n총 train 라인: {total}행 ({len(dirs)}개 사건)")
    print(f"전체 신뢰등급 분포: {agg} · 사용가능(적합+검토) {agg['적합']+agg['검토']}")
    print("사건별 부적합:")
    for ck, n in sorted(bad_by_case.items(), key=lambda x: -x[1]):
        print(f"  {n:2d}  {ck[:48]}")


if __name__ == "__main__":
    main()
