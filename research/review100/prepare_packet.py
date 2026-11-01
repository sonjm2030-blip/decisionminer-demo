"""Freeze the existing 100 IDs against final-submission content; no human labels generated."""
import argparse
import collections
import csv
import hashlib
import html
import json
import random
import re
import shutil
import unicodedata
from pathlib import Path

import openpyxl
from pypdf import PdfReader

BASELINE = "74135adccfc916b164546c7d6db0e50c170657d5"
NOTE = "※ 본 답변은 외부 검수 결과에 따라 일부 보정되었습니다."


def norm(value):
    return unicodedata.normalize("NFC", str(value or "")).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def display(value):
    return str(value or "").replace("\\n", "\n").strip()


def strip_note(value):
    # Remove this exact process annotation only; preserve the answer itself.
    return re.sub(r"(?:\\n|\n)*" + re.escape(NOTE), "", str(value or "")).strip()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--render-input", type=Path)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = repo / "releases/competition_final.xlsx"
    old_source = repo / "releases/reviewer_100.xlsx"
    audit = json.loads((repo / "docs/baseline_metrics.json").read_text())
    for p in [source, old_source]:
        if digest(p) != audit["input_sha256"][str(p.relative_to(repo))]:
            raise ValueError(f"Baseline source changed: {p.name}")
    final = openpyxl.load_workbook(source, read_only=True, data_only=True)
    original = openpyxl.load_workbook(old_source, read_only=True, data_only=True)
    old_rows = list(original.active.values)[1:]
    mapping_rows = [r for r in final["법리_검수"].values
                    if str(r[0]).startswith("QA-") and r[1]]
    mapping = {norm(r[0]): norm(r[1]) for r in mapping_rows}
    qa_rows = list(final["전체_QA"].values)[2:]
    qa = {norm(r[0]): r for r in qa_rows}
    assert len(qa) == len(qa_rows) == 990
    assert len(mapping) == len(mapping_rows) == len(old_rows) == 100
    assert len({norm(r[0]) for r in old_rows}) == 100
    assert set(mapping) == {norm(r[0]) for r in old_rows}
    cases = sorted({mapping[norm(r[0])].rsplit("_", 1)[0] for r in old_rows})
    assert len(cases) == 22
    pdfs = list(args.pdf_root.rglob("*.pdf"))
    # Three source filenames are truncated. These exact prefixes were checked
    # against the first-page case title and decision number, not guessed by similarity.
    aliases = {
        "경상북도교육청 발주 2018": ("경상북도교육청 발주 2018", "2020", "217"),
        "기업집단 금호아시아나": ("기업집단 금호아시아나", "2020", "294"),
        "새마을금고중앙회": ("새마을금고중앙회", "2022", "245"),
    }
    sources = []
    (out / "원문").mkdir(exist_ok=True)
    for i, case in enumerate(cases, 1):
        matches = [p for p in pdfs if norm(p.stem).rstrip(". ") == case.rstrip(". ")]
        alias = next((v for k, v in aliases.items() if case.startswith(k)), None)
        if not matches and alias:
            matches = [p for p in pdfs if norm(p.stem).startswith(alias[0])]
        if len(matches) != 1:
            raise ValueError(f"PDF must match uniquely: {case}: {len(matches)}")
        p = matches[0]
        reader = PdfReader(p)
        first = norm(reader.pages[0].extract_text())
        if alias and not all(s in first for s in alias[1:]):
            raise ValueError(f"Decision number mismatch: {case}")
        dest = f"원문/C{i:02d}.pdf"
        shutil.copyfile(p, out / dest)
        assert digest(p) == digest(out / dest)
        sources.append({"case_id": f"C{i:02d}", "case": case, "path": dest,
                        "pages": len(reader.pages), "sha256": digest(p)})
    by_case = {s["case"]: s for s in sources}
    shuffled = old_rows[:]
    random.Random(20261101).shuffle(shuffled)
    targets, provenance = [], []
    for i, old in enumerate(shuffled, 1):
        legacy_id = norm(old[0])
        full_id = mapping[legacy_id]
        r = qa[full_id]
        case = full_id.rsplit("_", 1)[0]
        presented = {"question": display(r[5]), "answer": display(strip_note(r[6])),
                     "evidence": display(r[7])}
        raw = {"question": str(r[5] or ""), "answer": str(r[6] or ""),
               "evidence": str(r[7] or "")}
        rid = f"R{i:03d}"
        targets.append({"review_id": rid, "case_id": by_case[case]["case_id"],
                        "case": case, "pdf": by_case[case]["path"], **presented})
        provenance.append({"review_id": rid, "legacy_id": legacy_id, "full_id": full_id,
                           "source_sheet": "전체_QA", "source_row": next(j for j, q in enumerate(qa_rows, 3) if norm(q[0]) == full_id),
                           "raw_target_sha256": content_hash(raw),
                           "presented_target_sha256": content_hash(presented),
                           "answer_text_changed": norm(r[6]) != norm(old[6]),
                           "answer_changed_without_note": norm(strip_note(r[6])) != norm(old[6]),
                           "question_text_changed": norm(r[5]) != norm(old[5]),
                           "annotation_removed": NOTE in str(r[6] or ""),
                           "persona": norm(r[1]), "question_type": norm(r[2]), "difficulty": norm(r[3]),
                           "case_id": by_case[case]["case_id"]})
    report = {
        "status": "preparation_only_no_new_human_labels", "protocol_version": "0.1-draft",
        "baseline_commit": BASELINE, "selection": "same existing 100 IDs; no resampling",
        "source_sha256": {str(p.relative_to(repo)): digest(p) for p in [source, old_source]},
        "target_count": len(targets), "case_count": len(cases), "shuffle_seed": 20261101,
        "answer_text_changed": sum(p["answer_text_changed"] for p in provenance),
        "answer_changed_without_note": sum(p["answer_changed_without_note"] for p in provenance),
        "question_text_changed": sum(p["question_text_changed"] for p in provenance),
        "question_or_answer_changed_without_note": sum(p["answer_changed_without_note"] or p["question_text_changed"] for p in provenance),
        "comparison": "NFC + strip exact string comparison; does not establish semantic or legal difference",
        "old_evidence_comparable": False,
        "old_evidence_note": "Original review has no identically defined evidence column; full input equivalence is unproven.",
        "display_transform": "Remove exact NOTE only from answer; replace literal backslash-n with newline; strip ends. No correction applied.",
        "note_removed": NOTE,
        "distributions": {key: dict(collections.Counter(p[key] for p in provenance))
                          for key in ["persona", "question_type", "difficulty", "case_id"]},
        "items": provenance, "sources": sources,
    }
    # Public manifest has provenance and hashes only, never old judgments or reviewer details.
    write_json(repo / "research/review100/target_manifest.json", report)
    write_json(out / "문항버전.json", {
        "protocol_version": report["protocol_version"], "baseline_commit": BASELINE,
        "source_sha256": report["source_sha256"],
        "transform": report["display_transform"],
        "targets": [{"review_id": p["review_id"], "presented_target_sha256": p["presented_target_sha256"]} for p in provenance],
    })
    # Renderer input is local support, outside the hand-off folder.
    if args.render_input:
        write_json(args.render_input, {"targets": targets, "sources": sources})
    with (out / "원문목록.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(sources[0]))
        writer.writeheader()
        writer.writerows(sources)
    esc = html.escape
    cards = []
    for t in targets:
        cards.append(f'<article id="{t["review_id"]}"><h2>{t["review_id"]}</h2>'
                     f'<p>{esc(t["case"])} <a href="{esc(t["pdf"])}">원문 PDF ({t["case_id"]})</a></p>'
                     + "".join(f'<h3>{label}</h3><pre>{esc(t[key])}</pre>'
                               for key, label in [("question", "질문"), ("answer", "검수 대상 답변"), ("evidence", "제공된 근거 발췌")])
                     + '<p><a href="#top">목록으로</a></p></article>')
    index = ' '.join(f'<a href="#{t["review_id"]}">{t["review_id"]}</a>' for t in targets)
    (out / "문항자료.html").write_text('<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<title>DecisionMiner 재검수 100건</title><style>body{font:16px/1.7 sans-serif;max-width:1000px;margin:40px auto;padding:0 24px;color:#213247}'
        'article{border-top:2px solid #d8e1eb;margin-top:40px;padding-top:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#f3f6f9;padding:18px}'
        'a{color:#1757a5}nav a{display:inline-block;margin:4px 10px 4px 0}</style><body id="top">'
        '<h1>DecisionMiner 법률 전문가 재검수</h1><p>기준: 공모전 최종 제출본. 판정은 검수표.xlsx에 기록합니다. '
        '제공된 근거도 검증 대상이며, 원문 PDF로 확인하세요. 보정 이력 안내 문구만 답변에서 제거했습니다.</p>'
        '<p>PDF 위치는 파일 뷰어의 페이지 번호와 의결서 본문 쪽수를 구분해 기록하세요. 법령은 사건 당시 적용 버전을 확인합니다.</p>'
        f'<nav>{index}</nav>{"".join(cards)}</body></html>', encoding="utf-8")
    shutil.copyfile(repo / "research/review100/REVIEW_GUIDE.md", out / "검수안내.md")
    (out / "시작안내.txt").write_text(
        "DecisionMiner 전문가 재검수 100건\n\n"
        "1. 압축파일을 전부 풀고 폴더 구성을 유지합니다.\n"
        "2. 검수안내.md에서 판정 기준을 확인합니다. 기준은 검수자와 합의 전 초안입니다.\n"
        "3. 문항자료.html을 브라우저로 열어 질문·답변·근거 전문을 읽습니다. 원문 PDF 링크도 있습니다.\n"
        "4. 검수표.xlsx의 검수입력 시트에서 같은 문항번호의 행을 작성합니다.\n"
        "5. 검수자정보_비공개양식.csv도 작성하고, 검수표와 함께 비공개로 반환합니다.\n\n"
        "검수표만 다른 폴더로 옮기면 문항·원문 링크가 끊길 수 있습니다.\n"
        "현재 판정란은 비어 있습니다. 검수 시작 전 5건으로 지침을 점검해 주세요.\n",
        encoding="utf-8")
    (out / "검수자정보_비공개양식.csv").write_text(
        '검수자코드,법학 전공 및 학위,법률 자격 및 취득연도,공정거래 관련 실무 및 연구경력,본 프로젝트 기존 참여 여부,독립 검수 가능 여부,사전 기준 합의일\n'
        ',,,,,,\n', encoding="utf-8-sig")
    print(json.dumps({k: v for k, v in report.items() if k not in ["items", "sources", "distributions"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
