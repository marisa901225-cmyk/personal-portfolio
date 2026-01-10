# Repository Guidelines

## Project Structure & Module Organization
- `frontend/`: Vite + React app. UI code lives in `frontend/src/` with feature folders under `frontend/src/features/`, shared utilities in `frontend/src/shared/`, and tests in `frontend/test/`.
- `backend/`: FastAPI service. Core app entry is `backend/main.py`, routes in `backend/routers/`, services in `backend/services/`, and tests in `backend/tests/`.
- `devplan/`: planning notes and prompts.
- `docker-compose.yml`: local orchestration (backend-focused).

## Build, Test, and Development Commands
- `npm run dev --prefix frontend` or `npm run dev:frontend`: run the frontend dev server.
- `npm run build --prefix frontend`: build the frontend for production (`frontend/dist/`).
- `npm run test --prefix frontend` or `npm run test:frontend`: run frontend unit tests with Vitest.
- `python -m venv backend/.venv && source backend/.venv/bin/activate`: create/activate backend venv.
- `pip install -r backend/requirements.txt`: install backend dependencies.
- `uvicorn backend.main:app --host 0.0.0.0 --port 8000`: run the API server locally.
- `npm run test:backend`: run backend tests via `unittest` discovery.

## Coding Style & Naming Conventions
- TypeScript/TSX uses 2-space indentation; Python uses 4-space indentation.
- Frontend modules use `camelCase` for variables and `PascalCase` for components (e.g., `AppErrorBanner`).
- Tests: `frontend/test/*.test.ts(x)` and `backend/tests/test_*.py`.
- No explicit formatter is configured; keep style consistent with nearby files. Prefer type-safe patterns and explicit typing in shared utilities.

## Testing Guidelines
- Frontend: Vitest + Testing Library. Run with `npm run test --prefix frontend`.
- Backend: `unittest` + FastAPI `TestClient`. Run with `python -m unittest discover backend/tests`.
- Add tests for new API endpoints and UI flows, especially those touching auth tokens or data transforms.

## Commit & Pull Request Guidelines
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `chore:`). Reverts use `Revert "..."`.
- PRs should include: a brief summary, testing performed, and screenshots for UI changes. Link related issues/tasks when applicable.

## Configuration & Security Notes
- Store secrets in environment variables (e.g., `API_TOKEN`, `DATABASE_URL`, `NEWS_LLM_BASE_URL`).
- Do not commit tokens or model paths; use `.env` or system envs when running locally.
