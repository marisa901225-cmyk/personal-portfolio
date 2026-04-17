#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

LOG_FILE="${LLM_FAN_GUARD_LOG_FILE:-$PROJECT_ROOT/backend/logs/llm_fan_guard.log}"
STATE_FILE="${LLM_FAN_GUARD_STATE_FILE:-$PROJECT_ROOT/backend/data/llm_fan_guard_state.json}"
LOCK_FILE="${LLM_FAN_GUARD_LOCK_FILE:-/tmp/llm_fan_guard.lock}"
SCHEDULE_SCRIPT="${LLM_FAN_GUARD_SCHEDULE_SCRIPT:-$PROJECT_ROOT/backend/scripts/shell/llm_service_schedule.sh}"
SENSORS_BIN="${LLM_FAN_GUARD_SENSORS_BIN:-sensors}"

ENABLED="${LLM_FAN_GUARD_ENABLED:-1}"
THRESHOLD_RPM="${LLM_FAN_GUARD_THRESHOLD_RPM:-1600}"
COOLDOWN_SEC="${LLM_FAN_GUARD_COOLDOWN_SEC:-3600}"
SENSOR_PATTERN="${LLM_FAN_GUARD_SENSOR_PATTERN:-}"
START_MAX_TEMP_C="${LLM_FAN_GUARD_START_MAX_TEMP_C:-0}"
START_RETRY_SEC="${LLM_FAN_GUARD_START_RETRY_SEC:-300}"
TEMP_SENSOR_PATTERN="${LLM_FAN_GUARD_TEMP_SENSOR_PATTERN:-$SENSOR_PATTERN}"
NOW_EPOCH="${LLM_FAN_GUARD_NOW_EPOCH:-$(date +%s)}"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$STATE_FILE")"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

format_epoch() {
  date -d "@$1" +"%Y-%m-%d %H:%M:%S %Z"
}

log() {
  printf '%s [LLM-FAN-GUARD] %s\n' "$(timestamp)" "$1" >> "$LOG_FILE"
}

read_state_number() {
  local key="$1"
  local default_value="${2:-0}"
  local value=""

  if [[ -f "$STATE_FILE" ]]; then
    value="$(grep -o "\"$key\": [0-9][0-9]*" "$STATE_FILE" | head -n 1 | grep -o "[0-9][0-9]*" || true)"
  fi

  if [[ -n "$value" ]]; then
    printf '%s' "$value"
  else
    printf '%s' "$default_value"
  fi
}

write_state() {
  local cooldown_active="$1"
  local cooldown_started_epoch="$2"
  local cooldown_until_epoch="$3"
  local last_trigger_rpm="$4"
  local last_seen_rpm="$5"
  local last_action="$6"
  local tmp_file

  tmp_file="$(mktemp "${STATE_FILE}.XXXXXX")"
  printf '{\n' > "$tmp_file"
  printf '  "cooldown_active": %s,\n' "$cooldown_active" >> "$tmp_file"
  printf '  "cooldown_started_epoch": %s,\n' "$cooldown_started_epoch" >> "$tmp_file"
  printf '  "cooldown_until_epoch": %s,\n' "$cooldown_until_epoch" >> "$tmp_file"
  printf '  "last_trigger_rpm": %s,\n' "$last_trigger_rpm" >> "$tmp_file"
  printf '  "last_seen_rpm": %s,\n' "$last_seen_rpm" >> "$tmp_file"
  printf '  "last_action": "%s",\n' "$last_action" >> "$tmp_file"
  printf '  "updated_at_epoch": %s\n' "$NOW_EPOCH" >> "$tmp_file"
  printf '}\n' >> "$tmp_file"
  mv "$tmp_file" "$STATE_FILE"
}

max_fan_rpm_from_output() {
  awk -v pattern="$SENSOR_PATTERN" '
    BEGIN {
      RS = ""
      max = -1
    }
    {
      if (pattern != "" && index($0, pattern) == 0) {
        next
      }

      line_count = split($0, lines, /\n/)
      for (i = 1; i <= line_count; i++) {
        if (lines[i] ~ /fan[0-9]+:[[:space:]]*[0-9]+/) {
          rpm_text = lines[i]
          sub(/.*fan[0-9]+:[[:space:]]*/, "", rpm_text)
          sub(/[^0-9].*$/, "", rpm_text)
          rpm = rpm_text + 0
          if (rpm > max) {
            max = rpm
          }
        }
      }
    }
    END {
      if (max >= 0) {
        print max
      }
    }
  '
}

