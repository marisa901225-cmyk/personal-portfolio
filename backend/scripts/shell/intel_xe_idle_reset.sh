#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/dlckdgn/personal-portfolio"
LOG_FILE="$PROJECT_ROOT/backend/logs/intel_xe_idle_reset.log"
GPU_DEVICE="${INTEL_XE_GPU_DEVICE:-/sys/class/drm/card0/device}"
AUTO_HOLD_SEC="${INTEL_XE_IDLE_RESET_AUTO_HOLD_SEC:-5}"

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

log "before control=$(read_value "$GPU_DEVICE/power/control") runtime_status=$(read_value "$GPU_DEVICE/power/runtime_status") gt0_cur_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/cur_freq") gt0_act_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/act_freq") gt0_idle=$(read_value "$GPU_DEVICE/tile0/gt0/gtidle/idle_status")"

echo auto > "$GPU_DEVICE/power/control"
log "set control=auto; holding for ${AUTO_HOLD_SEC}s"
sleep "$AUTO_HOLD_SEC"

echo on > "$GPU_DEVICE/power/control"
log "after control=$(read_value "$GPU_DEVICE/power/control") runtime_status=$(read_value "$GPU_DEVICE/power/runtime_status") gt0_cur_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/cur_freq") gt0_act_freq=$(read_value "$GPU_DEVICE/tile0/gt0/freq0/act_freq") gt0_idle=$(read_value "$GPU_DEVICE/tile0/gt0/gtidle/idle_status")"
