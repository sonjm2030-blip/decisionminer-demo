"""
DecisionMiner — 시연용 단일 서버 (진짜 파싱 + 문헌 기반 검수)

이 파일 하나로:
  1) 업로드된 의결서 PDF에서 실제 텍스트를 추출하고
  2) LLM으로 5단 분해(사건개요·법적판단·시정조치·근거매칭·QA)하고
  3) NIA·NIST·ISO 기준의 문헌 기반 검수(9개 오류코드)를 규칙으로 실행하고
  4) 시연 웹(index.html)을 같이 서빙한다.

실행:
    pip install flask anthropic pdfplumber
    export ANTHROPIC_API_KEY=sk-...        # (Windows: set ANTHROPIC_API_KEY=...)
    python server.py
    → 브라우저에서 http://localhost:5000
    ※ index.html 을 이 파일과 같은 폴더에 두세요.

검수 로직은 시연 웹의 검수 엔진(quality_checker_grounding)과 동일 규칙을 1:1 포팅한 것이라,
웹 화면의 판정과 서버 판정이 일치한다.
"""

import os
import re
import json
import time
import tempfile
import threading
from collections import deque, defaultdict
from flask import Flask, request, jsonify, send_file

import anthropic

MODEL = os.environ.get("DM_MODEL", "claude-sonnet-4-6")     # 빠름. 품질 우선이면 claude-opus-4-8
INDEX_HTML = os.environ.get("DM_INDEX", "index.html")
_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip())

# ── 배포(공개 URL) 안전장치 설정 ──────────────────────────────────
PORT = int(os.environ.get("PORT", 7860))                          # HF Spaces=7860, Render/Railway=$PORT
RATE_PER_MIN = int(os.environ.get("DM_RATE_PER_MIN", "1"))        # IP당 분당 분해 허용 횟수
RATE_PER_DAY = int(os.environ.get("DM_RATE_PER_DAY", "30"))       # 전체(서버) 일일 분해 총량 = 비용 상한
ACCESS_TOKEN = os.environ.get("DM_ACCESS_TOKEN", "").strip()      # 설정 시 ?t= / X-Access-Token 일치해야 분해 허용

_rate_lock = threading.Lock()
_ip_hits = defaultdict(deque)                # ip -> deque[timestamp] (최근 60초 슬라이딩 윈도)
_day_bucket = {"day": None, "count": 0}      # 전체 일일 카운터 (실제 LLM 호출 시에만 증가)


def _client_ip():
    # 호스팅 프록시(HF/Render) 뒤에서는 X-Forwarded-For 첫 IP가 실제 접속자
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _rate_check_minute(ip):
    """IP당 분당 횟수 제한(스팸 방지). 통과 시 기록."""
    now = time.time()
    with _rate_lock:
        dq = _ip_hits[ip]
        while dq and now - dq[0] >= 60:
            dq.popleft()
        if len(dq) >= RATE_PER_MIN:
            return False
        dq.append(now)
        return True


