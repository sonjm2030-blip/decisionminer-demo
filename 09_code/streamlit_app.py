"""
DecisionMiner Streamlit App — 3 화면 풀세트

화면 1: Gold 데이터셋 열람  (04_raw_outputs/ 22사건 + tier1_ai_auto/ 17열 조인)
화면 2: PDF 업로드 → 즉시 분해 (Step 1 facts + Step 2 legal)

실행:
  cd 09_code
  streamlit run streamlit_app.py
"""

from __future__ import annotations
import json
import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd


# ============================ CONFIG ============================
def get_data_root():
    app_dir = Path(__file__).resolve().parent
    project_root = app_dir.parent

    # 로컬 우선: 프로젝트 루트에 04_raw_outputs 있으면 로컬
    if (project_root / "04_raw_outputs").exists():
        return project_root

    # Cloud fallback: 09_code/data/
    cloud_data = app_dir / "data"
    if (cloud_data / "04_raw_outputs").exists():
        return cloud_data

    return Path.cwd()


DATA_ROOT  = get_data_root()
RAW_DIR    = DATA_ROOT / "04_raw_outputs"

# 자동 품질진단 결과 CSV (검수 시연용)
QC_CSV_PATH = Path(__file__).resolve().parent.parent / "11_data_quality" / "qc_result_990_v2.csv"
if not QC_CSV_PATH.exists():
    QC_CSV_PATH = Path(__file__).resolve().parent / "data" / "qc_result_990_v2.csv"
TIER1_DIR  = DATA_ROOT / "11_data_quality" / "tier1_ai_auto"
XLSX_DIR   = DATA_ROOT / "05_xlsx"
PROMPT_DIR = DATA_ROOT / "03_prompts" / "v2"

MODEL         = "claude-sonnet-4-6"
MAX_TOKENS    = 4000
PDF_MAX_CHARS = 45000

REQUIRED_FILES = ("qa_list.json", "legal.json", "facts.json")
STEP1_PROMPT = PROMPT_DIR / "step1_facts_v2.md"
STEP2_PROMPT = PROMPT_DIR / "step2_legal_v2.md"

st.set_page_config(page_title="DecisionMiner", page_icon="⚖️", layout="wide")


