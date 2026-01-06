# 🏗️ Personal Portfolio Refactoring Master Plan (2026)

> **Last Updated:** 2026-01-06 15:15
> **Status:** Phase 3 Complete (Storage Organized) ✅
> **Ref:** Context7 Verified Tech Stack

---

## 📊 Progress Tracker

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1** | ✅ Complete | `src/` 구조 + React Router 설정 |
| **Phase 2** | ✅ Complete | React Query 통합, 페이지 컴포넌트 분리 |
| **Phase 3** | ✅ Complete | Backend & Frontend 구조 정리 및 테스트 강화 |
| **Phase 4** | ⏳ Pending | UI/UX 최적화 (스켈레톤, 에러 바운더리) |

---

## Phase 3: Project Structure & Backend Clean-up

### ✅ Step 1: Market Data 분리
- `services/market_data_service.py`: KIS 비즈니스 로직 캡슐화.
- `routers/market_data.py`: 얇은 라우터 인터페이스.

### ✅ Step 2: Report Logic 완전 응집
- 모든 리포트 관련 비즈니스 로직을 `services/report_service.py`로 중심화.
- 라우터(`report_core.py`, `report_ai.py`)는 얇은 인터페이스 역할만 수행.

### ✅ Step 3: 테스트 코드 작성 및 검증
- `tests/test_market_data.py`, `tests/test_report_service.py` 추가.
- 전체 15개 테스트 통과 확인 (OK).

### ✅ Step 4: 전체 프로젝트 구조 정리 (Monorepo 스타일)
- **Frontend**: 모든 프론트엔드 관련 파일(`src`, `public`, `index.html`, `vite.config.ts`, `node_modules` 등)을 `frontend/` 디렉토리로 이동.
- **Backend**: 이미 `backend/` 하위에 정리됨.
- **Root**: `package.json`을 통해 전체 프로젝트 스크립트 관리.

---

## Final Project Structure

```
personal-portfolio/
├── frontend/             # 모든 프론트엔드 코드 및 설정
│   ├── src/
│   ├── components/
│   ├── index.html
│   ├── vite.config.ts
│   └── package.json
├── backend/              # 모든 백엔드 코드 및 설정
│   ├── core/             # DB, Auth, Models, Schemas
│   ├── routers/
│   ├── services/
│   ├── storage/          # DB 파일, 백업
│   ├── logs/             # 서비스 로그
│   └── main.py
├── devplan/              # 개발 계획 및 문서
└── package.json          # 루트 통합 스크립트
```

---

## Architecture Principles

- **Separation of Concerns**: Frontend와 Backend가 물리적으로 완전히 분리되어 독립적인 관리가 가능함.
- **Root Management**: 프로젝트 루트에서 전체 공통 작업을 수행할 수 있도록 엔트리포인트 제공.

---

## 다음 단계: Phase 4

### UI/UX 최적화

1. **Loading States**: React Query를 활용한 스켈레톤 UI 적용.
2. **Error Handling**: 전역 Error Boundary 및 토스트 알림 도입.
3. **Component Refinement**: `frontend/src/features` 하위 컴포넌트들의 디자인 완성도 제고.

---
**Note**: 프로젝트 구조 정리가 완료되었습니다. 이제 각 레이어에서의 역할이 명확해졌습니다.
