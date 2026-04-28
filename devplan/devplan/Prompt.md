# AI Agent Improvement Prompts

## ⚠️ Execution Rules
1. **No Text-Only Responses**: Do not just explain what you will do. You must use tools (`replace_string_in_file`, `create_file`, etc.) to modify the code.
2. **Sequential Execution**: Follow the checklist order strictly. Do not skip prompts.
3. **Verification is Mandatory**: For every prompt, run the specified verification command after the code change.
4. **English Only**: This file must remain in English. No Hangul characters allowed.
5. **Pending Items Only**: Do not re-implement already completed work. The previous backend `collect-only` fix is already done.

---

## ✅ Execution Checklist

| # | Prompt ID | Improvement ID | Title | Priority | Status |
|:---:|:---|:---|:---|:---:|:---:|
| 1 | `PROMPT-001` | `feat-error-boundary-001` | Frontend Error Boundary | P2 | ⬜ Pending |

**Distribution:** Total: 1 pending prompt | P1: 0 | P2: 1 | P3: 0 | OPT: 0

---

## 🟡 Priority 2 (Medium)

### [PROMPT-001] Frontend Error Boundary
**Directive:** Execute this prompt now, then proceed to Final Completion.

**Improvement ID:** `feat-error-boundary-001`

**Task:**
Implement a React Error Boundary component to catch rendering failures and show a graceful fallback UI instead of a full white screen.

**Target Files:**
- `frontend/src/shared/ui/ErrorBoundary.tsx` (new)
- `frontend/src/app/App.tsx`

**Steps:**
1. Create a reusable `ErrorBoundary` component in `shared/ui`.
2. Wrap the main application tree in `App.tsx` with the new boundary.
3. Provide a fallback UI with a reload action and a short user-facing message.

**Verification:**
- Simulate a render failure and verify that the app shows the fallback UI instead of crashing entirely.
- After completing this prompt, proceed to Final Completion.

---

## 🏁 Final Completion

After implementing **all prompts above**:
1. Run final verification:
   - Frontend: `npm run typecheck` in `frontend`
   - Backend: `pytest` in `backend` or the project-standard backend test command
2. If all pass, output:
   `ALL PROMPTS COMPLETED. All pending improvement and optimization items from the latest report have been applied.`
