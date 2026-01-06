# 🏗️ Personal Portfolio Refactoring Master Plan (2026)

> **Last Updated:** 2026-01-06 14:25
> **Status:** Phase 3 In Progress 🔄
> **Ref:** Context7 Verified Tech Stack

---

## 📊 Progress Tracker

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | ✅ Complete | `src/` 구조 + React Router 설정 |
| **Phase 2** | ✅ Complete | React Query 통합, 페이지 컴포넌트 분리 |
| **Phase 3** | 🔄 In Progress | Backend 정리 (main.py 분리) |
| **Phase 4** | ⏳ Pending | UI/UX 최적화 (스켈레톤, 에러 바운더리) |

---

## Phase 3: Backend Clean-up (현재 진행 중)

### ✅ 완료된 작업

#### Step 1: Market Data 분리
| 작업 | 상태 | 설명 |
|------|------|------|
| `backend/services/market_data_service.py` 생성 | ✅ | KIS 비즈니스 로직 서비스 레이어 |
| `backend/routers/market_data.py` 생성 | ✅ | KIS API 엔드포인트 라우터 |
| `backend/main.py` 정리 | ✅ | KIS 로직 제거, 라우터 include 추가 |
| Import 검증 | ✅ | `from backend.main import app` 성공 |

**새로 생성된 파일:**
- `backend/services/market_data_service.py` - 3개의 서비스 함수 + 3개의 예외 클래스
- `backend/routers/market_data.py` - 3개의 엔드포인트 + Pydantic 모델

**main.py 변경 사항:**
- 276줄 → 120줄로 축소 (56% 감소)
- KIS 관련 코드 완전 제거
- 라우터 등록과 미들웨어/헬스체크만 유지

### ⏳ 다음 작업

#### Step 2: Report Logic 응집 (추후 진행)
PRD에 따르면:
- `routers/report_core.py`의 `_build_report`, `_build_monthly_summaries` → `services/report_service.py`
- `routers/report_ai.py`의 AI 호출 로직 → `services/report_service.py`
- `routers/report_saved.py`의 CRUD → `services/report_service.py`

---

## File Structure Changes

### Before (Phase 3 전)
```
backend/
├── main.py               # 276줄 (KIS 로직 포함)
├── routers/
│   ├── report_core.py    # 329줄
│   ├── report_ai.py      # (분석 필요)
│   └── report_saved.py   # (분석 필요)
└── services/
    └── report_service.py # AI 유틸만 보유
```

### After (Phase 3 완료 시)
```
backend/
├── main.py                       # 120줄 (라우터 등록 + 헬스체크만)
├── routers/
│   ├── market_data.py           # ✅ 신설 (KIS 엔드포인트)
│   ├── report_core.py           # 얇은 라우터 (서비스 호출)
│   ├── report_ai.py             # 얇은 라우터 (서비스 호출)
│   └── report_saved.py          # 얇은 라우터 (서비스 호출)
└── services/
    ├── market_data_service.py   # ✅ 신설 (KIS 비즈니스 로직)
    └── report_service.py        # 확장 예정 (report 로직 집중)
```

---

## Architecture Principles (PRD 기반)

### 라우터 vs 서비스 책임 경계

| Layer | 책임 | 금지 사항 |
|-------|------|----------|
| **Router** | 요청/쿼리 검증, Depends 주입, HTTPException 매핑, response_model 선언 | 비즈니스 로직 (집계/DB 조작/복잡 분기) |
| **Service** | DB 접근/집계, 외부 API 호출, 로깅 | HTTP 객체 반환 (순수 데이터/도메인 예외 중심) |
| **main.py** | 앱 생성, 미들웨어, 라우터 include | 비즈니스 로직 |

### 순환 Import 회피
- Router는 Service만 import
- Service는 Router import 금지
- 공용 변환 로직은 `services/` 또는 `schemas.py`로 이동

---

## Commands

```bash
# 백엔드 Import 검증
cd /home/dlckdgn/personal-portfolio && source backend/.venv/bin/activate && python -c "from backend.main import app; print('✅ OK')"

# 백엔드 서버 실행
cd /home/dlckdgn/personal-portfolio/backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000

# 프론트엔드 개발 서버
npm run dev
```

---

## PRD Reference

전체 PRD는 `/home/dlckdgn/personal-portfolio/리팩토링.txt` 참조.

---
**Note**: Phase 3 Step 2 (Report Logic 응집)는 별도 세션에서 진행 권장. 현재 Market Data 분리는 완료됨.
