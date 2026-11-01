# DecisionMiner 2차 웹 시연

이 폴더는 공모전 2차 자료의 서버·자립형 HTML·React 소스를 원본 그대로 보존합니다. `index.html`은 기존 샘플, 브라우저 규칙 검사, 내보내기를 포함합니다. `DecisionMiner_web_v4.jsx`는 별도 React 소스이며 현재 HTML을 다시 빌드하는 설정은 포함하지 않습니다.

## 샘플 열람

저장소 루트에서 `python -m http.server 8000 --directory web_demo`를 실행하고 `http://localhost:8000`을 엽니다. 신규 PDF 분해는 Flask 서버가 필요합니다.

## 서버 실행

```bash
python -m pip install -r web_demo/requirements.txt
# ANTHROPIC_API_KEY를 환경변수로 설정
cd web_demo
python server.py
```

기본 주소는 `http://localhost:7860`입니다. 기존 소스의 docstring에 있는 5000 안내보다 실제 `PORT` 기본값 7860을 따릅니다.

| 환경변수 | 의미 | 기본값 |
| --- | --- | --- |
| ANTHROPIC_API_KEY | 신규 PDF 분해용 비밀키 | 없음 |
| DM_MODEL | 분해 모델 | 소스에 기록된 모델 식별자 |
| PORT | 서버 포트 | 7860 |
| DM_INDEX | HTML 경로 | index.html |
| DM_ACCESS_TOKEN | 분해 요청 접근 토큰, 선택 | 없음 |
| DM_RATE_PER_MIN | IP별 분당 요청 제한 | 1 |
| DM_RATE_PER_DAY | 서버 프로세스별 일일 분해 호출 제한 | 30 |
| DM_MAX_TOKENS | 모델 최대 출력 토큰 | 16000 |

기존 소스의 기본 모델 식별자는 실행 시 공급자 계정에서 사용 가능한지 확인해야 합니다. 기준 버전 검증에서는 모델 API를 호출하지 않습니다. 요청 카운터는 메모리에 있으므로 서버 재시작·다중 프로세스 전체의 영구 비용 한도로 보장되지는 않습니다.

`/api/validate`는 규칙 검사이고 `/api/decompose`만 모델을 호출합니다. 신규 PDF는 QA 6~9개를 요청하며 기존 코퍼스의 사건당 45개 생성과 다릅니다. 라이브 규칙 판정은 정적 990건의 저장 라벨과 동일한 분포를 보장하지 않습니다.

`DEPLOY.md`와 Dockerfile은 당시 배포 설정입니다. 이 기준 버전 정리에서 재배포는 하지 않았습니다.
