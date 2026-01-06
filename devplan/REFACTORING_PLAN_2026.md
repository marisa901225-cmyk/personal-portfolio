# 🏗️ Personal Portfolio Refactoring Master Plan (2026)

> **Last Updated:** 2026-01-06 14:50
> **Status:** Phase 3 Complete (Refinement Applied) ✅
> **Ref:** Context7 Verified Tech Stack

---

## 📊 Progress Tracker

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | ✅ Complete | `src/` 구조 + React Router 설정 |
| **Phase 2** | ✅ Complete | React Query 통합, 페이지 컴포넌트 분리 |
| **Phase 3** | ✅ Complete | Backend 정리 & 테스트 강화 (Router Slim, Logic Cohesion) |
| **Phase 4** | ⏳ Pending | UI/UX 최적화 (스켈레톤, 에러 바운더리) |

---

## Phase 3: Backend Clean-up (보완 완료)

### ✅ Step 1: Market Data 분리
- `services/market_data_service.py`: KIS 비즈니스 로직 캡슐화.
- `routers/market_data.py`: 얇은 라우터 인터페이스.

### ✅ Step 2: Report Logic 완전 응집 (리뷰 반영)
- `services/report_service.py`:
  - AI 입력 해석 (자연어 쿼리 파싱 포함) 이동.
  - DuckDB 정제 레이어(`refine_portfolio_for_ai`) 호출 캡슐화.
  - 리포트 데이터 조립 및 기간 계산(`get_report_data`) 이동.
  - AI API 호출 및 **SSE 스트리밍 제너레이터** 이동.
  - 저장된 리포트 CRUD 로직 통합.
- `routers/report_core.py`, `report_ai.py`:
  - 모든 비즈니스 로직 제거.
  - 요청 파라미터 매핑 및 HTTP 관련 처리(Exception, StreamingResponse)만 담당.

### ✅ Step 3: 테스트 코드 작성 및 검증
- `tests/test_market_data.py`: KIS 가격 조회, 티커 검색, 환율 모킹 테스트. (Pass)
- `tests/test_report_service.py`: 자연어 쿼리 해석 및 기간 계산 단위 테스트. (Pass)
- `tests/test_main.py`: 기존 API 엔드포인트 검증. (Regression Check)

---

## Architecture Principles

### 💎 Thin Router / Thick Service
- **Router**: FastAPI 엔드포인트 정의, `Depends` 주입, `StreamingResponse` 래핑, `HTTPException` 발생.
- **Service**: DB 조회/집계, 외부 API 호출, 복잡한 계산 로직, 순수 데이터 반환.
- **Layering**: `Routers -> Services -> Models/Schemas`. 라우터 간 import 금지.

---

## 다음 단계: Phase 4

### UI/UX 최적화

1. **Loading States**: React Query의 `isLoading`을 활용한 스켈레톤 디자인 적용.
2. **Error Feedback**: API 에러 시 사용자 친화적인 메시지 노출 및 Error Boundary 적용.
3. **Performance**: 프론트엔드 렌더링 최적화 및 불필요한 리렌더링 방지.

---
**Note**: Phase 3가 리뷰 결과를 반영하여 최종 완료되었습니다. 테스트 코드를 통해 핵심 로직의 안정성이 확인되었습니다.
