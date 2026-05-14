#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/home/dlckdgn/personal-portfolio}"
LOG_FILE="${INTEL_XE_CLOCK_LIMIT_LOG_FILE:-$PROJECT_ROOT/backend/logs/intel_xe_clock_limit.log}"
GPU_DEVICE="${INTEL_XE_GPU_DEVICE:-/sys/class/drm/card0/device}"
FREQ_DIR="${INTEL_XE_CLOCK_LIMIT_FREQ_DIR:-$GPU_DEVICE/tile0/gt0/freq0}"
TARGET_MAX_FREQ="${INTEL_XE_CLOCK_LIMIT_MAX_FREQ:-2683}"

mkdir -p "$(dirname "$LOG_FILE")"

timestamp() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

log() {
  echo "$(timestamp) [INTEL-XE-CLOCK-LIMIT] $*" >> "$LOG_FILE"
}

read_value() {
  local path="$1"
  if [[ -r "$path" ]]; then
    cat "$path"
  else
    echo "N/A"
  fi
}

is_positive_integer() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( "$1" > 0 ))
}

MAX_FREQ_PATH="$FREQ_DIR/max_freq"
MIN_FREQ_PATH="$FREQ_DIR/min_freq"
CUR_FREQ_PATH="$FREQ_DIR/cur_freq"
ACT_FREQ_PATH="$FREQ_DIR/act_freq"
RP0_FREQ_PATH="$FREQ_DIR/rp0_freq"

if [[ ! -e "$MAX_FREQ_PATH" ]]; then
  log "missing max_freq path: $MAX_FREQ_PATH"
  exit 1
fi

if [[ ! -w "$MAX_FREQ_PATH" ]]; then
  log "max_freq path is not writable; run as root: $MAX_FREQ_PATH"
  exit 1
fi

if ! is_positive_integer "$TARGET_MAX_FREQ"; then
  log "invalid target max freq: $TARGET_MAX_FREQ"
  exit 2
fi

current_max="$(read_value "$MAX_FREQ_PATH")"
rp0_freq="$(read_value "$RP0_FREQ_PATH")"
min_freq="$(read_value "$MIN_FREQ_PATH")"
cur_freq="$(read_value "$CUR_FREQ_PATH")"
act_freq="$(read_value "$ACT_FREQ_PATH")"

log "before max_freq=${current_max} target=${TARGET_MAX_FREQ} min_freq=${min_freq} cur_freq=${cur_freq} act_freq=${act_freq} rp0_freq=${rp0_freq}"

if ! is_positive_integer "$current_max"; then
  log "current max_freq is not numeric; skipped"
  exit 0
fi

if (( current_max <= TARGET_MAX_FREQ )); then
  log "max_freq already capped at ${current_max}; skipped"
  exit 0
fi

echo "$TARGET_MAX_FREQ" > "$MAX_FREQ_PATH"

log "after max_freq=$(read_value "$MAX_FREQ_PATH") min_freq=$(read_value "$MIN_FREQ_PATH") cur_freq=$(read_value "$CUR_FREQ_PATH") act_freq=$(read_value "$ACT_FREQ_PATH")"
