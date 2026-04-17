#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

if [[ -n "${BACKEND_AUTH_ROTATE_PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$BACKEND_AUTH_ROTATE_PYTHON_BIN"
elif [[ -x "$PROJECT_ROOT/venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/venv/bin/python"
elif [[ -x "$PROJECT_ROOT/backend/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/backend/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

cd "$PROJECT_ROOT"
exec "$PYTHON_BIN" -m backend.scripts.rotate_auth_secrets "$@"
