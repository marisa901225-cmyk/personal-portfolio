#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/dlckdgn/personal-portfolio"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
LOG_FILE="$PROJECT_ROOT/backend/logs/llm_schedule.log"
# Keep only the primary Vulkan server and the light reviewer model on
# automatic schedule to avoid bringing up heavier unused backends.
TARGET_SERVICES=(llama-server-light llama-server-vulkan-huihui)
ALLOW_WEEKEND_START="${LLM_SCHEDULE_ALLOW_WEEKEND_START:-0}"

ACTION="${1:-}"

mkdir -p "$(dirname "$LOG_FILE")"

if [[ -z "$ACTION" ]]; then
  echo "usage: $0 <start|stop>" >&2
  exit 2
fi

run_compose() {
  /usr/bin/docker compose -f "$COMPOSE_FILE" "$@"
}

timestamp() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

is_weekend() {
  local weekday
  weekday="$(date +%u)"
  [[ "$weekday" == "6" || "$weekday" == "7" ]]
}

get_available_services() {
  run_compose config --services
}

get_target_services() {
  mapfile -t available_services < <(get_available_services)
  local selected=()
  local service

  for service in "${TARGET_SERVICES[@]}"; do
    if printf '%s\n' "${available_services[@]}" | grep -Fxq "$service"; then
      selected+=("$service")
    fi
  done

  printf '%s\n' "${selected[@]}"
}

case "$ACTION" in
  start)
    if is_weekend && [[ "$ALLOW_WEEKEND_START" != "1" ]]; then
      echo "$(timestamp) [LLM-SCHEDULE] weekend start skipped (set LLM_SCHEDULE_ALLOW_WEEKEND_START=1 to override)" >> "$LOG_FILE"
      exit 0
    fi

    mapfile -t services_to_manage < <(get_target_services)
    if [[ ${#services_to_manage[@]} -eq 0 ]]; then
      echo "$(timestamp) [LLM-SCHEDULE] no target services found in compose file" >> "$LOG_FILE"
      exit 0
    fi

    if pgrep -f "upscale_.*\.sh" > /dev/null; then
      echo "$(timestamp) [LLM-SCHEDULE] upscale process detected, skipping auto-start to avoid GPU contention" >> "$LOG_FILE"
      exit 0
    fi

    echo "$(timestamp) [LLM-SCHEDULE] starting services: ${services_to_manage[*]}" >> "$LOG_FILE"
    run_compose up -d "${services_to_manage[@]}" >> "$LOG_FILE" 2>&1
    echo "$(timestamp) [LLM-SCHEDULE] start done" >> "$LOG_FILE"
    ;;
  stop)
    mapfile -t services_to_manage < <(get_target_services)
    if [[ ${#services_to_manage[@]} -eq 0 ]]; then
      echo "$(timestamp) [LLM-SCHEDULE] no target services found in compose file" >> "$LOG_FILE"
      exit 0
    fi

    echo "$(timestamp) [LLM-SCHEDULE] stopping services: ${services_to_manage[*]}" >> "$LOG_FILE"
    run_compose stop "${services_to_manage[@]}" >> "$LOG_FILE" 2>&1
    echo "$(timestamp) [LLM-SCHEDULE] stop done" >> "$LOG_FILE"
    ;;
  *)
    echo "unknown action: $ACTION (expected start|stop)" >&2
    exit 2
    ;;
esac
