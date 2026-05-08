"""
DecisionMiner quality_checker.py v2.4
규칙 기반 1차 자동 품질진단 엔진

v2.4 변경: 1)확인필요→Gold불가 2)warning_flags컬럼 3)gen_note확인필요mapping 4)run_all자동검증 5)summary warning통계 6)strict클래스저장
"""
import argparse, csv, json, os, re, sys
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Optional

CASE_TYPE_ENUM = ["담합","하도급","거래상지위","표시광고","전자상거래","사업자단체","가맹사업","부당고객유인","부당지원","재판매가격","기타"]
LAW_ALIASES = {"공정거래법":"독점규제 및 공정거래에 관한 법률","독점규제법":"독점규제 및 공정거래에 관한 법률","독점규제및공정거래에관한법률":"독점규제 및 공정거래에 관한 법률","독점규제 및 공정거래에 관한 법률":"독점규제 및 공정거래에 관한 법률","하도급법":"하도급거래 공정화에 관한 법률","하도급거래공정화에관한법률":"하도급거래 공정화에 관한 법률","하도급거래 공정화에 관한 법률":"하도급거래 공정화에 관한 법률","표시광고법":"표시·광고의 공정화에 관한 법률","표시·광고의 공정화에 관한 법률":"표시·광고의 공정화에 관한 법률","표시광고의공정화에관한법률":"표시·광고의 공정화에 관한 법률","전자상거래법":"전자상거래 등에서의 소비자보호에 관한 법률","전자상거래등에서의소비자보호에관한법률":"전자상거래 등에서의 소비자보호에 관한 법률","가맹사업법":"가맹사업거래의 공정화에 관한 법률","가맹사업거래의공정화에관한법률":"가맹사업거래의 공정화에 관한 법률","대규모유통업법":"대규모유통업에서의 거래 공정화에 관한 법률","대규모유통업에서의거래공정화에관한법률":"대규모유통업에서의 거래 공정화에 관한 법률","대리점법":"대리점거래의 공정화에 관한 법률","대리점거래공정화에관한법률":"대리점거래의 공정화에 관한 법률","대리점거래의공정화에관한법률":"대리점거래의 공정화에 관한 법률"}
MAIN_LAWS = set(LAW_ALIASES.values())
LEGAL_TERMS = ["부당공동행위","시장지배적지위","불공정거래행위","기업결합","과징금","시정명령","시정권고","경고","고발","합의","담합","카르텔","입찰담합","가격담합","거래거절","차별적취급","부당염매","끼워팔기","재판매가격유지행위","사업자단체","원사업자","수급사업자","하도급대금","부당감액","부당반품","기술탈취","기만적광고","부당표시","비교광고","추천보증","가맹본부","가맹점사업자","가맹금","영업지역","정보공개서","가맹계약","통신판매","청약철회","소비자피해보상","위반행위","행위요건","효과요건","부당성","경쟁제한성","소비자이익침해","공정거래저해","관련시장","시장획정","시장점유율","피심인","신고인","이해관계인","전원회의","소회의","약식절차","구성요건","포섭","비례성","선례","판례","법리","인용","기각","각하","취소소송","행정소송","과징금부과처분","시정조치","동의의결","자진시정","감면","리니언시","부당이득","위법성","공동행위","합의추정","정황증거","간접증거","직접증거"]
PERSONA_VALID = {"일반국민","기업 컴플라이언스 담당자","논문 준비 학생"}
QTYPE_VALID = {"제재중심","법령중심","유사사례","통계기반","시장영향"}
LEVEL_VALID = {"기초","심화","전문가"}
JUDGMENT_PATTERNS = [r"위법하다고\s*판단",r"위반이\s*인정된다",r"위반에\s*해당한다",r"부당성이\s*인정된다",r"위법성이\s*인정",r"공정거래를\s*저해할\s*우려",r"경쟁을\s*제한하는",r"소비자\s*이익을\s*현저히\s*저해"]
SANCTION_KEYWORDS = ["과징금","시정명령","시정권고","경고","고발","과태료","동의의결"]
OVERINFERENCE_KEYWORDS = ["시장에 미치는 영향","시장 전체에","산업 전반에","의도적으로","고의로","고의성","소비자 피해 확대","소비자 피해가 심각","경제적 파급","사회적 파급"]
POSITIVE_JUDGMENT = ["위반이 인정","위법성이 인정","부당성이 인정","해당한다","위반으로 판단"]
NEGATIVE_JUDGMENT = ["인정되지","해당하지 않","위반이 아니","무혐의","인정할 수 없"]
PII_FATAL = [r"\d{6}[-]\d{7}",r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}",r"0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}",r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",r"\d{3,4}[-]\d{4}[-]\d{4}[-]\d{4}"]
PII_WARN = [r"\d{3}[-]\d{2}[-]\d{5}"]
CASE_NUMBER_PATTERN = re.compile(r"\d{4}[가-힣]+\d+")
LAW_ARTICLE_PATTERN = re.compile(r"제\d+조(?:\s*제?\d+항)?")
LENGTH_MATRIX = {("일반국민","기초"):(50,200),("일반국민","심화"):(100,300),("일반국민","전문가"):(150,450),("기업 컴플라이언스 담당자","기초"):(100,300),("기업 컴플라이언스 담당자","심화"):(200,450),("기업 컴플라이언스 담당자","전문가"):(300,650),("논문 준비 학생","기초"):(150,400),("논문 준비 학생","심화"):(250,600),("논문 준비 학생","전문가"):(400,850)}

