# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
>
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
>
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`, `run_command`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
>
> ---
>
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**
> **If a prompt requires multiple steps, complete ALL steps before moving to the next prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | KIS Side-Effect Removal & Path Stabilization (P1-1) | P1 | ⬜ Pending |
| 2 | PROMPT-002 | KIS Token Async Update Implementation (P2-1) | P2 | ⬜ Pending |
| 3 | PROMPT-003 | News Core Refactoring & Code Debt Cleanup (P2-2) | P2 | ⬜ Pending |
| 4 | PROMPT-004 | Operation Script Standardization (P3-1) | P3 | ⬜ Pending |
| 5 | PROMPT-005 | Frontend Optimization & Bundle Efficiency (P3-2) | P3 | ⬜ Pending |
| 6 | PROMPT-006 | News Deduplication Logic Enhancement (P3-3) | P3 | ⬜ Pending |
| 7 | OPT-1 | Type Safety & Pydantic Enforcement (OPT-1) | OPT | ⬜ Pending |

**Distribution:** P1=1 | P2=2 | P3=3 | OPT=1
**Total: 7 prompts** | **Completed: 0** | **Remaining: 7**

---

## 🔴 Priority 1 (Critical) - Execute First

### [PROMPT-001] KIS Side-Effect Removal & Path Stabilization (P1-1)

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_file_content` or `create_file` to make changes.**

**Task**: Remove filesystem side-effects (directory creation at import time) and global logging overrides from KIS integration modules. Standardize configuration path usage.

**Target Files**
- `backend/integrations/kis/open_trading/kis_auth_state.py`
- `backend/integrations/kis/kis_client copy.py` (Delete/Stub)
- `backend/scripts/maintenance/test_err.py` (Delete/Stub)
- `backend/integrations/kis/open_trading/*` (Generated Endpoint Modules)

#### Instructions

1.  **Refactor `kis_auth_state.py`**:
    -   Modify `_resolve_config_root` to use `KIS_CONFIG_DIR` env var or safe default.
    -   Ensure directory creation only happens in `_ensure_config_root`, not at module level.
    -   Remove any top-level `os.makedirs` calls.

2.  **Quarantine/Stub Legacy Files**:
    -   Replace `backend/integrations/kis/kis_client copy.py` with a tombstone (deprecation warning).
    -   Replace `backend/scripts/maintenance/test_err.py` with a tombstone.

3.  **Sanitize Generated Modules**:
    -   Remove `sys.path.extend(...)` and `logging.basicConfig(...)` from all KIS generated modules (endpoint wrappers).
    -   This prevents the library from hijacking the application's logging config.

#### Implementation Details

**1. `backend/integrations/kis/open_trading/kis_auth_state.py`**
(Use this safe implementation)

```python
from __future__ import annotations

import os
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime
import yaml
from backend.core.config import settings

try:
    import fcntl
except Exception:
    fcntl = None

# ... (Include existing helper functions if needed, but ensure no side effects)

def _resolve_config_root() -> str:
    """
    Resolve KIS config directory.
    Priority 1: KIS_CONFIG_DIR env var
    Priority 2: Default to ~/KIS/config
    Note: DO NOT create directories here.
    """
    env_root = os.getenv("KIS_CONFIG_DIR")
    if env_root and env_root.strip():
        return env_root.strip()
    return os.path.join(os.path.expanduser("~"), "KIS", "config")

config_root = _resolve_config_root()
token_tmp = os.path.join(config_root, f"KIS{datetime.today().strftime('%Y%m%d')}")
token_lock = os.path.join(config_root, "KIS.token.lock")

def _ensure_config_root() -> None:
    """Create config directory only when needed (lazy)."""
    os.makedirs(config_root, exist_ok=True)

# ... (Rest of file: _token_file_lock, _load_cfg, etc. Ensure _ensure_config_root is called inside methods, not top level)
```

**2. Clean up Generated Modules**
Run a command or script to find all files in `backend/integrations/kis/open_trading/` containing `logging.basicConfig` or `sys.path.extend` and remove those lines.
(Or direct the agent to modify specific files if list is known).

