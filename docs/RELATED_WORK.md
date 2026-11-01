# 관련 연구와 현재 구현의 관계

기존 공모전 결과서의 비교 참조 데이터셋을 원문 링크로 연결했습니다. 아래 내용은 질적 설계 비교입니다. 모델 성능의 동일 조건 비교 실험은 아직 없습니다.

| 논문·자원 | 이 프로젝트에서 검토할 관점 | 현재 상태 |
| --- | --- | --- |
| [LBOX OPEN: A Multi-Task Benchmark for Korean Legal Language Understanding and Judgement Prediction](https://arxiv.org/abs/2206.05224) (NeurIPS 2022 Datasets and Benchmarks) | 한국어 법률 문서를 분류·판단·요약 과제로 구성하는 방법 | 기존 제출문서가 인용한 비교 자원. 공정위 의결서와 판결문의 원천 차이를 구분 |
| [KBL: Developing a Pragmatic Benchmark for Assessing Korean Legal Language Understanding in Large Language Models](https://aclanthology.org/2024.findings-emnlp.319/) (Findings of EMNLP 2024) | 법률 지식·추론 과제를 구분하고 전문가와 평가 문항을 만드는 과정 | 기존 제출문서가 인용한 비교 자원. 전문 자격과 검수 절차 설계의 참고 |
| [LegalBench: A Collaboratively Built Benchmark for Measuring Legal Reasoning in Large Language Models](https://arxiv.org/abs/2308.11462) | 법률 추론 유형별 과제를 정의하고 전문가 판단과 연결하는 방법 | 기존 제출문서가 인용한 비교 자원. 미국 법률 과제의 단순 전용은 하지 않음 |

## 후속 연구에서 읽을 후보

- [Korean Canonical Legal Benchmark](https://arxiv.org/abs/2512.24572): 문항별 근거와 루브릭을 제공해 법률 지식과 추론을 구분하는 평가 설계.
- [Self-Taught Evaluators](https://arxiv.org/abs/2408.02666): 합성 대비쌍으로 평가자를 개선하는 방법. 현재 DecisionMiner에는 이 논문의 평가자 학습을 구현하지 않았습니다.

이 후보들은 기준 버전의 실험 성과로 제시하지 않습니다. 전문가 검수 기준·독립 평가셋을 먼저 마련한 뒤 방법 재현과 비교 대상을 확정합니다.

## 연구 브랜치의 본문 대조와 기존 기록 분석

[기존 검수 분석 보고서](../research/legacy_review/README.md#7-기존-논문-본문의-방법과-대조)에서는 KBL·LegalBench·KCL·CoAnnotating의 데이터 구축·평가·검수 배분 관련 본문 절을 확인하고 현재 구현과 대조했습니다. 문헌별 확인 절과 링크·PDF 해시를 함께 기록했습니다. 여기서 수행한 실험은 기존 규칙 두 모드의 사후 비교와 검수 순서 분석이며, 해당 논문의 LLM·학습·비용 실험을 재현한 것은 아닙니다.

후속으로 [원문 발췌를 제공한 LLM Judge 비교](../research/judge/README.md)를 실행했습니다. 공통 항목별 기준과 단순 지시를 같은 79건에서 비교하고 인용·판단보류·출력 실패를 포함해 보고했습니다. 문항별 전문가 확정 루브릭, 논문의 독립 평가셋, 다중 모델·다운스트림 학습 실험을 재현한 것은 아닙니다.