def strip_particles(w):
    for p in ["에서는","에서의","에게는","으로는","에서도","에서","에게","으로","로서","부터","까지","였다","했다","됐다","된다","한다","이다","하고","하여","에는","은","는","이","가","을","를","의","에","로","와","과","도","만","뿐","든","요","며","고","서","면","지"]:
        if w.endswith(p) and len(w) > len(p)+1: return w[:-len(p)]
    return w

def extract_money_numbers(text):
    """억/만/천/원 단위 금액만 원 단위로 정규화하여 반환."""
    nums = set()
    UNIT_MULT = {"억":100000000, "만":10000, "천":1000, "원":1}
    for m in re.finditer(r"(\d[\d,]*)\s*(억|만|천|원)", text):
        raw = m.group(1).replace(",", "")
        unit = m.group(2)
        try: nums.add(str(int(raw) * UNIT_MULT[unit]))
        except ValueError: nums.add(raw)
    return nums

def extract_other_numbers(text):
    """날짜(YYYYMM)/%/건/개(!월)/명/4자리 이상 정수."""
    nums = set()
    for m in re.finditer(r"(\d[\d,]*)\s*(%|건|개(?!월)|명)", text):
        nums.add(m.group(1).replace(",", ""))
    for m in re.finditer(r"(\d{4})[.년/]\s*(\d{1,2})", text):
        nums.add(f"{m.group(1)}{m.group(2).zfill(2)}")
    for m in re.finditer(r"\b(\d{4,})\b", text):
        nums.add(m.group(1))
    return nums

def keyword_overlap(a,b,min_len=2):
    if not a or not b: return 0.0
    wa = {strip_particles(w) for w in re.findall(r"[가-힣a-zA-Z0-9]+",a) if len(w)>=min_len}
    wb = {strip_particles(w) for w in re.findall(r"[가-힣a-zA-Z0-9]+",b) if len(w)>=min_len}
    wa = {w for w in wa if len(w)>=min_len}; wb = {w for w in wb if len(w)>=min_len}
    return len(wa&wb)/len(wa) if wa else 0.0

