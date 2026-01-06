# 🏗️ Personal Portfolio Refactoring Master Plan (2026)

> **Last Updated:** 2026-01-06 14:35
> **Status:** Phase 3 Complete ✅
> **Ref:** Context7 Verified Tech Stack

---

## 📊 Progress Tracker

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | ✅ Complete | `src/` 구조 + React Router 설정 |
| **Phase 2** | ✅ Complete | React Query 통합, 페이지 컴포넌트 분리 |
| **Phase 3** | ✅ Complete | Backend 정리 (main.py 분리, 서비스 레이어 응집) |
| **Phase 4** | ⏳ Pending | UI/UX 최적화 (스켈레톤, 에러 바운더리) |

---

## Phase 3: Backend Clean-up (완료)

### ✅ Step 1: Market Data 분리
| 작업 | 설명 |
|------|------|
| `services/market_data_service.py` | KIS 비즈니스 로직 (시세, 티커 검색, 환율) |
| `routers/market_data.py` | KIS API 엔드포인트 (얇은 라우터) |
| `main.py` 정리 | 276줄 → 120줄 (56% 감소) |

### ✅ Step 2: Report Logic 응집
| 작업 | 설명 |
|------|------|
| `services/report_service.py` 확장 | report_core + report_ai + report_saved 로직 통합 |
| `services/settings_service.py` | `to_settings_read` 헬퍼 분리 |
| `services/expense_service.py` | `get_expense_summary` 서비스 분리 |
| `routers/report_core.py` 정리 | 329줄 → 125줄 (62% 감소) |
| `routers/report_saved.py` 정리 | 117줄 → 53줄 (55% 감소) |
| `routers/report_ai.py` 정리 | 라우터 간 의존 제거 |

### 주요 개선점

1. **라우터 간 의존 제거**
   - ❌ `report_core.py` → `settings.py` (제거됨)
   - ❌ `report_ai.py` → `report_core.py` (제거됨)
   - ❌ `report_ai.py` → `expenses.py` (제거됨)

2. **순환 Import 방지 구조**
   ```
   Routers → Services (OK)
   Services → Models, Schemas (OK)
   Services → Services (OK)
   Routers → Routers (FORBIDDEN)
   ```

3. **새로운 서비스 레이어**
   ```
   backend/services/
   ├── market_data_service.py  # KIS 시세/검색/환율
   ├── report_service.py       # 리포트 생성/저장/AI
   ├── settings_service.py     # 설정 변환 헬퍼
   ├── expense_service.py      # 지출 요약
   ├── portfolio.py            # 기존 포트폴리오 로직
   ├── users.py                # 사용자 관리
   └── ... (기타)
   ```

---

## File Structure (Phase 3 완료 후)

```
backend/
├── main.py                       # 120줄 (라우터 등록 + 헬스체크만)
├── routers/
│   ├── market_data.py           # KIS 엔드포인트
│   ├── report_core.py           # 125줄 (얇은 라우터)
│   ├── report_ai.py             # 라우터 간 의존 없음
│   ├── report_saved.py          # 53줄 (얇은 라우터)
│   ├── settings.py              # 서비스 헬퍼 사용
│   └── expenses.py              # 서비스 헬퍼 사용
└── services/
    ├── market_data_service.py   # KIS 비즈니스 로직
    ├── report_service.py        # 리포트 로직 집중
    ├── settings_service.py      # 설정 헬퍼
    └── expense_service.py       # 지출 요약 로직
```

---

## Architecture Principles (PRD 기반)

### 라우터 vs 서비스 책임 경계

| Layer | 책임 | 금지 사항 |
|-------|------|----------|
| **Router** | 요청/쿼리 검증, Depends 주입, HTTPException 매핑, response_model 선언 | 비즈니스 로직, 다른 라우터 import |
| **Service** | DB 접근/집계, 외부 API 호출, 로깅 | HTTP 객체 반환 |
| **main.py** | 앱 생성, 미들웨어, 라우터 include | 비즈니스 로직, 엔드포인트 정의 |

---

## 다음 단계: Phase 4

### UI/UX 최적화

1. **Loading States**
   - React Query의 `isLoading` 상태를 이용한 스켈레톤 UI 적용

2. **Error Boundaries**
   - React Error Boundary를 이용한 우아한 에러 처리

3. **Component Decomposition**
   - 기존 `components/` 폴더의 대형 컴포넌트들을 `src/features/`로 이동 및 분해

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
**Note**: Phase 3 완료. Phase 4는 UI/UX 최적화로 별도 세션에서 진행 권장.
