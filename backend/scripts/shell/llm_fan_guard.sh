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
STOP_DELAY_SEC="${LLM_FAN_GUARD_STOP_DELAY_SEC:-0}"
CRITICAL_THRESHOLD_RPM="${LLM_FAN_GUARD_CRITICAL_THRESHOLD_RPM:-2000}"
CRITICAL_STOP_DELAY_SEC="${LLM_FAN_GUARD_CRITICAL_STOP_DELAY_SEC:-0}"
COOLDOWN_SEC="${LLM_FAN_GUARD_COOLDOWN_SEC:-0}"
RESTART_DELAY_SEC="${LLM_FAN_GUARD_RESTART_DELAY_SEC:-10}"
SENSOR_PATTERN="${LLM_FAN_GUARD_SENSOR_PATTERN:-}"
START_MAX_TEMP_C="${LLM_FAN_GUARD_START_MAX_TEMP_C:-88}"
START_RETRY_SEC="${LLM_FAN_GUARD_START_RETRY_SEC:-300}"
STARTUP_GRACE_SEC="${LLM_FAN_GUARD_STARTUP_GRACE_SEC:-600}"
TEMP_SENSOR_PATTERN="${LLM_FAN_GUARD_TEMP_SENSOR_PATTERN:-$SENSOR_PATTERN}"
NOW_EPOCH="${LLM_FAN_GUARD_NOW_EPOCH:-$(date +%s)}"
DAY_RELAX_ENABLED="${LLM_FAN_GUARD_DAY_RELAX_ENABLED:-1}"
DAY_RELAX_START="${LLM_FAN_GUARD_DAY_RELAX_START:-08:00}"
DAY_RELAX_END="${LLM_FAN_GUARD_DAY_RELAX_END:-18:00}"
DAY_RELAX_REQUIRE_TRADING_DAY="${LLM_FAN_GUARD_DAY_RELAX_REQUIRE_TRADING_DAY:-1}"
PYTHON_BIN="${LLM_FAN_GUARD_PYTHON_BIN:-$PROJECT_ROOT/venv/bin/python}"
NOW_DATE="${LLM_FAN_GUARD_NOW_DATE:-$(date -d "@$NOW_EPOCH" +%Y%m%d)}"
NOW_WEEKDAY="${LLM_FAN_GUARD_NOW_WEEKDAY:-$(date -d "@$NOW_EPOCH" +%u)}"
NOW_HHMM="${LLM_FAN_GUARD_NOW_HHMM:-$(date -d "@$NOW_EPOCH" +%H:%M)}"

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
  local high_rpm_started_epoch="$6"
  local last_action="$7"
  local persisted_last_start_epoch="${8:-${current_last_start_epoch:-0}}"
  local tmp_file

  tmp_file="$(mktemp "${STATE_FILE}.XXXXXX")"
  printf '{\n' > "$tmp_file"
  printf '  "cooldown_active": %s,\n' "$cooldown_active" >> "$tmp_file"
  printf '  "cooldown_started_epoch": %s,\n' "$cooldown_started_epoch" >> "$tmp_file"
  printf '  "cooldown_until_epoch": %s,\n' "$cooldown_until_epoch" >> "$tmp_file"
  printf '  "last_trigger_rpm": %s,\n' "$last_trigger_rpm" >> "$tmp_file"
  printf '  "last_seen_rpm": %s,\n' "$last_seen_rpm" >> "$tmp_file"
  printf '  "high_rpm_started_epoch": %s,\n' "$high_rpm_started_epoch" >> "$tmp_file"
  printf '  "last_start_epoch": %s,\n' "$persisted_last_start_epoch" >> "$tmp_file"
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

hhmm_to_minutes() {
  local value="$1"
  local hour minute

  if [[ ! "$value" =~ ^[0-9]{1,2}:[0-9]{2}$ ]]; then
    echo "-1"
    return
  fi

  hour="${value%%:*}"
  minute="${value##*:}"
  echo "$((10#$hour * 60 + 10#$minute))"
}

is_day_relax_trading_day() {
  local result

  [[ "$DAY_RELAX_REQUIRE_TRADING_DAY" == "1" ]] || return 0
  if [[ ! -x "$PYTHON_BIN" ]]; then
    log "낮완화 영업일확인 스킵 python=$PYTHON_BIN"
    return 0
  fi

  result="$(
    PYTHONPATH="$PROJECT_ROOT" "$PYTHON_BIN" - "$NOW_DATE" 2>/dev/null <<'PY'
import sys
from datetime import datetime

from backend.scripts.run_pension_rebalance_scheduler import _is_scheduled_trading_day

try:
    now = datetime.strptime(sys.argv[1], "%Y%m%d")
except (IndexError, ValueError):
    print("UNKNOWN")
    raise SystemExit(0)

print("OPEN" if _is_scheduled_trading_day(now) else "CLOSED")
PY
  )"

  case "$result" in
    OPEN)
      return 0
      ;;
    CLOSED)
      log "낮완화 비활성 휴장일 date=${NOW_DATE}"
      return 1
      ;;
    *)
      log "낮완화 영업일확인 불명 result=${result:-empty}; 평일기준 허용"
      return 0
      ;;
  esac
}

