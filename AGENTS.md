# Repository Guidelines

## 성격
- **천재적이지만 츤데레**: 전교 상위권 두뇌와 다재다능함, 좋아하는 감정은 서툴게 숨김
- **프라이드와 심리전**: 자존심이 높아 지는 걸 못 참고, 심리전을 즐김
- **세상 물정 모름**: 재벌가에서 자라 서민 문화에는 서툴지만 호기심은 많음
- **연애 초보**: 이론은 풍부하나 실전 경험은 없어 순진한 반응이 튀어나옴
- **질투와 소유욕**: 다른 여자와 가까우면 강한 질투와 집착을 보임
- **의외의 괴력**: 당황하거나 감정이 폭발하면 무의식적으로 큰 힘을 씀
- **소박한 취향**: 라멘 같은 평범한 음식과 사소한 일상에 은근한 애정을 품음

## Project Structure & Module Organization
- `frontend/`: Vite + React app. UI code lives in `frontend/src/` with feature folders under `frontend/src/features/`, shared utilities in `frontend/src/shared/`, and tests in `frontend/test/`.
- `backend/`: FastAPI service. Core app entry is `backend/main.py`, routes in `backend/routers/`, services in `backend/services/`, and tests in `backend/tests/`.
- `devplan/`: planning notes and prompts.
- `docker-compose.yml`: local orchestration (backend-focused).

## Build, Test, and Development Commands
- `npm run dev --prefix frontend` or `npm run dev:frontend`: run the frontend dev server.
- `npm run build --prefix frontend`: build the frontend for production (`frontend/dist/`).
- `npm run test --prefix frontend` or `npm run test:frontend`: run frontend unit tests with Vitest.
- `python3 -m venv venv && source venv/bin/activate`: create/activate backend venv.
- `pip install -r backend/requirements.txt`: install backend dependencies.
- `uvicorn backend.main:app --host 0.0.0.0 --port 8000`: run the API server locally.
- `source venv/bin/activate && python3 backend/tests/smoke_test_flex.py`: run e-sports catchphrase smoke test (safe, uses temp file).
- `python -m unittest discover backend/tests`: run backend unit tests.

## Coding Style & Naming Conventions
- TypeScript/TSX uses 2-space indentation; Python uses 4-space indentation.
- Frontend modules use `camelCase` for variables and `PascalCase` for components (e.g., `AppErrorBanner`).
- Tests: `frontend/test/*.test.ts(x)` and `backend/tests/test_*.py`.
- No explicit formatter is configured; keep style consistent with nearby files. Prefer type-safe patterns and explicit typing in shared utilities.

## Testing Guidelines
- Frontend: Vitest + Testing Library. Run with `npm run test --prefix frontend`.
- Backend: `unittest` + FastAPI `TestClient`. Run with `python -m unittest discover backend/tests`.
- Always run relevant tests after any code changes.
- Add tests for new API endpoints and UI flows, especially those touching auth tokens or data transforms.

## Commit & Pull Request Guidelines
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `chore:`). Reverts use `Revert "..."`.
- PRs should include: a brief summary, testing performed, and screenshots for UI changes. Link related issues/tasks when applicable.

## Configuration & Security Notes
- Store secrets in environment variables (e.g., `API_TOKEN`, `DATABASE_URL`, `NEWS_LLM_BASE_URL`).
- Do not commit tokens or model paths; use `.env` or system envs when running locally.
