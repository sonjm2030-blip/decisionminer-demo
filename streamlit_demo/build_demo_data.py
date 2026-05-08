"""
쿠팡 사건 5단 분해 결과 + 검수 통계 + 메타 데이터셋 1건씩을
streamlit_demo/data/coupang_demo_data.json 단일 파일로 합친다.
"""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "04_raw_outputs"
DQ = ROOT / "11_data_quality"
OUT = Path(__file__).resolve().parent / "data" / "coupang_demo_data.json"

CASE_KEY = "쿠팡(주)의 전자상거래소비자보호법 등 위반행위에 대한 건"
CASE_DIR = RAW / CASE_KEY

# 명령서 lock — qa_id 마지막 3자리 (001 / 022 / 043)
QA_LOCK = [
    ("일반국민", "기초", "제재중심", "001"),
    ("기업 컴플라이언스 담당자", "심화", "법령중심", "022"),
    ("논문 준비 학생", "전문가", "유사사례", "043"),
]


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_csv(path):
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def truncate(s, n=200):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "..."


def collect_evidence_samples(evidence):
    """evidence.json의 facts/legal/sanction에서 각 카테고리당 1건씩 200자 샘플."""
    samples = []
    for top_key, label in [
        ("facts_evidence", "사실관계"),
        ("legal_evidence", "법적 판단"),
        ("sanction_evidence", "처분 근거"),
    ]:
        sec = evidence.get(top_key) or {}
        if not isinstance(sec, dict):
            continue
        for cat, items in sec.items():
            if not isinstance(items, list) or not items:
                continue
            first = items[0]
            if not isinstance(first, dict):
                continue
            text = (first.get("근거_원문") or "").strip()
            cid = first.get("chunk_id", "")
            if not text or text.startswith("<사유") or cid == "매칭 불가":
                continue
            samples.append({
                "section": label,
                "category": cat,
                "chunk_id": cid,
                "text": truncate(text, 200),
            })
            break  # 카테고리당 1건만
    return samples


