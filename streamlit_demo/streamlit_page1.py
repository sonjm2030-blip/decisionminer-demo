"""DecisionMiner — Page 1 시연 페이지
의결서 PDF → 5단 분해 → 5종 데이터셋 산출 시각화.

실행: streamlit run streamlit_page1.py
"""
import json
import time
from pathlib import Path

import streamlit as st


DATA_PATH = Path(__file__).resolve().parent / "data" / "coupang_demo_data.json"

with DATA_PATH.open(encoding="utf-8") as f:
    DATA = json.load(f)


st.set_page_config(
    page_title="DecisionMiner 시연",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 행정 톤 스타일
st.markdown("""
<style>
.case-cover {
    border: 2px solid #1E40AF;
    border-radius: 8px;
    padding: 1.6rem 1.4rem;
    background: #F8FAFC;
    font-family: -apple-system, "맑은 고딕", sans-serif;
}
.case-cover h3 { color: #1E40AF; margin: 0 0 0.4rem 0; font-size: 1.1rem; }
.case-cover .divider { border-top: 1px solid #CBD5E1; margin: 0.6rem 0 1rem 0; }
.case-cover .label { color: #475569; font-size: 0.78rem; margin-top: 0.7rem; }
.case-cover .value { color: #0F172A; font-size: 0.95rem; font-weight: 600; line-height: 1.4; }
.qa-mini { background: #F1F5F9; padding: 0.7rem 0.9rem; border-left: 3px solid #1E40AF;
           margin: 0.4rem 0; border-radius: 0 4px 4px 0; font-size: 0.88rem; }
.qa-mini .meta { color: #1E40AF; font-weight: 600; font-size: 0.78rem;
                 margin-bottom: 0.25rem; letter-spacing: 0.2px; }
.qa-mini .q { color: #0F172A; margin-top: 0.2rem; }
.qa-mini .a { color: #334155; margin-top: 0.3rem; line-height: 1.45; }
.evi-mini { background: #FEFCE8; padding: 0.55rem 0.8rem; border-left: 3px solid #CA8A04;
            margin: 0.3rem 0; border-radius: 0 4px 4px 0; font-size: 0.82rem; }
.evi-mini .head { color: #854D0E; font-weight: 600; font-size: 0.75rem; }
.dataset-card { text-align: center; padding: 0.5rem 0; }
.dataset-card .num { font-size: 1.8rem; font-weight: 700; color: #059669; }
.dataset-card .label { font-size: 0.85rem; color: #475569; }
</style>
""", unsafe_allow_html=True)


# 세션 상태
if "demo_completed" not in st.session_state:
    st.session_state.demo_completed = False


# ─── 헤더 ─────────────────────────────────────────────
st.markdown("# DecisionMiner — 데이터 인프라 작동 시연")
st.caption("의결서 PDF → 5단 분해 → 5종 데이터셋")

case_options = [DATA["case_key"]]
st.selectbox("표본 사건", case_options, index=0, disabled=True,
             help="시연용 표본 사건. 본 화면은 데이터 인프라 작동 시각화이며, 사용자 챗봇/검색 서비스가 아님.")

st.divider()


# ─── 좌(40) / 우(60) 컬럼 ───────────────────────────────
col_left, col_right = st.columns([2, 3], gap="large")


# ── 좌측: 의결서 표지 텍스트 카드 ──
with col_left:
    meta = DATA["case_meta"]
    proc = meta.get("처분결과", "")
    proc_short = proc.split(" | ")[0] if " | " in proc else proc
    proc_full = proc.replace(" | ", "<br>")
    st.markdown(f"""
<div class="case-cover">
  <h3>공정거래위원회 의결서</h3>
  <div class="divider"></div>
  <div class="label">사건명</div>
  <div class="value">{meta['사건명']}</div>
  <div class="label">의결일</div>
  <div class="value">{meta['의결일']}</div>
  <div class="label">적용법령</div>
  <div class="value">{meta['적용법령']}</div>
  <div class="label">처분결과</div>
  <div class="value">{proc_full}</div>
  <div class="label">사건유형</div>
  <div class="value">{meta['사건유형']}</div>
  <div class="divider"></div>
  <div class="label">출처</div>
  <div class="value" style="font-size:0.85rem; font-weight:500;">{meta['출처']}</div>
</div>
""", unsafe_allow_html=True)

    st.markdown("")
    st.caption("표지형 텍스트 카드 (PDF 썸네일 미사용 — 행정 톤 유지).")


# ── 우측: 5단계 시뮬레이션 placeholder들 ──
with col_right:
    st.markdown("### 5단 분해 시뮬레이션")
    button_ph = st.empty()
    step1_ph = st.empty()
    step2_ph = st.empty()
    step3_ph = st.empty()
    step4_ph = st.empty()
    step5_ph = st.empty()


# ── 하단: 데이터셋 카드 + 미니 대시보드 placeholder ──
st.markdown("")
datasets_ph = st.empty()
st.markdown("")
dashboard_ph = st.empty()


# ─── 단계별 렌더 함수들 ─────────────────────────────────

def _render_step1(ph):
    s1 = DATA["step1"]
    fs = s1["result"].get("facts_structured", {})
    with ph.container(border=True):
        st.success(f"Step 1 — {s1['title']} 완료")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**주체**  \n{s1['result'].get('주체','')}")
            st.markdown(f"**상대방**  \n{s1['result'].get('상대방','')}")
            st.markdown(f"**시장**  \n{s1['result'].get('시장','')}")
        with c2:
            st.markdown(f"**기간**  \n{fs.get('기간','—')}")
            st.markdown(f"**행위**  \n{s1['result'].get('행위','')}")
        st.markdown(f"**summary_short**  \n_{s1['result'].get('summary_short','')}_")


def _render_step2(ph):
    s2 = DATA["step2"]
    tags = s2["result"].get("classification_tags", {})
    reqs = s2["result"].get("판단요건", [])
    with ph.container(border=True):
        st.success(f"Step 2 — {s2['title']} 완료")
        c1, c2 = st.columns(2)
        c1.markdown(f"**적용법령**  \n{s2['result'].get('법령','')}")
        c2.markdown(f"**적용조문**  \n{s2['result'].get('조문','')}")
        st.markdown(f"**위반유형**  \n{s2['result'].get('위반유형','')}")
        if reqs:
            st.markdown("**판단요건**")
            for r in reqs[:4]:
                st.markdown(f"- {r}")
        if tags:
            st.markdown(f"**분류태그**  \n대분류: `{tags.get('사건유형_대분류','')}` · "
                        f"세분류: `{tags.get('사건유형_세분류','')}` · "
                        f"산업분야: `{tags.get('산업분야','')}`")


def _render_step3(ph):
    s3 = DATA["step3"]
    types = s3["result"].get("처분유형", [])
    with ph.container(border=True):
        st.success(f"Step 3 — {s3['title']} 완료")
        c1, c2 = st.columns(2)
        c1.markdown(f"**처분유형**  \n{', '.join(types) if types else '—'}")
        c2.markdown(f"**과태료/과징금**  \n{s3['result'].get('과태료') or s3['result'].get('과징금') or '—'}")
        st.markdown(f"**근거조문**  \n{s3['result'].get('근거조문','')}")
        if s3['result'].get('시정명령'):
            st.markdown("**시정명령 요지**")
            st.caption(s3['result']['시정명령'][:300] + ("..." if len(s3['result']['시정명령']) > 300 else ""))


def _render_step4(ph):
    s4 = DATA["step4"]
    with ph.container(border=True):
        st.success(f"Step 4 — {s4['title']} 완료 ({len(s4['evidence_samples'])}개 카테고리 매칭)")
        for ev in s4["evidence_samples"]:
            st.markdown(
                f"<div class='evi-mini'>"
                f"<div class='head'>[{ev['section']} · {ev['category']}] chunk_id={ev['chunk_id']}</div>"
                f"{ev['text']}</div>",
                unsafe_allow_html=True,
            )


def _render_step5(ph):
    s5 = DATA["step5"]
    with ph.container(border=True):
        st.success(f"Step 5 — {s5['title']} 완료 ({s5['qa_count']}건 자동 생성)")
        st.markdown("**미리보기 (페르소나/난이도/질문유형 3축)**")
        for qa in s5["qa_samples"]:
            q_short = qa["question"][:140] + ("..." if len(qa["question"]) > 140 else "")
            a_short = qa["answer"][:200] + ("..." if len(qa["answer"]) > 200 else "")
            st.markdown(
                f"<div class='qa-mini'>"
                f"<div class='meta'>{qa['persona']} · {qa['level']} · {qa['type']} "
                f"<span style='color:#64748B; font-weight:400;'>(qa_id 끝자리: {qa['qa_id'][-3:]})</span></div>"
                f"<div class='q'><b>Q.</b> {q_short}</div>"
                f"<div class='a'><b>A.</b> {a_short}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _render_datasets(ph):
    with ph.container():
        total = sum(d["count"] for d in DATA["datasets"].values())
        st.success(f"데이터 인프라 산출 완료 — 본 사건 1건에서 {total}건 데이터 추출")
        cols = st.columns(5)
        for i, (name, info) in enumerate(DATA["datasets"].items()):
            with cols[i]:
                st.markdown(
                    f"<div class='dataset-card'><div class='num'>{info['count']}</div>"
                    f"<div class='label'>{name}</div></div>",
                    unsafe_allow_html=True,
                )
                with st.expander("샘플 보기"):
                    sample = info["sample"]
                    if isinstance(sample, dict):
                        for k, v in sample.items():
                            if not str(v).strip():
                                continue
                            st.markdown(f"**{k}**")
                            st.caption(str(v))
                    else:
                        st.write(sample)


def _render_dashboard(ph):
    qc = DATA["qc_summary"]
    with ph.container(border=True):
        st.markdown("**본 사건 자동 검수 결과** _(qc_result_990.csv 필터링 결과)_")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("평균 점수", f"{qc['평균점수']}점")
        m2.metric("Gold", f"{qc['Gold']}건")
        m3.metric("보정필요", f"{qc['보정필요']}건")
        m4.metric("탈락", f"{qc['탈락']}건")
        if qc.get("주요_오류"):
            ann = []
            for it in qc["주요_오류"]:
                code = it.split(":")[0]
                if code == "E5": ann.append(f"{it} (금액 근거 불일치)")
                elif code == "E7": ann.append(f"{it} (페르소나 부적합)")
                else: ann.append(it)
            st.caption("**주요 오류**: " + " · ".join(ann))


def render_final_state():
    """완료 상태 즉시 렌더링 (rerun되어도 결과 유지)."""
    _render_step1(step1_ph)
    _render_step2(step2_ph)
    _render_step3(step3_ph)
    _render_step4(step4_ph)
    _render_step5(step5_ph)
    _render_datasets(datasets_ph)
    _render_dashboard(dashboard_ph)


def run_demo_sequence():
    """단일 콜백 안에서 placeholder + time.sleep으로 순차 진행."""
    sequence = [
        (step1_ph, _render_step1, 2.0, "Step 1: 사건개요·사실관계 추출 중..."),
        (step2_ph, _render_step2, 3.0, "Step 2: 법적 판단 추출 중..."),
        (step3_ph, _render_step3, 2.0, "Step 3: 시정조치·과징금 추출 중..."),
        (step4_ph, _render_step4, 2.0, "Step 4: 근거 텍스트 매칭 중..."),
        (step5_ph, _render_step5, 3.0, "Step 5: QA 생성 중 (45건, 페르소나·난이도·질문유형 3축)..."),
    ]
    for ph, fn, sec, msg in sequence:
        with ph.container(border=True):
            with st.spinner(msg):
                time.sleep(sec)
        fn(ph)

    with datasets_ph.container():
        with st.spinner("5종 데이터셋 산출 중..."):
            time.sleep(2.0)
    _render_datasets(datasets_ph)

    with dashboard_ph.container(border=True):
        with st.spinner("검수 결과 집계 중..."):
            time.sleep(1.0)
    _render_dashboard(dashboard_ph)


# ─── 분기 처리 ─────────────────────────────────────────
if st.session_state.demo_completed:
    with button_ph.container():
        if st.button("🔄 다시 시연", type="secondary"):
            st.session_state.demo_completed = False
            st.rerun()
    render_final_state()
else:
    with button_ph.container():
        start = st.button("▶ 시연 시작", type="primary")
    if start:
        run_demo_sequence()
        st.session_state.demo_completed = True
        st.rerun()
    else:
        with step1_ph.container(border=True):
            st.info("시연 시작 버튼을 눌러주세요. Step 1~5가 약 15초간 자동 진행됩니다.")
