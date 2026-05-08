"""
Tier 1 Col17 Generator — 22건 × 45 QA = 990건 "문제점 및 해결방안" 자동 생성

목적:
  04_raw_outputs/{사건키}/qa_list.json 의 각 Q&A 항목에 대해
  엑셀 17열 "문제점 및 해결방안"을 Sonnet 4.6 배치 호출로 자동 생성.

배치 전략:
  - 5건씩 묶어 1회 API 호출 → 사건당 9회 → 전체 ~198회
  - qa_id 는 사건 내 순서 기반 자동 생성 (001..045)
  - 응답 건수 부족·truncation 시 누락된 qa_id 만 1건씩 보충 호출
  - 보충은 call_batch_with_retry 1회만 호출 (내부 RETRY_MAX 재시도로 충분, qa_id당 최대 3회)
  - stop_reason=="max_tokens" 면 truncation 으로 간주 → 보충은 강제 1-by-1
  - placeholder([자동생성 실패]) 항목은 --resume 시 재처리 대상에 자동 포함
  - 사건별 _tier1.json 은 atomic write (tmp + os.replace) 로 저장

실행:
  python3 tier1_col17_generator.py --dry-run
  python3 tier1_col17_generator.py --execute
  python3 tier1_col17_generator.py --execute --limit 1
  python3 tier1_col17_generator.py --execute --resume

저장:
  11_data_quality/tier1_ai_auto/{사건키}_tier1.json   (사건별: 45개 항목)
  11_data_quality/tier1_ai_auto/_combined.json        (전체 통합)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ============================ CONFIG ============================
PROJECT_ROOT     = Path(__file__).resolve().parent.parent
RAW_OUTPUTS_DIR  = PROJECT_ROOT / "04_raw_outputs"
OUTPUT_DIR       = PROJECT_ROOT / "11_data_quality" / "tier1_ai_auto"
FAILED_DIR       = OUTPUT_DIR / "_failed"
META_DIR         = PROJECT_ROOT / "00_meta"
LOG_FILE         = META_DIR / "tier1_col17_log.txt"

MODEL            = "claude-sonnet-4-6"
MAX_TOKENS       = 6000
BATCH_SIZE       = 5

RETRY_MAX        = 3
RETRY_BACKOFF    = 5      # 일반 오류 재시도 백오프 (seconds × attempt)
RATELIMIT_DELAY  = 180    # 429 발생 시 대기 (초)
BATCH_DELAY      = 8      # 한 사건 내 배치 사이 대기 (초)
CASE_DELAY       = 20     # 사건 사이 대기 (초)

REQUIRED_FILES   = ("qa_list.json", "legal.json", "facts.json")

# 사건 컨텍스트는 사건 내 9개 배치에서 동일 → ephemeral cache hit (입력 토큰 절감)
CACHEABLE_HEADER_MARKER = "===== 사건 컨텍스트 (캐시) ====="

# 보충 실패 시 박제되는 sentinel — resume 시 이 값을 보면 미완료로 간주하여 재처리
FAIL_PLACEHOLDER = "[자동생성 실패]"

SYSTEM_PROMPT = """당신은 공정거래법 분야 Q&A 데이터셋 검수 전문가입니다.
입력으로 주어진 Q&A 항목 각각에 대해, 다음 4가지 관점에서 검수하고
"문제점"과 "해결방안"을 각각 1~3문장의 한국어로 작성하라.

검수 관점:
1. 사실 정확성 — 답변의 수치·조문·처분유형이 의결서/법령과 일치하는가?
2. 페르소나 적합성 — 어투/전문용어 수준이 페르소나(일반국민·기업 컴플라이언스 담당자·논문 준비 학생)에 맞는가?
3. 질문유형 정합성 — 질문유형(제재중심/요건중심/사실중심/판단중심/논점중심)과 답변 초점이 일치하는가?
4. 근거 명시성 — "근거_short" 가 답변의 핵심 주장을 실제로 뒷받침하는가?

출력 규칙:
- 입력 배열의 각 객체에 대해 정확히 1개씩 결과 객체 생성
- 결과 객체의 "qa_id" 는 입력의 "qa_id" 를 그대로 보존 (변형·재정렬 금지)
- 문제점이 없으면 "문제점": "특이사항 없음", "해결방안": "해당 없음"
- 응답은 JSON 배열 1개만 출력 (코드펜스·설명문·인사말 일체 금지)
"""

JSON_HARDENING_SUFFIX = """

