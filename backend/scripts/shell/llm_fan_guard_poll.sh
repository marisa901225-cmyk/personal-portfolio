#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

GUARD_SCRIPT="${LLM_FAN_GUARD_SCRIPT:-$SCRIPT_DIR/llm_fan_guard.sh}"
POLL_INTERVAL_SEC="${LLM_FAN_GUARD_POLL_INTERVAL_SEC:-5}"
POLL_DURATION_SEC="${LLM_FAN_GUARD_POLL_DURATION_SEC:-60}"
CRON_LOG_FILE="${LLM_FAN_GUARD_CRON_LOG_FILE:-$PROJECT_ROOT/backend/logs/llm_fan_guard.log}"

mkdir -p "$(dirname "$CRON_LOG_FILE")"

if (( POLL_INTERVAL_SEC < 1 )); then
  echo "LLM_FAN_GUARD_POLL_INTERVAL_SEC must be >= 1" >&2
  exit 2
fi

if (( POLL_DURATION_SEC < POLL_INTERVAL_SEC )); then
  echo "LLM_FAN_GUARD_POLL_DURATION_SEC must be >= interval" >&2
  exit 2
fi

end_epoch="$(($(date +%s) + POLL_DURATION_SEC))"

while (( $(date +%s) < end_epoch )); do
  if ! bash "$GUARD_SCRIPT" >> "$CRON_LOG_FILE" 2>&1; then
    printf '%s [LLM-FAN-GUARD-POLL] guard failed\n' "$(date +"%Y-%m-%d %H:%M:%S %Z")" >> "$CRON_LOG_FILE"
  fi

  next_epoch="$(($(date +%s) + POLL_INTERVAL_SEC))"
  if (( next_epoch > end_epoch )); then
    break
  fi
  sleep "$POLL_INTERVAL_SEC"
done
