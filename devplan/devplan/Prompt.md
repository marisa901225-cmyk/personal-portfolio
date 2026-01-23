# AI Agent Improvement Prompts

## ⚠️ Execution Rules
1. **No Text-Only Responses**: Do not just explain what you will do. You must use tools (`replace_string_in_file`, `create_file`, etc.) to modify the code.
2. **Sequential Execution**: Follow the checklist order strictly. Do not skip prompts.
3. **Verification is Mandatory**: For every prompt, you must run the specified verification command (e.g., `npm run typecheck` or `pytest`) to ensure the fix works.
4. **English Only**: This file must remain in English. No Hangul characters allowed.

---

## ✅ Execution Checklist

| # | Prompt ID | Improvement ID | Title | Priority | Status |
|:---:|:---|:---|:---|:---:|:---:|
| 1 | `PROMPT-001` | `test-backend-env-001` | Fix Backend Test Env | P1 | ✅ Completed |
| 2 | `PROMPT-002` | `code-cleanup-legacy-001` | Clean Legacy Scripts | P2 | ⬜ Pending |
| 3 | `PROMPT-003` | `feat-error-boundary-001` | Frontend Error Boundary | P2 | ⬜ Pending |
| 4 | `PROMPT-004` | `feat-telegram-template-001` | Telegram Templates | P3 | ⬜ Pending |
| 5 | `OPT-1` | `opt-duckdb-query-001` | DuckDB Optimization | OPT | ⬜ Pending |

**Distribution:** Total: 5 | P1: 1 | P2: 2 | P3: 1 | OPT: 1

---

## 🔴 Priority 1 (Critical)

### [PROMPT-001] Align Backend and Test Env
**Directive:** Execute this prompt now, then proceed to `PROMPT-002`.

**Improvement ID:** `test-backend-env-001`

**Task:**
Sync the backend and test environment by fixing broken import paths caused by refactoring and setting the correct test database path.

**Target Files:**
- `backend/tests/` (All files)
- `backend/pytest.ini`

**Steps:**
1. Fix all `ModuleNotFoundError` in `backend/tests/` by updating import statements to match the new backend structure (e.g., move scripts to `runners/`).
2. Update `pytest.ini` to set the environment variable `DATABASE_URL=sqlite:////home/dlckdgn/personal-portfolio/devplan/test_db/test.db`.
3. Identify and remove test files that reference scripts or services that were deleted during refactoring.
4. Add a `conftest.py` in `backend/tests/` to ensure `sys.path` correctly includes the backend root.

**Implementation Details:**
- Database path must be absolute: `/home/dlckdgn/personal-portfolio/devplan/test_db/test.db`.
- Use `pytest-env` or set via `os.environ` in `conftest.py` if necessary.

**Verification:**
- Run `.venv/bin/pytest --collect-only` and verify "0 errors" and that tests point to the correct DB.
- After completing this prompt, proceed to `[PROMPT-002]`.

---

## 🟡 Priority 2 (Medium)

### [PROMPT-002] Clean Legacy Scripts
**Directive:** Execute this prompt now, then proceed to `PROMPT-003`.

**Improvement ID:** `code-cleanup-legacy-001`

**Task:**
Clean up experimental and legacy scripts that are no longer part of the core backend but cause interference during testing.

**Target Files:**
- `backend/scripts/test_gemini_esports.py`
- `backend/scripts/test_gemini_vs.py`
- `backend/scripts/test_global_running.py`

**Steps:**
1. Create a `backend/scripts/legacy/` directory.
2. Move the target experimental/legacy files into this directory.
3. Update `.gitignore` or `pytest.ini` to ensure these legacy files are ignored by default test discovery.

**Implementation Details:**
- Moving files is preferred over deletion to preserve experimental history if needed later.

**Verification:**
- Confirm `pytest` no longer attempts to collect files in the `legacy/` directory.
- After completing this prompt, proceed to `[PROMPT-003]`.

---

### [PROMPT-003] Frontend Error Boundary
**Directive:** Execute this prompt now, then proceed to `PROMPT-004`.

**Improvement ID:** `feat-error-boundary-001`

**Task:**
Implement a React Error Boundary component to catch rendering errors and display a graceful fallback UI.

**Target Files:**
- `frontend/src/shared/ui/ErrorBoundary.tsx` (New)
- `frontend/src/app/App.tsx`

**Steps:**
1. Create a functional or class component `ErrorBoundary` in `shared/ui`.
2. Wrap the main application entry in `App.tsx` with this boundary.
3. Test by simulating a render error in a dashboard component.

**Implementation Details:**
- Use React 19 compatible syntax.
- Fallback UI should include a "Reload Page" button.

**Verification:**
- Verify that a simulated error doesn't crash the entire app.
- After completing this prompt, proceed to `[PROMPT-004]`.

---

## 🟢 Priority 3 (Normal)

### [PROMPT-004] Telegram Notification Templates
**Directive:** Execute this prompt now, then proceed to `OPT-1`.

**Improvement ID:** `feat-telegram-template-001`

**Task:**
Implement a template-based system for Telegram notifications to improve readability and allow for easier customization of messages.

**Target Files:**
- `backend/services/alarm/alarm_service.py`
- `backend/services/alarm/templates.py` (New)

**Steps:**
1. Create `templates.py` with predefined string templates (using f-strings or Jinja2) for different alarm types (News, Expense, Asset).
2. Refactor `alarm_service.py` to use these templates instead of hardcoded strings.
3. Enhance the templates with better emoji usage and clear headers.

**Verification:**
- Run a test alarm and verify the formatted output in the logs or via a Mocked telegram client.
- After completing this prompt, proceed to `[OPT-1]`.

---

## 🚀 Optimization (OPT)

### [OPT-1] DuckDB Query Optimization
**Directive:** Execute this prompt now, then FINISH.

**Improvement ID:** `opt-duckdb-query-001`

**Task:**
Optimize news analytics by implementing a summary table in DuckDB to avoid scanning large raw news tables repeatedly.

**Target Files:**
- `backend/services/news/duckdb_refine_queries.py`
- `backend/services/news/news_collector.py`

**Steps:**
1. Create a `news_stats` table in DuckDB.
2. Update the `news_collector.py` to refresh this table after each successful collection.
3. Update `duckdb_refine_queries.py` to read from `news_stats` for dashboard summaries.

**Verification:**
- Compare query execution time for statistics before and after the change.
- After completing this prompt, proceed to Final Completion.

---

## 🏁 Final Completion

After implementing **all prompts above**:
1. Run full system verification:
   - Frontend: `npm run typecheck` (in frontend dir)
   - Backend: `.venv/bin/pytest` (in backend dir)
2. If all pass, output the following message:
   `ALL PROMPTS COMPLETED. All pending improvement and optimization items from the latest report have been applied.`

