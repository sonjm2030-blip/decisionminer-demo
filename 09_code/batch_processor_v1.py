"""
Batch Processor v1 — 22건 5단 v2 일괄 처리

실행:
  python3 batch_processor_v1.py --dry-run                  # 경로/프롬프트/API키만 확인
  python3 batch_processor_v1.py --execute                  # 실제 처리
  python3 batch_processor_v1.py --execute --only-priority  # 6건 우선만
  python3 batch_processor_v1.py --execute --limit 1        # 1건만 (smoke test)

저장 위치 (사건키별):
  04_raw_outputs/{사건키}/facts.json     ← Opus 4.7 (fallback Sonnet 4.6)
  04_raw_outputs/{사건키}/legal.json     ← Opus 4.7 (fallback Sonnet 4.6)
  04_raw_outputs/{사건키}/sanction.json  ← Sonnet 4.6
  04_raw_outputs/{사건키}/evidence.json  ← Sonnet 4.6
  04_raw_outputs/{사건키}/qa_list.json   ← Sonnet 4.6 (45개 Q&A)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ============================ CONFIG ============================
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
LOCKED_CSV    = PROJECT_ROOT / "01_data_inventory" / "22_LOCKED_v1.csv"
INVENTORY_CSV = PROJECT_ROOT / "01_data_inventory" / "inventory_full.csv"
PROMPT_DIR    = PROJECT_ROOT / "03_prompts" / "v2"
OUTPUT_DIR    = PROJECT_ROOT / "04_raw_outputs"
FAILED_DIR    = OUTPUT_DIR / "_failed"
META_DIR      = PROJECT_ROOT / "00_meta"
BATCH_LOG     = META_DIR / "batch_log.txt"

# 실행 순서: facts → legal → sanction → evidence → qa_list
# (step5_persona가 evidence를 입력으로 받으므로 evidence가 먼저 실행되어야 함)
# 사용자 지정 출력명: Step4=qa_list.json, Step5=evidence.json
STEPS = [
    # (step_var,   output_filename,   prompt_filename,        model_tier)
    ("facts",      "facts.json",      "step1_facts_v2.md",    "opus"),
    ("legal",      "legal.json",      "step2_legal_v2.md",    "opus"),
    ("sanction",   "sanction.json",   "step3_sanction_v2.md", "sonnet"),
    ("evidence",   "evidence.json",   "step4_evidence_v2.md", "sonnet"),
    ("qa_list",    "qa_list.json",    "step5_persona_v2.md",  "sonnet"),
]

MODELS = {
    "opus":   "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
}
OPUS_FALLBACK_TIER = "sonnet"

PRIORITY_KEYWORDS = ["쿠팡", "네이버", "남양유업", "삼성전자", "신세계", "에스피피조선"]

# ROUND1: 신규 8건 — 사건유형 1건씩 균형 + PDF 작은 순 우선 (비용·시간 절감)
# --limit 14 사용 시: priority 6건(SKIP) + ROUND1 8건 처리
ROUND1_KEYWORDS = [
    "새마을금고",          # 담합 (PDF 16K)
    "평화이엔지",          # 하도급 (PDF 14K)
    "홈플러스",             # 거래상지위 (PDF 24K)
    "카카오엔터",           # 표시광고 (PDF 45K)
    "한국과수종묘",         # 사업자단체 (PDF 6K — 가장 작음)
    "엘지생활건강",         # 가맹사업 (PDF 15K)
    "금호아시아나",         # 부당지원 (PDF 45K — truncate 적용)
    "아모레퍼시픽",         # 재판매가격 (PDF 14K)
]
RETRY_MAX        = 3
RETRY_BACKOFF    = 5      # 일반 오류 재시도 백오프 (seconds × attempt)
RATELIMIT_DELAY  = 180    # RateLimitError 시 재시도 전 추가 대기 (초)
STEP_DELAY       = 30     # 각 Step API 호출 성공 후 대기 (초) — caching 5분 TTL 안에 들어가도록 30초로 단축
MAX_TOKENS       = 8000

# step별 max_tokens 오버라이드 (지정 안 된 step은 MAX_TOKENS 사용)
# qa_list는 분할 호출(QA_SPLIT_*)을 사용하므로 여기에 등록하지 않음.
STEP_MAX_TOKENS: dict = {
    "evidence": 14000,   # 의결서 1건당 evidence 청크 30개+ 가능 → 8000 tight
}

# qa_list 분할 호출 설정
# 난이도 3종은 03_prompts/v2/step5_persona_v2.md 정의(기초·심화·전문가)에 정합.
# (사용자 지정 라벨 "기초/중급/심화"는 prompt 용어 "기초/심화/전문가"로 매핑)
QA_DIFFICULTY_SPLITS = ["기초", "심화", "전문가"]
QA_SPLIT_MAX_TOKENS  = 16000
QA_SPLIT_DELAY       = 60   # 분할 호출 사이 대기 (초)
SKIP_MARKER      = "qa_list.json"   # 이 파일이 있으면 사건 전체 스킵

# 대형 의결서 토큰 절감: hybrid.json 상위 N개 chunk만 프롬프트에 전달
# (Step 1·2는 hybrid_chunks를 사용하지 않으므로 영향 없음. Step 4(evidence)에 절감 효과 직접 적용.)
# v3.4 옵션B: 30→20 (Step 4 ITPM 안전 마진 확보)
HYBRID_CHUNK_LIMIT = 20

# PDF 본문 상한 — Tier 1 ITPM(30K input tokens/min) 초과 방지.
# 한국어 평균 1 토큰 ≈ 2.5~3 chars, 45,000 chars ≈ 15~18K 토큰. step4(evidence)에서도 안전.
# 초과 시 앞부분만 사용하고 [PDF-TRUNC] 로그. (의결서는 보통 주문→이유→인정사실→법령→결론 순으로 핵심이 앞에 위치)
# v3.4 옵션B': 60000→45000 (step4 ITPM 30K 초과 3건 해결)
PDF_MAX_CHARS = 45000

# metadata.json 상한 — 11개 피심인 등 큰 metadata 사건 ITPM 초과 방지.
# metadata는 피심인정보·조치유형·사건번호 등 정형 정보가 앞에 위치. 10K로 핵심 정보 충분.
META_MAX_CHARS = 10000

# Prompt caching 마커 — render_prompt가 {{pdf_text}}/{{metadata}}를 이 marker로 교체.
# 실제 PDF·metadata 본문은 call_anthropic이 cache_control 블록으로 메시지 첫 부분에 prepend.
# 같은 사건의 step1·2·3에서 PDF·metadata 캐시 hit (90% input 절감), step4·5도 부분 hit.
PDF_PLACEHOLDER_MARKER  = "[PDF 본문은 본 메시지 첫 부분에 별도 블록으로 첨부되어 있습니다. 위에 첨부된 PDF 본문을 참조하라.]"
META_PLACEHOLDER_MARKER = "[metadata는 본 메시지 첫 부분에 별도 블록으로 첨부되어 있습니다. 위에 첨부된 metadata를 참조하라.]"

# JSON 형식 강화 — run_step_with_retry가 prompt body 끝에 자동 append.
# 새마을금고 qa_split[심화] 실패(Expecting ',' delimiter) 같은 케이스 방지.
JSON_HARDENING_SUFFIX = """

