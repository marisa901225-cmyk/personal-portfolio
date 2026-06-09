#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

HASS_SERVER="${HASS_SERVER:-http://127.0.0.1:8123}"
TOKEN_URL="${HASS_SERVER%/}/profile/security"
ENV_FILE="${HASS_ENV_FILE:-backend/.env}"

xdg-open "$TOKEN_URL" >/dev/null 2>&1 || true

message="Home Assistant profile page opened.

Scroll to Long-lived access tokens, create a token for jaw, then paste it here."

if command -v zenity >/dev/null 2>&1; then
  HASS_TOKEN="$(zenity --entry \
    --title="Home Assistant token setup" \
    --width=560 \
    --text="$message" \
    --hide-text)"
else
  printf '%s\n' "$message" >&2
  printf 'HASS_TOKEN: ' >&2
  read -r HASS_TOKEN
fi

if [ -z "${HASS_TOKEN:-}" ]; then
  printf 'No token entered. Nothing was changed.\n' >&2
  exit 2
fi

umask 077
if [ -f "$ENV_FILE" ]; then
  grep -v -E '^HASS_(SERVER|TOKEN)=' "$ENV_FILE" > "${ENV_FILE}.tmp"
  mv "${ENV_FILE}.tmp" "$ENV_FILE"
fi

{
  [ -s "$ENV_FILE" ] && printf '\n'
  printf 'HASS_SERVER=%q\n' "$HASS_SERVER"
  printf 'HASS_TOKEN=%q\n' "$HASS_TOKEN"
} >> "$ENV_FILE"

printf 'Saved Home Assistant CLI token to %s\n' "$ENV_FILE"
