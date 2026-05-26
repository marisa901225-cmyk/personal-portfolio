---
name: portfolio-ci-fix
description: Triage and fix this repository's GitHub Actions failures. Use when a PR or push fails CI, especially the frontend typecheck/tests/build job, backend test job, or secrets hygiene check.
---

# Portfolio CI Fix

Start with the failing job name or error text. If GitHub tooling is available, inspect the failed check first. Otherwise work from pasted logs.

## Local CI map

- `Secrets Hygiene Check` -> `bash scripts/check_sensitive_files.sh`
- `Frontend Typecheck` -> `npm run typecheck --prefix frontend`
- `Frontend Tests` -> `npm run test:frontend`
- `Frontend Build` -> `npm run build --prefix frontend`
- `Backend Environment and Tests` -> `npm run test:backend`

## Workflow

1. Read `.github/workflows/ci.yml` and match the failure to the smallest local command above.
2. Reproduce the failing step before editing code.
3. Fix the narrowest cause. Prefer setup, path, import, fixture, or test-data fixes before broader refactors.
4. Rerun the exact failing step.
5. If the fix changes runtime behavior, rerun the nearest broader check too.

## Repo guardrails

- Keep fixes aligned with the existing root scripts in `package.json`.
- For backend tests, prefer the repository virtualenv through `npm run test:backend` or `venv/bin/python -m pytest ...`.
- Respect `scripts/check_sensitive_files.sh`; do not work around it by tracking local env or backup files.
- Stay inside this repository. Do not inspect outside env files or machine-level secrets.

## Expected handoff

Report four things only:

- failing step
- root cause
- smallest file set changed
- verification command(s) and result