---

# 출력 형식 강화 (필수 준수)

1. **JSON 외 텍스트 절대 금지**: 응답의 첫 글자는 반드시 `{` 또는 `[`로 시작하라. 코드펜스(```)·설명·인사말 등 일체 금지.
2. **답변 내 큰따옴표 escape**: JSON string 내 큰따옴표는 반드시 `\\"`로 escape. 한국어 큰따옴표(" ")는 작은따옴표(' ') 또는 「 」로 대체 권장.
3. **줄바꿈 escape**: JSON string 내 줄바꿈은 `\\n`으로 표기. 실제 newline 문자 금지.
4. **trailing comma 금지**: 배열·객체 마지막 요소 뒤 콤마 금지 (`{...,}`·`[...,]` ❌).
5. **Backslash escape**: `\\`는 `\\\\`로 escape.
"""


# ============================ UTILS ============================
def safe_dirname(case_key: str) -> str:
    s = case_key.strip()
    s = re.sub(r'[\\/:*?"<>|]', '_', s)
    return s


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(line: str, console: bool = True):
    META_DIR.mkdir(parents=True, exist_ok=True)
    msg = f"[{now_ts()}] {line}"
    with BATCH_LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")
    if console:
        print(msg, flush=True)


def sleep_with_log(seconds: int, reason: str):
    log(f"대기 중 {seconds}초... ({reason})")
    time.sleep(seconds)


# ============================ DATA LOAD ============================
def load_locked() -> list[dict]:
    rows = []
    with LOCKED_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def build_inventory_index() -> dict:
    idx = {}
    with INVENTORY_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = r["사건키"].strip()
            idx[key] = r
    return idx


def order_priority(rows: list[dict]) -> list[dict]:
    """3단 우선순위: PRIORITY (이미 완료 6건, SKIP) → ROUND1 (신규 8건, 다양성+소형) → 나머지."""
    pri, round1, rest = [], [], []
    for r in rows:
        if any(kw in r["사건키"] for kw in PRIORITY_KEYWORDS):
            pri.append(r)
        elif any(kw in r["사건키"] for kw in ROUND1_KEYWORDS):
            round1.append(r)
        else:
            rest.append(r)

    def pri_rank(r):
        for i, kw in enumerate(PRIORITY_KEYWORDS):
            if kw in r["사건키"]:
                return i
        return 99
    pri.sort(key=pri_rank)

    def r1_rank(r):
        for i, kw in enumerate(ROUND1_KEYWORDS):
            if kw in r["사건키"]:
                return i
        return 99
    round1.sort(key=r1_rank)

    return pri + round1 + rest


def find_metadata_path(pdf_path: Path) -> Path | None:
    parent = pdf_path.parent
    # 일부 파일명에 trailing space가 있어 strip 하지 않은 stem과 strip 한 stem 모두 시도
    stems = [pdf_path.stem, pdf_path.stem.strip()]
    for stem in dict.fromkeys(stems):  # dedupe, keep order
        for cand in [
            parent / f"{stem}_metadata.json",
            parent / f"{stem}.metadata.json",
            parent / f"{stem}_meta.json",
            parent / f"{stem}.json",
        ]:
            if cand.exists():
                return cand
    return None


def find_hybrid_path(pdf_path: Path) -> Path | None:
    parent = pdf_path.parent
    stems = [pdf_path.stem, pdf_path.stem.strip()]
    for stem in dict.fromkeys(stems):
        for cand in [
            parent / f"{stem}_hybrid.json",
            parent / f"{stem}.hybrid.json",
        ]:
            if cand.exists():
                return cand
    return None


# ============================ I/O ============================
def read_pdf(pdf_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber not installed (in requirements.txt — activate .venv)")
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            parts.append(p.extract_text() or "")
    return "\n".join(parts)


def render_prompt(prompt_md: Path, variables: dict) -> tuple[str, bool, bool]:
    """prompt 본문 렌더링.

    {{pdf_text}}, {{metadata}}는 placeholder marker로 교체 — 실제 본문은
    call_anthropic이 cache_control 블록으로 메시지 첫 부분에 prepend함.
    그 외 변수({{facts}}, {{legal}} 등)는 일반 substitute.

    반환: (body, has_pdf_placeholder, has_meta_placeholder)
      - has_pdf=True  → caller가 pdf_text를 cache 블록으로 전달해야 함
      - has_meta=True → caller가 metadata_str을 cache 블록으로 전달해야 함
    """
    body = prompt_md.read_text(encoding="utf-8")
    has_pdf  = "{{pdf_text}}" in body
    has_meta = "{{metadata}}" in body
    if has_pdf:
        body = body.replace("{{pdf_text}}", PDF_PLACEHOLDER_MARKER)
    if has_meta:
        body = body.replace("{{metadata}}", META_PLACEHOLDER_MARKER)
    for k, v in variables.items():
        if k in ("pdf_text", "metadata"):
            continue
        body = body.replace("{{" + k + "}}", v)
    return body, has_pdf, has_meta


def truncate_hybrid_chunks(hybrid_str: str, limit: int = HYBRID_CHUNK_LIMIT):
    """hybrid.json 문자열을 파싱하여 상위 limit개 chunk만 남기고 재직렬화.

    파싱 불가능하거나 list 형태가 아니면 원본 그대로 반환.
    반환: (truncated_str, total_count, kept_count)
      - total_count == kept_count == 0  : 입력 비어있음
      - total_count == kept_count == -1 : 파싱 실패 또는 chunk 배열 미발견 (원본 사용)
      - 그 외                         : 정상 동작
    """
    if not hybrid_str.strip():
        return hybrid_str, 0, 0
    try:
        data = json.loads(hybrid_str)
    except Exception:
        return hybrid_str, -1, -1

    items = None
    container_key = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for k in ("chunks", "items", "hybrid_chunks", "data"):
            v = data.get(k)
            if isinstance(v, list):
                items = v
                container_key = k
                break

    if items is None:
        return hybrid_str, -1, -1

    total = len(items)
    if total <= limit:
        return hybrid_str, total, total

    truncated = items[:limit]
    if isinstance(data, list):
        new_data = truncated
    else:
        new_data = dict(data)
        new_data[container_key] = truncated
    return json.dumps(new_data, ensure_ascii=False), total, limit


def repair_json(s: str) -> str:
    """일반적인 JSON malformed 패턴 자동 복구. 실패해도 raise 안 함, 시도만."""
    # 1. Trailing comma in array/object: ,] → ] / ,} → }
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    # 2. Smart quotes (한국어 입력에서 자주 발생): " " ' ' → " ' ASCII
    s = s.replace('“', '"').replace('”', '"')
    s = s.replace('‘', "'").replace('’', "'")
    return s


def save_raw_response(case_key: str, step_var: str, raw_text: str, parse_error: str):
    """parse 실패 시 raw 응답 디스크 저장 (forensics). _failed/<case>_<step>_raw.txt"""
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    safe = safe_dirname(case_key)
    p = FAILED_DIR / f"{safe}_{step_var}_raw.txt"
    try:
        with p.open("w", encoding="utf-8") as f:
            f.write(f"=== Parse error: {parse_error}\n")
            f.write(f"=== Case: {case_key}\n")
            f.write(f"=== Step: {step_var}\n")
            f.write(f"=== Timestamp: {now_ts()}\n")
            f.write(f"=== Length: {len(raw_text)}\n")
            f.write("=" * 70 + "\n")
            f.write(raw_text)
        log(f"[RAW-SAVED] {case_key} {step_var} → {p.relative_to(PROJECT_ROOT)}")
    except Exception as e:
        log(f"[RAW-SAVE-FAIL] {case_key} {step_var}: {e}")


def extract_json(text: str):
    """LLM 응답에서 JSON 추출.

    1) ```json ... ``` 코드펜스 제거 (위치 무관, 본문 중간 OK)
    2) 첫 { 또는 [ 위치부터 균형 brace 스캔으로 종료 위치 결정
    3) 트레일링 프로즈가 있어도 정확한 JSON 경계만 잘라 파싱
    4) strict 파싱 실패 시 repair_json으로 자동 복구 시도
    5) 그래도 실패하면 head/tail snippet 포함한 에러 메시지로 raise
    """
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
        raise ValueError(f"no JSON found in response (head={text[:200]!r})")

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
    # 1차: strict 파싱
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e1:
        # 2차: 자동 복구 시도 (trailing comma, smart quote 등)
        try:
            repaired = repair_json(candidate)
            if repaired != candidate:
                return json.loads(repaired)
        except json.JSONDecodeError:
            pass
        # 3차: 실패 — head/tail snippet 포함 raise
        head = candidate[:200]
        tail = candidate[-200:] if len(candidate) > 400 else ""
        raise ValueError(
            f"JSONDecodeError: {e1} | balanced={'yes' if end>=0 else 'no'} "
            f"| len={len(candidate)} | head={head!r} | tail={tail!r}"
        ) from e1


# ============================ ANTHROPIC CALL ============================
_ANTHROPIC_CLIENT = None


def _get_client():
    """Anthropic 클라이언트 1회 생성 후 재사용 (커넥션 풀)."""
    global _ANTHROPIC_CLIENT
    if _ANTHROPIC_CLIENT is None:
        from anthropic import Anthropic
        _ANTHROPIC_CLIENT = Anthropic()
    return _ANTHROPIC_CLIENT


def call_anthropic(prompt_body: str, pdf_text: str, metadata_str: str,
                   model: str, max_tokens: int = MAX_TOKENS) -> dict:
    """Anthropic Messages API 호출 — prompt caching 적용.

    PDF·metadata는 cache_control 블록으로 메시지 첫 부분에 prepend.
    같은 사건의 step1·2·3 호출 시 PDF·metadata 캐시 hit (90% input 절감).
    step4: PDF만 hit, step5: metadata만 hit.

    반환에 cache_creation_input_tokens / cache_read_input_tokens 포함.
    """
    client = _get_client()
    content = []
    if pdf_text:
        content.append({"type": "text", "text": pdf_text, "cache_control": {"type": "ephemeral"}})
    if metadata_str:
        content.append({"type": "text", "text": metadata_str, "cache_control": {"type": "ephemeral"}})
    content.append({"type": "text", "text": prompt_body})

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
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


def _is_rate_limit(exc: Exception) -> bool:
    if exc.__class__.__name__ == "RateLimitError":
        return True
    try:
        from anthropic import RateLimitError as _RL
        if isinstance(exc, _RL):
            return True
    except Exception:
        pass
    status = getattr(exc, "status_code", None)
    return status == 429


def _call_and_parse(prompt_body: str, pdf_text: str, metadata_str: str,
                    model: str, max_tokens: int, step_var: str, case_key: str):
    """1회 호출 + 파싱. 성공 시 (parsed, "ok"), truncation 시 (None, "truncated"),
    그 외 예외는 raise (호출자가 재시도 결정).

    parse 실패 시 raw 응답을 _failed/<case>_<step>_raw.txt에 저장.
    """
    response = call_anthropic(prompt_body, pdf_text, metadata_str, model, max_tokens=max_tokens)
    in_t = response.get("input_tokens")
    out_t = response.get("output_tokens")
    cache_w = response.get("cache_creation_input_tokens", 0)
    cache_r = response.get("cache_read_input_tokens", 0)
    stop = response.get("stop_reason")
    log(f"[USAGE] {case_key} {step_var} {model} in={in_t} out={out_t} cache_w={cache_w} cache_r={cache_r} stop={stop}")
    if stop == "max_tokens":
        log(
            f"[TRUNC] {case_key} {step_var} {model}: stop_reason=max_tokens "
            f"(out={out_t}/max={max_tokens}). max_tokens 상향 필요. 재시도/폴백 생략."
        )
        save_raw_response(case_key, step_var, response.get("text", ""), "stop_reason=max_tokens")
        return None, "truncated"
    raw_text = response.get("text", "")
    try:
        return extract_json(raw_text), "ok"
    except (ValueError, json.JSONDecodeError) as e:
        save_raw_response(case_key, step_var, raw_text, str(e))
        raise


def run_step_with_retry(step_var: str, prompt_body: str, pdf_text: str, metadata_str: str,
                        tier: str, case_key: str, max_tokens: int | None = None):
    """Step 1회 호출 + 재시도/폴백 관리.

    prompt_body: 본문 (markers는 이미 적용됨, JSON suffix는 여기서 자동 append)
    pdf_text:    PDF 본문 (cache 블록, step1·2·3·4용. 미사용 step은 "")
    metadata_str: metadata (cache 블록, step1·2·3·5용. 미사용 step은 "")
    """
    primary_model = MODELS[tier]
    if max_tokens is None:
        max_tokens = STEP_MAX_TOKENS.get(step_var, MAX_TOKENS)

    # JSON 형식 강화 instruction을 prompt 끝에 추가 (escape 실수 방지)
    full_body = prompt_body + JSON_HARDENING_SUFFIX

    log(f"[CALL] {case_key} {step_var} {primary_model} body={len(full_body)} pdf={len(pdf_text)} meta={len(metadata_str)} max_tok={max_tokens}")

    for attempt in range(1, RETRY_MAX + 1):
        try:
            parsed, status = _call_and_parse(full_body, pdf_text, metadata_str, primary_model, max_tokens, step_var, case_key)
            if status == "truncated":
                return None, None
            return parsed, primary_model
        except Exception as e:
            log(f"[RETRY {attempt}/{RETRY_MAX}] {case_key} {step_var} {primary_model}: {type(e).__name__}: {e}")
            if attempt < RETRY_MAX:
                if _is_rate_limit(e):
                    sleep_with_log(RATELIMIT_DELAY, f"RateLimit {step_var} 재시도 전")
                else:
                    sleep_with_log(RETRY_BACKOFF * attempt, f"재시도 백오프 {step_var}")

    if tier == "opus":
        fb_model = MODELS[OPUS_FALLBACK_TIER]
        log(f"[FALLBACK] {case_key} {step_var} opus → sonnet ({fb_model})")
        for attempt in range(1, RETRY_MAX + 1):
            try:
                parsed, status = _call_and_parse(full_body, pdf_text, metadata_str, fb_model, max_tokens, step_var, case_key)
                if status == "truncated":
                    return None, None
                return parsed, fb_model
            except Exception as e:
                log(f"[RETRY-FB {attempt}/{RETRY_MAX}] {case_key} {step_var}: {type(e).__name__}: {e}")
                if attempt < RETRY_MAX:
                    if _is_rate_limit(e):
                        sleep_with_log(RATELIMIT_DELAY, f"RateLimit fallback {step_var}")
                    else:
                        sleep_with_log(RETRY_BACKOFF * attempt, f"fallback 백오프 {step_var}")
    return None, None


# ============================ QA_LIST 분할 호출 ============================
def _qa_items_from(result):
    """LLM 결과에서 Q&A 항목 배열을 추출."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for k in ("qa_list", "qa", "items", "data"):
            v = result.get(k)
            if isinstance(v, list):
                return v
    return []


