#!/bin/bash
set -euo pipefail

# Fail if sensitive files are tracked by Git.
# Prints file paths only (never prints file contents).

SENSITIVE_PATTERNS=(
  "*.env*"
  "token*.json"
  "*.token*"
  "*token.json"
  "*.key"
  "*.secret"
  "*.credential"
  "*.db"
  "*.db-shm"
  "*.db-wal"
  "*.bak"
  "*.zip"
  "*.gz"
  "*.xlsx"
  "*.xls"
)

# Allowlist for tracked files that are known to be non-secret and required.
# Keep this list short and explicit.
ALLOWLIST_GLOBS=(
  "backend/integrations/kis/stocks_info/*.xlsx"
  "*.env.example"
  "*.env.secrets.example"
  "*.env.sample"
  "*.env.template"
  "backend/config/crontab.bak"
)

is_allowlisted() {
  local path="$1"
  for allow in "${ALLOWLIST_GLOBS[@]}"; do
    case "$path" in
      $allow) return 0 ;;
    esac
  done
  return 1
}

echo "Checking for sensitive files tracked by Git..."

FAILED=0

for pattern in "${SENSITIVE_PATTERNS[@]}"; do
  MATCHED_FILES="$(git ls-files -- "$pattern" 2>/dev/null || true)"
  if [ -z "$MATCHED_FILES" ]; then
    continue
  fi

  while IFS= read -r file; do
    [ -z "$file" ] && continue
    if is_allowlisted "$file"; then
      continue
    fi
    echo "CRITICAL: Tracked sensitive file detected (Pattern: $pattern): $file"
    FAILED=1
  done <<< "$MATCHED_FILES"
done

echo "Checking for common untracked sensitive files (warning only)..."
UNTRACKED_SENSITIVE=(
  ".env"
  "backend/.env"
)

for file in "${UNTRACKED_SENSITIVE[@]}"; do
  if [ -f "$file" ]; then
    echo "WARNING: Sensitive file exists in workspace (untracked): $file"
  fi
done

if [ "$FAILED" -eq 1 ]; then
  echo "Secrets hygiene check FAILED. Remove sensitive files from Git tracking."
  exit 1
fi

echo "Secrets hygiene check PASSED."
