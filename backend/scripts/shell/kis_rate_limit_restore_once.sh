#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

COMPOSE_FILE="${KIS_RATE_LIMIT_RESTORE_COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.yml}"
ENV_FILE="${KIS_RATE_LIMIT_RESTORE_ENV_FILE:-$PROJECT_ROOT/backend/.env}"
LOG_FILE="${KIS_RATE_LIMIT_RESTORE_LOG_FILE:-$PROJECT_ROOT/backend/logs/kis_rate_limit_restore.log}"
STATE_FILE="${KIS_RATE_LIMIT_RESTORE_STATE_FILE:-$PROJECT_ROOT/backend/data/kis_rate_limit_restore_state.json}"
LOCK_FILE="${KIS_RATE_LIMIT_RESTORE_LOCK_FILE:-/tmp/kis_rate_limit_restore.lock}"
DOCKER_BIN="${KIS_RATE_LIMIT_RESTORE_DOCKER_BIN:-/usr/bin/docker}"
CRON_BLOCK_NAME="${KIS_RATE_LIMIT_RESTORE_CRON_BLOCK_NAME:-MYASSET_KIS_RATE_LIMIT_RESTORE}"

# Default: cut over before market hours when the prod REST limit drops from 20/sec to 18/sec.
RESTORE_AT="${KIS_RATE_LIMIT_RESTORE_AT:-2026-04-20 00:00:00}"
RESTORE_TZ="${KIS_RATE_LIMIT_RESTORE_TZ:-Asia/Seoul}"
TARGET_RATE_LIMIT="${KIS_RATE_LIMIT_RESTORE_TARGET:-18}"
TARGET_SERVICES="${KIS_RATE_LIMIT_RESTORE_SERVICES:-backend-api news-scheduler sync-prices}"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

log() {
  printf '%s [KIS-RATE-RESTORE] %s\n' "$(timestamp)" "$1" >> "$LOG_FILE"
}

restore_epoch() {
  TZ="$RESTORE_TZ" date -d "$RESTORE_AT" +%s
}

read_state_flag() {
  local key="$1"
  if [[ ! -f "$STATE_FILE" ]]; then
    return 1
  fi
  grep -q "\"$key\": true" "$STATE_FILE"
}

state_matches_current_plan() {
  if [[ ! -f "$STATE_FILE" ]]; then
    return 1
  fi
  grep -q "\"restore_at\": \"$RESTORE_AT\"" "$STATE_FILE" \
    && grep -q "\"restore_tz\": \"$RESTORE_TZ\"" "$STATE_FILE" \
    && grep -q "\"target_rate_limit\": $TARGET_RATE_LIMIT" "$STATE_FILE"
}

write_state_done() {
  local tmp_file
  tmp_file="$(mktemp "${STATE_FILE}.XXXXXX")"
  cat > "$tmp_file" <<EOF
{
  "done": true,
  "restored_at": "$(timestamp)",
  "restore_at": "$RESTORE_AT",
  "restore_tz": "$RESTORE_TZ",
  "target_rate_limit": $TARGET_RATE_LIMIT,
  "services": "$(printf '%s' "$TARGET_SERVICES")"
}
EOF
  mv "$tmp_file" "$STATE_FILE"
}

ensure_rate_limit_value() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "env file not found: $ENV_FILE" >&2
    exit 1
  fi

  if grep -q '^KIS_REST_RATE_LIMIT_PER_SEC=' "$ENV_FILE"; then
    sed -i "s/^KIS_REST_RATE_LIMIT_PER_SEC=.*/KIS_REST_RATE_LIMIT_PER_SEC=$TARGET_RATE_LIMIT/" "$ENV_FILE"
  else
    printf '\nKIS_REST_RATE_LIMIT_PER_SEC=%s\n' "$TARGET_RATE_LIMIT" >> "$ENV_FILE"
  fi
}

run_compose() {
  "$DOCKER_BIN" compose -f "$COMPOSE_FILE" "$@"
}

cleanup_crontab_block() {
  local tmp_file
  local begin_marker="# BEGIN $CRON_BLOCK_NAME"
  local end_marker="# END $CRON_BLOCK_NAME"

  if ! command -v crontab >/dev/null 2>&1; then
    return 0
  fi

  tmp_file="$(mktemp)"
  if ! crontab -l 2>/dev/null | awk -v begin="$begin_marker" -v end="$end_marker" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    !skip { print }
  ' > "$tmp_file"; then
    rm -f "$tmp_file"
    return 1
  fi

  crontab "$tmp_file"
  rm -f "$tmp_file"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  exit 0
fi

if read_state_flag done && state_matches_current_plan; then
  exit 0
fi

NOW_EPOCH="${KIS_RATE_LIMIT_RESTORE_NOW_EPOCH:-$(date +%s)}"
RESTORE_EPOCH="$(restore_epoch)"

if (( NOW_EPOCH < RESTORE_EPOCH )); then
  exit 0
fi

log "restore window reached; updating KIS_REST_RATE_LIMIT_PER_SEC to $TARGET_RATE_LIMIT"
ensure_rate_limit_value

read -r -a services_to_restart <<< "$TARGET_SERVICES"
log "restarting services: ${services_to_restart[*]}"
run_compose up -d --force-recreate "${services_to_restart[@]}" >> "$LOG_FILE" 2>&1

write_state_done

if cleanup_crontab_block; then
  log "cron block removed after successful restore"
else
  log "warning: failed to remove cron block automatically"
fi

log "restore completed successfully"