**Verification**
- command: `python3 -c "import backend.integrations.kis.open_trading.kis_auth_state; print('Import success, no side effects')"`
- check: Ensure no `KIS` folder is created in home dir just by importing.

**After completing this prompt, proceed to [PROMPT-002].**

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-002] KIS Token Async Update Implementation (P2-1)

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_file_content` to make changes.**

**Task**: Implement non-blocking async token refresh in `token_store.py` to prevent API blocking during token renewal.

**Target Files**
- `backend/integrations/kis/token_store.py`

#### Instructions

1.  **Modify `backend/integrations/kis/token_store.py`**:
    -   Locate the `kis_token_refresh` logic.
    -   Add a check: if token is valid but expires soon (< 5 mins), call `_trigger_async_refresh()`.
    -   Implement `_trigger_async_refresh` using `asyncio.create_task` (if running in loop) or threading if necessary, but preferred asyncio for FastAPI.
    -   Ensure the main `get_token` returns the *current* valid token immediately while refresh happens in background.

#### Implementation Guidance

```python
# In backend/integrations/kis/token_store.py

# Add import
import asyncio

# ... inside TokenStore class ...

    def get_token(self):
        # ... logic to check expiration ...
        if self.is_expiring_soon():
            self._trigger_async_refresh()
        return self.token

    def _trigger_async_refresh(self):
        # Check if refresh task is already running
        # If not, start it
        # This prevents "Stampede"
        pass
```

**(Agent: You must write the actual full code based on the existing file structure.)**

**Verification**
- command: `pytest backend/tests/test_auth.py` (or relevant test)
- check: Ensure `get_token` makes a background call and returns fast.

**After completing this prompt, proceed to [PROMPT-003].**

### [PROMPT-003] Esports Module Refactoring & Extensibility (P2-2)

**⏱️ Execute this prompt now, then proceed to PROMPT-004**

> **🚨 REQUIRED: Use `replace_file_content` or `multi_replace_file_content` to make changes.**

**Task**: Refactor the e-sports collection module to remove hardcoded game-specific logic (LoL, Valorant) and implement a registry-based pattern to easily support new games like PUBG.

**Target Files**
- `backend/services/news/core.py`
- `backend/services/news/esports.py`
- `backend/core/esports_config.py` (New File)

#### Instructions

1.  **Create `backend/core/esports_config.py`**:
    -   Define a `GAME_REGISTRY` dictionary containing configuration for each game:
        -   `id` (e.g., `league-of-legends`, `valorant`, `pubg`)
        -   `display_name` (e.g., `LoL`, `Valorant`, `PUBG`)
        -   `interest_keywords` (Moved from `esports.py`)
        -   `tagging_rules` (Logic to determine `league_tag`)

2.  **Refactor `backend/services/news/esports.py`**:
    -   Replace the hardcoded `is_lol`/`is_valorant` checks with a loop over `GAME_REGISTRY`.
    -   Use the registry to fetch schedules and results for all enabled games.
    -   Consolidate `is_noise` and `get_display_league_tag` to use registry-defined rules.
    -   Ensure the code is "PUBG Ready" (adding PUBG to the registry should allow its collection).

3.  **Clean up `backend/services/news/core.py`**:
    -   Implement the logic for remaining `# TODO` items.
    -   Move `NAVER_ESPORTS_QUERIES` and other hardcoded keywords to the registry or a consolidated `CONSTANTS` block.

**Verification**
- command: `grep "is_lol" backend/services/news/esports.py` -> Should find no occurrences of hardcoded game checks.
- command: `python3 -m unittest backend/tests/test_news.py` (if exists) or manual syntax check.

**After completing this prompt, proceed to [PROMPT-004].**

---

## 🟢 Priority 3 (Medium) - Execute Third

### [PROMPT-004] Operation Script Standardization (P3-1)

**⏱️ Execute this prompt now, then proceed to PROMPT-005**

> **🚨 REQUIRED: Use `replace_file_content` or `create_file` to make changes.**

**Task**: Standardize the execution interface for backend scripts (logging, confirmation prompts) and document them.

