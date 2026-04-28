# My Personal Asset Portfolio

개인 자산, 지출, 뉴스, 알림, 리포트, 실험용 자동매매를 한 저장소에서 운영하는 홈서버 프로젝트입니다.

현재 기준으로 이 저장소는 아래 흐름을 중심으로 유지되고 있습니다.
- 자산/거래/환율/현금흐름 관리
- 스마트폰 알림 기반 지출 수집
- 뉴스/경제/e스포츠 수집과 텔레그램 브리핑
- AI 리포트와 운영 보조 자동화
- 개인용 소액 자동매매 엔진 실험

## 현재 서비스 구성

`docker-compose.yml` 기준 주요 서비스는 아래와 같습니다.
- `backend-api`: FastAPI 메인 API 서버
- `alarm-collector`: 모바일 알림 수집 엔드포인트
- `news-scheduler`: 뉴스/알림/운영성 스케줄 작업
- `trading-scheduler`: 트레이딩 엔진 전용 스케줄 작업
- `esports-monitor`: e스포츠 일정/상태 모니터
- `sync-prices`: 시세/리포트 보조 동기화
- `llama-server-light`, `llama-server-vulkan-huihui`: LLM 추론 서버

핵심 데이터 저장은 SQLite 기반이며, 분석성 조회는 DuckDB를 함께 사용합니다.

## 기술 스택

- Backend: FastAPI, SQLAlchemy, APScheduler
- Frontend: React, Vite, TypeScript, TanStack Query
- Data: SQLite, DuckDB, FAISS/Qdrant 자산 일부
- External: KIS Open API, PandaScore, Telegram, Naver OAuth
- LLM: 로컬 llama.cpp 서버 + 선택적 외부 API

## 빠른 시작

### 1. 환경 설정

비밀이 아닌 런타임 설정은 repo 안 `backend/.env`에 두고, 토큰/API 키는 repo 밖 secrets 파일에 둡니다.

```bash
cp backend/.env.example backend/.env
cp backend/.env.secrets.example ~/ai-models/myasset.secrets.env
```

기본 외부 secrets 경로는 `~/ai-models/myasset.secrets.env`입니다.
다른 경로를 쓰려면 호스트 환경변수 `MYASSET_SECRETS_ENV_FILE`로 바꿉니다.

자주 쓰는 설정 예시:

```ini
# backend/.env
LLM_BASE_URL=http://llama-server-vulkan-huihui:8083
ALARM_SUMMARY_LLM_BASE_URL=http://llama-server-vulkan-huihui:8083
ALARM_RANDOM_LLM_BASE_URL=http://llama-server-vulkan-huihui:8083
TRADING_ENGINE_SCHEDULE_INTERVAL_MIN=2
TRADING_ENGINE_ENABLED=1
```

```ini
# ~/ai-models/myasset.secrets.env
API_TOKEN=...
JWT_SECRET_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
KIS_MY_APP=...
KIS_MY_SEC=...
PANDASCORE_API_KEY=...
AI_REPORT_API_KEY=...
```

### 2. 실행

```bash
docker compose up -d
```

### 3. 접속

- Frontend: `http://localhost:5173`
- Backend API docs: `http://localhost:8000/docs`
- Alarm collector health: `http://localhost:8001/health`

## 자주 쓰는 운영 명령

```bash
# 전체 서비스 상태
docker compose ps

# 메인 API 로그
docker compose logs -f backend-api

# 트레이딩 스케줄러 로그
docker compose logs -f trading-scheduler

# 뉴스 스케줄러 로그
docker compose logs -f news-scheduler

# 특정 서비스 재시작
docker compose restart backend-api
docker compose restart trading-scheduler

# 이미지 재빌드 포함 재기동
docker compose up -d --build
```

## 디렉토리 가이드

```text
backend/
  core/           DB 모델, 설정, 인증
  routers/        FastAPI 라우터
  services/       도메인 로직
  integrations/   외부 API/KIS 연동
  scripts/        운영/점검/마이그레이션 스크립트
  storage/        SQLite DB, 산출물, 백업
  data/           런타임 데이터/캐시/보조 산출물

frontend/
  src/app/        앱 진입점과 라우팅
  src/pages/      화면 단위 페이지
  src/shared/     공용 API/유틸/UI
```

## 문서 상태

현재 기준으로 자주 보는 문서는 아래 세 개만 우선 신뢰하면 됩니다.
- [README.md](/home/dlckdgn/personal-portfolio/README.md)
- [devplan/사용설명서.md](/home/dlckdgn/personal-portfolio/devplan/사용설명서.md)
- [devplan/devplan/Project_Evaluation_Report.md](/home/dlckdgn/personal-portfolio/devplan/devplan/Project_Evaluation_Report.md)

`devplan/` 아래에는 과거 자동 생성 보고서와 중복 문서가 일부 남아 있습니다. 현재 운영 기준 설명은 위 문서들을 우선합니다.

## 스크립트 정리 기준

- `backend/scripts/runners`, `maintenance`, `db_setup`, `migrations`: 현재 운영/정비에 직접 쓰는 스크립트
- `backend/scripts/legacy`: 완전 폐기 코드가 아니라, 가끔 수동 실행하는 실험/진단/보조 스크립트가 섞여 있는 영역

즉 `legacy` 디렉토리는 "삭제 예정"이 아니라 "기본 운영 경로는 아닌 수동 도구 모음"에 가깝습니다.

## 참고

- 프런트 인증 기본 경로는 네이버 로그인 + 쿠키 세션입니다.
- 비상용으로 `API_TOKEN` 직접 입력 로그인도 남아 있습니다.
- 트레이딩 엔진은 개인용 소액 계좌 실험 전제로 운영 중이며, 범용 SaaS 성격의 기능이 아닙니다.
