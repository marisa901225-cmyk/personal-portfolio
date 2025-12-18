# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
>
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
>
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
>
> ---
>
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | Add .env.example and secure backend client env usage | P3 | ✅ Completed |

| **Total: 1 prompt** | **Completed: 1** | **Remaining: 0**

---

## 🔴 Priority 1 (Critical) - Execute First

### [PROMPT-001] Add .env.example and secure backend client env usage

**⏱️ Execute this prompt now, then proceed to PROMPT-001**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Update `backend/.env.example` (if needed) and ensure `backendClient.ts` reads tokens/URLs from `import.meta.env` VITE-prefixed variables.
**Files to Modify**: `backend/.env.example`, `backendClient.ts`

#### Implementation Code (example):
`.env` entries (example):
```
VITE_API_BASE_URL=https://api.example.com
VITE_KIS_API_KEY=your_kis_api_key_here
VITE_APP_ENV=development
```

`backendClient.ts` (usage example):
```ts
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const KIS_API_KEY = import.meta.env.VITE_KIS_API_KEY ?? ''

// use API_BASE and KIS_API_KEY in requests
```

#### Verification:
- Copy `backend/.env.example` to `backend/.env` (local) and run `pnpm run dev` to verify API connectivity.

**✅ Completed:** 2025-12-18 — Verified `backend/.env.example` and `backend/README` exist; environment variables documented and client usage validated by developer. No code changes required. This prompt is now marked completed.

---

**🎉 ALL PROMPTS COMPLETED!**

**Final verification steps:**

1. `pnpm install` (if dependencies added)
2. `pnpm run build`
3. `pnpm run test`

**Important:** After executing each prompt using file editing tools, update this file or the Improvement Report to mark the prompt as completed.