def main():
    print(f"▶ 쿠팡 사건 데이터 추출")
    print(f"  사건키: {CASE_KEY}")

    facts = load_json(CASE_DIR / "facts.json")
    legal = load_json(CASE_DIR / "legal.json")
    sanction = load_json(CASE_DIR / "sanction.json")
    evidence = load_json(CASE_DIR / "evidence.json")
    qa_list = load_json(CASE_DIR / "qa_list.json")

    summary_rows = load_csv(DQ / "dataset_summary_22.csv")
    facts_rows = load_csv(DQ / "dataset_facts_22.csv")
    classif_rows = load_csv(DQ / "dataset_classification_22.csv")
    infer_rows = load_csv(DQ / "dataset_inference_22.csv")
    qa_rows = load_csv(DQ / "qa_evaluated_990.csv")
    qc_rows = load_csv(DQ / "qc_result_990.csv")

    # 사건키 일치 확인
    assert any(r["사건키"] == CASE_KEY for r in summary_rows), "summary에 쿠팡 매칭 실패"
    assert any(r["사건키"] == CASE_KEY for r in qa_rows), "QA에 쿠팡 매칭 실패"

    summary_row = next(r for r in summary_rows if r["사건키"] == CASE_KEY)
    facts_row = next(r for r in facts_rows if r["사건키"] == CASE_KEY)
    classif_row = next(r for r in classif_rows if r["사건키"] == CASE_KEY)
    infer_row = next(r for r in infer_rows if r["사건키"] == CASE_KEY)

    coupang_qa = [r for r in qa_rows if r["사건키"] == CASE_KEY]
    coupang_qc = [r for r in qc_rows if r["사건키"] == CASE_KEY]

    # QA 3건 lock 추출
    qa_samples = []
    for persona, level, qtype, suffix in QA_LOCK:
        target_id = f"{CASE_KEY}_{suffix}"
        f = [r for r in coupang_qa
             if r["페르소나"] == persona and r["난이도"] == level and r["질문유형"] == qtype]
        if not f:
            raise SystemExit(f"QA 매칭 실패: ({persona}, {level}, {qtype})")
        # ID 끝 3자리도 추가 검증
        chosen = next((r for r in f if r["ID"] == target_id), f[0])
        if chosen["ID"] != target_id:
            print(f"  ⚠ ID lock 미스매치: {chosen['ID']} ≠ {target_id} (persona/level/type만 일치)")
        qa_samples.append({
            "qa_id": chosen["ID"],
            "persona": chosen["페르소나"],
            "level": chosen["난이도"],
            "type": chosen["질문유형"],
            "question": chosen["질문"],
            "answer": chosen["답변"],
        })
        print(f"  ✓ {persona}/{level}/{qtype} → {chosen['ID'][-30:]}")

    # QC 통계
    n = len(coupang_qc)
    scores = [int(r["score_total"]) for r in coupang_qc if r["score_total"]]
    avg = sum(scores) / n if scores else 0.0
    judg = Counter(r["judgment"] for r in coupang_qc)
    err_codes = []
    for r in coupang_qc:
        if r.get("error_codes"):
            err_codes.extend(c.strip() for c in r["error_codes"].split(",") if c.strip())
    err_top = Counter(err_codes).most_common(5)

    # 명령서 lock 검증
    if round(avg, 1) != 96.3:
        raise SystemExit(f"평균 검증 실패: round({avg}, 1) = {round(avg, 1)} ≠ 96.3")
    if judg.get("Gold", 0) != 11 or judg.get("보정필요", 0) != 34 or judg.get("탈락", 0) != 0:
        raise SystemExit(f"판정 분포 검증 실패: {dict(judg)}")
    err_dict = dict(err_top)
    if err_dict.get("E5") != 11 or err_dict.get("E7") != 10:
        raise SystemExit(f"오류 분포 검증 실패: {err_dict}")
    print(f"  ✓ 검수 통계 lock 통과: avg={round(avg,1)}, Gold={judg['Gold']}, E5={err_dict['E5']}, E7={err_dict['E7']}")

    # case_meta — 의결일은 CSV에 없어 빈값
    case_meta = {
        "사건명": CASE_KEY,
        "의결일": summary_row.get("의결일", "") or "정보 없음",
        "적용법령": summary_row.get("적용법령", ""),
        "처분결과": summary_row.get("처분결과", ""),
        "사건유형": summary_row.get("사건유형", ""),
        "summary_short": summary_row.get("summary_short", ""),
        "출처": summary_row.get("출처", "공정거래위원회 의결서"),
    }

    # Step 1: facts.json (압축 view — 핵심 필드만)
    step1 = {
        "title": "사건개요·사실관계 추출",
        "fields_extracted": ["주체", "상대방", "시장", "행위", "결과", "summary_short", "facts_structured"],
        "result": {
            "주체": facts.get("주체", ""),
            "상대방": facts.get("상대방", ""),
            "시장": facts.get("시장", ""),
            "행위": facts.get("행위", ""),
            "결과": facts.get("결과", ""),
            "summary_short": facts.get("summary_short", ""),
            "facts_structured": facts.get("facts_structured", {}),
        },
    }

    # Step 2: legal.json
    step2 = {
        "title": "법적 판단 추출",
        "fields_extracted": ["법령", "조문", "위반유형", "판단요건", "classification_tags"],
        "result": {
            "법령": legal.get("법령", ""),
            "조문": legal.get("조문", ""),
            "위반유형": legal.get("위반유형", ""),
            "판단요건": legal.get("판단요건", []),
            "classification_tags": legal.get("classification_tags", {}),
        },
    }

    # Step 3: sanction.json
    step3 = {
        "title": "시정조치·과징금 추출",
        "fields_extracted": ["피심인", "시정명령", "과징금", "과태료", "처분유형", "근거조문"],
        "result": {
            "피심인": sanction.get("피심인", ""),
            "시정명령": sanction.get("시정명령", ""),
            "과징금": sanction.get("과징금", ""),
            "과태료": sanction.get("과태료", ""),
            "과징금액": sanction.get("과징금액", ""),
            "처분유형": sanction.get("처분유형", []),
            "근거조문": sanction.get("근거조문", ""),
        },
    }

    # Step 4: evidence samples
    step4 = {
        "title": "근거 텍스트 매칭",
        "evidence_samples": collect_evidence_samples(evidence),
    }

    # Step 5: QA 생성
    step5 = {
        "title": "QA 생성 (페르소나·난이도·질문유형 3축)",
        "qa_count": len(qa_list),
        "qa_samples_source": f"04_raw_outputs/{CASE_KEY}/qa_list.json",
        "qa_samples_id_lock": [s["qa_id"] for s in qa_samples],
        "qa_samples": qa_samples,
    }

    # 5종 데이터셋 샘플
    datasets = {
        "QA": {
            "count": len(coupang_qa),
            "sample": {
                "ID": qa_samples[0]["qa_id"],
                "페르소나": qa_samples[0]["persona"],
                "난이도": qa_samples[0]["level"],
                "질문유형": qa_samples[0]["type"],
                "질문": truncate(qa_samples[0]["question"], 120),
                "답변": truncate(qa_samples[0]["answer"], 200),
            },
        },
        "요약": {"count": 1, "sample": summary_row},
        "사실관계": {"count": 1, "sample": facts_row},
        "분류": {"count": 1, "sample": classif_row},
        "추론": {
            "count": 1,
            "sample": {
                "ID": infer_row["ID"],
                "사건키": infer_row["사건키"],
                "사건유형": infer_row["사건유형"],
                "전제1": truncate(infer_row.get("전제1", ""), 200),
                "전제2": truncate(infer_row.get("전제2", ""), 200),
                "결론": truncate(infer_row.get("결론", ""), 150),
                "근거": truncate(infer_row.get("근거", ""), 150),
                "적용법령": infer_row.get("적용법령", ""),
                "적용조문": infer_row.get("적용조문", ""),
                "처분결과": infer_row.get("처분결과", ""),
            },
        },
    }

    qc_summary = {
        "총건수": n,
        "평균점수": round(avg, 1),
        "평균점수_raw": avg,
        "Gold": judg.get("Gold", 0),
        "보정필요": judg.get("보정필요", 0),
        "탈락": judg.get("탈락", 0),
        "주요_오류": [f"{c}: {n_}건" for c, n_ in err_top[:5]],
    }

    out = {
        "case_key": CASE_KEY,
        "case_meta": case_meta,
        "step1": step1,
        "step2": step2,
        "step3": step3,
        "step4": step4,
        "step5": step5,
        "datasets": datasets,
        "qc_summary": qc_summary,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 저장: {OUT} ({OUT.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
