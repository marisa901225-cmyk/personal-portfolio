#!/bin/bash
#
# 작업 완료 후 텔레그램 알림을 보내는 스크립트
# 사용법: ./send_telegram.sh "작업 완료 메시지"
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    if [[ -f "$SCRIPT_DIR/backend/.env" ]]; then
        set -a
        source "$SCRIPT_DIR/backend/.env"
        set +a
    elif [[ -f "$SCRIPT_DIR/.env" ]]; then
        set -a
        source "$SCRIPT_DIR/.env"
        set +a
    fi
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    echo "❌ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다."
    exit 1
fi

if [[ $# -gt 0 ]]; then
    MESSAGE="$*"
else
    MESSAGE="🔧 작업이 완료되었습니다."
fi

JSON_PAYLOAD=$(python3 - "$TELEGRAM_CHAT_ID" "$MESSAGE" <<'PY'
import json
import sys

chat_id = sys.argv[1]
message = sys.argv[2]
payload = {
    "chat_id": chat_id,
    "text": message,
    "parse_mode": "HTML",
}
print(json.dumps(payload, ensure_ascii=False))
PY
)

RESPONSE=$(curl -sS -w "\n%{http_code}" -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "$JSON_PAYLOAD" \
    --connect-timeout 10 \
    --max-time 30)

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ "$HTTP_CODE" -eq 200 ]]; then
    echo "✅ 텔레그램 메시지 전송 완료!"
    exit 0
fi

if [[ "$HTTP_CODE" -eq 000 ]]; then
    echo "❌ 텔레그램 전송 실패 (HTTP 000): 네트워크 연결/방화벽을 확인해주세요."
    exit 1
fi

echo "❌ 텔레그램 전송 실패 (HTTP ${HTTP_CODE}): ${BODY}"
exit 1
