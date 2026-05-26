---
name: portfolio-pr-review
description: Address PR review comments for this repository with minimal diffs and repo-appropriate verification. Use when review feedback, requested changes, or unresolved comments need to be turned into focused fixes.
---

# Portfolio PR Review

Use this when the task is "apply the review" rather than "review the whole PR".

## Workflow

1. Gather review comments or requested changes.
2. Group them by behavior and touched file instead of answering one comment at a time.
3. Ignore already-resolved noise unless the user asks to revisit it.
4. Apply the smallest patch that satisfies the review intent and preserves current behavior elsewhere.
5. Run the lightest meaningful verification for the touched area.

## Verification guide

- Frontend typing issue -> `npm run typecheck --prefix frontend`
- Frontend test or component behavior -> `npm run test:frontend`
- Frontend build or routing issue -> `npm run build --prefix frontend`
- Backend behavior or API contract -> `npm run test:backend` or a narrower `venv/bin/python -m pytest ...`
- CI-only complaint -> follow the `portfolio-ci-fix` skill

## Repo guardrails

- Prefer targeted fixes over refactors.
- Add or update tests when the review points at missing coverage.
- Do not relax assertions, types, or validation just to make a comment disappear.
- If multiple comments point to the same root cause, fix the root cause once and call that out.

## Expected handoff

Summarize by comment group:

- what changed
- why that resolves the feedback
- what was verified
