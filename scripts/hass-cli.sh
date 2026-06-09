#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f backend/.env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./backend/.env
  set +a
fi

if [ -f .env.homeassistant.local ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.homeassistant.local
  set +a
fi

if [ -z "${HASS_TOKEN:-}" ]; then
  printf 'HASS_TOKEN is required. Run scripts/hass-token-setup.sh first.\n' >&2
  exit 2
fi

exec docker compose exec \
  -e HASS_SERVER="${HASS_SERVER:-http://127.0.0.1:8123}" \
  -e HASS_TOKEN="$HASS_TOKEN" \
  homeassistant-cli \
  hass-cli "$@"
