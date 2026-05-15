#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/dlckdgn/personal-portfolio"
LOG_FILE="$PROJECT_ROOT/backend/logs/intel_xe_idle_reset.log"
GPU_DEVICE="${INTEL_XE_GPU_DEVICE:-/sys/class/drm/card0/device}"
AUTO_HOLD_SEC="${INTEL_XE_IDLE_RESET_AUTO_HOLD_SEC:-5}"
DAY_AUTO_ENABLED="${INTEL_XE_IDLE_RESET_DAY_AUTO_ENABLED:-1}"
DAY_AUTO_START="${INTEL_XE_IDLE_RESET_DAY_AUTO_START:-08:00}"
DAY_AUTO_END="${INTEL_XE_IDLE_RESET_DAY_AUTO_END:-18:00}"
DAY_AUTO_REQUIRE_TRADING_DAY="${INTEL_XE_IDLE_RESET_DAY_AUTO_REQUIRE_TRADING_DAY:-1}"
PYTHON_BIN="${INTEL_XE_IDLE_RESET_PYTHON_BIN:-$PROJECT_ROOT/venv/bin/python}"
NOW_DATE="${INTEL_XE_IDLE_RESET_NOW_DATE:-$(date +%Y%m%d)}"
NOW_WEEKDAY="${INTEL_XE_IDLE_RESET_NOW_WEEKDAY:-$(date +%u)}"
NOW_HHMM="${INTEL_XE_IDLE_RESET_NOW_HHMM:-$(date +%H:%M)}"

mkdir -p "$(dirname "$LOG_FILE")"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

log() {
  echo "$(timestamp) [INTEL-XE-IDLE-RESET] $*" >> "$LOG_FILE"
}

if [[ ! -e "$GPU_DEVICE/power/control" ]]; then
  log "missing power control path: $GPU_DEVICE/power/control"
  exit 1
fi

if [[ ! -w "$GPU_DEVICE/power/control" ]]; then
  log "power control path is not writable; run as root: $GPU_DEVICE/power/control"
  exit 1
fi

read_value() {
  local path="$1"
  if [[ -r "$path" ]]; then
    cat "$path"
  else
    echo "N/A"
  fi
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

in_day_auto_window() {
  local start_min end_min now_min

  [[ "$DAY_AUTO_ENABLED" == "1" ]] || return 1
  [[ "$NOW_WEEKDAY" =~ ^[1-5]$ ]] || return 1
  is_day_auto_trading_day || return 1

  start_min="$(hhmm_to_minutes "$DAY_AUTO_START")"
  end_min="$(hhmm_to_minutes "$DAY_AUTO_END")"
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

is_day_auto_trading_day() {
  local result

  [[ "$DAY_AUTO_REQUIRE_TRADING_DAY" == "1" ]] || return 0
  if [[ ! -x "$PYTHON_BIN" ]]; then
    log "trading-day check skipped; python not executable: $PYTHON_BIN"
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
      log "day auto window suppressed; KIS trading-day check reports closed date=${NOW_DATE}"
      return 1
      ;;
    *)
      log "trading-day check inconclusive result=${result:-empty}; allowing weekday day-auto fallback"
      return 0
      ;;
  esac
}

log "before control=$(read_value "$GPU_DEVICE/power/control") runtime_status=$(read_value "$GPU_DEVICE/power/runtime_status") gt0_cur_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/cur_freq") gt0_act_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/act_freq") gt0_idle=$(read_value "$GPU_DEVICE/tile0/gt0/gtidle/idle_status")"

if in_day_auto_window; then
  echo auto > "$GPU_DEVICE/power/control"
  log "day auto window active date=${NOW_DATE} weekday=${NOW_WEEKDAY} time=${NOW_HHMM} window=${DAY_AUTO_START}-${DAY_AUTO_END}; keeping control=auto runtime_status=$(read_value "$GPU_DEVICE/power/runtime_status")"
  exit 0
fi

echo auto > "$GPU_DEVICE/power/control"
log "set control=auto; holding for ${AUTO_HOLD_SEC}s"
sleep "$AUTO_HOLD_SEC"

echo on > "$GPU_DEVICE/power/control"
log "after control=$(read_value "$GPU_DEVICE/power/control") runtime_status=$(read_value "$GPU_DEVICE/power/runtime_status") gt0_cur_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/cur_freq") gt0_act_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/act_freq") gt0_idle=$(read_value "$GPU_DEVICE/tile0/gt0/gtidle/idle_status")"
