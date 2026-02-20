#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/dlckdgn/personal-portfolio"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
LOG_FILE="$PROJECT_ROOT/backend/logs/llm_schedule.log"

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

case "$ACTION" in
  start)
    echo "$(timestamp) [LLM-SCHEDULE] starting llama services" >> "$LOG_FILE"
    run_compose up -d llama-server llama-server-light >> "$LOG_FILE" 2>&1
    echo "$(timestamp) [LLM-SCHEDULE] start done" >> "$LOG_FILE"
    ;;
  stop)
    echo "$(timestamp) [LLM-SCHEDULE] stopping llama services" >> "$LOG_FILE"
    run_compose stop llama-server llama-server-light >> "$LOG_FILE" 2>&1
    echo "$(timestamp) [LLM-SCHEDULE] stop done" >> "$LOG_FILE"
    ;;
  *)
    echo "unknown action: $ACTION (expected start|stop)" >&2
    exit 2
    ;;
esac

