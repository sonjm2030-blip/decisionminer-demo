# 배포 단계서 — HF Spaces (Docker) · 완전 공개

## 0. 먼저 콘솔에서 (★ 비용 안전장치 — 배포 전 필수)
완전 공개 URL이라 이 두 가지가 유일한 비용 방어선입니다.

1. **Anthropic 예산 한도** — console.anthropic.com → Settings → Billing/Limits
   → 월 사용 한도 설정(권장 $30). 봇·남용으로 폭증해도 여기서 끊김. **이게 진짜 상한.**
2. **배포 전용 API 키** — console.anthropic.com → API Keys → Create Key
   (이름 예: `decisionminer-deploy`) → 복사. 메인 키 쓰지 말 것. 문제 시 이 키만 폐기.

## 1. HF Space 생성 (웹 UI)
1. huggingface.co 로그인/가입 → 우상단 **New → Space**
2. 이름 정하고 → **Space SDK = `Docker`** (Blank), Hardware = **CPU basic(무료)**, Visibility = **Public**
3. **Create Space**

## 2. 파일 업로드 (드래그앤드롭)
Space 화면 → **Files** 탭 → **Add file → Upload files** →
`~/Desktop/1`의 **아래 6개**를 끌어다 놓고 Commit:
- `server.py`  `index.html`  `Dockerfile`  `requirements.txt`  `README.md`  `.gitignore`

⚠️ `.venv/` 폴더는 **올리지 말 것**(용량 큼·빌드 깨짐). `.gitignore`가 막아주지만 수동 업로드 시 직접 제외.
※ HF가 만든 기본 README가 있으면 내 README.md로 덮어쓰기(= Space 메타데이터 `sdk: docker`, `app_port: 7860` 포함).

## 3. 시크릿 등록
Space → **Settings → Variables and secrets** → New secret:
- `ANTHROPIC_API_KEY` = (배포 전용 키) — **Secret**
- (권장) `DM_RATE_PER_DAY` = `15` — Variable  ※ 완전 공개라 기본 30보다 낮춰 비용 보수적으로
- 완전 공개이므로 `DM_ACCESS_TOKEN`은 **설정 안 함**

## 4. 빌드 & 공개 URL
- 시크릿 저장하면 자동 재빌드(Docker, 약 2~3분). **Logs** 탭에서 `Running on http://0.0.0.0:7860` 뜨면 라이브.
- 공개 주소: `https://huggingface.co/spaces/<소유자>/<이름>` (앱 직접: `https://<소유자>-<이름>.hf.space`)

## 5. 배포 후 확인 (체크리스트)
1. URL 접속 → 화면 정상 로드(200)
2. 실제 의결서 PDF 1건 업로드 → **약 2.5분 안 끊기고** 결과+검수+ZIP  ← ★ 아래 위험 주목
3. 연속 2회 업로드 → 2번째 **429**(분당 1회)
4. 발표 직전 한 번 접속해 **콜드스타트 깨우기**(무료 Space는 미사용 시 sleep)

## ⚠️ 가장 큰 기술 위험 — 응답 타임아웃
분해가 ~2.5분 걸리는데, HF Spaces 리버스 프록시가 **단일 요청을 ~60초쯤에서 끊을 가능성**이 있습니다.
5-2 확인에서 502/504/끊김이 나면 그게 이 증상입니다. 그때 대응(택1, 내가 바로 적용 가능):
- (A) 분해를 가볍게 — QA 6개·`DM_MAX_TOKENS` 축소로 60초 이내로 단축
- (B) 분해를 비동기(작업 시작→폴링)로 전환 + index.html 폴링 로직(소폭 수정)
- (C) 타임아웃 넉넉한 플랫폼(Render 유료/자체 VM)로 이전

## ★ 발표·심사 종료 후 (방치 비용·키 위험)
- HF Space **Settings → Pause/Delete**
- Anthropic 콘솔에서 **배포 전용 키 폐기(Revoke)**
