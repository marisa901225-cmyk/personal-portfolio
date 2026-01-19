# AI Agent Improvement Prompts

**Mandatory Execution Rules:**
1.  **Strict Sequential Order:** Execute prompts PROMPT-001, PROMPT-002, etc., in order. Do not skip.
2.  **Use Tools:** Always use file-editing tools (write_to_file, replace_string) to modify code. Do not just output text.
3.  **No Placeholders:** Write complete, working code. implementation should be production-ready.
4.  **English Only:** Maintain all comments and commit messages in English (or Korean if context requires, but this file is English-only).

---

## 2. Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-002 | Frontend Type Safety (Remove Any) | P2 | ⬜ Pending |
| 2 | PROMPT-003 | Fix Hardcoded Script Paths | P2 | ⬜ Pending |
| 3 | PROMPT-004 | Scheduler Retry Logic | P2 | ⬜ Pending |
| 4 | PROMPT-005 | Environment Variable Validation | P2 | ⬜ Pending |
| 5 | PROMPT-006 | Structured Logging (JSON) | P3 | ⬜ Pending |
| 6 | PROMPT-007 | Dashboard i18n Unification | P3 | ⬜ Pending |
| 7 | OPT-001 | Dashboard Data Loading Optimization | OPT | ⬜ Pending |

**Distribution:** Total: 7 | P1: 0 | P2: 4 | P3: 2 | OPT: 1

---


## 4. P2 Prompts (High Priority)

### [PROMPT-002] Frontend Type Safety (Remove Any)

**Directive:** Execute this prompt now, then proceed to PROMPT-003.

**Task:**
Refactor frontend hooks and API clients to replace explicit `any` types with proper interfaces/DTOs.

**Target Files:**
-   `frontend/hooks/usePortfolio.ts`
-   `frontend/src/shared/api/client/mappers.ts`
-   `frontend/src/shared/api/types.ts` (Update/Create)

**Steps:**
1.  Define `PortfolioUpdatePayload` interface in `types.ts`.
2.  Update `usePortfolio.ts`: Replace `updates: any` with `updates: PortfolioUpdatePayload`.
3.  Update `mappers.ts`: Add type guards for `safeNum` or ensure incoming data is typed as `unknown` and validated, not `any`.

**Verification:**
-   Run: `cd frontend && npm run typecheck`
-   Ensure no new type errors are introduced.

After completing this prompt, proceed to [PROMPT-003].

---

### [PROMPT-003] Fix Hardcoded Script Paths

**Directive:** Execute this prompt now, then proceed to PROMPT-004.

**Task:**
Refactor python scripts to use `pathlib` for dynamic path resolution instead of hardcoded strings or assumption of CWD.

**Target Files:**
-   `backend/scripts/check_db_alarms.py`
-   `backend/scripts/generate_v2_fix.py`
-   (And any other script using `open("backend/...")` directly)

**Steps:**
1.  Import `pathlib.Path`.
2.  Define `BASE_DIR = Path(__file__).resolve().parent.parent` (adjust levels as needed).
3.  Replace string paths like `"backend/storage/db"` with `BASE_DIR / "storage" / "db"`.

**Verification:**
-   Run one modified script (dry-run mode if possible) to check no FileNotFoundError.

After completing this prompt, proceed to [PROMPT-004].

---

### [PROMPT-004] Scheduler Retry Logic

**Directive:** Execute this prompt now, then proceed to PROMPT-005.

**Task:**
Implement retry logic for scheduler jobs using `tenacity` to handle transient external API failures.

**Target Files:**
-   `backend/services/news/collector.py` (or relevant data collector)
-   `backend/scheduler.py`

**Steps:**
1.  Install `tenacity` if missing (add to requirements).
2.  Apply `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))` to connection-heavy functions (e.g., `collector.fetch_news`).
3.  Log retries with a warning.

**Verification:**
-   Simulate network failure (temporarily change URL) and verify retries in logs.

After completing this prompt, proceed to [PROMPT-005].

---

### [PROMPT-005] Environment Variable Validation