max_temp_c_from_output() {
  awk -v pattern="$TEMP_SENSOR_PATTERN" '
    BEGIN {
      RS = ""
      max = -1
    }
    {
      if (pattern != "" && index($0, pattern) == 0) {
        next
      }

      line_count = split($0, lines, /\n/)
      for (i = 1; i <= line_count; i++) {
        if (lines[i] ~ /^[[:space:]]*[^:]+:[[:space:]]*\+[0-9]+(\.[0-9]+)?/ && lines[i] ~ /C/) {
          temp_text = lines[i]
          sub(/^[[:space:]]*[^:]+:[[:space:]]*\+/, "", temp_text)
          sub(/[^0-9.].*$/, "", temp_text)
          if (temp_text != "") {
            temp = temp_text + 0
            if (temp > max) {
              max = temp
            }
          }
        }
      }
    }
    END {
      if (max >= 0) {
        print max
      }
    }
  '
}

temp_is_at_or_above_threshold() {
  local current_temp="$1"
  local threshold_temp="$2"

  awk -v current="$current_temp" -v threshold="$threshold_temp" 'BEGIN { exit !(current + 0 >= threshold + 0) }'
}

temp_threshold_enabled() {
  local threshold_temp="$1"

  awk -v threshold="$threshold_temp" 'BEGIN { exit !(threshold + 0 > 0) }'
}

run_schedule() {
  local action="$1"

  if [[ "$action" == "start" ]]; then
    env LLM_SCHEDULE_ALLOW_WEEKEND_START=1 bash "$SCHEDULE_SCRIPT" start
  else
    bash "$SCHEDULE_SCRIPT" stop
  fi
}

if [[ "$ENABLED" != "1" ]]; then
  exit 0
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another guard process is already running; skipping this tick"
  exit 0
fi

cooldown_active="$(read_state_number cooldown_active 0)"
cooldown_started_epoch="$(read_state_number cooldown_started_epoch 0)"
cooldown_until_epoch="$(read_state_number cooldown_until_epoch 0)"
last_trigger_rpm="$(read_state_number last_trigger_rpm 0)"

if [[ "$cooldown_active" == "1" ]]; then
  if (( NOW_EPOCH < cooldown_until_epoch )); then
    exit 0
  fi

  if temp_threshold_enabled "$START_MAX_TEMP_C"; then
    if sensors_output="$("$SENSORS_BIN" 2>/dev/null)"; then
      start_temp_c="$(printf '%s\n' "$sensors_output" | max_temp_c_from_output)"
      if [[ -n "$start_temp_c" ]] && temp_is_at_or_above_threshold "$start_temp_c" "$START_MAX_TEMP_C"; then
        next_retry_epoch="$((NOW_EPOCH + START_RETRY_SEC))"
        write_state 1 "$cooldown_started_epoch" "$next_retry_epoch" "$last_trigger_rpm" 0 "start_deferred_hot"
        log "restart deferred: sensor temp ${start_temp_c}C reached start limit ${START_MAX_TEMP_C}C; retry after $(format_epoch "$next_retry_epoch")"
        exit 0
      fi

      if [[ -z "$start_temp_c" ]]; then
        log "restart temperature gate skipped; no temperature lines matched${TEMP_SENSOR_PATTERN:+ for pattern '$TEMP_SENSOR_PATTERN'}"
      fi
    else
      log "restart temperature gate skipped; failed to read sensors output from $SENSORS_BIN"
    fi
  fi

  log "cooldown expired at $(format_epoch "$cooldown_until_epoch"); restarting LLM services"
  if run_schedule start; then
    write_state 0 0 0 "$last_trigger_rpm" 0 "start"
    log "LLM services restarted after cooldown"
    exit 0
  fi

  write_state 1 "$cooldown_started_epoch" "$cooldown_until_epoch" "$last_trigger_rpm" 0 "start_failed"
  log "failed to restart LLM services after cooldown"
  exit 1
fi

if ! sensors_output="$("$SENSORS_BIN" 2>/dev/null)"; then
  log "failed to read sensors output from $SENSORS_BIN"
  write_state 0 0 0 0 0 "sensors_error"
  exit 0
fi

max_rpm="$(printf '%s\n' "$sensors_output" | max_fan_rpm_from_output)"
if [[ -z "$max_rpm" ]]; then
  log "no fan RPM lines matched from sensors output${SENSOR_PATTERN:+ for pattern '$SENSOR_PATTERN'}"
  write_state 0 0 0 0 0 "no_fan_data"
  exit 0
fi

if (( max_rpm < THRESHOLD_RPM )); then
  exit 0
fi

cooldown_until_epoch="$((NOW_EPOCH + COOLDOWN_SEC))"
log "fan RPM $max_rpm exceeded threshold $THRESHOLD_RPM; stopping LLM services for ${COOLDOWN_SEC}s"

if run_schedule stop; then
  write_state 1 "$NOW_EPOCH" "$cooldown_until_epoch" "$max_rpm" "$max_rpm" "stop"
  log "LLM services stopped; cooldown runs until $(format_epoch "$cooldown_until_epoch")"
  exit 0
fi

write_state 0 0 0 "$max_rpm" "$max_rpm" "stop_failed"
log "failed to stop LLM services after high fan RPM $max_rpm"
exit 1