**Target Files**
- `backend/scripts/README.md` (Create/Update)
- `backend/scripts/common.py` (Update)
- `backend/scripts/manage.py` (Update usage of common utils)

#### Instructions

1.  **Refactor `backend/scripts/common.py`**:
    -   Ensure there is a standard `setup_script_logger(name)` function.
    -   Ensure there is a `confirm_action(msg)` function for dangerous operations (writes/deletes).

2.  **Update `backend/scripts/manage.py`**:
    -   Use `setup_script_logger` from `common.py`.
    -   Add confirmation prompt before running migrations if environment is 'production'.

3.  **Create/Update `backend/scripts/README.md`**:
    -   List available scripts (`manage.py`, `scheduler/run.py`, etc.).
    -   Document environment variables intended for scripts.
    -   Add a "Safety First" section about DRY-RUNs.

**Verification**
- command: `python3 backend/scripts/manage.py --help` (Check if logging format matches standard).
- file: Check `backend/scripts/README.md` existence.

**After completing this prompt, proceed to [PROMPT-005].**

### [PROMPT-005] Frontend Optimization & Bundle Efficiency (P3-2)

**⏱️ Execute this prompt now, then proceed to PROMPT-006**

> **🚨 REQUIRED: Use `replace_file_content` to make changes.**

**Task**: Improve frontend load performance by splitting chunks and lazily loading routes.

**Target Files**
- `frontend/vite.config.ts`
- `frontend/src/App.tsx` (or main Router file)

#### Instructions

1.  **Update `frontend/vite.config.ts`**:
    -   Configure `build.rollupOptions.output.manualChunks` to separate vendor libraries (e.g., `react`, `react-dom`, `recharts` or huge libs) into separate chunks.

2.  **Update `frontend/src/App.tsx`**:
    -   Identify heavy routes (e.g., Dashboards, Heavy Charts).
    -   Wrap them with `React.lazy(() => import(...))` and `Suspense`.

**Verification**
- command: `cd frontend && npm run build`
- check: Output showing multiple chunks (vendors, index, etc.) instead of one giant bundle.

**After completing this prompt, proceed to [PROMPT-006].**

### [PROMPT-006] News Deduplication Logic Enhancement (P3-3)

**⏱️ Execute this prompt now, then proceed to [OPT-1]**

> **🚨 REQUIRED: Use `replace_file_content` to make changes.**

**Task**: Refine the deduplication logic in DuckDB refinement steps or News Core.

**Target Files**
- `backend/services/duckdb_refine.py` (or where SQL/Dedup happens)
- `backend/services/news/core.py`

#### Instructions

1.  **Enhance Deduplication**:
    -   If currently using distinct URL, add a check for "Similar Title" (normalized strings).
    -   Implement a helper function to normalize strings (remove special chars, lowercase) before comparison.
    -   Update the query or Python logic to filter out duplicates based on this normalized key.

**Verification**
- Check logic in `duckdb_refine.py`.

**After completing this prompt, proceed to [OPT-1].**

---

## 🚀 Optimization (OPT)

### [OPT-1] Type Safety & Pydantic Enforcement

**⏱️ Execute this prompt now, then FINISH.**

> **🚨 REQUIRED: Use `replace_file_content` to make changes.**

**Task**: Remove `Any` types from critical paths and ensure Pydantic models are used for router payloads.

**Target Files**
- `backend/routers/handlers/query_handler.py`
- `backend/misc/*` (Pick one utils file to improve)

#### Instructions

1.  **Refactor `query_handler.py`**:
    -   Replace `Dict[str, Any]` with specific Pydantic models or TypedDicts where possible.
    -   Ensure return types are annotated.

2.  **Misc Utils**:
    -   Add type hints to a selected utility file in `backend/misc`.

**Verification**
- command: `mypy backend/routers/handlers/query_handler.py` (If mypy installed) or visual check.

---

# ✅ ALL PROMPTS COMPLETED

**Congratulations! You have completed the Project Improvement Plan.**
**Please verify the application stability one last time:**
1. `docker-compose up -d`
2. Check logs: `docker-compose logs -f`
3. Verify Frontend: `http://localhost:5173`

**End of Execution.**

