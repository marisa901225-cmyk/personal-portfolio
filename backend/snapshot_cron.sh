#!/usr/bin/env bash
set -euo pipefail

# Simple helper script to create a portfolio snapshot via backend API.
# - Use together with cron/systemd timer.
# - Requires API_TOKEN environment variable to be set to the same value
#   as backend's API_TOKEN.
#
# Optional:
#   BACKEND_URL (default: http://127.0.0.1:8000)

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
API_TOKEN="${API_TOKEN:-}"

if [[ -z "${API_TOKEN}" ]]; then
  echo "ERROR: API_TOKEN is not set. Export API_TOKEN before running this script." >&2
  exit 1
fi

curl -sS -X POST \
  -H "X-API-Token: ${API_TOKEN}" \
  "${BACKEND_URL%/}/api/portfolio/snapshots"

