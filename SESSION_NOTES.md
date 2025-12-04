# Personal Portfolio Project Notes

Last Updated: 2025-12-04

> **🚨 CODING LAW (STRICTLY FOLLOW)**
>
> Your goal is to implement new features WITHOUT making the codebase unnecessarily larger or more complex.
>
> **1. Reuse existing abstractions**
> - Before creating new functions/hooks/utils/components, look for existing ones that can be reused or slightly extended.
> - If similar logic already exists (API calls, header building, error handling, form validation, conditional branches), integrate with that instead of duplicating it.
>
> **2. Function/component size and responsibility**
> - Each function/component should have a single, clear responsibility.
> - If it grows beyond ~30–40 lines or the nesting depth exceeds 3 levels, consider splitting it into smaller, meaningful units.
> - Do NOT extract functions just to reduce line count if you cannot give them a clear, meaningful name.
>
> **3. Minimize duplication (DRY)**
> - If the same (or almost the same) code appears 2+ times, consider extracting it into a shared helper/custom hook/utility.
> - However, avoid over-abstracting: do not create helpers that are used only once and add no real semantic clarity.
>
> **4. Avoid unnecessary abstraction**
> - Do NOT introduce wrapper components/hooks, highly generic utilities, or complex generics that are only used in one place.
> - Do NOT add “future-proof” options/parameters/layers that are not required by the current feature.
>
> **5. Minimize change surface**
> - Keep the change set as small and local as possible while satisfying the feature requirements.
> - Avoid touching many files for a single feature if a focused change in one or two modules is enough.
>
> **6. Prefer readability over cleverness**
> - Do NOT sacrifice readability just to shorten the code (e.g., overly compact one-liners, nested ternaries).
> - Use clear, descriptive names and stay consistent with the existing naming/style in the project.
>
> **7. Diff-friendly changes**
> - Follow the existing style and structure of the file instead of reformatting everything.
> - Avoid purely cosmetic changes that bloat the diff (e.g., moving code around or changing quote styles without functional reason).
>
> **After implementing the change, briefly explain:**
> - Where you reduced duplication,
> - Where you reused existing code,
> - Where you explicitly avoided over-abstraction.

## 1. Project Overview
A personal investment portfolio dashboard for a single user.
- **Frontend**: Vercel-deployed SPA (React/Vite).
- **Backend**: Home server (FastAPI) exposed via Tailscale.
- **Database**: SQLite (local file on home server).
- **Auth**: Simple API Token (Environment Variable).

## 2. Tech Stack
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS, Recharts, Lucide React.
- **Backend**: Python 3.11+, FastAPI, SQLAlchemy, Pydantic, Uvicorn.
- **Infrastructure**: Vercel (Frontend Hosting), Tailscale (Private Network Access), Ubuntu Server.

## 3. Frontend Architecture
Deployed on Vercel. Connects to the backend via `settings.serverUrl`.

### Key Components
- **App.tsx**: Main layout, routing (Dashboard/List/Add/Settings), and global state management via `usePortfolio` hook.
- **Dashboard.tsx**:
  - Displays Total Assets, Profit/Loss (Realized + Unrealized), Asset Allocation (Pie Chart), and Asset Trend (Area Chart).
  - **Asset Trend**: Shows historical value from backend snapshots. Displays "Not enough data" if empty.
  - **Rebalancing**: Shows alerts if current index allocation deviates >5%p from target.
- **AssetList.tsx**:
  - List of assets with inline Buy/Sell forms.
  - Handles trade execution and deletion.