def _rate_day_try():
    """전체 일일 총량 제한(비용 상한). 실제 LLM 호출 직전에만 호출 → 통과 시 카운트 증가."""
    now = time.time()
    with _rate_lock:
        day = int(now // 86400)
        if _day_bucket["day"] != day:
            _day_bucket["day"], _day_bucket["count"] = day, 0
        if _day_bucket["count"] >= RATE_PER_DAY:
            return False
        _day_bucket["count"] += 1
        return True

# ───────────────────────────────────────────────────────────────────
# 문헌 기반 검수 (시연 웹 validate 1:1 포팅)
# ───────────────────────────────────────────────────────────────────
ENUMS = {
    "페르소나": ["일반국민", "기업 컴플라이언스 담당자", "논문 준비 학생"],
    "질문유형": ["제재중심", "법령중심", "유사사례", "통계기반", "시장영향"],
    "난이도": ["기초", "심화", "전문가"],
    "사건유형": ["담합", "하도급", "거래상지위", "표시광고", "전자상거래",
                "사업자단체", "가맹사업", "재판매가격", "부당지원", "부당고객유인"],
}
REQUIRED = ["ID", "페르소나", "질문유형", "난이도", "사건유형", "질문", "답변", "근거"]


def extract_amounts(text):
    s = set()
    if not text:
        return s
    t = re.sub(r"\s", "", str(text))
    # 각 패턴은 반드시 숫자로 시작 — "므로,만일"의 콤마처럼 숫자 없는 매칭(빈 문자열→int 오류) 방지
    for m in re.finditer(r"(\d[\d,]*)억", t):
        s.add(int(m.group(1).replace(",", "")) * 10**8)
    for m in re.finditer(r"(\d[\d,]*)백만", t):
        s.add(int(m.group(1).replace(",", "")) * 10**6)
    for m in re.finditer(r"(\d[\d,]*)만", t):
        v = int(m.group(1).replace(",", "")) * 10**4
        if v >= 10**4:
            s.add(v)
    for m in re.finditer(r"(\d[\d,]{3,})원", t):
        s.add(int(m.group(1).replace(",", "")))
    return s


def near(a, ss):
    return any(abs(a - g) / max(a, g, 1) < 0.02 for g in ss)


def validate(r):
    A = r.get("답변", "") or ""
    G = r.get("근거", "") or ""

    def has(p, s):
        return bool(re.search(p, s or ""))

    stages = []

    # 1단계 · 원문무결성
    c1 = []
    missing = [k for k in REQUIRED if not r.get(k) or str(r.get(k)).strip() == ""]
    if missing:
        c1.append({"lvl": "block", "code": "E1", "label": "필수필드 누락: " + ", ".join(missing), "std": "NIA 완전성"})
    else:
        c1.append({"lvl": "pass", "label": "필수필드 8종 모두 존재", "std": "NIA 완전성·ISO Completeness"})
    if not G or len(G.strip()) < 10:
        if "근거" not in missing:
            c1.append({"lvl": "block", "code": "E1", "label": "근거(원문 매칭) 누락", "std": "ISO Traceability"})
    else:
        c1.append({"lvl": "pass", "label": "근거 원문 매칭 존재 (출처 추적 가능)", "std": "ISO Traceability"})
    stages.append({"name": "1단계 · 원문무결성", "std": "NIA 완전성 · ISO 25012", "checks": c1})

    # 2단계 · 구조분해
    c2 = []
    enum_bad = False
    for k in ["페르소나", "질문유형", "난이도", "사건유형"]:
        if r.get(k) and str(r[k]).strip() not in ENUMS[k]:
            enum_bad = True
            c2.append({"lvl": "block", "code": "E3", "label": f'enum 위반: {k}="{r[k]}"', "std": "NIA 구문정확성"})
    if not enum_bad:
        c2.append({"lvl": "pass", "label": "페르소나·질문유형·난이도·사건유형 enum 정합", "std": "NIA 구문정확성·ISO Consistency"})
    grounded = (r.get("위반조문") and str(r["위반조문"]).strip()) or r.get("적용법령") or has(r"제\s?\d+\s?조|[가-힣]{2,}법", G)
    if grounded:
        lab = f'법적 근거 확인 (위반조문 {r["위반조문"]})' if r.get("위반조문") else "법적 근거 확인 (근거에 법령·조항 매칭)"
        c2.append({"lvl": "pass", "label": lab, "std": "ISO Compliance · 구조화 법리"})
    else:
        c2.append({"lvl": "block", "code": "E3", "label": "법적 근거 없음 (위반조문·법령 미확인)", "std": "ISO Compliance"})
    stages.append({"name": "2단계 · 구조분해", "std": "NIA 구문정확성 · ISO", "checks": c2})

    # 3단계 · 메타정합
    c3 = []
    art_ground = (r.get("위반조문") and str(r["위반조문"]).strip()) or has(r"제\s?\d+\s?조", G)
    if art_ground:
        c3.append({"lvl": "pass", "label": "조항 정합 (위반조문·근거 매칭)", "std": "NIA 의미정확성·ISO Accuracy"})
    else:
        c3.append({"lvl": "block", "code": "E3", "label": "조항 미확인 (위반조문·근거 없음)", "std": "NIA 의미정확성"})
    if r.get("질문유형") == "법령중심" and not has(r"제\s?\d+\s?조", A):
        c3.append({"lvl": "adv", "code": "E3", "label": "조항 명시 권장 (법령중심 답변에 조문 표기 없음)", "std": "NIA 의미정확성"})
    if has(r"위반", A) and has(r"무혐의|위반하지\s?않|해당하지\s?않", A):
        c3.append({"lvl": "block", "code": "E4", "label": "상반 판단 동시 출현", "std": "ISO Consistency"})
    else:
        c3.append({"lvl": "pass", "label": "판단 일관성 (상반 판단 없음)", "std": "ISO Consistency"})
    stages.append({"name": "3단계 · 메타정합", "std": "NIA 의미정확성 · ISO", "checks": c3})

    # 4단계 · 사실정합
    c4 = []
    if has(r"아마|추정되|것으로\s?보|일\s?것|예상되|짐작", A) and not has(r"아마|추정|예상", G):
        c4.append({"lvl": "block", "code": "E6", "label": "환각 (근거 없는 추론 표현)", "std": "NIST 600-1 Confabulation"})
    else:
        c4.append({"lvl": "pass", "label": "근거 범위 내 응답 (환각 없음)", "std": "NIST 600-1 Confabulation"})
    a_amt = extract_amounts(A)
    g_amt = extract_amounts(G)
    mism = [a for a in a_amt if not near(a, g_amt)]
    if g_amt and mism:
        c4.append({"lvl": "adv", "code": "E5", "label": "수치 확인 권장 (답변 금액을 근거에서 자동 확인 못 함)", "std": "NIST Integrity · 사람검수 보정"})
    else:
        c4.append({"lvl": "pass", "label": "금액 정합 (답변↔근거 일치)", "std": "NIST 600-1 Integrity"})
    under = False
    if r.get("질문유형") == "제재중심" and not has(r"과징금|시정명령|시정조치|과태료|처분|시정", A):
        under = True
    if r.get("질문유형") == "법령중심" and not has(r"제\s?\d+\s?조", A):
        under = True
    if len(re.sub(r"\s", "", A)) < 40:
        under = True
    if under:
        c4.append({"lvl": "adv", "code": "E8", "label": "분량·필수요소 보강 권장", "std": "NIA 유효성"})
    else:
        c4.append({"lvl": "pass", "label": "질문유형 필수요소·분량 충족", "std": "NIA 유효성"})
    stages.append({"name": "4단계 · 사실정합", "std": "NIST 600-1 · NIA 유효성", "checks": c4})

    # 5단계 · 활용성
    c5 = []
    if has(r"\d{6}-\d{7}|01\d-?\d{3,4}-?\d{4}|[\w.]+@[\w.]+\.[a-z]{2,}", A):
        c5.append({"lvl": "block", "code": "E10", "label": "개인정보 포함 (주민번호·연락처·이메일)", "std": "NIST 600-1 Data Privacy"})
    else:
        c5.append({"lvl": "pass", "label": "개인정보 미포함", "std": "NIST 600-1 Data Privacy"})
    jargon = len(re.findall(r"제\s?\d+\s?조|소정의|동법|시행령|구성요건|법리|판시|위법성|귀책", A))
    e7 = False
    if r.get("페르소나") == "일반국민" and jargon >= 3:
        e7 = True
    elif (r.get("페르소나") == "논문 준비 학생" or r.get("난이도") == "전문가" or r.get("페르소나") == "기업 컴플라이언스 담당자") and jargon == 0:
        e7 = True
    if e7:
        c5.append({"lvl": "adv", "code": "E7", "label": "페르소나 톤 다듬기 권장", "std": "NIA 다양성"})
    else:
        c5.append({"lvl": "pass", "label": "페르소나 톤·전문성 적합", "std": "NIA 다양성"})
    stages.append({"name": "5단계 · 활용성", "std": "NIST 600-1 · NIA", "checks": c5})

    block_n = sum(1 for s in stages for c in s["checks"] if c["lvl"] == "block")
    adv_n = sum(1 for s in stages for c in s["checks"] if c["lvl"] == "adv")
    tier = "부적합" if block_n > 0 else ("검토" if adv_n > 0 else "적합")
    return {"tier": tier, "blockN": block_n, "advN": adv_n, "stages": stages}


# ───────────────────────────────────────────────────────────────────
# PDF 텍스트 추출
# ───────────────────────────────────────────────────────────────────
def pdf_to_text(path):
    import pdfplumber
    parts = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            t = pg.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


# ───────────────────────────────────────────────────────────────────
# 5단 분해 (LLM)
# ───────────────────────────────────────────────────────────────────
DECOMPOSE_SYSTEM = """당신은 공정거래위원회 의결서를 분석해 AI 학습데이터로 구조화하는 전문가입니다.
주어진 의결서 본문을 읽고 아래 JSON 스키마로만 출력하세요. 설명·마크다운 없이 JSON만 출력합니다.

엄격 규칙:
- 모든 내용은 의결서 원문에 근거해야 하며, 원문에 없는 사실을 지어내지 마세요(환각 금지).
- evidence의 q는 의결서 원문에서 그대로 인용한 문장이어야 합니다.
- qa의 답변(a)은 반드시 근거(g) 범위 안에서 작성하고, "아마/추정/예상" 같은 추측 표현을 쓰지 마세요.
- 금액·조문은 원문과 정확히 일치시키세요(임의 변경 금지).

스키마:
{
  "title": "사건 전체 명칭",
  "short": "짧은 사건명(회사/단체명 위주, 12자 이내 권장)",
  "type": "담합|하도급|거래상지위|표시광고|전자상거래|사업자단체|가맹사업|재판매가격|부당지원|부당고객유인 중 정확히 하나",
  "law": "주요 적용 법률명(예: 공정거래법)",
  "article": "위반 조문(예: 공정거래법 제40조 제1항 제1호)",
  "source": "공정거래위원회 의결서",
  "facts": {"당사자": "", "기간": "", "행위": "", "피해규모": "", "피해범위": "", "요약": "2~3문장 요약"},
  "legal": {"세분류": "", "위반조문": "", "산업분야": "", "전제1": "적용 법조문 설명", "전제2": "본 사건의 요건 충족 설명", "결론": "위반 결론"},
  "sanction": {"처분유형": "", "처분결과": "", "근거조문": ""},
  "evidence": [{"f": "근거 대상(예: 행위/위법성/처분)", "cid": "", "h": "원문 위치(예: 이 유 > 1. 기초사실)", "q": "원문에서 그대로 인용한 문장"}],
  "qa": [{"ID": "001", "persona": "일반국민|기업 컴플라이언스 담당자|논문 준비 학생", "qtype": "제재중심|법령중심|유사사례|통계기반|시장영향", "diff": "기초|심화|전문가", "q": "질문", "a": "근거 범위 내 답변", "g": "답변의 근거가 되는 원문/사실 문장"}]
}

qa는 페르소나 3종을 고르게 포함해 6~9개 생성하세요.
- 일반국민 질문/답변: 법조문 용어를 줄이고 쉬운 말로.
- 논문 준비 학생·기업 컴플라이언스·전문가 난이도: 답변에 위반 조문(제○조)을 포함.
- 제재중심 답변에는 과징금/시정명령 등 처분을, 법령중심 답변에는 조문을 반드시 포함."""


MAX_TOKENS = int(os.environ.get("DM_MAX_TOKENS", "16000"))


def decompose(pdf_text):
    if len(pdf_text) > 60000:
        pdf_text = pdf_text[:60000]
    msg = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=DECOMPOSE_SYSTEM,
        messages=[{"role": "user", "content": "다음 공정거래위원회 의결서를 구조화하세요:\n\n" + pdf_text}],
    )
    # 출력이 max_tokens 한도에 걸려 잘리면 JSON이 깨진다 → 명확히 알린다.
    if getattr(msg, "stop_reason", "") == "max_tokens":
        raise ValueError(
            f"모델 출력이 토큰 한도({MAX_TOKENS})에 걸려 잘렸습니다. "
            "DM_MAX_TOKENS 를 키우거나 의결서가 너무 큰 경우입니다."
        )
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt).strip()
    # 모델이 앞뒤에 설명을 덧붙여도 가장 바깥 JSON 객체만 안전하게 추출.
    if not txt.startswith("{"):
        i = txt.find("{")
        if i != -1:
            txt = txt[i:]
    if not txt.endswith("}"):
        j = txt.rfind("}")
        if j != -1:
            txt = txt[: j + 1]
    # strict=False: 모델이 인용 원문에 그대로 넣은 줄바꿈·탭 등 제어문자를 허용(법령 인용에서 흔함)
    data = json.loads(txt, strict=False)
    data.setdefault("source", "공정거래위원회 의결서")
    data.setdefault("key", "case_" + str(int(time.time())))
    # qa ID 정규화(3자리 문자열)
    for i, q in enumerate(data.get("qa", []), 1):
        q["ID"] = str(q.get("ID") or i).zfill(3) if str(q.get("ID") or i).isdigit() else f"{i:03d}"
    return data


