# Step 4: 근거 매핑 (Evidence Mapping) — DecisionMiner 5단 분해 v1

> **버전**: v1 (Day 1, 4/27)
> **잠금 예정**: Day 2 v2 잠금 (#2)
> **출처**: PRD v2.3 § 7 (5단 컨셉)
> **v3.4 변경**: 없음 (v3.3 그대로 유지. 데이터셋 5종 메타는 Step 1·2에만 박음)
> **목표**: Step 1·2·3의 각 주장을 hybrid.json chunk에 매핑 → 13개 sub-claim 근거 + 1개 key_evidence
> **목표 길이**: 약 400자 (chunk 인용 50자 × 13개 + 메타)
> **선행 입력**: Step 1 (사실 추출) + Step 2 (법리 판단) + Step 3 (제재 정량화)
> **⚠️ 가장 중요한 원칙**: **페이지 번호 절대 사용 금지**. hybrid.json은 페이지 정보 없음.

---

## 📌 이 파일의 사용법

이 파일은 **5단 분해 Step 4를 실행할 때 LLM에게 그대로 전달하는 프롬프트 템플릿**이다.
실행 시 다음 네 변수가 채워진 상태로 전달:
- `{{hybrid_chunks}}` — hybrid.json의 chunk 리스트 (LangChain Document 형식)
- `{{facts}}` — Step 1 출력 JSON
- `{{legal}}` — Step 2 출력 JSON
- `{{sanction}}` — Step 3 출력 JSON

> ⚠️ **`{{pdf_text}}` 변수 없음**. hybrid_chunks가 PDF의 chunk화된 형태이므로 pdf_text는 불필요.

Cowork·Claude Code·API 호출 시 아래 "프롬프트 본문" 섹션을 그대로 사용.

---

## 🎯 프롬프트 본문 (LLM 전달용)

````
# 역할

당신은 공정거래 의결서 근거 추적 전문가다. 의결서를 사전 chunk화한 hybrid.json을 입력받아, 앞서 추출된 사실관계·법리·제재 결과의 각 주장이 의결서 어느 부분(chunk)에 근거하는지 정확히 매핑하는 것이 본 작업의 핵심이다.

본 작업의 가장 중요한 원칙은 **페이지 번호를 절대 사용하지 않는다**는 것이다. hybrid.json은 LangChain Document 리스트로 chunk 단위로 분할되어 있으며, 페이지 번호 정보를 포함하지 않는다. 근거 표기는 반드시 `chunk_id (Header § Header2)` 또는 `chunk_id [section]` 형식으로만 박는다.

당신의 출력은 후속 Step 5(페르소나 변환)의 핵심 입력이며, 학습데이터 17열 중 "근거_short"·"근거_원문" 컬럼의 직접 소스가 된다. chunk_id의 정확성이 곧 학습데이터의 검증 가능성이다.

---

# 작업 (Task)

입력으로 주어진 hybrid_chunks와 Step 1·2·3 결과를 분석하여, 각 주장의 근거를 4개 묶음으로 매핑하라.

**4개 매핑 묶음**:
1. `facts_evidence` — 사실관계 5요소(주체·상대방·시장·행위·결과) 각각의 근거 chunk
2. `legal_evidence` — 법리 4요소(법령·조문·위반유형·판단요건) 각각의 근거 chunk
3. `sanction_evidence` — 제재 3요소(처분종류·금액·기간) 각각의 근거 chunk (의결서 "주문" 섹션)
4. `key_evidence` — 사건 전체에서 가장 핵심이 되는 chunk **1개** + 선정 이유

각 sub-claim마다 **1~3개의 chunk** 매핑. 가장 관련성 높은 chunk를 우선.

---

# 입력

## hybrid_chunks (hybrid.json)
```json
{{hybrid_chunks}}
```

## facts (Step 1 출력)
```json
{{facts}}
```

## legal (Step 2 출력)
```json
{{legal}}
```

## sanction (Step 3 출력)
```json
{{sanction}}
```

---

# hybrid.json 스키마 (필수 이해)

hybrid.json은 LangChain Document 리스트다. 각 항목 구조:

```json
{
  "page_content": "이 chunk의 본문 텍스트 (수백 자)",
  "metadata": {
    "Header": "주문 또는 이유",
    "Header2": "1. 기초사실 등 (선택)",
    "section": "주문 또는 이유 (Header와 중복인 경우 다수)",
    "chunk_id": "DOC-<uuid>-CH-<번호>"
  }
}
```

## 핵심 인지 사항

| 항목 | 박음 | 비박음 |
|---|---|---|
| 페이지 번호 | ❌ **절대 없음** | "p.12", "12쪽" 등 추측 금지 |
| `chunk_id` | ✅ 고유 식별자 (`DOC-xxxxx-CH-NNN`) | 임의 생성 ❌ |
| `Header` | ✅ 1차 섹션 (주문/이유/...) | — |
| `Header2` | ⚠️ 선택 (있으면 박음, 없으면 생략) | 추측 금지 |
| `section` | ✅ 보조 섹션 (Header와 동일한 경우 다수) | — |

## 근거 표기 형식 (강제)

다음 두 형식 중 1개로만:

1. **권장 (Header2 있을 때)**: `chunk_id (Header § Header2)`
   - 예: `"DOC-184d-CH-005 (이유 § 2. 인정사실)"`
2. **대체 (Header2 없을 때)**: `chunk_id [section]`
   - 예: `"DOC-184d-CH-001 [주문]"`

`(Header § Header2)` 또는 `[section]` 외 형식 ❌. 페이지 번호·줄 번호 ❌.

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

대부분 `Header="이유"`, `Header2="1. 기초사실"` 또는 `"2. 인정사실"`에 위치.

## 2. legal_evidence — 4개 sub-claim

| sub-claim | 매핑 대상 |
|---|---|
| `법령` | 적용 법령명 명시 chunk |
| `조문` | 조문 번호 명시 chunk |
| `위반유형` | 위반 유형(법적 분류명) chunk |
| `판단요건` | 위반 판단 요건 분석 chunk |

대부분 `Header="이유"`, `Header2="3. 법령의 적용"` 또는 `"4. 위반행위 인정"`에 위치.

## 3. sanction_evidence — 3개 sub-claim

| sub-claim | 매핑 대상 |
|---|---|
| `처분종류` | 시정명령·과징금·고발 등 명시 chunk |
| `금액` | 과징금 액수 명시 chunk |
| `기간` | 시정명령 이행 기간·행위 금지 기간 chunk |

**반드시** `Header="주문"` 섹션에서만 매핑. 본문 "이유"의 산정표 ❌.

## 4. key_evidence — 1개

사건 전체를 가장 잘 대표하는 chunk **1개** 선정. 보통:
- 위반행위 핵심 묘사 chunk (`이유 § 2. 인정사실` 또는 `이유 § 위반행위`)
- 또는 처분 결정 chunk (`주문` 1항)

선정 기준: "이 chunk만 보면 사건의 본질을 70% 이상 파악 가능한가?"

---

# 핵심 원칙 (반드시 준수)

## 원칙 1 — 페이지 번호 절대 금지 ⚠️ 최우선
- "p.12", "12쪽", "페이지 12", "page 12" 등 모든 페이지 표기 금지
- hybrid.json에 페이지 정보 없음. 추측·창작 금지
- 위반 시 출력 무효

## 원칙 2 — chunk_id 화이트리스트 강제
- 입력 hybrid_chunks에 **실제 존재하는** chunk_id만 사용
- 임의 생성·추측 ❌ (예: `DOC-184d-CH-099`가 입력에 없으면 사용 ❌)
- chunk_id 형식이 `DOC-<uuid>-CH-<번호>` 패턴이라도 입력에 없으면 ❌

## 원칙 3 — 매핑 1~3개 제한
- 각 sub-claim당 chunk 1~3개
- 0개 ❌ (매칭 불가 시 `"매칭 불가"` 명시 + 사유)
- 4개 이상 ❌ (가장 관련성 높은 3개로 압축)

## 원칙 4 — 의미 기반 매칭
- 단순 키워드 매칭 X. **의미적 일치** 우선
- 예: facts.주체="에스피피조선(주)" → 회사명·피심인 명시 + 법인격 설명 chunk
- 예: facts.행위="단가 일방 인하" → "정당한 사유 없이 인하" 묘사 chunk
- 동의어·유사 표현 OK (예: "감액" ↔ "인하" ↔ "낮추다")

## 원칙 5 — 근거_원문 50자 이내 인용
- `근거_원문` 필드: chunk page_content의 핵심 문장 1~2개 발췌
- 50자 이내 (그 이상은 chunk 자체 참조)
- 원문 그대로 (창작·요약 ❌, 단 줄임표 `...` 허용)

## 원칙 6 — sanction_evidence는 "주문" 섹션 전용
- `Header="주문"` chunk만 매핑
- 본문 "이유" 섹션의 과징금 산정표는 매핑 ❌
- Step 3과 동일 원칙

## 원칙 7 — JSON 스키마 강제
- 출력은 반드시 아래 "출력 스키마"의 키 구조 그대로
- chunk 매핑은 항상 배열 (1개여도 `[{...}]`)

---

# Few-shot 예시 (1건 — 에스피피조선)

## 입력 (요약 표시)

### hybrid_chunks (5개 발췌, 실제는 51개)
```json
[
  {
    "page_content": "피심인 에스피피조선(주)는 선박 블록 제작을 영위하는 사업자이며, 12개 수급사업자에게 ... 선박 부품 제조를 위탁하였다.",
    "metadata": {
      "Header": "이유",
      "Header2": "1. 기초사실",
      "section": "이유",
      "chunk_id": "DOC-184d-CH-005"
    }
  },
  {
    "page_content": "피심인은 위 기간 동안 발주 후 단가를 7~15% 인하하여 정당한 사유 없이 단가를 일방적으로 인하하여 총 4억 8,300만 원의 하도급대금을 부당하게 감액하였다.",
    "metadata": {
      "Header": "이유",
      "Header2": "2. 위반행위",
      "section": "이유",
      "chunk_id": "DOC-184d-CH-018"
    }
  },
  {
    "page_content": "하도급법 제11조 제1항: 원사업자는 ... 정당한 사유 없이 하도급대금을 감액해서는 아니 된다.",
    "metadata": {
      "Header": "이유",
      "Header2": "3. 법령의 적용",
      "section": "이유",
      "chunk_id": "DOC-184d-CH-031"
    }
  },
  {
    "page_content": "1. 피심인 에스피피조선(주)는 다음과 같이 시정하라. 가. ... 나. 피심인은 이 명령을 받은 날부터 60일 이내에 ... 통지하여야 한다.",
    "metadata": {
      "Header": "주문",
      "Header2": null,
      "section": "주문",
      "chunk_id": "DOC-184d-CH-001"
    }
  },
  {
    "page_content": "2. 피심인 에스피피조선(주)에 과징금 480,000,000원을 부과한다.",
    "metadata": {
      "Header": "주문",
      "Header2": null,
      "section": "주문",
      "chunk_id": "DOC-184d-CH-002"
    }
  }
]
```

### Step 1·2·3 결과 (요약)
```json
{
  "facts": {
    "주체": "에스피피조선(주)",
    "상대방": "12개 수급사업자",
    "시장": "선박부품제조",
    "행위": "발주 후 단가를 7~15% 일방 인하",
    "결과": "총 4억 8,300만 원 부당감액"
  },
  "legal": {
    "법령": "하도급법",
    "조문": "제11조 제1항",
    "위반유형": "부당한 하도급대금의 감액",
    "판단요건": ["정당한 사유 없을 것", "사후적 일방 감액일 것"]
  },
  "sanction": {
    "처분종류": ["시정명령", "과징금"],
    "금액": 480000000,
    "기간": "이 명령을 받은 날부터 60일 이내"
  }
}
```

## 출력 (JSON)

```json
{
  "facts_evidence": {
    "주체": [
      {
        "chunk_id": "DOC-184d-CH-005",
        "Header": "이유",
        "Header2": "1. 기초사실",
        "근거_원문": "피심인 에스피피조선(주)는 선박 블록 제작을 영위하는 사업자이며..."
      }
    ],
    "상대방": [
      {
        "chunk_id": "DOC-184d-CH-005",
        "Header": "이유",
        "Header2": "1. 기초사실",
        "근거_원문": "...12개 수급사업자에게 ... 선박 부품 제조를 위탁하였다."
      }
    ],
    "시장": [
      {
        "chunk_id": "DOC-184d-CH-005",
        "Header": "이유",
        "Header2": "1. 기초사실",
        "근거_원문": "...선박 블록 제작을 영위하는 사업자... 선박 부품 제조를 위탁..."
      }
    ],
    "행위": [
      {
        "chunk_id": "DOC-184d-CH-018",
        "Header": "이유",
        "Header2": "2. 위반행위",
        "근거_원문": "...발주 후 단가를 7~15% 인하하여 정당한 사유 없이 단가를 일방적으로 인하..."
      }
    ],
    "결과": [
      {
        "chunk_id": "DOC-184d-CH-018",
        "Header": "이유",
        "Header2": "2. 위반행위",
        "근거_원문": "...총 4억 8,300만 원의 하도급대금을 부당하게 감액하였다."
      }
    ]
  },
  "legal_evidence": {
    "법령": [
      {
        "chunk_id": "DOC-184d-CH-031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "하도급법 제11조 제1항: 원사업자는 ... 하도급대금을 감액해서는 아니 된다."
      }
    ],
    "조문": [
      {
        "chunk_id": "DOC-184d-CH-031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "하도급법 제11조 제1항: 원사업자는..."
      }
    ],
    "위반유형": [
      {
        "chunk_id": "DOC-184d-CH-031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "...정당한 사유 없이 하도급대금을 감액해서는 아니 된다."
      }
    ],
    "판단요건": [
      {
        "chunk_id": "DOC-184d-CH-031",
        "Header": "이유",
        "Header2": "3. 법령의 적용",
        "근거_원문": "...정당한 사유 없이 하도급대금을 감액..."
      }
    ]
  },
  "sanction_evidence": {
    "처분종류": [
      {
        "chunk_id": "DOC-184d-CH-001",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "1. 피심인 에스피피조선(주)는 다음과 같이 시정하라."
      },
      {
        "chunk_id": "DOC-184d-CH-002",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "2. 피심인 에스피피조선(주)에 과징금 480,000,000원을 부과한다."
      }
    ],
    "금액": [
      {
        "chunk_id": "DOC-184d-CH-002",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "...과징금 480,000,000원을 부과한다."
      }
    ],
    "기간": [
      {
        "chunk_id": "DOC-184d-CH-001",
        "Header": "주문",
        "Header2": null,
        "근거_원문": "...이 명령을 받은 날부터 60일 이내에 ... 통지하여야 한다."
      }
    ]
  },
  "key_evidence": {
    "chunk_id": "DOC-184d-CH-018",
    "Header": "이유",
    "Header2": "2. 위반행위",
    "근거_원문": "...발주 후 단가를 7~15% 인하하여 ... 총 4억 8,300만 원의 하도급대금을 부당하게 감액하였다.",
    "선정이유": "위반행위(일방 단가 인하)와 결과(4억 8,300만 원 감액)를 한 chunk에 모두 담음. 사건 본질 70% 이상 파악 가능."
  }
}
```

## 위 예시의 박음 포인트

- **chunk_id 재사용 OK**: `DOC-184d-CH-005`가 facts.주체·상대방·시장 모두에 등장 (1 chunk가 다수 sub-claim 근거가 될 수 있음)
- **legal_evidence 4개 sub-claim 모두 같은 chunk** (`CH-031`): 법령의 적용 섹션은 보통 단일 chunk에 응축
- **sanction_evidence는 "주문" chunk만**: `CH-001`(시정명령)·`CH-002`(과징금) 두 개의 주문 chunk
- **Header2 null 처리**: 주문 섹션은 보통 Header2 없음 → `null` 박음 (생략 X)
- **근거_원문 50자 내외** + 줄임표(`...`) 활용해 핵심 발췌
- **key_evidence**: 위반행위 + 결과를 모두 담은 `CH-018` 선정. `선정이유` 명시

---

# 출력 스키마 (JSON 강제)

LLM은 반드시 아래 구조로만 출력한다. JSON 외 텍스트(서두·후미 설명) 금지.

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
    "법령":     [{"chunk_id": "string", "Header": "string", "Header2": "string|null", "근거_원문": "string ≤50자"}],
    "조문":     [{}],
    "위반유형": [{}],
    "판단요건": [{}]
  },
  "sanction_evidence": {
    "처분종류": [{"chunk_id": "string", "Header": "주문", "Header2": "string|null", "근거_원문": "string ≤50자"}],
    "금액":     [{}],
    "기간":     [{}]
  },
  "key_evidence": {
    "chunk_id": "string",
    "Header": "string",
    "Header2": "string|null",
    "근거_원문": "string ≤50자",
    "선정이유": "string (왜 이 chunk가 사건 본질을 가장 잘 담았는지, 1~2문장)"
  }
}
```

---

# 자동 검증 룰 (출력 후 자가 점검)

LLM은 출력 직전 다음을 스스로 점검:

- [ ] **모든 chunk_id가 입력 hybrid_chunks에 실제 존재** (화이트리스트 강제)
- [ ] 모든 `Header` 값이 입력 hybrid_chunks의 해당 chunk_id metadata와 일치
- [ ] 페이지 번호 표기 0건 (`p.`, `쪽`, `page`, 숫자만 등)
- [ ] `facts_evidence`의 5 sub-claim 모두 존재 (주체·상대방·시장·행위·결과)
- [ ] `legal_evidence`의 4 sub-claim 모두 존재 (법령·조문·위반유형·판단요건)
- [ ] `sanction_evidence`의 3 sub-claim 모두 존재 (처분종류·금액·기간)
- [ ] **`sanction_evidence`의 모든 chunk의 `Header == "주문"`** (강제)
- [ ] 각 sub-claim의 chunk 배열 길이 1~3 (0 또는 4+ ❌)
- [ ] `key_evidence`는 단일 객체 (배열 ❌)
- [ ] 모든 `근거_원문` ≤ 50자 (한글 기준)
- [ ] `근거_원문`이 해당 chunk의 page_content에 실제 등장 (창작 0건)
- [ ] `Header2` 값이 chunk metadata와 일치 (없으면 `null`)
- [ ] JSON 외 텍스트 0건

검증 실패 시 출력 재구성.

---

# 예외 처리

## 케이스 1 — 매칭 chunk 없음
- 입력 hybrid_chunks에 해당 sub-claim의 근거가 명확히 없을 시
- 해당 sub-claim 배열을 `[{"chunk_id": "매칭 불가", "Header": null, "Header2": null, "근거_원문": "<사유: 예) 의결서 본문에 시장 획정 섹션 부재>"}]` 박음
- ⚠️ **자주 발생**: 시장(`facts.시장`)이 의결서에 명시 안 된 경우
- ⚠️ **드물게 발생**: 판단요건(`legal.판단요건`)이 일반론 추론이라 직접 chunk 없음

## 케이스 2 — Header2 없음
- chunk metadata에 `Header2` 키가 없거나 `null`인 경우 (주문 섹션에서 흔함)
- 출력의 `Header2`도 `null`로 박음 (빈 문자열 `""` ❌)
- 근거 표기는 `chunk_id [section]` 형식 사용

## 케이스 3 — 1 chunk가 다수 sub-claim의 근거
- 같은 chunk_id를 여러 sub-claim에 박는 것 OK (예: `CH-005`가 주체·상대방·시장 모두)
- 단, `근거_원문`은 sub-claim마다 다른 부분 발췌 (해당 sub-claim 관련 문장)

## 케이스 4 — 다수 chunk가 1 sub-claim의 근거
- 위반행위가 여러 chunk에 걸쳐 있을 시
- 가장 핵심 chunk 1개 + 보조 chunk 1~2개 (총 3개 이내)
- 첫 번째 chunk가 가장 관련성 높음 (정렬 기준: 의미적 일치도)

## 케이스 5 — sanction_evidence에 "이유" chunk 잘못 매핑
- 본문 "이유"의 과징금 산정표에 매력적인 표현이 있어도 ❌
- 반드시 `Header="주문"` chunk만 사용
- 검증 룰 위반 시 출력 재구성

## 케이스 6 — chunk_id 형식 의심
- 입력 hybrid_chunks의 chunk_id가 예상 형식 (`DOC-xxxxx-CH-NNN`)과 다를 수 있음
- 입력의 실제 형식을 그대로 사용 (예: `chunk-001`, `id_5` 등도 입력대로)
- 형식 정규화 ❌

## 케이스 7 — key_evidence 후보 다수
- 사건 본질을 잘 담은 chunk가 2~3개 보일 때
- 우선순위:
  1. 위반행위 + 결과를 한 chunk에 담은 것 (`이유 § 위반행위`)
  2. 위반행위만 담은 것 (`이유 § 인정사실`)
  3. 처분 결정 (`주문` 1항)
- 동률 시 위반행위 chunk 우선 (제재 chunk보다 사건 본질에 가까움)

````

---

## 📋 실행 시 체크리스트 (사용자용)

이 프롬프트를 LLM에 전달하기 전:

- [ ] `{{hybrid_chunks}}` 자리에 hybrid.json 전체 내용 (51개 정도)
- [ ] `{{facts}}` 자리에 Step 1 출력
- [ ] `{{legal}}` 자리에 Step 2 출력
- [ ] `{{sanction}}` 자리에 Step 3 출력
- [ ] LLM 모델: **Sonnet 4.6 권장** (Step 4는 chunk 매칭이 핵심, 추론 부담 보통)
- [ ] hybrid_chunks 토큰 수 확인 (51 chunks × 평균 500자 = 약 25K 토큰. context window 충분)

LLM 출력 받은 후 (이 검증은 사용자 측 코드로 자동화 권장):

- [ ] JSON 파싱 정상
- [ ] **모든 chunk_id가 hybrid.json에 실제 존재** (Python set 비교)
  ```python
  hybrid_ids = {c['metadata']['chunk_id'] for c in hybrid_chunks}
  output_ids = extract_all_chunk_ids(output_json)
  assert output_ids.issubset(hybrid_ids), f"환각 chunk_id: {output_ids - hybrid_ids}"
  ```
- [ ] 페이지 번호 표기 0건 (정규식 `r'p\.\s*\d+|쪽|페이지'` 검사)
- [ ] sanction_evidence의 모든 Header가 "주문"
- [ ] 13 sub-claim + 1 key_evidence 모두 존재
- [ ] 결과 저장: `04_raw_outputs/<사건키>/evidence.json`

---

## 🔗 다음 Step

- **Step 5 (페르소나 변환)** — `step5_persona.md` 참조
  - 입력: 본 Step 4의 evidence.json + Step 1·2·3 결과 + metadata
  - 출력: 45개 Q&A (페르소나 3 × 질문유형 5 × 난이도 3)
  - 각 Q&A의 `근거_short` 필드는 본 Step 4의 chunk_id 그대로 인용

---

## 📜 변경 이력

| 버전 | 일자 | 변경 |
|---|---|---|
| v1 | 2026-04-27 | 최초 작성. 4개 매핑 묶음(13 sub-claim + 1 key) + chunk_id 화이트리스트 강제 |
| v2 (예정) | 2026-04-28 | Day 2 정제 후 잠금 (#2). 매칭 불가 케이스 처리 강화 |

---

> 💡 **잠금 안내**: 본 v1은 Day 1 작성용 초안. Day 2에 v2 정제 거쳐 잠금. v2 잠금 후엔 minor patch(v2.1)만 허용.

> ⚠️ **5단 중 가장 까다로운 단계**: 페이지 번호 추측이 가장 흔한 환각. 자동 검증 룰 + 사용자 측 코드 검증 둘 다 필수.

> 🔗 **연쇄 의존성**: Step 4가 잘못되면 Step 5의 45개 Q&A 전체의 `근거_short` 필드가 신뢰 불가. 검수 우선순위 최고.