def jaccard_sim(a,b):
    wa = {strip_particles(w) for w in re.findall(r"[가-힣a-zA-Z0-9]+",a) if len(w)>=2}
    wb = {strip_particles(w) for w in re.findall(r"[가-힣a-zA-Z0-9]+",b) if len(w)>=2}
    wa = {w for w in wa if len(w)>=2}; wb = {w for w in wb if len(w)>=2}
    return len(wa&wb)/len(wa|wb) if (wa and wb) else 0.0

def count_legal_terms(t): return sum(1 for term in LEGAL_TERMS if term in t)
def legal_term_ratio(t):
    words = re.findall(r"[가-힣]+",t)
    return sum(1 for w in words if any(tm in w for tm in LEGAL_TERMS))/len(words) if words else 0.0
def broken_char_ratio(t): return sum(1 for c in t if c in "\ufffd\x00")/len(t) if t else 1.0
def normalize_law(n):
    c = n.replace(" ","").replace("·","").replace("ㆍ","")
    for a,s in LAW_ALIASES.items():
        if a.replace(" ","").replace("·","")==c: return s
    return n

class QualityChecker:
    REQUIRED_COLS = ["ID","사건키","사건유형","페르소나","난이도","질문유형","질문","답변","핵심키워드","적용법령","적용조문","처분결과","근거","Confidence_Score","검수자_평가","비고","문제점_및_해결방안"]

    def __init__(self, data, inv=None, strict=False):
        self.data = data; self.inv = inv or {}; self.results = []; self.strict = strict; self._validated = False

    def validate_cols(self, strict=None):
        if strict is None: strict = self.strict
        if not self.data: raise ValueError("QA 데이터 비어있음")
        cols = set(self.data[0].keys())
        miss = [c for c in self.REQUIRED_COLS if c not in cols]
        if miss and strict:
            raise ValueError(f"필수 17컬럼 누락: {', '.join(miss)}")
        if miss:
            print(f"  ⚠️ 누락 컬럼 {len(miss)}개: {', '.join(miss)} → 빈값 처리")
            for r in self.data:
                for c in miss: r.setdefault(c,"")
        self._validated = True

    def detect_case_errors(self, groups):
        errs = defaultdict(lambda:{"s2":[],"s4":[]})
        for ck, items in groups.items():
            rows = [r for _,r in items]
            types = set(r.get("사건유형","").strip() for r in rows if r.get("사건유형","").strip())
            if len(types)>1:
                for i,_ in items: errs[i]["s2"].append(f"E2:동일사건_사건유형_불일치({','.join(types)})")
            laws = set(normalize_law(r.get("적용법령","").strip()) for r in rows if r.get("적용법령","").strip())
            if len(laws)>2:
                for i,_ in items: errs[i]["s2"].append(f"확인필요:동일사건_법령_다수({len(laws)}종)")
            best_dup = defaultdict(float)
            for a in range(len(items)):
                ia,ra = items[a]; qa = ra.get("질문","")
                for b in range(a+1,len(items)):
                    ib,rb = items[b]; qb = rb.get("질문","")
                    s = jaccard_sim(qa,qb)
                    # 공통 토큰 수 조건 (v2.3)
                    wa = {strip_particles(w) for w in re.findall(r"[가-힣a-zA-Z0-9]+",qa) if len(w)>=2}
                    wb = {strip_particles(w) for w in re.findall(r"[가-힣a-zA-Z0-9]+",qb) if len(w)>=2}
                    common = len({w for w in wa if len(w)>=2} & {w for w in wb if len(w)>=2})
                    if s > 0.85 and common >= 5:
                        best_dup[ia] = max(best_dup[ia], s)
                        best_dup[ib] = max(best_dup[ib], s)
            for idx, sim in best_dup.items():
                errs[idx]["s4"].append(f"E9:중복질문({sim:.0%})")
        return errs

    def stg1(self, r):
        sc=15; er=[]
        ck = r.get("사건키","")
        if not ck: sc-=3; er.append("E1:사건번호_불일치")
        elif not (CASE_NUMBER_PATTERN.search(ck) or (len(ck)>=10 and re.search(r"[가-힣]",ck))): sc-=3; er.append("E1:사건번호_불일치")
        for f in ["사건유형","적용법령","처분결과"]:
            if not r.get(f,"").strip(): sc-=1; er.append(f"E1:{f}_누락")
        if not ck.strip(): sc-=1; er.append("E1:사건키_누락")
        ev = r.get("근거","")
        if not ev or len(ev)<50: sc-=5; er.append("E1:evidence_50자미만")
        elif broken_char_ratio(ev)>0.05: sc-=3; er.append("E1:깨진문자")
        rt = r.get("raw_text","")
        if rt and len(rt)<1000: sc-=2; er.append("E1:raw_text_부족")
        if self.inv and ck and ck not in self.inv: sc-=3; er.append("E1:PDF_불일치")
        return max(0,sc), er

    def stg2(self, r, ce):
        sc=20; er=[]
        miss = [f for f in ["질문","답변","근거","페르소나","질문유형","난이도"] if not r.get(f,"").strip()]
        if miss: sc-=min(4,len(miss)); er.append(f"E2:필수필드_누락({','.join(miss)})")
        ans=r.get("답변",""); qt=r.get("질문유형","")
        if qt in ("통계기반","유사사례"):
            jc = sum(1 for p in JUDGMENT_PATTERNS if re.search(p,ans))
            if jc>=3: sc-=2; er.append(f"확인필요:판단표현_과다({jc})")
        law=r.get("적용법령",""); art=r.get("적용조문","")
        if law.strip():
            nl = normalize_law(law)
            if nl not in MAIN_LAWS and nl==law: er.append(f"확인필요:주요법령외({law})")
        else: sc-=4; er.append("E3:법령명_미검출")
        if art.strip() and not LAW_ARTICLE_PATTERN.search(art): sc-=2; er.append("E3:조항_불일치")
        san=r.get("처분결과","")
        if not san.strip(): sc-=4; er.append("E2:조치결과_없음")
        elif not any(k in san for k in SANCTION_KEYWORDS): sc-=2; er.append("확인필요:조치키워드_불명확")
        if ce:
            e2e = [e for e in ce if e.startswith("E")]
            if e2e: sc-=4
            er.extend(ce)
        return max(0,sc), er

    def stg3(self, r):
        sc=15; er=[]
        ct=r.get("사건유형","")
        if ct not in CASE_TYPE_ENUM: sc-=5; er.append(f"E3:사건유형_enum({ct})")
        p=r.get("페르소나",""); q=r.get("질문유형",""); l=r.get("난이도","")
        if p not in PERSONA_VALID: sc-=2; er.append(f"E3:페르소나_enum({p})")
        if q not in QTYPE_VALID: sc-=2; er.append(f"E3:질문유형_enum({q})")
        if l not in LEVEL_VALID: sc-=1; er.append(f"E3:난이도_enum({l})")
        return max(0,sc), er

    def stg4(self, r, dup):
        sc=35; er=[]; q=r.get("질문",""); a=r.get("답변",""); ev=r.get("근거","")
        ps=r.get("페르소나",""); lv=r.get("난이도",""); qt=r.get("질문유형","")
        # 4-1
        qm = keyword_overlap(q,ev)
        if qm<0.1: sc-=3; er.append(f"확인필요:질문매칭낮음({qm:.0%})")
        elif qm<0.2: sc-=1; er.append(f"확인필요:질문매칭주의({qm:.0%})")
        # 4-2
        k=(ps,lv)
        if k in LENGTH_MATRIX:
            mn,mx = LENGTH_MATRIX[k]; al=len(a)
            if al<mn*0.5: sc-=4; er.append(f"E8:답변과소({al}자)")
            elif al<mn: sc-=2; er.append(f"확인필요:답변짧음({al}자)")
            elif al>mx*1.5: sc-=2; er.append(f"확인필요:답변과장({al}자)")
        # 4-3a 금액 일치 → E5:금액불일치 (근거에 금액이 있을 때만 검사)
        am_money = extract_money_numbers(a); ev_money = extract_money_numbers(ev)
        if am_money and ev_money:
            um_money = am_money - ev_money
            if len(um_money) >= 1: sc-=6; er.append(f"E5:금액불일치({len(um_money)}개)")
        # 4-3b 기타 수치 (날짜/%/건/명) → 확인필요만
        an_other = extract_other_numbers(a); ev_other = extract_other_numbers(ev)
        if an_other:
            um_other = an_other - ev_other
            if len(um_other) >= 3: er.append(f"확인필요:수치확인({len(um_other)}개)")
        # 4-4 페르소나
        tr=legal_term_ratio(a); tc=count_legal_terms(a)
        if ps=="일반국민" and tr>0.15: sc-=4; er.append(f"E7:일반국민_전문어과다({tr:.0%})")
        elif ps=="논문 준비 학생":
            if not(r.get("적용법령","") in a or LAW_ARTICLE_PATTERN.search(a) or any(k in a for k in SANCTION_KEYWORDS)) and tc<2:
                sc-=4; er.append("E7:전문가용_요소부재")
        elif ps=="기업 컴플라이언스 담당자" and tc<1: sc-=2; er.append("E7:기업용_전문어부족")
        # 4-5 중복
        if dup: sc-=4; er.extend(dup)
        # 4-6 답변-근거 (핵심키워드 보강) — 종합서술형 질문유형은 스킵
        if qt not in ("유사사례","시장영향","통계기반"):
            am=keyword_overlap(a + " " + r.get("핵심키워드",""), ev)
            if am<0.05: er.append(f"확인필요:답변매칭_낮음({am:.0%})")
            elif am<0.15: er.append(f"확인필요:답변매칭_주의({am:.0%})")
        # 4-7 구조
        if qt=="제재중심" and not any(k in a for k in SANCTION_KEYWORDS): sc-=3; er.append("E8:제재_처분없음")
        elif qt=="법령중심" and not LAW_ARTICLE_PATTERN.search(a): sc-=3; er.append("E8:법령_조문없음")
        # E4 판단왜곡
        hp=any(p in a for p in POSITIVE_JUDGMENT); hn=any(n in a for n in NEGATIVE_JUDGMENT)
        if hp and hn: sc-=5; er.append("E4:상반판단_동시출현")
        asnc={k for k in SANCTION_KEYWORDS if k in a}; esnc={k for k in SANCTION_KEYWORDS if k in ev}
        if asnc and esnc and not(asnc&esnc): sc-=1; er.append("확인필요:처분유형_evidence차이")
        # E6
        for kw in OVERINFERENCE_KEYWORDS:
            if kw in a and kw not in ev: sc-=3; er.append(f"E6:과잉추론({kw})"); break
        # E10
        ft=" ".join(str(v) for v in r.values())
        for p in PII_FATAL:
            if re.search(p,ft): er.append("E10:개인정보"); break
        for p in PII_WARN:
            if re.search(p,ft): er.append("확인필요:사업자등록번호"); break
        return max(0,sc), er

    def stg5(self, rows):
        sc=15; n=len(rows)
        if n==0: return 0
        ps=Counter(r.get("페르소나","") for r in rows if r.get("페르소나","") in PERSONA_VALID)
        ls=Counter(r.get("난이도","") for r in rows if r.get("난이도","") in LEVEL_VALID)
        qs=Counter(r.get("질문유형","") for r in rows if r.get("질문유형","") in QTYPE_VALID)
        e3=n/3; e5=n/5
        pd=sum(abs(ps.get(p,0)-e3) for p in PERSONA_VALID)/n
        ld=sum(abs(ls.get(l,0)-e3) for l in LEVEL_VALID)/n
        qd=sum(abs(qs.get(q,0)-e5) for q in QTYPE_VALID)/n
        if pd>0.3: sc-=4
        elif pd>0.15: sc-=2
        if ld>0.3: sc-=4
        elif ld>0.15: sc-=2
        if qd>0.3: sc-=4
        elif qd>0.15: sc-=2
        ic=sum(1 for r in rows if len(r.get("질문",""))<10 or not re.search(r"[은는이가을를에서]",r.get("질문","")))
        if ic>n*0.3: sc-=3
        elif ic>n*0.1: sc-=1
        return max(0,sc)

    def judge(self, total, errs):
        ec = set(e.split(":")[0] for e in errs if e.startswith("E") and ":" in e)
        has_warning = any(e.startswith("확인필요:") for e in errs)
        if "E10" in ec: return "탈락"
        sv=len(ec & {"E4","E5","E6"}); mn=len(ec & {"E7","E8","E9"})
        if total>=80 and sv==0 and mn==0 and not has_warning: return "Gold"
        elif total>=80 and sv==0: return "보정필요"
        elif total>=60 and sv<=1: return "보정필요"
        return "탈락"

    def gen_note(self, errs):
        notes=[]; seen=set()
        mapping={"E7:일반국민":"전문용어→쉬운표현","E7:전문가용":"법령·조문·처분 추가","E7:기업용":"전문용어 보강","E5:답변매칭":"답변 근거 재검토","E5:수치":"숫자·금액 원문 대조","E4:상반판단":"판단표현 일관성 정리","E6:":"과잉추론 표현 삭제","E8:답변과소":"답변 길이 보강","E8:제재":"처분내용 명시","E8:법령":"조문인용 추가","E9:":"유사질문 차별화","E3:법령_비표준":"법령 정식명칭 통일","E1:":"원문 데이터 보강","E2:동일사건":"사건 내 메타데이터 통일","확인필요:질문매칭":"질문-근거 연결성 검토","확인필요:답변짧음":"답변 길이 기준 검토","확인필요:답변과장":"답변 과장 여부 검토","확인필요:처분유형":"처분유형 차이 확인","확인필요:사업자등록번호":"사업자등록번호 공개 여부 확인","확인필요:주요법령외":"주요 법령 외 법령 확인","확인필요:조치키워드":"처분결과 표기 확인","확인필요:판단표현":"사실-판단 혼재 여부 확인"}
        for e in errs:
            for k,v in mapping.items():
                if k in e and k not in seen: seen.add(k); notes.append(v); break
        return " / ".join(notes)

    def run_all(self):
        if not self._validated: self.validate_cols()
        groups = defaultdict(list)
        for i,r in enumerate(self.data): groups[r.get("사건키",f"unk_{i}")].append((i,r))
        ce = self.detect_case_errors(groups)
        s5s = {ck:self.stg5([r for _,r in items]) for ck,items in groups.items()}
        results=[]
        for i,r in enumerate(self.data):
            ck=r.get("사건키",f"unk_{i}"); ae=[]
            s1,e1=self.stg1(r); ae.extend(e1)
            s2,e2=self.stg2(r,ce[i]["s2"]); ae.extend(e2)
            s3,e3=self.stg3(r); ae.extend(e3)
            s4,e4=self.stg4(r,ce[i]["s4"]); ae.extend(e4)
            s5=s5s.get(ck,15); tot=s1+s2+s3+s4+s5
            ec=sorted(set(e.split(":")[0] for e in ae if e.startswith("E") and ":" in e))
            wf=sorted(set(e.split("(")[0] for e in ae if e.startswith("확인필요:")))
            jd=self.judge(tot,ae)
            cn=self.gen_note(ae) if jd in ("보정필요","탈락") else ""
            if jd=="탈락" and cn: cn = "[재생성 권장] " + cn
            results.append({"사건키":ck,"QA_ID":r.get("ID",f"QA_{i+1:04d}"),"score_total":tot,"score_stage1":s1,"score_stage2":s2,"score_stage3":s3,"score_stage4":s4,"score_stage5":s5,"error_codes":",".join(ec),"warning_flags":",".join(wf),"error_details":" | ".join(ae),"judgment":jd,"correction_note":cn})
        self.results=results; return results

    def summary(self):
        if not self.results: return {}
        n=len(self.results); jd=Counter(r["judgment"] for r in self.results); sc=[r["score_total"] for r in self.results]
        er=sum(1 for r in self.results if r["error_codes"])
        sv=sum(1 for r in self.results if (set(r["error_codes"].split(",")) if r["error_codes"] else set()) & {"E4","E5","E6","E10"})
        wr=sum(1 for r in self.results if r.get("warning_flags",""))
        ac=[]; [ac.extend(r["error_codes"].split(",")) for r in self.results if r["error_codes"]]
        aw=[]; [aw.extend(r["warning_flags"].split(",")) for r in self.results if r.get("warning_flags","")]
        return {"total":n,"gold":jd.get("Gold",0),"correction":jd.get("보정필요",0),"rejected":jd.get("탈락",0),"gold_rate":f"{jd.get('Gold',0)/n*100:.1f}%","avg_score":f"{sum(sc)/n:.1f}","min_score":min(sc),"max_score":max(sc),"error_rate":f"{er/n*100:.1f}%","severe_error_rate":f"{sv/n*100:.1f}%","warning_rate":f"{wr/n*100:.1f}%","top_errors":Counter(ac).most_common(10),"top_warnings":Counter(aw).most_common(10)}