- **AddAssetForm.tsx**:
  - Create new assets.
  - Features "Auto-fill" for Ticker using Backend API (`/api/search_ticker`).
  - When category is **현금/예금**, hides stock-specific fields (ticker, quantity, avg price) and treats the entered amount as the cash balance (amount=1, price=입력금액).
  - App-level settings (server URL, target index allocations) are persisted to `localStorage` and, when backend is configured, also synced with `GET/PUT /api/settings` so 그룹 비중이 새로고침/기기 간에도 유지됨.
  - Settings now include optional `usdFxBase` / `usdFxNow` (기준/현재 USD-KRW 환율). Dashboard reads these and, for 해외주식(US) 자산 합계 기준으로 대략적인 환차익/환차손을 별도 표기한다 (정확한 값 아님, 추세 확인용).
  - `현금/예금` 자산(예비금)은 자산 목록에서 기존 연필 아이콘을 눌렀을 때 티커 대신 잔액 입력창이 뜨도록 바꿨고, 서버 연결 시 `PATCH /api/assets/{id}`로 amount=1, current_price/purchase_price=잔액, realized_profit=0 형태로 동기화된다 (거래 기록 없이 잔액만 바로 맞추는 용도).
  - Settings에 `dividendTotalYear`(배당금 세후 총액, 수동 입력), `dividendYear`(연도), `dividends`(연도별 합계 리스트)를 추가했고, "자산 추가" 화면 하단의 작은 카드에서 연도+합계를 입력한 뒤 "연도별 합계에 추가"를 누르면 settings.dividends에 `{year,total}`가 누적된다. 대시보드는 최신/선택 연도 1개를 강조하고, 하단에 연도별 배당 리스트를 함께 보여준다. 값은 localStorage와 백엔드 `settings` 테이블(`dividend_year`/`dividend_total`/`dividends` JSON)에 모두 저장되며, `GET/PUT /api/settings`로 동기화된다.

### State Management (`hooks/usePortfolio.ts`)
- **Dual Mode**:
  - **Remote**: If `serverUrl` & `apiToken` are set, syncs with Backend.
  - **Local**: Fallback to `localStorage` if backend is unreachable or not configured.
- **Sync**:
  - `syncPrices()`: Fetches current prices from KIS via Backend.
  - `loadHistoryFromServer()`: Fetches portfolio snapshots for the trend graph.

## 4. Backend Architecture
Runs on Home Server (Ubuntu). Listens on port `8000` (Tailscale interface recommended).

### Core Modules
- **main.py**: Entry point. Configures CORS (currently `*`) and includes routers.
- **auth.py**: Verifies `X-API-Token` header against `API_TOKEN` env var.
- **db.py**: SQLite connection (`portfolio.db`), SQLAlchemy session handling.
- **models.py**: DB Schema (User, Asset, Trade, Setting, PortfolioSnapshot).

### API Endpoints
- **Portfolio**:
  - `GET /api/portfolio`: Full snapshot (Assets, Recent Trades, Summary).
  - `POST /api/assets`: Create asset.
  - `PATCH /api/assets/{id}`: Update asset (ticker, etc).
  - `DELETE /api/assets/{id}`: Soft delete asset.
  - `POST /api/assets/{id}/trades`: Execute Buy/Sell. Updates asset quantity/avg-price/realized-profit.
- **Market Data (KIS Integration)**:
  - `POST /api/kis/prices`: Fetch real-time prices (KRW) for KR/US stocks.
  - `GET /api/search_ticker`: Search stock ticker by name.
- **Snapshots**:
  - `POST /api/portfolio/snapshots`: Create daily snapshot (for cron job).
  - `GET /api/portfolio/snapshots`: Get history for trend graph.
- **Settings**:
  - `GET/PUT /api/settings`: Manage target index allocations.

## 5. Security & Deployment
- **Authentication**:
  - Backend requires `X-API-Token` header for all sensitive operations.
  - Frontend prompts user for password (API Token) on first load.
- **Network**:
  - Backend is intended to be accessed via Tailscale IP (e.g., `http://100.x.x.x:8000`).
  - Firewall (UFW) should restrict port 8000 to Tailscale interface.

## 6. Future Roadmap
- **Cron Job**: Set up a daily cron job to call `POST /api/portfolio/snapshots` for accumulating history data. A helper script `backend/snapshot_cron.sh` is provided; example (server에서 crontab):  
  `0 3 * * * API_TOKEN=your_token BACKEND_URL=http://127.0.0.1:8000 /path/to/repo/backend/snapshot_cron.sh >/dev/null 2>&1`
- **Multi-Portfolio**: Support multiple accounts/portfolios.
- **Advanced Analytics**: Currency effect analysis, dividend tracking.
