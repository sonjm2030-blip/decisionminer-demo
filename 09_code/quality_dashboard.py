"""
DecisionMiner 품질진단 대시보드
quality_checker v2.4 결과 CSV를 시각화하는 Streamlit 앱

실행: streamlit run quality_dashboard.py
입력: qc_result.csv (quality_checker 출력)
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import Counter
import os
from pathlib import Path

# ─────────────────────────────────────────────
# NaN-safe helper (P1 수정)
# ─────────────────────────────────────────────

def has_value(x) -> bool:
    """NaN/빈문자열/None을 안전하게 걸러내는 helper"""
    if x is None:
        return False
    if pd.isna(x):
        return False
    return str(x).strip() not in ("", "nan")

def parse_codes(x) -> list:
    """error_codes/warning_flags 문자열 → strip된 코드 리스트 (NaN/공백 안전)"""
    if not has_value(x):
        return []
    return [c.strip() for c in str(x).split(",") if c.strip()]

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="DecisionMiner 품질진단",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# 스타일
# ─────────────────────────────────────────────

st.markdown("""
<style>
    .main > div { padding-top: 1rem; }
    .metric-card {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        border: 1px solid #e9ecef;
    }
    .metric-value { font-size: 2.2rem; font-weight: 700; }
    .metric-label { font-size: 0.85rem; color: #6c757d; margin-top: 0.3rem; }
    .gold { color: #f59e0b; }
    .correction { color: #3b82f6; }
    .rejected { color: #ef4444; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 20px;
        border-radius: 8px 8px 0 0;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

@st.cache_data
def load_data(path):
    """검수 결과 CSV 로드 (다중 인코딩 fallback)"""
    for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
        try:
            df = pd.read_csv(path, encoding=enc)
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


def find_result_file():
    """결과 파일 자동 탐색 — __file__ 기준 + cwd 기준 양쪽 탐색 (P1 수정)"""
    candidates = [
        "11_data_quality/qc_result_990.csv",
        "qc_result_990.csv",
        "qc_result.csv",
        "sample_result_v24.csv",
        "11_data_quality/qc_result.csv",
    ]
    # 1) 앱 파일 기준 디렉터리
    app_dir = Path(__file__).resolve().parent
    project_root = app_dir.parent  # 09_code의 상위 = 프로젝트 루트
    # 2) cwd 기준
    search_bases = [Path.cwd(), app_dir, project_root]
    for base in search_bases:
        for c in candidates:
            p = base / c
            if p.exists():
                return str(p)
    return None


REQUIRED_DASHBOARD_COLS = ["QA_ID", "사건키", "score_total", "judgment"]


def validate_dashboard_cols(df):
    """필수 컬럼 검증 (P2 수정)"""
    missing = [c for c in REQUIRED_DASHBOARD_COLS if c not in df.columns]
    if missing:
        return False, missing
    return True, []


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────

with st.sidebar:
    st.title("🔍 DecisionMiner")
    st.caption("규칙 기반 1차 자동 품질진단 엔진 v2.4")
    st.divider()

    # 파일 업로드 또는 자동 탐색
    uploaded = st.file_uploader("검수 결과 CSV 업로드", type=["csv"])

    if uploaded:
        # P2 수정: 업로드도 다중 인코딩 fallback
        import io
        raw = uploaded.read()
        df = None
        for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if df is None:
            st.error("CSV 인코딩을 감지할 수 없습니다.")
            st.stop()
    else:
        auto_path = find_result_file()
        if auto_path:
            df = load_data(auto_path)
            if df is None:
                st.error(f"파일을 읽을 수 없습니다: {auto_path}")
                st.stop()
            st.success(f"자동 로드: {auto_path}")
        else:
            st.warning("qc_result.csv를 업로드하세요")
            st.stop()

    # P2 수정: 필수 컬럼 검증
    ok, missing = validate_dashboard_cols(df)
    if not ok:
        st.error(f"필수 컬럼 누락: {', '.join(missing)}")
        st.stop()

    # score_total 정규화 (P2 수정)
    df["score_total"] = pd.to_numeric(df["score_total"], errors="coerce")
    bad_scores = df["score_total"].isna().sum()
    if bad_scores > 0:
        st.warning(f"점수 결측 {bad_scores}건 제외")
        df = df.dropna(subset=["score_total"])

    st.divider()

    # 필터
    st.subheader("필터")

    judgments = df["judgment"].unique().tolist()
    sel_judgment = st.multiselect("판정", judgments, default=judgments)

    case_keys = sorted(df["사건키"].unique().tolist())
    sel_cases = st.multiselect("사건키", case_keys, default=case_keys)

    score_range = st.slider(
        "점수 범위",
        int(df["score_total"].min()),
        int(df["score_total"].max()),
        (int(df["score_total"].min()), int(df["score_total"].max()))
    )

# 필터 적용
mask = (
    df["judgment"].isin(sel_judgment) &
    df["사건키"].isin(sel_cases) &
    df["score_total"].between(score_range[0], score_range[1])
)
filtered = df[mask]

# ─────────────────────────────────────────────
# 메인 콘텐츠
# ─────────────────────────────────────────────

st.title("품질진단 대시보드")
st.caption(f"전체 {len(df)}건 중 {len(filtered)}건 표시")

# ── 탭 구성 ──
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 종합 현황", "📈 점수 분포", "🔴 오류 분석",
    "🗺️ 사건별 히트맵", "🔎 개별 QA 검색"
])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 1: 종합 현황
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab1:
    n = len(filtered)
    if n == 0:
        st.warning("필터 조건에 맞는 데이터가 없습니다.")
        st.stop()

    jd = Counter(filtered["judgment"])
    gold = jd.get("Gold", 0)
    corr = jd.get("보정필요", 0)
    rej = jd.get("탈락", 0)
    avg = filtered["score_total"].mean()

    # 오류율 — parse_codes로 strip/NaN 안전 처리
    err_count = sum(1 for _, r in filtered.iterrows() if parse_codes(r.get("error_codes")))
    sev_count = sum(1 for _, r in filtered.iterrows()
                    if set(parse_codes(r.get("error_codes"))) & {"E4", "E5", "E6", "E10"})
    warn_count = sum(1 for _, r in filtered.iterrows() if parse_codes(r.get("warning_flags")))

    # KPI 카드
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("전체 건수", f"{n}건")
    with c2:
        st.metric("🥇 Gold", f"{gold}건", f"{gold/n*100:.1f}%")
    with c3:
        st.metric("🔧 보정필요", f"{corr}건", f"{corr/n*100:.1f}%")
    with c4:
        st.metric("❌ 탈락", f"{rej}건", f"{rej/n*100:.1f}%")
    with c5:
        st.metric("평균 점수", f"{avg:.1f}점")

    st.divider()

    # 판정 분포 + 오류율
    col_a, col_b = st.columns([1, 1])

    with col_a:
        st.subheader("판정 분포")
        fig_pie = px.pie(
            names=["Gold", "보정필요", "탈락"],
            values=[gold, corr, rej],
            color_discrete_sequence=["#f59e0b", "#3b82f6", "#ef4444"],
            hole=0.4
        )
        fig_pie.update_layout(height=350, margin=dict(t=20, b=20))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_b:
        st.subheader("품질 지표")
        metrics = pd.DataFrame({
            "지표": ["전체 오류율", "중대 오류율 (E4~E6,E10)", "확인필요율"],
            "값": [
                f"{err_count/n*100:.1f}%",
                f"{sev_count/n*100:.1f}%",
                f"{warn_count/n*100:.1f}%"
            ],
            "건수": [err_count, sev_count, warn_count]
        })
        st.dataframe(metrics, use_container_width=True, hide_index=True)

        st.divider()
        st.caption("**Gold 기준**: 80점 이상 + 중대·경미·확인필요 모두 없음")
        st.caption("**보정필요**: 60점 이상 + 중대 오류 1개 이하")
        st.caption("**탈락**: 59점 이하, 또는 E10, 또는 중대 2개 이상")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 2: 점수 분포
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab2:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("점수 분포 히스토그램")
        fig_hist = px.histogram(
            filtered, x="score_total",
            color="judgment",
            color_discrete_map={"Gold": "#f59e0b", "보정필요": "#3b82f6", "탈락": "#ef4444"},
            nbins=20,
            barmode="stack"
        )
        fig_hist.update_layout(
            xaxis_title="총점",
            yaxis_title="건수",
            height=400,
            margin=dict(t=30)
        )
        fig_hist.add_vline(x=80, line_dash="dash", line_color="green", annotation_text="Gold 기준 80점")
        fig_hist.add_vline(x=60, line_dash="dash", line_color="orange", annotation_text="탈락 기준 60점")
        st.plotly_chart(fig_hist, use_container_width=True)

    with col2:
        st.subheader("단계별 점수 요약")
        # P3 수정: 컬럼명별 라벨/만점 dict
        stage_map = {
            "score_stage1": ("1.원문무결성", 15),
            "score_stage2": ("2.구조분해", 20),
            "score_stage3": ("3.메타데이터", 15),
            "score_stage4": ("4.QA정합성", 35),
            "score_stage5": ("5.다양성", 15),
        }
        existing_stages = [(c, stage_map[c]) for c in stage_map if c in filtered.columns]

        if existing_stages:
            stage_df = pd.DataFrame([
                {
                    "단계": label,
                    "평균": f"{filtered[col].mean():.1f}",
                    "만점": mx,
                    "달성률": f"{filtered[col].mean()/mx*100:.0f}%"
                }
                for col, (label, mx) in existing_stages
            ])
            st.dataframe(stage_df, use_container_width=True, hide_index=True)

    st.divider()

    # 5단계 레이더 차트
    if existing_stages:
        st.subheader("5단계 달성률 레이더")
        pcts = [filtered[col].mean()/mx*100 for col, (label, mx) in existing_stages]
        labels = [label for _, (label, _) in existing_stages]
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=pcts + [pcts[0]],
            theta=labels + [labels[0]],
            fill="toself",
            fillcolor="rgba(59,130,246,0.2)",
            line_color="#3b82f6"
        ))
        fig_radar.update_layout(
            polar=dict(radialaxis=dict(range=[0, 100], ticksuffix="%")),
            height=400,
            margin=dict(t=30)
        )
        st.plotly_chart(fig_radar, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 3: 오류 분석
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab3:
    col_e, col_w = st.columns(2)

    with col_e:
        st.subheader("🔴 오류코드 TOP 10")
        all_codes = []
        for _, r in filtered.iterrows():
            all_codes.extend(parse_codes(r.get("error_codes")))

        if all_codes:
            code_counts = Counter(all_codes).most_common(10)
            code_df = pd.DataFrame(code_counts, columns=["오류코드", "건수"])
            fig_bar = px.bar(
                code_df, x="건수", y="오류코드",
                orientation="h",
                color="오류코드",
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig_bar.update_layout(height=400, showlegend=False, margin=dict(t=20))
            st.plotly_chart(fig_bar, use_container_width=True)

            # 오류코드 설명
            code_desc = {
                "E1": "원문 누락/파싱 실패",
                "E2": "구조 분해 오류",
                "E3": "법령·조항 추출 오류",
                "E4": "판단 왜곡 의심",
                "E5": "금액 근거 확인 필요 (의심)",
                "E6": "과잉 추론 의심",
                "E7": "페르소나 부적합",
                "E8": "난이도 분류 오류",
                "E9": "중복 질문",
                "E10": "개인정보 위험"
            }
            desc_df = pd.DataFrame(
                [(c, cnt, code_desc.get(c, "")) for c, cnt in code_counts],
                columns=["코드", "건수", "설명"]
            )
            st.dataframe(desc_df, use_container_width=True, hide_index=True)
        else:
            st.info("오류코드가 없습니다.")

    with col_w:
        st.subheader("🟡 확인필요 플래그 TOP 10")
        all_warnings = []
        for _, r in filtered.iterrows():
            all_warnings.extend(parse_codes(r.get("warning_flags")))

        if all_warnings:
            warn_counts = Counter(all_warnings).most_common(10)
            warn_df = pd.DataFrame(warn_counts, columns=["플래그", "건수"])
            fig_wbar = px.bar(
                warn_df, x="건수", y="플래그",
                orientation="h",
                color_discrete_sequence=["#f59e0b"]
            )
            fig_wbar.update_layout(height=400, showlegend=False, margin=dict(t=20))
            st.plotly_chart(fig_wbar, use_container_width=True)
        else:
            st.info("확인필요 플래그가 없습니다.")

    st.divider()

    # E5 세부유형 분포 (P2)
    st.subheader("🔍 E5 세부유형 분포")
    import re
    e5_pat = re.compile(r"(E5:[가-힣A-Za-z0-9_]+)")
    e5_counts = Counter()
    for _, r in filtered.iterrows():
        details = r.get("error_details")
        if has_value(details):
            for m in e5_pat.findall(str(details)):
                e5_counts[m] += 1

    if e5_counts:
        e5_df = pd.DataFrame(e5_counts.most_common(), columns=["E5 세부유형", "건수"])
        fig_e5 = px.bar(
            e5_df, x="건수", y="E5 세부유형",
            orientation="h",
            color="E5 세부유형",
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig_e5.update_layout(height=max(250, len(e5_df) * 50), showlegend=False, margin=dict(t=20))
        st.plotly_chart(fig_e5, use_container_width=True)
    else:
        st.info("E5 세부유형이 없습니다.")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 4: 사건별 히트맵
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab4:
    st.subheader("사건별 평균 점수 히트맵")

    stage_cols_exist = [c for c in ["score_stage1", "score_stage2", "score_stage3", "score_stage4", "score_stage5"] if c in filtered.columns]

    if stage_cols_exist:
        heatmap_data = filtered.groupby("사건키")[stage_cols_exist].mean()

        fig_heat = go.Figure(data=go.Heatmap(
            z=heatmap_data.values,
            x=[c.replace("score_", "") for c in stage_cols_exist],
            y=heatmap_data.index.tolist(),
            colorscale="RdYlGn",
            text=[[f"{v:.0f}" for v in row] for row in heatmap_data.values],
            texttemplate="%{text}",
            hovertemplate="사건: %{y}<br>단계: %{x}<br>평균: %{z:.1f}점<extra></extra>"
        ))
        fig_heat.update_layout(
            height=max(400, len(heatmap_data) * 30),
            margin=dict(t=30),
            xaxis_title="검수 단계",
            yaxis_title="사건키"
        )
        st.plotly_chart(fig_heat, use_container_width=True)

    st.divider()

    # 사건별 판정 분포
    st.subheader("사건별 판정 분포")
    case_judgment = filtered.groupby(["사건키", "judgment"]).size().unstack(fill_value=0)
    for j in ["Gold", "보정필요", "탈락"]:
        if j not in case_judgment.columns:
            case_judgment[j] = 0
    case_judgment = case_judgment[["Gold", "보정필요", "탈락"]]

    fig_stack = px.bar(
        case_judgment.reset_index(),
        x="사건키",
        y=["Gold", "보정필요", "탈락"],
        color_discrete_map={"Gold": "#f59e0b", "보정필요": "#3b82f6", "탈락": "#ef4444"},
        barmode="stack"
    )
    fig_stack.update_layout(height=400, margin=dict(t=30), xaxis_tickangle=45)
    st.plotly_chart(fig_stack, use_container_width=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 탭 5: 개별 QA 검색
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

with tab5:
    st.subheader("개별 QA 검색 및 상세 열람")

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        search_id = st.text_input("QA_ID 검색", placeholder="예: QA_0001")
    with col_f2:
        search_judgment = st.selectbox("판정 필터", ["전체"] + list(filtered["judgment"].unique()))
    with col_f3:
        search_error = st.text_input("오류코드 필터", placeholder="예: E5 / 금액불일치 / 질문매칭낮음")

    # 필터 적용
    view_df = filtered.copy()
    if search_id:
        view_df = view_df[view_df["QA_ID"].str.contains(search_id, na=False)]
    if search_judgment != "전체":
        view_df = view_df[view_df["judgment"] == search_judgment]
    if search_error:
        cols_to_search = [c for c in ["error_codes", "warning_flags", "error_details"] if c in view_df.columns]
        if cols_to_search:
            mask = pd.Series(False, index=view_df.index)
            for col in cols_to_search:
                mask = mask | view_df[col].apply(lambda x: has_value(x) and search_error in str(x))
            view_df = view_df[mask]
        else:
            st.info("검색 가능한 컬럼이 없습니다.")

    st.caption(f"{len(view_df)}건 표시")

    # 테이블
    display_cols = ["QA_ID", "사건키", "score_total", "judgment", "error_codes", "warning_flags"]
    display_cols = [c for c in display_cols if c in view_df.columns]
    st.dataframe(
        view_df[display_cols].head(50),
        use_container_width=True,
        hide_index=True
    )

    # 상세 카드
    if len(view_df) > 0:
        st.divider()
        sel_idx = st.selectbox(
            "상세 보기",
            view_df.index.tolist(),
            format_func=lambda x: f"{view_df.loc[x, 'QA_ID']} ({view_df.loc[x, 'score_total']}점 {view_df.loc[x, 'judgment']})"
        )

        row = view_df.loc[sel_idx]
        jd_icon = "🥇" if row["judgment"] == "Gold" else "🔧" if row["judgment"] == "보정필요" else "❌"

        st.markdown(f"### {jd_icon} {row['QA_ID']} — {row['score_total']}점 {row['judgment']}")

        c1, c2, c3, c4, c5 = st.columns(5)
        for col, name, val in zip(
            [c1, c2, c3, c4, c5],
            ["원문무결성", "구조분해", "메타데이터", "QA정합성", "다양성"],
            ["score_stage1", "score_stage2", "score_stage3", "score_stage4", "score_stage5"]
        ):
            with col:
                if val in row.index:
                    st.metric(name, f"{row[val]}점")

        if has_value(row.get("error_codes")):
            st.error(f"**오류코드**: {row['error_codes']}")
        if has_value(row.get("warning_flags")):
            st.warning(f"**확인필요**: {row['warning_flags']}")
        if has_value(row.get("error_details")):
            with st.expander("상세 사유"):
                for detail in str(row["error_details"]).split(" | "):
                    st.markdown(f"- {detail}")
        if has_value(row.get("correction_note")):
            st.info(f"**보정 지침**: {row['correction_note']}")

# ─────────────────────────────────────────────
# 푸터
# ─────────────────────────────────────────────

st.divider()
st.caption("DecisionMiner 규칙 기반 1차 자동 품질진단 엔진 v2.4 | 공정거래위원회 의결서 기반 QA 학습데이터 품질관리")
st.caption("AI가 만든 데이터의 한계를 숨기지 않고, 측정하고, 조치하고, 문서화합니다.")