def load_csv(p):
    for e in["utf-8-sig","utf-8","cp949","euc-kr"]:
        try:
            with open(p,"r",encoding=e) as f: return list(csv.DictReader(f))
        except(UnicodeDecodeError,UnicodeError): continue
    raise ValueError(f"CSV 인코딩 실패: {p}")

def load_inv(p):
    return {r.get("사건키","").strip():True for r in load_csv(p) if r.get("사건키","").strip() and r.get("PDF있음","")=="Y"}

def save_results(res,p):
    if not res: return
    with open(p,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(res[0].keys())); w.writeheader(); w.writerows(res)

def main():
    pa=argparse.ArgumentParser(description="DecisionMiner 품질진단 v2.4")
    pa.add_argument("--input",required=True); pa.add_argument("--inventory",default=None); pa.add_argument("--output",default="qc_result.csv"); pa.add_argument("--strict",action="store_true",help="필수 컬럼 누락 시 중단")
    a=pa.parse_args()
    print("="*60+"\nDecisionMiner 규칙 기반 1차 자동 품질진단 엔진 v2.4\n"+"="*60)
    print(f"\n[1/4] 로드: {a.input}"); d=load_csv(a.input); print(f"  → {len(d)}건")
    inv={}
    if a.inventory: print(f"[1/4] Inventory: {a.inventory}"); inv=load_inv(a.inventory); print(f"  → {len(inv)}건")
    print(f"\n[2/4] 5단계 품질진단..."); c=QualityChecker(d,inv,strict=a.strict); r=c.run_all(); print(f"  → {len(r)}건 완료")
    print(f"\n[3/4] 저장: {a.output}"); save_results(r,a.output)
    print(f"\n[4/4] 요약"); s=c.summary()
    print(f"  총:{s['total']} 평균:{s['avg_score']} Gold:{s['gold']}({s['gold_rate']}) 보정:{s['correction']} 탈락:{s['rejected']}")
    print(f"  오류율:{s['error_rate']} 중대:{s['severe_error_rate']} 확인필요율:{s['warning_rate']}")
    print(f"  오류 TOP 5:")
    for cd,ct in s["top_errors"][:5]: print(f"    {cd}: {ct}건")
    if s["top_warnings"]:
        print(f"  확인필요 TOP 5:")
        for cd,ct in s["top_warnings"][:5]: print(f"    {cd}: {ct}건")
    print(f"\n✅ 완료: {a.output}")

if __name__=="__main__": main()