# ───────────────────────────────────────────────────────────────────
# 웹 서버
# ───────────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route("/")
def index():
    return send_file(INDEX_HTML)


@app.route("/api/decompose", methods=["POST"])
def api_decompose():
    # (1) 접근 토큰 — 설정된 경우에만 검사
    if ACCESS_TOKEN:
        tok = (request.args.get("t") or request.headers.get("X-Access-Token") or "").strip()
        if tok != ACCESS_TOKEN:
            return jsonify({"error": "접근 권한이 없습니다. 공유받은 링크(?t=…)로 접속해 주세요."}), 401
    # (2) IP당 분당 제한(스팸 방지)
    if not _rate_check_minute(_client_ip()):
        return jsonify({"error": f"요청이 너무 잦습니다. 분당 {RATE_PER_MIN}회까지 가능합니다. 잠시 후 다시 시도해 주세요."}), 429
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "PDF 파일이 없습니다."}), 400
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    path = tmp.name
    tmp.close()
    f.save(path)
    try:
        text = pdf_to_text(path)
        if len(text.strip()) < 100:
            return jsonify({"error": "PDF에서 텍스트를 거의 추출하지 못했습니다(스캔 이미지 PDF일 수 있음)."}), 422
        # (3) 전체 일일 총량(비용 상한) — 실제 LLM 호출 직전에만 카운트 (텍스트 없는 요청은 미차감)
        if not _rate_day_try():
            return jsonify({"error": f"오늘의 분해 한도({RATE_PER_DAY}회)를 모두 사용했습니다. 발표 운영자에게 문의해 주세요."}), 429
        t0 = time.time()
        data = decompose(text)
        data["_elapsed_sec"] = round(time.time() - t0, 1)
        return jsonify(data)
    except json.JSONDecodeError as e:
        return jsonify({"error": "모델 출력 JSON 파싱 실패: " + str(e)}), 502
    except Exception as e:
        return jsonify({"error": type(e).__name__ + ": " + str(e)}), 500
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@app.route("/api/validate", methods=["POST"])
def api_validate():
    return jsonify(validate(request.get_json(force=True)))


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print("[오류] 환경변수 ANTHROPIC_API_KEY 가 비어 있습니다. 키를 설정한 뒤 다시 실행하세요.")
        raise SystemExit(1)
    if not os.path.exists(INDEX_HTML):
        print(f"[경고] {INDEX_HTML} 을 찾지 못했습니다. server.py 와 같은 폴더에 두세요. (웹은 안 열리고 API만 동작)")
    print("──────────────────────────────────────────")
    print(" DecisionMiner 서버 실행")
    print(f" 포트: {PORT}  (host 0.0.0.0)")
    print(f" 분해 모델: {MODEL}")
    print(f" 안전장치: 분당 {RATE_PER_MIN}회/IP · 일일 {RATE_PER_DAY}회 총량 · 접근토큰 {'ON' if ACCESS_TOKEN else 'OFF'}")
    print("──────────────────────────────────────────")
    app.run(host="0.0.0.0", port=PORT, debug=False)