def run_qa_list_split(prompt_path: Path, variables: dict, tier: str, case_key: str, case_dir: Path):
    """qa_list step을 난이도별 3회로 분할 호출, 결과 병합 (45개 목표).

    각 호출:
      - 난이도 필터 instruction을 기본 프롬프트 끝에 추가
      - max_tokens = QA_SPLIT_MAX_TOKENS
      - 호출 사이 QA_SPLIT_DELAY (60초) 대기

    부분 결과 보존:
      각 split 완료 즉시 case_dir/_qa_split_{난이도}.json 으로 체크포인트 저장.
      재실행 시 캐시 우선 로드 → 누락된 split만 재호출하여 비용/시간 절감.
      최종 qa_list.json 저장 후에도 _qa_split_*.json은 forensics용으로 보존.
    """
    # qa_list step5는 PDF 미사용, metadata만 사용 → metadata만 cache 블록으로
    base_body, has_pdf, has_meta = render_prompt(prompt_path, variables)
    pdf_arg  = variables.get("pdf_text", "") if has_pdf else ""
    meta_arg = variables.get("metadata", "") if has_meta else ""

    merged: list = []
    used_models: list = []

    total_runs = len(QA_DIFFICULTY_SPLITS)
    for i, diff in enumerate(QA_DIFFICULTY_SPLITS, 1):
        split_path = case_dir / f"_qa_split_{diff}.json"

        # 1) 캐시(이전 실행에서 성공한 split) 우선 로드
        if split_path.exists():
            try:
                cached = json.loads(split_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and isinstance(cached.get("items"), list):
                    items = cached["items"]
                    used = cached.get("model", "cached")
                    log(f"[QA-SPLIT-CACHED {i}/{total_runs}] {case_key} 난이도={diff} → {len(items)}개 (resume)")
                    merged.extend(items)
                    used_models.append(used)
                    continue
                else:
                    log(f"[QA-SPLIT-CACHE-BAD] {case_key} 난이도={diff} schema 불일치, 재호출")
            except Exception as e:
                log(f"[QA-SPLIT-CACHE-BAD] {case_key} 난이도={diff} read fail: {e}, 재호출")

        # 2) 신규 호출 — 분할 instruction은 body 끝에 append (cache 블록 뒤 dynamic 부분)
        instruction = (
            f"\n\n# ⚠️ 분할 호출 지시 ({i}/{total_runs})\n"
            f"이번 호출에서는 난이도 \"{diff}\"에 해당하는 **정확히 15개만** 출력하라.\n"
            f"- 페르소나 3종(일반국민·기업 컴플라이언스 담당자·논문 준비 학생) × 질문유형 5종 × 난이도 1종(\"{diff}\") = **15개**\n"
            f"- 다른 난이도(기초·심화·전문가 중 \"{diff}\" 외 2종)는 절대 포함하지 마라.\n"
            f"- 출력은 JSON 배열 1개, 객체 정확히 15개. 배열 외 텍스트 금지.\n"
        )
        full_body = base_body + instruction

        log(f"[QA-SPLIT {i}/{total_runs}] {case_key} 난이도={diff} max_tokens={QA_SPLIT_MAX_TOKENS}")
        result, used_model = run_step_with_retry(
            f"qa_list[{diff}]", full_body, pdf_arg, meta_arg, tier, case_key,
            max_tokens=QA_SPLIT_MAX_TOKENS,
        )
        if result is None:
            log(
                f"[QA-SPLIT-FAIL] {case_key} 난이도={diff} 분할 호출 실패. "
                f"앞선 split={len(merged)}개는 _qa_split_*.json에 보존됨 — 재실행 시 자동 resume."
            )
            return None, None

        items = _qa_items_from(result)
        log(f"[QA-SPLIT {i}/{total_runs}] {case_key} 난이도={diff} → {len(items)}개 수집")

        # 3) 체크포인트 즉시 저장 (다음 split 호출 전)
        try:
            split_path.parent.mkdir(parents=True, exist_ok=True)   # 디렉토리 재보강
            split_path.write_text(
                json.dumps(
                    {"diff": diff, "items": items, "model": used_model, "ts": now_ts(), "count": len(items)},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as e:
            log(f"[QA-SPLIT-CKPT-WARN] {case_key} 난이도={diff} 체크포인트 저장 실패: {e} (계속 진행)")

        merged.extend(items)
        used_models.append(used_model)

        if i < total_runs:
            sleep_with_log(QA_SPLIT_DELAY, f"qa_list[{diff}] 완료, 다음 분할 호출 전")

    return merged, "+".join(dict.fromkeys(used_models))


# ============================ VALIDATION ============================
def _walk_get(d, key):
    """Return key value at any nested dict level (first match)."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = _walk_get(v, key)
            if r is not None:
                return r
    return None


def validate_case(case_dir: Path) -> list[str]:
    issues = []

    facts_p = case_dir / "facts.json"
    legal_p = case_dir / "legal.json"
    qa_p    = case_dir / "qa_list.json"
    evid_p  = case_dir / "evidence.json"

    if facts_p.exists():
        f = json.loads(facts_p.read_text(encoding="utf-8"))
        if _walk_get(f, "summary_short") in (None, ""):
            issues.append("facts.summary_short missing")
        if _walk_get(f, "facts_structured") in (None, {}):
            issues.append("facts.facts_structured missing")

    if legal_p.exists():
        l = json.loads(legal_p.read_text(encoding="utf-8"))
        if _walk_get(l, "classification_tags") in (None, {}):
            issues.append("legal.classification_tags missing")
        if _walk_get(l, "inference_chain") in (None, []):
            issues.append("legal.inference_chain missing")

    if qa_p.exists():
        q = json.loads(qa_p.read_text(encoding="utf-8"))
        if isinstance(q, list):
            qs = q
        else:
            qs = q.get("qa_list") or q.get("qa") or q.get("items") or []
        if len(qs) != 45:
            issues.append(f"qa_list count {len(qs)} ≠ 45")

    if evid_p.exists():
        ev = json.loads(evid_p.read_text(encoding="utf-8"))
        if isinstance(ev, list):
            items = ev
        else:
            items = ev.get("evidence") or ev.get("items") or ev.get("chunks") or []
        miss = sum(1 for x in items if not (isinstance(x, dict) and x.get("chunk_id")))
        if miss:
            issues.append(f"evidence chunk_id missing × {miss}")

    return issues


# ============================ FAILURE HANDLING ============================
def save_failure(case_key: str, msg: str):
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    p = FAILED_DIR / f"{safe_dirname(case_key)}_error.txt"
    with p.open("a", encoding="utf-8") as f:
        f.write(f"[{now_ts()}] {msg}\n")
    log(f"[FAIL] {case_key} :: {msg}")


# ============================ CASE PROCESS ============================
def process_case(row: dict, inv_idx: dict, dry_run: bool) -> bool:
    case_key = row["사건키"].strip()
    case_dir_name = safe_dirname(case_key)
    case_dir = OUTPUT_DIR / case_dir_name

    inv = inv_idx.get(case_key)
    if inv is None:
        log(f"[INV-MISS] {case_key} not in inventory_full.csv")
        return False

    pdf_path = Path(inv["PDF경로"].strip())
    meta_path = find_metadata_path(pdf_path)
    hybrid_path = find_hybrid_path(pdf_path)

    skip_marker = case_dir / SKIP_MARKER
    if skip_marker.exists() and not dry_run:
        log(f"[SKIP] {case_key} (qa_list.json exists)")
        return True

    if dry_run:
        log(f"[DRY] {case_key}")
        log(f"      PDF    : {'OK ' if pdf_path.exists() else 'MISS'} {pdf_path}")
        log(f"      META   : {'OK ' if meta_path else 'MISS'} {meta_path or '(searched: .json / metadata/)'}")
        log(f"      HYBRID : {'OK ' if hybrid_path else 'MISS'} {hybrid_path or '(searched: .hybrid.json / hybrid/)'}")
        log(f"      OUTDIR : {case_dir}")
        return True

    case_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        save_failure(case_key, f"PDF not found: {pdf_path}")
        return False

    try:
        pdf_text = read_pdf(pdf_path)
    except Exception as e:
        save_failure(case_key, f"PDF read failed: {type(e).__name__}: {e}")
        return False

    # PDF 본문 상한 적용 — Tier 1 ITPM 30K 초과 방지
    if len(pdf_text) > PDF_MAX_CHARS:
        original_len = len(pdf_text)
        pdf_text = pdf_text[:PDF_MAX_CHARS]
        log(f"[PDF-TRUNC] {case_key} {original_len:,}자 → {PDF_MAX_CHARS:,}자 (절감 {original_len - PDF_MAX_CHARS:,}자)")

    try:
        metadata_str = meta_path.read_text(encoding="utf-8") if meta_path else ""
    except Exception as e:
        log(f"[WARN] {case_key} metadata read failed: {e} — empty 처리 후 계속")
        metadata_str = ""

    # metadata 상한 적용 — 11개 피심인 등 큰 metadata.json (조달청 17K) ITPM 초과 방지
    if len(metadata_str) > META_MAX_CHARS:
        original_len = len(metadata_str)
        metadata_str = metadata_str[:META_MAX_CHARS]
        log(f"[META-TRUNC] {case_key} {original_len:,}자 → {META_MAX_CHARS:,}자 (절감 {original_len - META_MAX_CHARS:,}자)")

    try:
        hybrid_str = hybrid_path.read_text(encoding="utf-8") if hybrid_path else ""
    except Exception as e:
        log(f"[WARN] {case_key} hybrid read failed: {e} — empty 처리 후 계속")
        hybrid_str = ""

    # hybrid_chunks 상위 N개로 잘라 프롬프트 토큰 절감 (대형 의결서 대비)
    if hybrid_str:
        truncated_str, total, kept = truncate_hybrid_chunks(hybrid_str)
        if total > 0 and kept > 0 and total != kept:
            saved_chars = len(hybrid_str) - len(truncated_str)
            log(f"[HYBRID-TRUNC] {case_key} chunks {total} → {kept} (절감 {saved_chars} chars)")
        elif total == -1:
            log(f"[HYBRID-WARN] {case_key} hybrid 파싱 또는 chunk 배열 인식 실패 — 원본 사용")
        hybrid_str = truncated_str

    variables = {
        "pdf_text": pdf_text,
        "metadata": metadata_str,
        "hybrid_chunks": hybrid_str,
    }

    t0 = time.time()
    last_step_var = STEPS[-1][0]
    for step_var, out_name, prompt_name, tier in STEPS:
        out_path = case_dir / out_name
        if out_path.exists():
            try:
                variables[step_var] = out_path.read_text(encoding="utf-8")
                log(f"[HAVE] {case_key} {step_var} (skip call)")
                continue
            except Exception as e:
                log(f"[REPROC] {case_key} {step_var} unreadable: {e}")

        prompt_path = PROMPT_DIR / prompt_name
        if not prompt_path.exists():
            save_failure(case_key, f"prompt missing: {prompt_path}")
            return False

        if step_var == "qa_list":
            result, used_model = run_qa_list_split(prompt_path, variables, tier, case_key, case_dir)
        else:
            # render_prompt가 PDF·meta 사용 여부를 판단하여 placeholder marker로 교체
            prompt_body, has_pdf, has_meta = render_prompt(prompt_path, variables)
            pdf_arg  = pdf_text     if has_pdf  else ""
            meta_arg = metadata_str if has_meta else ""
            result, used_model = run_step_with_retry(
                step_var, prompt_body, pdf_arg, meta_arg, tier, case_key,
            )
        if result is None:
            save_failure(case_key, f"{step_var} failed after retries")
            return False

        # 디렉토리 재보강 — macOS Unicode 정규화 등으로 case_dir.mkdir이 누락된 케이스 방어
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        variables[step_var] = json.dumps(result, ensure_ascii=False)
        if step_var == "qa_list" and isinstance(result, list):
            log(f"[OK] {case_key} {step_var} → {out_name} ({used_model}) total={len(result)}")
        else:
            log(f"[OK] {case_key} {step_var} → {out_name} ({used_model})")

        if step_var != last_step_var:
            sleep_with_log(STEP_DELAY, f"{step_var} 완료, 다음 step 전")

    elapsed = time.time() - t0
    log(f"[DONE] {case_key} in {elapsed:.1f}s")

    issues = validate_case(case_dir)
    if issues:
        log(f"[VALIDATE] {case_key} :: {' | '.join(issues)}")
    else:
        log(f"[VALIDATE-OK] {case_key}")
    return True


# ============================ MAIN ============================
def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="경로/프롬프트/API키만 확인")
    g.add_argument("--execute", action="store_true", help="실제 API 호출")
    ap.add_argument("--only-priority", action="store_true", help="6건 우선만")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N건만 처리 (0=전체)")
    args = ap.parse_args()

    if not LOCKED_CSV.exists():
        sys.exit(f"missing: {LOCKED_CSV}")
    if not INVENTORY_CSV.exists():
        sys.exit(f"missing: {INVENTORY_CSV}")

    locked = load_locked()
    inv = build_inventory_index()
    queue = order_priority(locked)
    if args.only_priority:
        queue = [r for r in queue if any(kw in r["사건키"] for kw in PRIORITY_KEYWORDS)]
    if args.limit and args.limit > 0:
        queue = queue[:args.limit]

    mode = "DRY-RUN" if args.dry_run else "EXECUTE"
    log("=" * 70)
    log(f"BATCH START [{mode}] cases={len(queue)} priority_only={args.only_priority} limit={args.limit}")
    log("=" * 70)

    log(f"prompt dir : {'OK' if PROMPT_DIR.exists() else 'MISS'} {PROMPT_DIR}")
    for step_var, out_name, prompt_name, tier in STEPS:
        p = PROMPT_DIR / prompt_name
        log(f"  prompt {step_var:9s} ({tier:6s}) → {out_name:14s} : {'OK ' if p.exists() else 'MISS'} {prompt_name}")

    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    log(f"ANTHROPIC_API_KEY : {'SET' if api_key_set else 'NOT SET'}")
    if args.execute and not api_key_set:
        sys.exit("ANTHROPIC_API_KEY not set — `export ANTHROPIC_API_KEY=...` first")

    succ = fail = 0
    for i, r in enumerate(queue, 1):
        log(f"--- [{i}/{len(queue)}] {r['사건키'][:50]} ({r.get('사건유형','')}) ---")
        try:
            ok = process_case(r, inv, dry_run=args.dry_run)
        except KeyboardInterrupt:
            log("[INTERRUPT] 사용자 중단 — 배치 종료")
            break
        except Exception as e:
            log(f"[CRASH] {r['사건키'][:50]} unhandled: {type(e).__name__}: {e}")
            try:
                save_failure(r["사건키"].strip(), f"unhandled exception: {type(e).__name__}: {e}")
            except Exception:
                pass
            ok = False
        if ok:
            succ += 1
        else:
            fail += 1

    log("=" * 70)
    log(f"BATCH END   [{mode}] ok={succ} fail={fail}")
    log("=" * 70)


if __name__ == "__main__":
    main()