**Directive:** Execute this prompt now, then proceed to PROMPT-006.

**Task:**
Strengthen configuration loading by validating essential environment variables at startup.

**Target Files:**
-   `backend/core/config.py`

**Steps:**
1.  Enhance `Settings` class (Pydantic based).
2.  Mark critical fields (e.g., `DATABASE_URL`, `KIS_APP_KEY`) as required (remove default `None` or use `...`).
3.  Add a startup check that prints a clear error and exits if keys are missing.

**Verification:**
-   Temporarily rename `.env` to `.env.bak`.
-   Run `uvicorn main:app`. Expect a clear validation error.
-   Restore `.env`.

After completing this prompt, proceed to [PROMPT-006].

---

## 5. P3 Prompts (Features & Usability)

### [PROMPT-006] Structured Logging (JSON)

**Directive:** Execute this prompt now, then proceed to PROMPT-007.

**Task:**
Implement structured JSON logging (using `structlog` or `json-logging`) to replace plain text logs for better observability.

**Target Files:**
-   `backend/core/logger.py` (Create/Modify)
-   `backend/main.py` (Apply logger)

**Steps:**
1.  Configure the logger to output JSON.
2.  Include standard fields: `timestamp`, `level`, `message`, `correlation_id` (if possible).
3.  Replace standard `print` or `logging` calls in `main.py` startup logic with the new logger.

**Verification:**
-   Run the backend locally: `uvicorn main:app`.
-   Observe console output. It should be in JSON format: `{"timestamp": "...", "level": "INFO", "message": "Startup..."}`.

After completing this prompt, proceed to [PROMPT-007].

---

### [PROMPT-007] Dashboard i18n Unification

**Directive:** Execute this prompt now, then proceed to [OPT-001].

**Task:**
Unify all Dashboard UI text to Korean to ensure consistent user experience, removing residual English labels.

**Target Files:**
-   `frontend/components/DashboardSummary.tsx`
-   `frontend/components/DashboardCharts.tsx`

**Steps:**
1.  Scan the files for English strings like "Total P&L", "Dividends", "YTD".
2.  Replace them with Korean equivalents: "총 손익", "배당금", "연초 대비 수익률".
3.  Ensure number formatting (currency) uses KRW/USD correctly with Korean labels.

**Verification:**
-   Start frontend: `npm run dev`.
-   Visually check the Dashboard. No English labels should remain in the main summary view.

After completing this prompt, proceed to [OPT-001].

---

---

## 6. Optimization Prompts (OPT)

### [OPT-001] Dashboard Data Loading Optimization

**Directive:** Execute this prompt now, then proceed to FINAL COMPLETION.

**Task:**
Optimize dashboard initial loading by creating an aggregated API endpoint, reducing separate calls for Assets, News, and Alarms.

**Target Files:**
-   `backend/routers/dashboard.py` (Create/Modify)
-   `frontend/hooks/useDashboardData.ts` (Create/Modify)

**Steps:**
1.  **Backend:** Create `GET /api/dashboard/summary` in `dashboard.py`.
    -   Handler should gather data from `AssetService`, `NewsService`, `AlarmService` concurrently (using `asyncio.gather`).
    -   Return a combined JSON structure.
2.  **Frontend:** Create or update a hook to fetch from this single endpoint.
3.  **Frontend:** Update `Dashboard.tsx` to use this data, eliminating "Waterfall" loading effects.

**Verification:**
-   Open Browser DevTools (Network tab).
-   Reload Dashboard.
-   Verify that valid API calls are reduced (e.g., replaced by 1 main call).
-   Ensure Total Blocking Time (TBT) is minimized.

After completing this prompt, proceed to FINAL COMPLETION section.

---

## 7. Final Completion

**Directive:** This is the final step.

**Actions:**
1.  Run a full project build/check one last time:
    -   `cd frontend && npm run build`
    -   `cd backend && python3 -m unittest discover tests`
2.  If all checks pass, output the message below.

**Completion Message:**
> ALL PROMPTS COMPLETED. All pending improvement and optimization items from the latest report have been applied.