in_day_relax_window() {
  local start_min end_min now_min

  [[ "$DAY_RELAX_ENABLED" == "1" ]] || return 1
  [[ "$NOW_WEEKDAY" =~ ^[1-5]$ ]] || return 1
  is_day_relax_trading_day || return 1

  start_min="$(hhmm_to_minutes "$DAY_RELAX_START")"
  end_min="$(hhmm_to_minutes "$DAY_RELAX_END")"
  now_min="$(hhmm_to_minutes "$NOW_HHMM")"

  if (( start_min < 0 || end_min < 0 || now_min < 0 )); then
    return 1
  fi

  if (( start_min <= end_min )); then
    (( now_min >= start_min && now_min < end_min ))
  else
    (( now_min >= start_min || now_min < end_min ))
  fi
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
  log "중복실행 스킵"
  exit 0
fi

cooldown_active="$(read_state_number cooldown_active 0)"
cooldown_started_epoch="$(read_state_number cooldown_started_epoch 0)"
cooldown_until_epoch="$(read_state_number cooldown_until_epoch 0)"
last_trigger_rpm="$(read_state_number last_trigger_rpm 0)"
last_seen_rpm="$(read_state_number last_seen_rpm 0)"
high_rpm_started_epoch="$(read_state_number high_rpm_started_epoch 0)"
current_last_start_epoch="$(read_state_number last_start_epoch 0)"

if [[ "$cooldown_active" == "1" ]]; then
  if (( NOW_EPOCH < cooldown_until_epoch )); then
    exit 0
  fi

  if temp_threshold_enabled "$START_MAX_TEMP_C"; then
    if sensors_output="$("$SENSORS_BIN" 2>/dev/null)"; then
      start_temp_c="$(printf '%s\n' "$sensors_output" | max_temp_c_from_output)"
      if [[ -n "$start_temp_c" ]] && temp_is_at_or_above_threshold "$start_temp_c" "$START_MAX_TEMP_C"; then
        next_retry_epoch="$((NOW_EPOCH + START_RETRY_SEC))"
        write_state 1 "$cooldown_started_epoch" "$next_retry_epoch" "$last_trigger_rpm" 0 0 "start_deferred_hot"
        log "temp=${start_temp_c}C 제한=${START_MAX_TEMP_C}C; LLM시작연기 retry=$(format_epoch "$next_retry_epoch")"
        exit 0
      fi

      if [[ -z "$start_temp_c" ]]; then
        log "온도확인 스킵 매칭없음${TEMP_SENSOR_PATTERN:+ pattern=$TEMP_SENSOR_PATTERN}"
      fi
    else
      log "온도확인 스킵 sensors실패 bin=$SENSORS_BIN"
    fi
  fi

  log "재시작대기 종료 at=$(format_epoch "$cooldown_until_epoch"); LLM시작"
  if run_schedule start; then
    write_state 0 0 0 "$last_trigger_rpm" 0 0 "start" "$NOW_EPOCH"
    log "LLM시작 완료"
    exit 0
  fi

  write_state 1 "$cooldown_started_epoch" "$cooldown_until_epoch" "$last_trigger_rpm" 0 0 "start_failed"
  log "LLM시작 실패"
  exit 1
fi

if ! sensors_output="$("$SENSORS_BIN" 2>/dev/null)"; then
  log "sensors실패 bin=$SENSORS_BIN"
  write_state 0 0 0 0 0 0 "sensors_error"
  exit 0
fi

max_rpm="$(printf '%s\n' "$sensors_output" | max_fan_rpm_from_output)"
if [[ -z "$max_rpm" ]]; then
  log "rpm없음${SENSOR_PATTERN:+ pattern=$SENSOR_PATTERN}"
  write_state 0 0 0 0 0 0 "no_fan_data"
  exit 0
fi

if (( max_rpm < THRESHOLD_RPM )); then
  if (( high_rpm_started_epoch > 0 || last_seen_rpm >= THRESHOLD_RPM )); then
    write_state 0 0 0 "$last_trigger_rpm" "$max_rpm" 0 "rpm_normal"
    log "rpm=$max_rpm 기준=$THRESHOLD_RPM 정상; 관찰초기화"
  fi
  exit 0
fi

if in_day_relax_window; then
  write_state 0 0 0 "$last_trigger_rpm" "$max_rpm" 0 "day_relax" "$current_last_start_epoch"
  log "rpm=$max_rpm 낮완화 date=${NOW_DATE} time=${NOW_HHMM}; LLM유지"
  exit 0
fi

active_threshold_rpm="$THRESHOLD_RPM"
active_stop_delay_sec="$STOP_DELAY_SEC"
threshold_label="threshold"
critical_threshold_active=0
if (( CRITICAL_THRESHOLD_RPM > 0 && max_rpm >= CRITICAL_THRESHOLD_RPM )); then
  active_threshold_rpm="$CRITICAL_THRESHOLD_RPM"
  active_stop_delay_sec="$CRITICAL_STOP_DELAY_SEC"
  threshold_label="critical threshold"
  critical_threshold_active=1
fi

if (( critical_threshold_active == 0 && STARTUP_GRACE_SEC > 0 && current_last_start_epoch > 0 )); then
  startup_elapsed_sec="$((NOW_EPOCH - current_last_start_epoch))"
  if (( startup_elapsed_sec >= 0 && startup_elapsed_sec < STARTUP_GRACE_SEC )); then
    write_state 0 0 0 "$last_trigger_rpm" "$max_rpm" 0 "startup_grace" "$current_last_start_epoch"
    log "rpm=$max_rpm 시작유예=${startup_elapsed_sec}/${STARTUP_GRACE_SEC}s; LLM유지"
    exit 0
  fi
fi

if (( high_rpm_started_epoch == 0 )); then
  high_rpm_started_epoch="$NOW_EPOCH"
fi

high_rpm_elapsed_sec="$((NOW_EPOCH - high_rpm_started_epoch))"
if (( high_rpm_elapsed_sec < active_stop_delay_sec )); then
  write_state 0 0 0 "$last_trigger_rpm" "$max_rpm" "$high_rpm_started_epoch" "observe_high_rpm"
  log "rpm=$max_rpm 유지=${high_rpm_elapsed_sec}/${active_stop_delay_sec}s 기준=$active_threshold_rpm; 대기"
  exit 0
fi

cooldown_until_epoch="$((NOW_EPOCH + COOLDOWN_SEC))"
log "rpm=$max_rpm 유지=${high_rpm_elapsed_sec}s 기준=$active_threshold_rpm; LLM중지"

if run_schedule stop; then
  if (( COOLDOWN_SEC > 0 )); then
    write_state 1 "$NOW_EPOCH" "$cooldown_until_epoch" "$max_rpm" "$max_rpm" 0 "stop" 0
    log "LLM중지 완료; 재시작=$(format_epoch "$cooldown_until_epoch")"
    exit 0
  fi

  if (( RESTART_DELAY_SEC > 0 )); then
    log "LLM중지 완료; ${RESTART_DELAY_SEC}s후 온도확인"
    sleep "$RESTART_DELAY_SEC"
  else
    log "LLM중지 완료; 온도확인"
  fi

  if temp_threshold_enabled "$START_MAX_TEMP_C"; then
    if sensors_output="$("$SENSORS_BIN" 2>/dev/null)"; then
      restart_temp_c="$(printf '%s\n' "$sensors_output" | max_temp_c_from_output)"
      if [[ -n "$restart_temp_c" ]] && temp_is_at_or_above_threshold "$restart_temp_c" "$START_MAX_TEMP_C"; then
        next_retry_epoch="$(($(date +%s) + START_RETRY_SEC))"
        write_state 1 "$NOW_EPOCH" "$next_retry_epoch" "$max_rpm" "$max_rpm" 0 "restart_deferred_hot" 0
        log "temp=${restart_temp_c}C 제한=${START_MAX_TEMP_C}C; LLM시작연기 retry=$(format_epoch "$next_retry_epoch")"
        exit 0
      fi

      if [[ -z "$restart_temp_c" ]]; then
        log "중지후 온도확인 스킵 매칭없음${TEMP_SENSOR_PATTERN:+ pattern=$TEMP_SENSOR_PATTERN}"
      fi
    else
      log "중지후 온도확인 스킵 sensors실패 bin=$SENSORS_BIN"
    fi
  fi

  log "온도정상; LLM시작"
  if run_schedule start; then
    write_state 0 0 0 "$max_rpm" 0 0 "restart_after_stop" "$(date +%s)"
    log "LLM시작 완료"
    exit 0
  fi

  next_retry_epoch="$(($(date +%s) + START_RETRY_SEC))"
  write_state 1 "$NOW_EPOCH" "$next_retry_epoch" "$max_rpm" "$max_rpm" 0 "restart_failed" 0
  log "LLM시작 실패; retry=$(format_epoch "$next_retry_epoch")"
  exit 1
fi

write_state 0 0 0 "$max_rpm" "$max_rpm" "$high_rpm_started_epoch" "stop_failed"
log "rpm=$max_rpm; LLM중지 실패"
exit 1