---

# 출력 형식 강화 (필수 준수)
1. 응답 첫 글자는 반드시 `[` (JSON 배열). 코드펜스(```)·설명문 금지.
2. 각 객체는 정확히 3개 키: "qa_id", "문제점", "해결방안". 추가 키 금지.
3. JSON string 내 큰따옴표는 반드시 \\" 로 escape. 한국어 큰따옴표(" ")는 「 」 또는 ' '로 대체 권장.
4. JSON string 내 줄바꿈은 \\n 으로 표기. 실제 newline 문자 금지.
5. trailing comma 금지 (`,]`·`,}` ❌).
6. 입력 qa_id 순서대로, 누락·중복 없이 정확히 입력 개수만큼 반환.
"""


# ============================ UTILS ============================
def safe_dirname(case_key: str) -> str:
    s = case_key.strip()
    return re.sub(r'[\\/:*?"<>|]', '_', s)


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(line: str, console: bool = True):
    META_DIR.mkdir(parents=True, exist_ok=True)
    msg = f"[{now_ts()}] {line}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")
    if console:
        print(msg, flush=True)


def sleep_with_log(seconds: int, reason: str):
    log(f"대기 {seconds}s ({reason})")
    time.sleep(seconds)


def atomic_write_text(path: Path, text: str):
    """tmp 파일에 쓴 뒤 os.replace 로 원자적 교체 — 중간 인터럽트로 인한 손상 방지."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def repair_json(s: str) -> str:
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    s = s.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    return s


def extract_json(text: str):
    """LLM 응답에서 JSON 추출 — 코드펜스 제거, 균형 brace 스캔, repair 폴백."""
    if not text or not text.strip():
        raise ValueError("empty response")
    t = text.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()

    start = -1
    for i, ch in enumerate(t):
        if ch in "{[":
            start = i
            break
    if start < 0:
        raise ValueError(f"no JSON found (head={text[:200]!r})")

    open_ch = t[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    end = -1
    for i in range(start, len(t)):
        ch = t[i]
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                end = i
                break

    candidate = t[start:end + 1] if end >= 0 else t[start:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e1:
        try:
            repaired = repair_json(candidate)
            if repaired != candidate:
                return json.loads(repaired)
        except json.JSONDecodeError:
            pass
        head = candidate[:200]
        tail = candidate[-200:] if len(candidate) > 400 else ""
        raise ValueError(
            f"JSONDecodeError: {e1} | balanced={'yes' if end>=0 else 'no'} "
            f"| len={len(candidate)} | head={head!r} | tail={tail!r}"
        ) from e1


def save_raw_response(case_key: str, batch_tag: str, raw_text: str, parse_error: str):
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    p = FAILED_DIR / f"{safe_dirname(case_key)}_{batch_tag}_raw.txt"
    try:
        with p.open("w", encoding="utf-8") as f:
            f.write(f"=== Parse error: {parse_error}\n")
            f.write(f"=== Case: {case_key}\n")
            f.write(f"=== Batch: {batch_tag}\n")
            f.write(f"=== Timestamp: {now_ts()}\n")
            f.write(f"=== Length: {len(raw_text)}\n")
            f.write("=" * 70 + "\n")
            f.write(raw_text)
        log(f"[RAW-SAVED] {case_key} {batch_tag} → {p.relative_to(PROJECT_ROOT)}")
    except Exception as e:
        log(f"[RAW-SAVE-FAIL] {case_key} {batch_tag}: {e}")


def save_failure(case_key: str, msg: str):
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    p = FAILED_DIR / f"{safe_dirname(case_key)}_error.txt"
    with p.open("a", encoding="utf-8") as f:
        f.write(f"[{now_ts()}] {msg}\n")
    log(f"[FAIL] {case_key} :: {msg}")


# ============================ ANTHROPIC CALL ============================
_ANTHROPIC_CLIENT = None


def _get_client():
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is None:
        from anthropic import Anthropic
        _ANTHROPIC_CLIENT = Anthropic()
    return _ANTHROPIC_CLIENT


def _is_rate_limit(exc: Exception) -> bool:
    if exc.__class__.__name__ == "RateLimitError":
        return True
    try:
        from anthropic import RateLimitError as _RL
        if isinstance(exc, _RL):
            return True
    except Exception:
        pass
    return getattr(exc, "status_code", None) == 429


def call_anthropic(case_context: str, qa_batch_json: str, max_tokens: int) -> dict:
    """사건 컨텍스트는 cache 블록(같은 사건의 9개 배치 hit), QA 배치는 dynamic."""
    client = _get_client()
    user_content = [
        {"type": "text", "text": case_context, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "다음 Q&A 항목들을 검수하라:\n\n" + qa_batch_json + JSON_HARDENING_SUFFIX},
    ]
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    parts = []
    for blk in resp.content:
        txt = getattr(blk, "text", None)
        if txt:
            parts.append(txt)
    usage = getattr(resp, "usage", None)
    return {
        "text": "".join(parts),
        "stop_reason": getattr(resp, "stop_reason", None),
        "input_tokens":  getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
        "cache_read_input_tokens":     getattr(usage, "cache_read_input_tokens", None) or 0,
    }


def call_batch_with_retry(case_context: str, qa_batch: list, case_key: str, batch_tag: str) -> tuple[list, str]:
    """1배치 호출 + 재시도 (qa_id당 최대 RETRY_MAX 회).

    반환: (results, status)
      status ∈ {"ok", "truncated", "failed"}
        - "ok"        : 정상 파싱 (results 는 LLM 응답 list, 건수는 호출자 검증)
        - "truncated" : stop_reason=="max_tokens" — 호출자가 1-by-1 분할 결정
        - "failed"    : RETRY_MAX 회 모두 예외/파싱 실패
    """
    qa_batch_json = json.dumps(qa_batch, ensure_ascii=False, indent=2)
    log(f"[CALL] {case_key} {batch_tag} n={len(qa_batch)} ctx={len(case_context)} batch={len(qa_batch_json)}")

    for attempt in range(1, RETRY_MAX + 1):
        try:
            resp = call_anthropic(case_context, qa_batch_json, MAX_TOKENS)
            log(
                f"[USAGE] {case_key} {batch_tag} in={resp['input_tokens']} out={resp['output_tokens']} "
                f"cache_w={resp['cache_creation_input_tokens']} cache_r={resp['cache_read_input_tokens']} "
                f"stop={resp['stop_reason']}"
            )
            if resp["stop_reason"] == "max_tokens":
                log(f"[TRUNC] {case_key} {batch_tag} stop=max_tokens (out={resp['output_tokens']}/max={MAX_TOKENS}). 보충은 1-by-1 로 분할.")
                save_raw_response(case_key, batch_tag, resp["text"], "stop_reason=max_tokens")
                return [], "truncated"
            try:
                parsed = extract_json(resp["text"])
            except (ValueError, json.JSONDecodeError) as e:
                save_raw_response(case_key, batch_tag, resp["text"], str(e))
                raise
            if not isinstance(parsed, list):
                save_raw_response(case_key, batch_tag, resp["text"], f"not a list (got {type(parsed).__name__})")
                raise ValueError(f"expected list, got {type(parsed).__name__}")
            return parsed, "ok"
        except Exception as e:
            log(f"[RETRY {attempt}/{RETRY_MAX}] {case_key} {batch_tag}: {type(e).__name__}: {e}")
            if attempt < RETRY_MAX:
                if _is_rate_limit(e):
                    sleep_with_log(RATELIMIT_DELAY, f"RateLimit {batch_tag}")
                else:
                    sleep_with_log(RETRY_BACKOFF * attempt, f"백오프 {batch_tag}")
    return [], "failed"


# ============================ DATA LOAD ============================
def discover_cases() -> list[Path]:
    """qa_list.json + legal.json + facts.json 모두 존재하는 사건 폴더만 큐에 포함."""
    cases = []
    for d in sorted(RAW_OUTPUTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith("_") or d.name.startswith("v2_시범"):
            continue
        if all((d / f).exists() for f in REQUIRED_FILES):
            cases.append(d)
    return cases


def load_all_qa(case_dir: Path) -> list[dict] | None:
    """qa_list.json 로드 (실측: list 형태, 45개). qa_id 자동 부여 (001..N)."""
    qa_path = case_dir / "qa_list.json"
    try:
        data = json.loads(qa_path.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"[LOAD-FAIL] {case_dir.name} qa_list.json: {e}")
        return None
    if not isinstance(data, list):
        # 방어적 처리: dict 안에 wrap 된 경우 흔한 키 탐색
        wrapped = None
        if isinstance(data, dict):
            for k in ("qa_list", "qa", "items", "data"):
                v = data.get(k)
                if isinstance(v, list):
                    wrapped = v
                    break
        if wrapped is None:
            log(f"[LOAD-FAIL] {case_dir.name} qa_list.json: not a list")
            return None
        data = wrapped
    items = []
    for i, qa in enumerate(data, 1):
        if not isinstance(qa, dict):
            continue
        item = dict(qa)
        item["qa_id"] = f"{i:03d}"
        items.append(item)
    return items


def _extract_case_type(legal: dict) -> str:
    """legal.json → classification_tags.사건유형_대분류 (없으면 세분류 → 위반_조문 폴백)."""
    tags = legal.get("classification_tags")
    if isinstance(tags, dict):
        for k in ("사건유형_대분류", "사건유형_세분류", "위반_조문"):
            v = tags.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    v = legal.get("위반유형")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return "(미상)"


def _extract_applied_law(legal: dict) -> str:
    """최상위 '법령' + '조문' 결합 (예: '공정거래법 제29조 제1항').
    없으면 classification_tags.위반_조문 폴백."""
    law = legal.get("법령")
    article = legal.get("조문")
    parts = []
    if isinstance(law, str) and law.strip():
        parts.append(law.strip())
    if isinstance(article, str) and article.strip():
        parts.append(article.strip())
    if parts:
        return " ".join(parts)
    tags = legal.get("classification_tags")
    if isinstance(tags, dict):
        v = tags.get("위반_조문")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "(미상)"


def build_case_context(case_dir: Path, legal: dict, facts: dict) -> str:
    summary = facts.get("summary_short", "")
    if not isinstance(summary, str):
        summary = json.dumps(summary, ensure_ascii=False)
    case_type = _extract_case_type(legal)
    applied_law = _extract_applied_law(legal)
    return (
        f"{CACHEABLE_HEADER_MARKER}\n"
        f"# 사건명\n{case_dir.name}\n\n"
        f"# 사건유형\n{case_type}\n\n"
        f"# 적용법조\n{applied_law}\n\n"
        f"# 사건 요약\n{summary}\n"
    )


def _slim(qa: dict) -> dict:
    """프롬프트로 보낼 QA 슬림화 (qa_id 보존)."""
    return {
        "qa_id":     qa["qa_id"],
        "페르소나":  qa.get("페르소나", ""),
        "질문유형":  qa.get("질문유형", ""),
        "난이도":    qa.get("난이도", ""),
        "질문":      qa.get("질문", ""),
        "답변":      qa.get("답변", ""),
        "근거_short": qa.get("근거_short", ""),
    }


def _is_complete_result(r) -> bool:
    """Resume 시 완료 판정 — placeholder/빈 값은 미완료로 본다."""
    if not isinstance(r, dict) or not r.get("qa_id"):
        return False
    p = r.get("문제점")
    s = r.get("해결방안")
    if not isinstance(p, str) or not isinstance(s, str):
        return False
    if p.strip() in ("", FAIL_PLACEHOLDER):
        return False
    if s.strip() in ("", FAIL_PLACEHOLDER):
        return False
    return True


# ============================ CASE PROCESS ============================
def process_case(case_dir: Path, dry_run: bool, resume: bool) -> bool:
    case_key = case_dir.name
    out_path = OUTPUT_DIR / f"{safe_dirname(case_key)}_tier1.json"

    qa_items = load_all_qa(case_dir)
    if qa_items is None or len(qa_items) == 0:
        save_failure(case_key, "qa_list 로드 실패 또는 빈 배열")
        return False

    try:
        legal = json.loads((case_dir / "legal.json").read_text(encoding="utf-8"))
        facts = json.loads((case_dir / "facts.json").read_text(encoding="utf-8"))
    except Exception as e:
        save_failure(case_key, f"legal/facts 로드 실패: {e}")
        return False

    case_context = build_case_context(case_dir, legal, facts)
    case_type = _extract_case_type(legal)
    applied_law = _extract_applied_law(legal)

    # 기존 결과 로드 — placeholder/빈 값은 미완료 취급 (재처리 대상에 포함)
    existing: dict[str, dict] = {}
    if out_path.exists():
        if not resume:
            log(f"[SKIP] {case_key} 이미 존재 (resume 미사용) → {out_path.name}")
            return True
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            prev_results = prev.get("results", []) if isinstance(prev, dict) else []
            placeholder_n = 0
            for r in prev_results:
                if _is_complete_result(r):
                    existing[r["qa_id"]] = r
                elif isinstance(r, dict) and r.get("qa_id"):
                    placeholder_n += 1
            log(f"[RESUME] {case_key} 완료 {len(existing)}/{len(qa_items)} 항목 로드 (placeholder/incomplete 재처리: {placeholder_n})")
        except Exception as e:
            log(f"[RESUME-WARN] {case_key} 기존 파일 read fail ({e}) — 새로 시작")

    if dry_run:
        log(f"[DRY] {case_key}")
        log(f"      qa_count   : {len(qa_items)}")
        log(f"      case_type  : {case_type}")
        log(f"      applied_law: {applied_law}")
        log(f"      summary    : {(facts.get('summary_short') or '')[:80]}...")
        log(f"      out_path   : {out_path}")
        log(f"      existing   : {len(existing)}")
        return True

    pending = [q for q in qa_items if q["qa_id"] not in existing]
    if not pending:
        log(f"[DONE-ALREADY] {case_key} 누락 없음")
        return True

    log(f"[START] {case_key} qa_total={len(qa_items)} pending={len(pending)} batch_size={BATCH_SIZE}")

    results: dict[str, dict] = dict(existing)
    t0 = time.time()

    batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
    for bi, batch in enumerate(batches, 1):
        batch_tag = f"b{bi:02d}"
        slim_batch = [_slim(q) for q in batch]
        returned, status = call_batch_with_retry(case_context, slim_batch, case_key, batch_tag)

        ret_by_id = {r["qa_id"]: r for r in returned if isinstance(r, dict) and r.get("qa_id")}
        for q in batch:
            r = ret_by_id.get(q["qa_id"])
            if r and r.get("문제점") and r.get("해결방안"):
                results[q["qa_id"]] = {
                    "qa_id":     q["qa_id"],
                    "문제점":   r["문제점"],
                    "해결방안": r["해결방안"],
                }

        # 누락 보충 — 1-by-1 단일 호출 (call_batch_with_retry 내부 RETRY_MAX 재시도로 충분)
        # 외부 루프 없음: qa_id당 최대 RETRY_MAX(=3) 회만 호출, 비용 폭주 방지
        missing_in_batch = [q for q in batch if q["qa_id"] not in results]
        if missing_in_batch:
            log(f"[FILL] {case_key} {batch_tag} 누락 {len(missing_in_batch)}개 → 1-by-1 보충 (이전 status={status})")
        for q in missing_in_batch:
            tag = f"{batch_tag}-fill-{q['qa_id']}"
            fill_returned, fill_status = call_batch_with_retry(case_context, [_slim(q)], case_key, tag)
            if fill_status == "truncated":
                log(f"[FILL-TRUNC] {case_key} qa_id={q['qa_id']} 단일 호출도 truncated. placeholder 처리.")
                continue
            fb = {r["qa_id"]: r for r in fill_returned if isinstance(r, dict) and r.get("qa_id")}
            r = fb.get(q["qa_id"])
            if r and r.get("문제점") and r.get("해결방안"):
                results[q["qa_id"]] = {
                    "qa_id":     q["qa_id"],
                    "문제점":   r["문제점"],
                    "해결방안": r["해결방안"],
                }

        # 그래도 누락 → placeholder (다음 --resume 실행 시 자동 재시도 대상)
        for q in batch:
            if q["qa_id"] not in results:
                log(f"[MISSING] {case_key} qa_id={q['qa_id']} 보충 실패 → placeholder (resume 시 재시도)")
                results[q["qa_id"]] = {
                    "qa_id":     q["qa_id"],
                    "문제점":   FAIL_PLACEHOLDER,
                    "해결방안": FAIL_PLACEHOLDER,
                }

        # 사건 단위 중간 저장 (atomic) — 배치마다, 인터럽트 대비
        _save_case_result(out_path, case_key, qa_items, results, case_type, applied_law)

        if bi < len(batches):
            sleep_with_log(BATCH_DELAY, f"{case_key} {batch_tag} 완료, 다음 배치 전")

    elapsed = time.time() - t0
    failed_n = sum(1 for v in results.values() if v.get("문제점") == FAIL_PLACEHOLDER)
    log(f"[DONE] {case_key} ok={len(results) - failed_n}/{len(qa_items)} fail={failed_n} in {elapsed:.1f}s")
    return failed_n == 0


def _save_case_result(out_path: Path, case_key: str, qa_items: list, results: dict,
                      case_type: str, applied_law: str):
    """사건별 결과 저장 — qa_id 순서대로 정렬, atomic write."""
    ordered = []
    for q in qa_items:
        r = results.get(q["qa_id"])
        if r:
            ordered.append(r)
    payload = {
        "case_key":     case_key,
        "case_type":    case_type,
        "applied_law":  applied_law,
        "model":        MODEL,
        "generated_at": now_ts(),
        "qa_total":     len(qa_items),
        "result_count": len(ordered),
        "results":      ordered,
    }
    atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2))


def build_combined():
    """모든 사건의 _tier1.json 을 _combined.json 으로 통합 (atomic)."""
    if not OUTPUT_DIR.exists():
        return
    combined = []
    files = sorted(p for p in OUTPUT_DIR.glob("*_tier1.json") if p.name != "_combined.json")
    for p in files:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            combined.append(doc)
        except Exception as e:
            log(f"[COMBINE-WARN] {p.name}: {e}")
    out = OUTPUT_DIR / "_combined.json"
    payload = {
        "generated_at": now_ts(),
        "model":        MODEL,
        "case_count":   len(combined),
        "qa_total":     sum(d.get("qa_total", 0) for d in combined),
        "cases":        combined,
    }
    atomic_write_text(out, json.dumps(payload, ensure_ascii=False, indent=2))
    log(f"[COMBINED] {out.relative_to(PROJECT_ROOT)} cases={len(combined)} qa_total={payload['qa_total']}")


# ============================ MAIN ============================
def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="경로/파일/API키만 확인")
    g.add_argument("--execute", action="store_true", help="실제 API 호출")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N건만 처리 (0=전체)")
    ap.add_argument("--resume", action="store_true", help="기존 _tier1.json 의 누락/placeholder qa_id 만 재호출")
    args = ap.parse_args()

    if not RAW_OUTPUTS_DIR.exists():
        sys.exit(f"missing: {RAW_OUTPUTS_DIR}")

    queue = discover_cases()
    if args.limit and args.limit > 0:
        queue = queue[:args.limit]

    mode = "DRY-RUN" if args.dry_run else "EXECUTE"
    log("=" * 70)
    log(f"TIER1 COL17 START [{mode}] cases={len(queue)} resume={args.resume} limit={args.limit}")
    log(f"  model={MODEL} batch_size={BATCH_SIZE} max_tokens={MAX_TOKENS}")
    log(f"  out_dir={OUTPUT_DIR.relative_to(PROJECT_ROOT)}")
    log("=" * 70)

    for d in queue:
        log(f"  case: {d.name[:60]}")

    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    log(f"ANTHROPIC_API_KEY : {'SET' if api_key_set else 'NOT SET'}")
    if args.execute and not api_key_set:
        sys.exit("ANTHROPIC_API_KEY not set — `export ANTHROPIC_API_KEY=...` first")

    succ = fail = 0
    for i, d in enumerate(queue, 1):
        log(f"--- [{i}/{len(queue)}] {d.name[:60]} ---")
        try:
            ok = process_case(d, dry_run=args.dry_run, resume=args.resume)
        except KeyboardInterrupt:
            log("[INTERRUPT] 사용자 중단")
            break
        except Exception as e:
            log(f"[CRASH] {d.name[:60]} unhandled: {type(e).__name__}: {e}")
            try:
                save_failure(d.name, f"unhandled: {type(e).__name__}: {e}")
            except Exception:
                pass
            ok = False
        if ok:
            succ += 1
        else:
            fail += 1
        if not args.dry_run and i < len(queue):
            sleep_with_log(CASE_DELAY, "사건 간 대기")

    if not args.dry_run:
        build_combined()

    log("=" * 70)
    log(f"TIER1 COL17 END   [{mode}] ok={succ} fail={fail}")
    log("=" * 70)


if __name__ == "__main__":
    main()