def set_custom_theme():
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #6B5CE7 0%, #2ECEC0 100%);
    }

    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        color: white !important;
    }

    section[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="tag"] span {
        color: white !important;
    }

    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        color: initial !important;
    }
    div[role="listbox"] *,
    ul[role="listbox"] *,
    [data-baseweb="popover"] * {
        color: initial !important;
    }

    main h1 {
        color: #2D2B55 !important;
    }

    div[data-testid="stMetric"] {
        background: #f0eeff;
        border-radius: 12px;
        padding: 14px 16px;
        border: 1px solid rgba(107, 92, 231, 0.14);
    }

    [data-testid="stMetricValue"] {
        color: #6B5CE7;
    }

    button[data-baseweb="tab"][aria-selected="true"] {
        color: #6B5CE7 !important;
        border-bottom-color: #6B5CE7 !important;
    }

    button[kind="primary"],
    div[data-testid="stDownloadButton"] button {
        background: #6B5CE7 !important;
        border-color: #6B5CE7 !important;
    }

    div[data-testid="stExpander"] {
        border-left: 3px solid transparent;
        transition: border-left-color 140ms ease, box-shadow 140ms ease;
    }

    div[data-testid="stExpander"]:hover {
        border-left-color: #6B5CE7;
        box-shadow: 0 4px 14px rgba(107, 92, 231, 0.10);
    }
    </style>
    """, unsafe_allow_html=True)


# ============================ COMMON UTILS ============================
def render_prompt(template_path: Path, variables: dict) -> str:
    """프롬프트 파일의 모든 {{변수}} 패턴을 치환. variables 에 없는 키는 빈 문자열로 대체.
    반환 보장: str (bytes 가 들어와도 utf-8 로 디코드)."""
    body = template_path.read_text(encoding="utf-8")
    pat = re.compile(r"\{\{([^}]+)\}\}")

    def sub(m):
        key = m.group(1).strip()
        v = variables.get(key, "")
        if v is None:
            return ""
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="replace")
        return str(v)

    return str(pat.sub(sub, body))


def find_template_vars(template_path: Path) -> list[str]:
    body = template_path.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\{\{([^}]+)\}\}", body)))


def repair_json(s: str) -> str:
    """일반적인 JSON malformed 패턴 자동 복구 (batch_processor_v1.py 패턴)."""
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    s = s.replace('“', '"').replace('”', '"')   # ""
    s = s.replace('‘', "'").replace('’', "'")   # ''
    return s


def extract_json(text: str):
    """LLM 응답에서 JSON 추출 (batch_processor_v1.py 패턴)."""
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
            r = repair_json(candidate)
            if r != candidate:
                return json.loads(r)
        except json.JSONDecodeError:
            pass
        raise ValueError(f"JSON parse failed: {e1}") from e1


def get_case_type(legal: dict) -> str:
    tags = legal.get("classification_tags") if isinstance(legal.get("classification_tags"), dict) else {}
    v = (tags.get("사건유형_대분류") or "").strip() if isinstance(tags, dict) else ""
    return v or "(미상)"


def get_applied_law(legal: dict) -> str:
    law = (legal.get("법령") or "").strip()
    art = (legal.get("조문") or "").strip()
    return f"{law} {art}".strip() or "(미상)"


# ============================ DATA LOAD ============================
@st.cache_data(show_spinner=False)
def discover_cases() -> list[str]:
    """qa_list+legal+facts 모두 있는 사건 폴더명 list."""
    if not RAW_DIR.exists():
        return []
    cases = []
    for d in sorted(RAW_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name.startswith("v2_"):
            continue
        if all((d / f).exists() for f in REQUIRED_FILES):
            cases.append(d.name)
    return cases


@st.cache_data(show_spinner=False)
def load_case(case_key: str) -> dict:
    """단일 사건 — qa_list/legal/facts 로드 + tier1 조인. 누락은 dict 안에 빈 값으로 보관."""
    case_dir = RAW_DIR / case_key
    out = {
        "case_key":    case_key,
        "qa_items":    [],
        "legal":       {},
        "facts":       {},
        "tier1_by_qa": {},
        "tier1_loaded": False,
        "tier1_error":  None,
        "errors":      [],
    }
    if not case_dir.exists():
        out["errors"].append(f"폴더 없음: {case_dir}")
        return out

    # qa_list — 순서 기반 qa_id 자동 부여
    try:
        qa_raw = json.loads((case_dir / "qa_list.json").read_text(encoding="utf-8"))
        items = qa_raw if isinstance(qa_raw, list) else (
            (qa_raw.get("qa_list") if isinstance(qa_raw, dict) else None)
            or (qa_raw.get("items") if isinstance(qa_raw, dict) else None) or []
        )
        for i, qa in enumerate(items, 1):
            if isinstance(qa, dict):
                item = dict(qa)
                item["qa_id"] = f"{i:03d}"
                out["qa_items"].append(item)
    except Exception as e:
        out["errors"].append(f"qa_list.json 로드 실패: {e}")

    try:
        out["legal"] = json.loads((case_dir / "legal.json").read_text(encoding="utf-8"))
    except Exception as e:
        out["errors"].append(f"legal.json 로드 실패: {e}")

    try:
        out["facts"] = json.loads((case_dir / "facts.json").read_text(encoding="utf-8"))
    except Exception as e:
        out["errors"].append(f"facts.json 로드 실패: {e}")

    # tier1 join — 없으면 fallback
    tier1_path = TIER1_DIR / f"{case_key}_tier1.json"
    if tier1_path.exists():
        try:
            tier1 = json.loads(tier1_path.read_text(encoding="utf-8"))
            for r in tier1.get("results", []):
                if isinstance(r, dict) and r.get("qa_id"):
                    out["tier1_by_qa"][r["qa_id"]] = r
            out["tier1_loaded"] = True
        except Exception as e:
            out["tier1_error"] = str(e)

    return out


@st.cache_data(show_spinner=False)
def load_all_case_types() -> dict:
    """{case_key: case_type} 매핑 — 사이드바 사건유형 필터용."""
    out = {}
    for ck in discover_cases():
        try:
            legal = json.loads((RAW_DIR / ck / "legal.json").read_text(encoding="utf-8"))
            out[ck] = get_case_type(legal)
        except Exception:
            out[ck] = "(미상)"
    return out


# ============================ PAGE 1: Gold 열람 ============================
def find_xlsx_for_download():
    """다운로드 대상 xlsx — 우선순위 적용"""
    # 1순위: 정확한 파일명
    primary = XLSX_DIR / "학습데이터_설계서_DecisionMiner_v2_6.xlsx"
    if primary.exists():
        return primary

    # 2순위: exclude 필터 후 최신
    exclude_keywords = ["checkpoint", "b용", "예시", "backup", "bak", "old"]
    candidates = []
    for f in XLSX_DIR.glob("*.xlsx"):
        name_lower = f.name.lower()
        if any(kw in name_lower for kw in exclude_keywords):
            continue
        candidates.append(f)

    if candidates:
        return max(candidates, key=lambda f: f.stat().st_mtime)

    return None


def page_gold():
    st.title("Gold 데이터셋 열람")
    st.caption("04_raw_outputs/ 22사건 × 45 Q&A = 990건. 11_data_quality/tier1_ai_auto/ 의 17열(문제점·해결방안)을 자동 조인.")

    xlsx_path = find_xlsx_for_download()
    if xlsx_path:
        with open(xlsx_path, "rb") as f:
            st.download_button(
                label="📥 학습데이터 설계서 다운로드 (.xlsx)",
                data=f.read(),
                file_name="DecisionMiner_학습데이터_설계서.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
    else:
        st.info("다운로드 가능한 학습데이터 설계서 파일이 없습니다.")

    case_keys = discover_cases()
    if not case_keys:
        st.error(f"사건 폴더를 찾을 수 없음: {RAW_DIR}")
        return

    case_type_map = load_all_case_types()
    all_types = sorted(set(case_type_map.values()))

    st.sidebar.markdown("### 사건 필터")
    sel_types = st.sidebar.multiselect("사건유형", all_types, default=all_types)

    visible_cases = [ck for ck in case_keys if case_type_map.get(ck) in sel_types]
    if not visible_cases:
        st.warning("선택한 사건유형에 해당하는 사건이 없습니다.")
        return

    selected_case = st.sidebar.selectbox(
        "사건",
        visible_cases,
        format_func=lambda x: f"[{case_type_map.get(x, '?')}] {x[:42]}",
    )

    case = load_case(selected_case)
    if case["errors"]:
        for e in case["errors"]:
            st.error(e)
    if not case["qa_items"]:
        st.error("표시할 Q&A 가 없습니다.")
        return

    case_type = get_case_type(case["legal"])
    applied_law = get_applied_law(case["legal"])
    summary = case["facts"].get("summary_short") if isinstance(case["facts"], dict) else None
    summary = summary or "(요약 없음)"

    c1, c2, c3 = st.columns([2, 3, 2])
    c1.metric("사건유형", case_type)
    c2.metric("적용법령", applied_law)
    c3.metric("Q&A 수", f"{len(case['qa_items'])}")

    st.markdown(f"**사건 요약**: {summary}")

    if not case["tier1_loaded"]:
        if case.get("tier1_error"):
            st.warning(f"⚠️ tier1.json 로드 오류: {case['tier1_error']} — 17열은 fallback 표시")
        else:
            st.info("ℹ️ 이 사건의 17열(문제점·해결방안)은 아직 생성되지 않았습니다.")

    st.sidebar.markdown("### Q&A 필터")
    personas = sorted({q.get("페르소나", "") for q in case["qa_items"] if q.get("페르소나")})
    qtypes   = sorted({q.get("질문유형", "") for q in case["qa_items"] if q.get("질문유형")})
    levels   = sorted({q.get("난이도", "") for q in case["qa_items"] if q.get("난이도")})

    sel_personas = st.sidebar.multiselect("페르소나", personas, default=personas)
    sel_qtypes   = st.sidebar.multiselect("질문유형", qtypes, default=qtypes)
    sel_levels   = st.sidebar.multiselect("난이도", levels, default=levels)

    filtered = [
        q for q in case["qa_items"]
        if q.get("페르소나") in sel_personas
        and q.get("질문유형") in sel_qtypes
        and q.get("난이도") in sel_levels
    ]

    st.markdown(f"### Q&A 카드 — {len(filtered)} / {len(case['qa_items'])}")

    if not filtered:
        st.info("필터 조건에 맞는 Q&A 가 없습니다.")
        return

    for q in filtered:
        qid = q["qa_id"]
        title = (
            f"[{qid}] {q.get('페르소나', '')} · {q.get('난이도', '')} · {q.get('질문유형', '')} — "
            f"{(q.get('질문', '') or '')[:50]}"
        )
        with st.expander(title):
            st.markdown(f"**질문**\n\n{q.get('질문', '')}")
            st.markdown(f"**답변**\n\n{q.get('답변', '')}")
            st.caption(f"근거: {q.get('근거_short') or '(없음)'}")

            tier1 = case["tier1_by_qa"].get(qid)
            st.markdown("---")
            if tier1:
                st.markdown(f"**17열 문제점**\n\n{tier1.get('문제점', '')}")
                st.markdown(f"**17열 해결방안**\n\n{tier1.get('해결방안', '')}")
            else:
                st.markdown("**17열 문제점**: _아직 생성되지 않음_")
                st.markdown("**17열 해결방안**: _아직 생성되지 않음_")


# ============================ PAGE 2: PDF 분해 ============================
def get_api_key() -> str | None:
    """st.secrets 또는 환경변수에서 API 키 로드. bytes/공백/BOM 정리."""
    raw = None
    try:
        raw = st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[attr-defined]
    except Exception:
        pass
    if not raw:
        raw = os.environ.get("ANTHROPIC_API_KEY")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    # BOM(U+FEFF), zero-width space(U+200B), 일반 공백 제거
    raw = raw.lstrip("﻿").strip().strip("​")
    return raw or None


def _validate_api_key(api_key: str):
    """HTTP Authorization 헤더는 ASCII 만 허용 — 비-ASCII 사전 차단."""
    if not api_key.isascii():
        bad = [(i, ch, hex(ord(ch))) for i, ch in enumerate(api_key) if ord(ch) > 127]
        sample = bad[:5]
        raise RuntimeError(
            f"ANTHROPIC_API_KEY 에 비-ASCII 문자가 포함됨 (HTTP 헤더는 ASCII만 허용). "
            f"위치/문자/코드(앞 5개): {sample}. "
            "원인 가능성: (1) 쉘 export 시 한글 자판 잔존 (2) 텍스트 에디터의 smart quote (3) BOM/zero-width 문자. "
            "재설정: `export ANTHROPIC_API_KEY=sk-ant-...` (영문 자판으로 직접 타이핑)"
        )


# Anthropic 클라이언트는 module 단위 캐시 (재생성 시 키 검증 부담)
_ANTHROPIC_CLIENT = None
_CACHED_API_KEY = None


def _get_client():
    global _ANTHROPIC_CLIENT, _CACHED_API_KEY
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정 (st.secrets 또는 환경변수)")
    _validate_api_key(api_key)
    if _ANTHROPIC_CLIENT is None or _CACHED_API_KEY != api_key:
        from anthropic import Anthropic
        _ANTHROPIC_CLIENT = Anthropic(api_key=api_key)
        _CACHED_API_KEY = api_key
    return _ANTHROPIC_CLIENT


def call_anthropic(system: str, user_text: str, max_tokens: int = MAX_TOKENS) -> dict:
    """Anthropic Messages API 호출. 실패 시 raise.
    system/user_text 는 str 강제 (bytes 들어오면 decode)."""
    if isinstance(system, bytes):
        system = system.decode("utf-8", errors="replace")
    if isinstance(user_text, bytes):
        user_text = user_text.decode("utf-8", errors="replace")
    system = str(system)
    user_text = str(user_text)

    client = _get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    text = "".join(getattr(b, "text", "") or "" for b in resp.content)
    usage = getattr(resp, "usage", None)
    return {
        "text": text,
        "stop_reason": getattr(resp, "stop_reason", None),
        "input_tokens":  getattr(usage, "input_tokens", None) if usage else None,
        "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
    }


def extract_pdf_text(uploaded_file) -> str:
    """pdfplumber 로 PDF 텍스트 추출. 결과는 str 강제."""
    import pdfplumber
    parts = []
    with pdfplumber.open(uploaded_file) as pdf:
        for p in pdf.pages:
            t = p.extract_text() or ""
            if isinstance(t, bytes):
                t = t.decode("utf-8", errors="replace")
            parts.append(str(t))
    return "\n".join(parts)


def _format_unicode_error_hint(e: Exception) -> str:
    """UnicodeEncodeError 가 났을 때 사용자에게 보여줄 진단 힌트."""
    return (
        f"UnicodeEncodeError: {e}\n\n"
        "원인 후보:\n"
        "1. ANTHROPIC_API_KEY 에 비-ASCII 문자 포함 (가장 흔함) — 쉘 export 시 한글 자판/smart quote 끼임\n"
        "2. 환경변수 LANG / LC_ALL 이 C/POSIX — `export LANG=ko_KR.UTF-8` 후 streamlit 재시작\n"
        "3. PYTHONIOENCODING 미설정 — `export PYTHONIOENCODING=utf-8` 후 재시작"
    )


SYSTEM_PROMPT_FACTS = "당신은 공정거래 의결서 분석 전문가다. 사용자 메시지의 지시에 따라 JSON 객체 1개만 출력하라. 코드펜스·설명문 일체 금지."
SYSTEM_PROMPT_LEGAL = "당신은 공정거래 법리 분석 전문가다. 사용자 메시지의 지시에 따라 JSON 객체 1개만 출력하라. 코드펜스·설명문 일체 금지."


def render_cached_results():
    """22건 캐시된 facts.json + legal.json 표시"""
    all_keys = discover_cases()  # list[str] 반환
    if not all_keys:
        st.info("캐시된 결과가 없습니다.")
        return

    # qa_list + facts + legal 모두 있는 사건만
    valid_keys = []
    for key in all_keys:
        case_dir = RAW_DIR / key
        if (case_dir / "qa_list.json").exists() and \
           (case_dir / "facts.json").exists() and \
           (case_dir / "legal.json").exists():
            valid_keys.append(key)

    if not valid_keys:
        st.info("완전한 캐시 데이터(qa_list + facts + legal)가 있는 사건이 없습니다.")
        return

    case_type_map = load_all_case_types()  # dict[str, str]

    selected = st.selectbox(
        "사건 선택",
        valid_keys,
        format_func=lambda k: f"{k} ({case_type_map.get(k, '미상')})"
    )
    case_dir = RAW_DIR / selected

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Step 1: 사실관계")
        data = json.loads((case_dir / "facts.json").read_text(encoding="utf-8"))
        st.json(data, expanded=False)

    with col2:
        st.subheader("Step 2: 위반법리")
        data = json.loads((case_dir / "legal.json").read_text(encoding="utf-8"))
        st.json(data, expanded=False)


def page_pdf_analysis():
    st.header("📄 의결서 PDF 분해")
    st.info("ℹ️ 라이브 분해는 Step 1·2 시각화 시연용. 풀 5단 분해 + 자동 품질진단 결과는 22건 캐시 탭에서 확인 가능")

    tab_a, tab_b = st.tabs(["22건 캐시 결과", "새 PDF 실시간 분해"])

    with tab_a:
        render_cached_results()

    with tab_b:
        st.warning("⚠️ 이 탭은 Anthropic API를 호출합니다. 건당 약 $0.3~0.5 비용이 발생합니다.")
        render_live_analysis()


def render_live_analysis():
    st.caption(
        "공정거래 의결서 PDF 1건을 업로드하면 Sonnet 4.6 API 가 사실관계 5요소(Step 1) + 법리(Step 2)를 자동 추출합니다. "
        "이 화면은 **이 의결서에서 자동 추출된 학습데이터 원재료**를 미리 확인하는 용도입니다."
    )

    uploaded = st.file_uploader("의결서 PDF 업로드", type=["pdf"])
    if uploaded is None:
        st.info("PDF 를 업로드한 뒤 [분해 실행] 버튼을 누르세요. 업로드만으로는 API 가 호출되지 않습니다.")
        return

    st.success(f"파일: {uploaded.name} ({uploaded.size:,} bytes)")

    if "analysis" not in st.session_state:
        st.session_state.analysis = {}

    # 새 파일 감지 시 이전 결과 무효화
    sig = (uploaded.name, uploaded.size)
    if st.session_state.analysis.get("sig") != sig:
        st.session_state.analysis = {"sig": sig}

    if st.button("분해 실행", type="primary"):
        st.session_state.analysis = {"sig": sig}
        a = st.session_state.analysis

        # ===== PDF 추출 =====
        with st.spinner("PDF 텍스트 추출 중..."):
            try:
                pdf_text = extract_pdf_text(uploaded)
            except Exception as e:
                st.error(f"PDF 추출 실패: {type(e).__name__}: {e}")
                return

        if not pdf_text.strip():
            st.warning("텍스트 추출 실패 — 스캔 PDF일 수 있습니다")
            return

        original_len = len(pdf_text)
        truncated = False
        if len(pdf_text) > PDF_MAX_CHARS:
            pdf_text = pdf_text[:PDF_MAX_CHARS]
            truncated = True
            st.warning(f"PDF 본문 {original_len:,}자 → {PDF_MAX_CHARS:,}자로 잘림 (Tier 1 ITPM 보호)")

        # ===== 최소 metadata 자동 생성 =====
        metadata = json.dumps(
            {
                "file_name":       uploaded.name,
                "file_size_bytes": uploaded.size,
                "uploaded_at":     datetime.now().isoformat(timespec="seconds"),
                "source":          "streamlit_upload",
            },
            ensure_ascii=False,
            indent=2,
        )

        a["pdf_text_len"] = len(pdf_text)
        a["pdf_truncated"] = truncated
        a["metadata"] = metadata

        # ===== Step 1: facts =====
        if not STEP1_PROMPT.exists():
            st.error(f"Step 1 prompt 파일 없음: {STEP1_PROMPT}")
            return
        vars1 = {"pdf_text": pdf_text, "metadata": metadata}
        body1 = render_prompt(STEP1_PROMPT, vars1)

        with st.spinner("Step 1 (facts) Sonnet 4.6 호출 중..."):
            try:
                resp1 = call_anthropic(SYSTEM_PROMPT_FACTS, body1, max_tokens=MAX_TOKENS)
            except UnicodeEncodeError as e:
                st.error(f"❌ Step 1 API 호출 실패: {_format_unicode_error_hint(e)}")
                return
            except Exception as e:
                st.error(f"❌ Step 1 API 호출 실패: {type(e).__name__}: {e}")
                return

        a["step1_raw"] = resp1["text"]
        a["step1_stop_reason"] = resp1["stop_reason"]
        a["step1_usage"] = (resp1.get("input_tokens"), resp1.get("output_tokens"))
        a["step1_vars"] = list(vars1.keys())
        a["step1_template_vars"] = find_template_vars(STEP1_PROMPT)

        try:
            facts = extract_json(resp1["text"])
        except Exception as e:
            st.error(f"❌ Step 1 JSON 파싱 실패: {e}")
            with st.expander("Raw response (Step 1)"):
                st.code(resp1["text"][:3000] or "(empty)")
            return
        a["facts"] = facts

        # ===== Step 2: legal =====
        if not STEP2_PROMPT.exists():
            st.error(f"Step 2 prompt 파일 없음: {STEP2_PROMPT}")
            return
        facts_str = json.dumps(facts, ensure_ascii=False, indent=2)
        vars2 = {"pdf_text": pdf_text, "metadata": metadata, "facts": facts_str}
        body2 = render_prompt(STEP2_PROMPT, vars2)

        with st.spinner("Step 2 (legal) Sonnet 4.6 호출 중..."):
            try:
                resp2 = call_anthropic(SYSTEM_PROMPT_LEGAL, body2, max_tokens=MAX_TOKENS)
            except UnicodeEncodeError as e:
                st.error(f"❌ Step 2 API 호출 실패: {_format_unicode_error_hint(e)}")
                return
            except Exception as e:
                st.error(f"❌ Step 2 API 호출 실패: {type(e).__name__}: {e}")
                return

        a["step2_raw"] = resp2["text"]
        a["step2_stop_reason"] = resp2["stop_reason"]
        a["step2_usage"] = (resp2.get("input_tokens"), resp2.get("output_tokens"))
        a["step2_vars"] = list(vars2.keys())
        a["step2_template_vars"] = find_template_vars(STEP2_PROMPT)

        try:
            legal = extract_json(resp2["text"])
        except Exception as e:
            st.error(f"❌ Step 2 JSON 파싱 실패: {e}")
            with st.expander("Raw response (Step 2)"):
                st.code(resp2["text"][:3000] or "(empty)")
            return
        a["legal"] = legal

    # ===== 결과 표시 =====
    a = st.session_state.get("analysis", {})
    if "facts" not in a:
        return

    st.markdown("---")
    st.markdown("## Step 1 — 사실관계 5요소 (facts)")
    facts = a["facts"]
    cols = st.columns(5)
    for i, k in enumerate(["주체", "상대방", "시장", "행위", "결과"]):
        v = facts.get(k, "(없음)") if isinstance(facts, dict) else "(없음)"
        with cols[i]:
            st.markdown(f"**{k}**")
            st.write(v)

    st.markdown(f"**summary_short**: {facts.get('summary_short', '(없음)') if isinstance(facts, dict) else ''}")

    fs = facts.get("facts_structured") if isinstance(facts, dict) else None
    if fs:
        st.markdown("**facts_structured**")
        st.json(fs)

    if "legal" in a:
        st.markdown("---")
        st.markdown("## Step 2 — 법리 (legal)")
        legal = a["legal"]
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**법령**: {legal.get('법령', '(없음)')}")
        c2.markdown(f"**조문**: {legal.get('조문', '(없음)')}")
        c3.markdown(f"**위반유형**: {legal.get('위반유형', '(없음)')}")

        pj = legal.get("판단요건")
        if pj:
            st.markdown("**판단요건**")
            if isinstance(pj, list):
                for i, item in enumerate(pj, 1):
                    st.markdown(f"{i}. {item}")
            else:
                st.write(pj)

        ct = legal.get("classification_tags")
        if ct:
            st.markdown("**classification_tags**")
            st.json(ct)

        ic = legal.get("inference_chain")
        if ic:
            st.markdown("**inference_chain (추론 단계)**")
            st.json(ic)

    with st.expander("Raw JSON 및 치환 변수"):
        st.markdown("### Step 1")
        s1u = a.get("step1_usage", (None, None))
        st.caption(
            f"치환 변수 (입력): {a.get('step1_vars')} | "
            f"템플릿 내 발견 변수: {a.get('step1_template_vars')} | "
            f"stop_reason: {a.get('step1_stop_reason')} | "
            f"tokens in/out: {s1u[0]}/{s1u[1]}"
        )
        st.code(a.get("step1_raw", "")[:3000] or "(empty)")

        st.markdown("### Step 2")
        s2u = a.get("step2_usage", (None, None))
        st.caption(
            f"치환 변수 (입력): {a.get('step2_vars')} | "
            f"템플릿 내 발견 변수: {a.get('step2_template_vars')} | "
            f"stop_reason: {a.get('step2_stop_reason')} | "
            f"tokens in/out: {s2u[0]}/{s2u[1]}"
        )
        st.code(a.get("step2_raw", "")[:3000] or "(empty)")

        st.markdown("### 자동 생성된 metadata")
        st.code(a.get("metadata", "") or "(empty)")


# ============================ MAIN ============================
def main():
    set_custom_theme()
    st.sidebar.title("⚖️ DecisionMiner")
    st.sidebar.caption("공정거래 의결서 학습데이터 표준화 도구")
    page = st.sidebar.selectbox(
        "화면 선택",
        ["Gold 데이터셋 열람", "PDF 분해"],
        index=0,
    )
    st.sidebar.markdown("---")

    if page == "Gold 데이터셋 열람":
        page_gold()
    elif page == "PDF 분해":
        page_pdf_analysis()



if __name__ == "__main__":
    main()
