# Step 4: 근거 매핑 (Evidence Mapping) — DecisionMiner 5단 분해 v2

> **버전**: v2 (Day 2, 4/28 잠금 #2)
> **선행 버전**: v1 (4/27)
> **출처**: PRD v2.3 § 7
> **목표**: Step 1·2·3의 각 주장을 hybrid.json chunk에 매핑 → 13개 sub-claim 근거 + 1개 key_evidence
> **선행 입력**: Step 1·2·3 모든 결과 + hybrid.json (chunk 리스트)
> **⚠️ 가장 중요한 원칙**: **페이지 번호 절대 사용 금지** (hybrid.json 페이지 정보 없음)

---

## 🔄 v1 → v2 변경 이력

| 항목 | v1 | v2 |
|---|---|---|
| chunk_id 형식 | `DOC-<uuid>-CH-<번호>` | **`{사건키}_{3자리숫자}` 강제** (예: `에스피피조선_018`) |
| 페이지 번호 | 금지 | **금지 명시 강화** (hybrid.json에 없음 명문화) |
| 근거 매핑 수 | 각 sub-claim 1~3개 | **각 sub-claim 1~3개 + 전체 서로 다른 chunk_id ≥ 3개** (다양성 강제) |
| 값 없음 처리 | 매칭 불가 일부 빈 | **`"매칭 불가"` 명시 강제** |
| Few-shot | 에스피피조선 1건 | **에스피피조선 1건 유지** |

---

## 📌 사용법

전달 변수:
- `{{사건키}}` — 본 사건의 사건키 (chunk_id 형식 강제용, v2 추가)
- `{{hybrid_chunks}}` — hybrid.json의 chunk 리스트
- `{{facts}}`, `{{legal}}`, `{{sanction}}`

> ⚠️ **`{{pdf_text}}` 변수 없음**. hybrid_chunks가 PDF chunk화 형태.

---

## 🎯 프롬프트 본문 (LLM 전달용)

````
# 역할

당신은 공정거래 의결서 근거 추적 전문가다. 사전 chunk화한 hybrid.json을 입력받아, 앞서 추출된 사실관계·법리·제재의 각 주장이 의결서 어느 부분(chunk)에 근거하는지 정확히 매핑하는 것이 본 작업의 핵심이다.

가장 중요한 원칙은 **페이지 번호를 절대 사용하지 않는다**. hybrid.json은 LangChain Document 리스트로 chunk 단위로 분할되어 있으며, **페이지 번호 정보를 포함하지 않는다**. 근거 표기는 반드시 `chunk_id (Header § Header2)` 또는 `chunk_id [section]` 형식으로만.

본 프롬프트는 **공정거래 11종 사건유형 모두**에 작동: 담합 / 하도급 / 거래상지위 / 표시광고 / 전자상거래 / 사업자단체 / 가맹사업 / 부당고객유인 / 부당지원 / 재판매가격 / 기타.

---

# 작업 (Task)

hybrid_chunks와 Step 1·2·3 결과를 분석하여, 각 주장의 근거를 4개 묶음으로 매핑하라.

**4개 매핑 묶음**:
1. `facts_evidence` — 사실관계 5요소 근거 (주체·상대방·시장·행위·결과)
2. `legal_evidence` — 법리 4요소 근거 (법령·조문·위반유형·판단요건)
3. `sanction_evidence` — 제재 3요소 근거 (처분유형·과징금액·기간) — **"주문" 섹션만**
4. `key_evidence` — 사건 전체 핵심 chunk **1개** + 선정 이유

---

# 입력

## 사건키 (chunk_id 형식 강제용)
```
{{사건키}}
```
> 본 변수는 chunk_id 형식 정규화 시 사용. 예: `에스피피조선`이면 chunk_id는 `에스피피조선_001`, `에스피피조선_002` 형식.

## hybrid_chunks
```json
{{hybrid_chunks}}
```

## facts (Step 1)
```json
{{facts}}
```

## legal (Step 2)
```json
{{legal}}
```

## sanction (Step 3)
```json
{{sanction}}
```

---

# hybrid.json 스키마

각 항목 구조:

```json
{
  "page_content": "이 chunk의 본문 텍스트",
  "metadata": {
    "Header": "주문 또는 이유",
    "Header2": "1. 기초사실 등 (선택)",
    "section": "주문 또는 이유",
    "chunk_id": "..."
  }
}
```

## ⭐ chunk_id 형식 강제 (v2)

**입력 hybrid_chunks의 chunk_id를 다음 형식으로 정규화하여 출력**:

```
{사건키}_{3자리숫자}
```

예시:
- `에스피피조선_001`
- `에스피피조선_018`
- `A건설_005`
- `삼성전자_023`

> 입력 hybrid_chunks의 chunk_id가 다른 형식(예: `DOC-184d-CH-018`)이면 → 입력 순서대로 1번부터 3자리 zero-padding으로 매핑.
> 입력에 이미 `{사건키}_{3자리}` 형식으로 박혀있으면 그대로 사용.

## ⛔ 페이지 번호 절대 금지 (v2 강조)

| 항목 | 박음 | 비박음 |
|---|---|---|
| 페이지 번호 | ❌ **hybrid.json에 절대 없음** | "p.12", "12쪽", "페이지 12", "page 12" 등 추측 ❌ |
| `chunk_id` | ✅ `{사건키}_{3자리숫자}` 형식 | 임의 생성 ❌ |
| `Header` | ✅ 1차 섹션 (주문/이유) | — |
| `Header2` | ⚠️ 선택 (있으면 박음, 없으면 `null`) | 추측 ❌ |

## 근거 표기 형식 (강제)

다음 두 형식 중 1개로만:

1. **권장 (Header2 있을 때)**: `{사건키}_NNN (Header § Header2)`
   - 예: `"에스피피조선_005 (이유 § 1. 기초사실)"`
2. **대체 (Header2 없을 때)**: `{사건키}_NNN [section]`
   - 예: `"에스피피조선_001 [주문]"`

페이지 번호·줄 번호 ❌.

---

# 매핑 대상 (총 13개 sub-claim + 1 key)

## 1. facts_evidence — 5개 sub-claim

| sub-claim | 매핑 대상 |
|---|---|
| `주체` | 피심인 회사명·법인격 명시 chunk |
| `상대방` | 피해자 그룹·수 명시 chunk |
| `시장` | 산업분야·관련시장 설명 chunk |
| `행위` | 위반행위 묘사 chunk (이유 섹션) |
| `결과` | 피해 금액·기간 명시 chunk |

대부분 `Header="이유"`, `Header2="1. 기초사실"` 또는 `"2. 인정사실"`.

## 2. legal_evidence — 4개 sub-claim

| sub-claim | 매핑 대상 |
|---|---|
| `법령` | 적용 법령명 명시 chunk |
| `조문` | 조문 번호 명시 chunk |
| `위반유형` | 위반 유형(법적 분류명) chunk |
| `판단요건` | 위반 판단 요건 분석 chunk |

대부분 `Header="이유"`, `Header2="3. 법령의 적용"` 또는 `"4. 위반행위 인정"`.

## 3. sanction_evidence — 3개 sub-claim

| sub-claim | 매핑 대상 |
|---|---|
| `처분유형` | 시정명령·과징금·고발 명시 chunk |
| `과징금액` | 과징금 액수 명시 chunk |
| `기간` | 시정명령 이행 기간 chunk |

**반드시** `Header="주문"` 섹션에서만 매핑. 본문 "이유"의 산정표 ❌.

## 4. key_evidence — 1개

사건 전체를 가장 잘 대표하는 chunk **1개** 선정.

---

# 핵심 원칙

## 원칙 1 — 페이지 번호 절대 금지 ⚠️ 최우선
- hybrid.json에 페이지 정보 없음. 추측·창작 ❌
- "p.", "쪽", "페이지" 표기 시 출력 무효

## 원칙 2 — chunk_id 형식 강제 (v2)
- 형식: `{사건키}_{3자리숫자}` (예: `에스피피조선_018`)
- 입력 hybrid_chunks의 chunk_id가 다른 형식이면 → 입력 순서대로 1번부터 3자리 zero-padding으로 매핑
- 입력에 없는 chunk_id 임의 생성 ❌

## 원칙 3 — 매핑 1~3개 + 다양성 ≥ 3개 (v2 강화)
- 각 sub-claim당 chunk **1~3개** (매칭 가능한 경우)
- 매칭 불가 시: `[{"chunk_id": "매칭 불가", "Header": null, "Header2": null, "근거_원문": "<사유>"}]` 명시 강제 (빈 배열 ❌)
- ⭐ **전체 출력에서 서로 다른 chunk_id가 최소 3개 이상** (모든 sub-claim에 같은 chunk 1개만 박는 것 방지)

## 원칙 4 — 의미 기반 매칭
- 단순 키워드 X. 의미적 일치 우선
- 동의어·유사 표현 OK (예: "감액" ↔ "인하" ↔ "낮추다")

## 원칙 5 — 근거_원문 50자 이내 인용
- chunk page_content의 핵심 문장 1~2개 발췌
- 50자 이내 + 줄임표(`...`) 허용
- 원문 그대로 (창작·요약 ❌)

## 원칙 6 — sanction_evidence는 "주문" 섹션 전용
- `Header="주문"` chunk만 매핑
- 본문 "이유"의 과징금 산정표 ❌

## 원칙 7 — JSON 스키마 강제
- 키 누락·추가 ❌
- chunk 매핑은 항상 배열 (1개여도 `[{...}]`)
- Header2 없으면 `null` (빈 문자열 ❌)

---

# Few-shot 예시 (1건 — 에스피피조선)

## 입력 (요약)

### 사건키
```
에스피피조선
```

### hybrid_chunks (5개 발췌, 실제는 51개)
```json
[
  {
    "page_content": "피심인 에스피피조선(주)는 선박 블록 제작을 영위하는 사업자이며, 12개 수급사업자에게 ... 선박 부품 제조를 위탁하였다.",
    "metadata": {
      "Header": "이유",
      "Header2": "1. 기초사실",
      "section": "이유",
      "chunk_id": "에스피피조선_005"
    }
  },
  {
    "page_content": "피심인은 위 기간 동안 발주 후 단가를 7~15% 인하하여 정당한 사유 없이 단가를 일방적으로 인하하여 총 4억 8,300만 원의 하도급대금을 부당하게 감액하였다.",
    "metadata": {
      "Header": "이유",
      "Header2": "2. 위반행위",
      "section": "이유",
      "chunk_id": "에스피피조선_018"
    }
  },
  {
    "page_content": "하도급법 제11조 제1항: 원사업자는 ... 정당한 사유 없이 하도급대금을 감액해서는 아니 된다.",
    "metadata": {
      "Header": "이유",
      "Header2": "3. 법령의 적용",
      "section": "이유",
      "chunk_id": "에스피피조선_031"
    }
  },
  {
    "page_content": "1. 피심인 에스피피조선(주)는 다음과 같이 시정하라. 가. ... 나. 피심인은 이 명령을 받은 날부터 60일 이내에 ... 통지하여야 한다.",
    "metadata": {
      "Header": "주문",
      "Header2": null,
      "section": "주문",
      "chunk_id": "에스피피조선_001"
    }
  },
  {
    "page_content": "2. 피심인 에스피피조선(주)에 과징금 480,000,000원을 부과한다.",
    "metadata": {
      "Header": "주문",
      "Header2": null,
      "section": "주문",
      "chunk_id": "에스피피조선_002"
    }
  }
]
```

## 출력 (JSON, 일부 발췌)

```json
{
  "facts_evidence": {
    "주체": [
      {
        "chunk_id": "에스피피조선_005",
        "Header": "이유",
        "Header2": "1. 기초사실",
        "근거_원문": "피심인 에스피피조선(주)는 선박 블록 제작을 영위하는 사업자이며..."
      }
    ],
    "상대방": [
      {
        "chunk_id": "에스피피조선_005",
        "Header": "이유",
        "Header2": "1. 기초사실",
        "근거_원문": "...12개 수급사업자에게 ... 선박 부품 제조를 위탁하였다."
      }
    ],
    "시장": [
      {
        "chunk_id": "에스피피조선_005",
        "Header": "이유",
        "Header2": "1. 기초사실",
        "근거_원문": "...선박 블록 제작을 영위하는 사업자... 선박 부품 제조를 위탁..."
      }
    ],
    "행위": [
      {
        "chunk_id": "에스피피조선_018",
        "Header": "이유",
        "Header2": "2. 위반행위",
        "근거_원문": "...발주 후 단가를 7~15% 인하하여 정당한 사유 없이 단가를 일방적으로 인하..."
      }
    ],
    "결과": [
      {
        "chunk_id": "에스피피조선_018",
        "Header": "이유",
        "Header2": "2. 위반행위",
        "근거_원문": "...총 4억 8,300만 원의 하도급대금을 부당하게 감액하였다."
      }
    ]
  },
  "legal_evidence": {
    "법령": [
      {
        "chunk_id": "에스피피조선_031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "하도급법 제11조 제1항: 원사업자는 ... 하도급대금을 감액해서는 아니 된다."
      }
    ],
    "조문": [
      {
        "chunk_id": "에스피피조선_031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "하도급법 제11조 제1항: 원사업자는..."
      }
    ],
    "위반유형": [
      {
        "chunk_id": "에스피피조선_031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "...정당한 사유 없이 하도급대금을 감액해서는 아니 된다."
      }
    ],
    "판단요건": [
      {
        "chunk_id": "에스피피조선_031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "...정당한 사유 없이 하도급대금을 감액..."
      }
    ]
  },
  "sanction_evidence": {
    "처분유형": [
      {
        "chunk_id": "에스피피조선_001",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "1. 피심인 에스피피조선(주)는 다음과 같이 시정하라."
      },
      {
        "chunk_id": "에스피피조선_002",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "2. 피심인 에스피피조선(주)에 과징금 480,000,000원을 부과한다."
      }
    ],
    "과징금액": [
      {
        "chunk_id": "에스피피조선_002",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "...과징금 480,000,000원을 부과한다."
      }
    ],
    "기간": [
      {
        "chunk_id": "에스피피조선_001",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "...이 명령을 받은 날부터 60일 이내에 ... 통지하여야 한다."
      }
    ]
  },
  "key_evidence": {
    "chunk_id": "에스피피조선_018",
    "Header": "이유",
    "Header2": "2. 위반행위",
    "근거_원문": "...발주 후 단가를 7~15% 인하하여 ... 총 4억 8,300만 원의 하도급대금을 부당하게 감액하였다.",
    "선정이유": "위반행위(일방 단가 인하)와 결과(4억 8,300만 원 감액)를 한 chunk에 모두 담음. 사건 본질 70% 이상 파악 가능."
  }
}
```

## 박음 포인트
- **chunk_id 형식**: `에스피피조선_005` (`{사건키}_{3자리}` 강제)
- **chunk_id 다양성 검증**: 출력에서 서로 다른 chunk_id = `_005, _018, _031, _001, _002` = **5개 ≥ 3개** ✅
- **chunk_id 재사용 OK**: `_005`가 주체·상대방·시장에 등장 (1 chunk가 다수 sub-claim 근거)
- **sanction_evidence 모두 `Header="주문"`**: `_001`(시정명령)·`_002`(과징금)
- **Header2 null 처리**: 주문 섹션 → `null` (빈 문자열 ❌)
- **근거_원문 50자 내외** + 줄임표(`...`)

---

# 출력 스키마 (JSON 강제)

```json
{
  "facts_evidence": {
    "주체":   [{"chunk_id": "string", "Header": "string", "Header2": "string|null", "근거_원문": "string ≤50자"}],
    "상대방": [{}],
    "시장":   [{}],
    "행위":   [{}],
    "결과":   [{}]
  },
  "legal_evidence": {
    "법령":     [{...}],
    "조문":     [{}],
    "위반유형": [{}],
    "판단요건": [{}]
  },
  "sanction_evidence": {
    "처분유형": [{...}],
    "과징금액": [{}],
    "기간":     [{}]
  },
  "key_evidence": {
    "chunk_id": "string",
    "Header": "string",
    "Header2": "string|null",
    "근거_원문": "string ≤50자",
    "선정이유": "string (1~2문장)"
  }
}
```

JSON 외 텍스트 금지.

---

# 자가 검증 룰

## chunk_id 검증 (v2 강화)
- [ ] **모든 chunk_id가 `{사건키}_{3자리숫자}` 형식** (정규식 `^.+_\d{3}$`)
- [ ] **모든 chunk_id가 입력 hybrid_chunks에 실제 존재** (화이트리스트)
- [ ] **출력 전체에서 서로 다른 chunk_id ≥ 3개** (다양성 강제) ⭐

## 페이지 번호 검증
- [ ] 페이지 번호 표기 0건 (정규식 `r'p\.\s*\d+|쪽|페이지'` 검사)
- [ ] "p.12", "12쪽" 등 표기 0건

## 구조 검증
- [ ] `facts_evidence` 5 sub-claim 모두 존재 (주체·상대방·시장·행위·결과)
- [ ] `legal_evidence` 4 sub-claim 모두 존재 (법령·조문·위반유형·판단요건)
- [ ] `sanction_evidence` 3 sub-claim 모두 존재 (처분유형·과징금액·기간)
- [ ] **`sanction_evidence` 모든 chunk의 `Header == "주문"`** (강제)
- [ ] 각 sub-claim chunk 배열 길이 1~3
- [ ] `key_evidence`는 단일 객체 (배열 ❌)

## 메타 검증
- [ ] 모든 `Header` 값이 입력 hybrid_chunks의 metadata와 일치
- [ ] `Header2` 값이 chunk metadata와 일치 (없으면 `null`, 빈 문자열 ❌)
- [ ] 모든 `근거_원문` ≤ 50자 (한글 기준)
- [ ] `근거_원문`이 해당 chunk의 page_content에 실제 등장 (창작 0건)
- [ ] JSON 외 텍스트 0건

검증 실패 시 출력 재구성.

---

# 예외 처리

## 케이스 1 — 매칭 chunk 없음
- 해당 sub-claim 배열을 다음과 같이 박음:
  ```json
  [{"chunk_id": "매칭 불가", "Header": null, "Header2": null, "근거_원문": "<사유: 예) 의결서 본문에 시장 획정 섹션 부재>"}]
  ```
- 빈 배열 ❌. **반드시 `"매칭 불가"` 명시**
- 자주 발생: 시장(`facts.시장`)이 의결서에 명시 안 된 경우
- 매칭 불가가 많아도 다양성 ≥ 3개 검증은 다른 sub-claim에서 충족 필요

## 케이스 2 — Header2 없음
- chunk metadata에 `Header2` 키가 없거나 `null` (주문 섹션에서 흔함)
- 출력 `Header2`도 `null` (빈 문자열 `""` ❌)
- 근거 표기는 `chunk_id [section]` 형식

## 케이스 3 — 1 chunk가 다수 sub-claim의 근거
- 같은 chunk_id 재사용 OK
- 단, `근거_원문`은 sub-claim마다 다른 부분 발췌

## 케이스 4 — sanction_evidence에 "이유" chunk 잘못 매핑
- 본문 "이유"의 산정표 매력적이어도 ❌
- 반드시 `Header="주문"` chunk만

## 케이스 5 — chunk_id 형식 불일치
- 입력 hybrid_chunks의 chunk_id가 `{사건키}_{3자리}` 형식이 아닌 경우
  - 입력 순서대로 1번부터 3자리 zero-padding으로 매핑
  - 예: 51개 chunk → `{사건키}_001` ~ `{사건키}_051`
- 본 매핑은 일관되게 유지 (출력 전체 동일 매핑 사용)

## 케이스 6 — key_evidence 후보 다수
- 우선순위:
  1. 위반행위 + 결과를 한 chunk에 담은 것 (`이유 § 위반행위`)
  2. 위반행위만 담은 것 (`이유 § 인정사실`)
  3. 처분 결정 (`주문` 1항)
- 동률 시 위반행위 chunk 우선
````

---

## 📋 사용자 체크리스트

전달 전:
- [ ] `{{사건키}}` 채움 (chunk_id 형식 강제용)
- [ ] `{{hybrid_chunks}}` 채움 (51개 정도)
- [ ] `{{facts}}`, `{{legal}}`, `{{sanction}}` 채움
- [ ] LLM: Sonnet 4.6 권장

출력 후 (사용자 측 코드 검증 권장):

```python
import re, json
from collections import Counter

evidence = json.load(open('evidence.json'))

# 1. chunk_id 형식 검증
def all_chunk_ids(d):
    ids = []
    for k, v in d.items():
        if k == 'chunk_id': ids.append(v)
        elif isinstance(v, dict): ids.extend(all_chunk_ids(v))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict): ids.extend(all_chunk_ids(item))
    return ids

ids = all_chunk_ids(evidence)
pattern = re.compile(r'^.+_\d{3}$')
non_format = [i for i in ids if i != '매칭 불가' and not pattern.match(i)]
assert not non_format, f"형식 위반: {non_format}"

# 2. 다양성 ≥ 3개
unique_ids = set(i for i in ids if i != '매칭 불가')
assert len(unique_ids) >= 3, f"다양성 부족: {unique_ids}"

# 3. 페이지 번호 0건
text = json.dumps(evidence, ensure_ascii=False)
assert not re.search(r'p\.\s*\d+|쪽|페이지', text), "페이지 번호 박힘"

# 4. sanction_evidence 모두 Header="주문"
for sub in evidence['sanction_evidence'].values():
    for item in sub:
        if item['chunk_id'] != '매칭 불가':
            assert item['Header'] == '주문', f"sanction에 비-주문 chunk: {item}"

print("✅ Step 4 검증 통과")
```

- [ ] 저장: `04_raw_outputs/<사건키>/evidence.json`

---

## 📜 변경 이력

| 버전 | 일자 | 변경 |
|---|---|---|
| v1 | 2026-04-27 | 최초 작성 (DOC-uuid-CH-NNN 형식) |
| **v2** | **2026-04-28** | **잠금 #2. chunk_id `{사건키}_{3자리}` 형식 + 다양성 ≥ 3개 + 페이지 금지 강화** |

> ⚠️ **5단 중 가장 까다로운 단계**: 페이지 번호 추측 + chunk_id 형식 불일치가 가장 흔한 환각.

> 🔗 **연쇄 의존성**: Step 4가 잘못되면 Step 5 45개 Q&A의 `근거_short` 전체 신뢰 불가.
