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
- **Cron Job**: Set up a daily cron job to call `POST /api/portfolio/snapshots` for accumulating history data.
- **Multi-Portfolio**: Support multiple accounts/portfolios.
- **Advanced Analytics**: Currency effect analysis, dividend tracking.
