# 📊 My Personal Asset Portfolio

**개인 자산, 지출, 뉴스, 알림을 통합 관리하는 홈서버 기반 올인원 플랫폼**입니다.  
최신 AI 기술(EXAONE, RAG)과 빅데이터 기술(DuckDB)을 활용하여 내 자산 흐름과 관심 정보를 실시간으로 브리핑해줍니다.

![License](https://img.shields.io/badge/license-MIT-blue.svg) ![Python](https://img.shields.io/badge/python-3.10+-blue) ![React](https://img.shields.io/badge/react-18-blue) ![LLM](https://img.shields.io/badge/AI-EXAONE4.0-purple)

---

## ✨ 핵심 기능 (Key Features)

### 💰 자산 및 투자 관리 (Asset Management)
- **실시간 가치 평가**: 한국투자증권(KIS) API와 환율 정보를 연동하여 자산 가치를 초 단위로 평가합니다.
- **포트폴리오 분석**: 주식, 현금 비중을 시각화하고 배당금 흐름을 추적합니다.
- **XIRR 계산**: 입출금 내역을 기반으로 정확한 투자 수익률을 산출합니다.

### 💸 지출 자동화 (Smart Expense Tracking)
- **Tasker 연동**: 스마트폰의 은행/카드 알림을 서버로 실시간 전송합니다.
- **AI 자동 분류**: 머신러닝 및 키워드 매칭을 통해 소비처를 카테고리별로 자동 분류합니다.
- **대량 업로드**: 엑셀/CSV 파일을 통한 과거 내역 일괄 등록 및 중복 방지 처리를 지원합니다.

### 📰 지능형 뉴스 & e스포츠 (News & Esports RAG)
- **DuckDB 기반 필터링**: `LCK`, `Macro`, `Tech` 등 태그 기반으로 뉴스를 정밀하게 분류합니다.
- **e스포츠 특화**: PandaScore API를 통해 LCK, 국제대회 일정을 **위트 있는 말투와 이모지**로 브리핑합니다.
- **경제 뉴스 큐레이션**: 거시경제, 기술주, 환율 등 관심 분야 뉴스를 3줄로 요약해 전달합니다.
- **중복 제거**: SimHash 알고리즘으로 유사 기사를 80% 이상 걸러내어 정보 밀도를 높입니다.

### 🔔 스마트 알림 (Smart Notifications)
- **Telegram 봇**: 매일 아침 6:30(미국장 마감) 및 7:00부터 5분 간격으로 알림을 요약해 브리핑합니다.
- **스팸 차단**: 단순 광고나 OTP 문자는 AI가 요약 전 단계에서 필터링합니다.

---

## 🛠️ 기술 스택 (Tech Stack)

이 프로젝트는 **Local-First** 원칙을 따르며, 민감한 금융 데이터는 외부로 전송되지 않고 홈서버 내에서 처리됩니다.

### Backend
- **Framework**: `FastAPI` (Python 3.10+)
- **Database**: 
  - `SQLite` (Main DB): 가계부, 자산, 알림 저장
  - `DuckDB` (Analytics): 뉴스 필터링, 로그 분석, 통계 쿼리 최적화
  - `Qdrant` / `FAISS` (Vector Store): RAG용 임베딩 저장
- **ORM**: `SQLAlchemy 2.0` (Async Support)
- **Scheduling**: `APScheduler`

### Frontend
- **Framework**: `React` (Vite)
- **Language**: `TypeScript`
- **UI Toolkit**: `TailwindCSS`, `ShadcnUI` (Radix Primitives)
- **State Management**: `TanStack Query` (React Query)

### AI & LLM (On-Premises)
- **Model**: `EXAONE 4.0` (GGUF Quantized)
  - 선택 이유: 뛰어난 한국어 성능 및 가벼운 리소스 점유 (4-bit quantization)
- **Inference**: `llama-cpp-python` (GPU Acceleration via CuBLAS)
- **Workflow**:
  - 금융/개인정보 처리: **Local LLM** (Private)
  - 대규모 뉴스 요약: **Remote LLM** (Main PC 또는 API)

### Data Sources
- **Finance**: 한국투자증권(KIS) Open API
- **Esports**: PandaScore API
- **Automation**: Android Tasker Webhook

---

## 🚀 설치 및 실행 (Quick Start)

Docker Compose를 사용하여 백엔드, 프론트엔드, LLM 서버를 한 번에 실행할 수 있습니다.

### 1. 환경 설정 (.env)
`backend/.env.example`을 복사하여 `.env`를 생성하세요.

```ini
# Security
API_TOKEN=your_secure_token_hash

# KIS Config Directory (Required for stock price sync)
KIS_CONFIG_DIR=/path/to/your/KIS/config

# Database
DATABASE_URL=sqlite:///backend/storage/db/portfolio.db

# LLM Config
LOCAL_LLM_MODEL_PATH=backend/data/EXAONE-3.5-7.8B-Instruct-Llamafied-Q4_K_M.gguf
NEWS_LLM_BASE_URL=http://your-main-pc:8080/v1

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=123456789

# APIs
KIS_APP_KEY=...
PANDASCORE_API_KEY=...
NAVER_CLIENT_ID=...
```

### 2. 실행
```bash
# 전체 시스템 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f backend-api
```

### 3. 접속
- **Web UI**: `http://localhost:5173` (또는 서버 IP)
- **API Docs**: `http://localhost:8000/docs`

---

## 📂 주요 디렉토리 구조

```
personal-portfolio/
├── backend/
│   ├── core/             # DB 모델 (User, Asset, GameNews 등)
│   ├── routers/          # API 엔드포인트
│   ├── services/         # 비즈니스 로직
│   │   ├── alarm/        # 알림 필터링 및 분석
│   │   ├── news/         # 뉴스 수집/정제 (DuckDB, RSS)
│   │   └── llm_service.py # EXAONE/Llama 연동
│   ├── scripts/          # 마이그레이션 및 유틸리티
│   └── storage/          # DB 및 백업 데이터
├── frontend/
│   ├── src/components/   # React 컴포넌트
│   └── src/hooks/        # 커스텀 훅
└── devplan/              # 개발 문서 및 프롬프트
```

---

## 🔗 관련 문서

- [📖 사용설명서 (User Guide)](file:///home/dlckdgn/personal-portfolio/사용설명서.md): 상세한 기능 설명 및 문제 해결 가이드
- [📝 개발 계획 (Task)](file:///home/dlckdgn/.gemini/antigravity/brain/cf5c960b-13f9-4bb3-b30e-fa060b63290e/task.md): 진행 중인 작업 목록
