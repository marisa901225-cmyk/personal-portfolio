---
name: portfolio-test-triage
description: Reproduce and classify failing tests in this repository before changing code. Use when tests are red locally or in CI and you need a small, evidence-based fix path.
---

# Portfolio Test Triage

This skill is for "understand the failure first", not "rewrite tests until green".

## Reproduction commands

- Frontend full suite: `npm run test:frontend`
- Frontend single file: `cd frontend && npx vitest run test/<file>.test.tsx`
- Backend full suite: `npm run test:backend`
- Backend single test: `cd backend && ../venv/bin/python -m pytest tests/<file>.py::<test_name> -v`

## Classification order

1. Reproduce the narrowest failing test.
2. Classify the failure before editing:
   - product regression
   - stale test expectation
   - fixture or test-data issue
   - environment or path setup issue
   - flaky timing or ordering issue
3. Trace the owning runtime file and the owning test file.
4. Fix the smallest root cause.
5. Rerun the exact failing test, then the nearest broader suite if needed.

## Repo guardrails

- Do not hide failures by weakening assertions unless behavior intentionally changed.
- Prefer existing fixtures and helpers over ad hoc setup.
- When a CI failure does not reproduce locally, compare against `.github/workflows/ci.yml` and repo scripts before assuming nondeterminism.
- If the issue is truly environmental and cannot be fixed in-repo, stop with a crisp blocker instead of guessing.

## Expected handoff

Return:

- failure classification
- root cause file(s)
- fix path taken
- exact rerun command(s)
