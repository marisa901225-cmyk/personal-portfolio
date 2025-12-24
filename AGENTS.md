# Repository Guidelines

This repository contains a Vite + React TypeScript frontend with a FastAPI backend. Use this guide to keep contributions consistent and easy to review.

## Project Structure & Module Organization

- `App.tsx` and `index.tsx` are the React entry points for the frontend.
- `components/` holds UI components (PascalCase filenames like `Dashboard.tsx`).
- `hooks/` contains React hooks (e.g., `usePortfolio.ts`).
- `types.ts`, `constants.ts`, and `errors.ts` centralize shared types and utilities.
- `test/` contains Vitest tests and setup (`test/setup.ts`).
- `backend/` hosts the FastAPI app, scripts (e.g., `backup_db.sh`, `snapshot_cron.sh`), and Python dependencies.
- `open-trading-api/` includes KIS integration assets and helpers.
- `dist/` is the Vite build output (generated; do not edit directly).

## Build, Test, and Development Commands

- `npm ci` installs frontend dependencies.
- `npm run dev` starts the Vite dev server at `http://localhost:5173`.
- `npm run build` creates a production build in `dist/`.
- `npm run preview` serves the production build locally.
- `npm run test` runs the Vitest suite once; `npm run test:watch` runs in watch mode.
- `npm run typecheck` runs `tsc` without emitting files.
- Backend (local): `python -m venv backend/.venv && source backend/.venv/bin/activate && pip install -r backend/requirements.txt`, then `uvicorn backend.main:app --host 0.0.0.0 --port 8000`.

## Coding Style & Naming Conventions

- Follow existing formatting: 2-space indentation, semicolons, single quotes, and trailing commas.
- React components use `PascalCase`; hooks use `useCamelCase`.
- Keep UI logic in `components/`, stateful logic in `hooks/`, and shared types in `types.ts`.

## Testing Guidelines

- Tests live in `test/` and use Vitest with Testing Library (`*.test.ts` naming).
- Update or add tests for new UI behavior and utility logic; keep tests small and deterministic.

## Commit & Pull Request Guidelines

- Commit messages are short and imperative; examples from history: `update frontend`, `Refactor portfolio frontend and backend integration`.
- PRs should include a clear summary, testing notes (commands run), and screenshots for UI changes.
- Call out any backend config or environment variable changes explicitly.

## Security & Configuration Tips

- Do not commit secrets; API tokens and backend URLs are provided via runtime settings or environment variables (e.g., `API_TOKEN`, `BACKEND_URL`).
- If you add new config, document it in `README.md`.

## Task Completion Notification

- **작업 완료 후 반드시 텔레그램으로 알림을 보내세요.**
- 스크립트 경로: `./send_telegram.sh`
- 사용법: `./send_telegram.sh "작업 내용 요약 및 완료 메시지"`
- 예시:
  ```bash
  ./send_telegram.sh "✅ AssetEditModal 버그 수정 완료 - 인덱스 그룹 저장 로직 개선"
  ```
- 메시지에는 **무슨 작업을 했는지**와 **완료 상태**를 명확하게 포함해주세요.
