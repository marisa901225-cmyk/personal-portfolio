#!/bin/bash
#
# 작업 완료 후 텔레그램 알림을 보내는 스크립트
# 사용법: ./send_telegram.sh "작업 완료 메시지"
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# .env 파일 경로 찾기
if [[ -f "$SCRIPT_DIR/backend/.env" ]]; then
    ENV_FILE="$SCRIPT_DIR/backend/.env"
elif [[ -f "$SCRIPT_DIR/.env" ]]; then
    ENV_FILE="$SCRIPT_DIR/.env"
else
    echo "❌ .env 파일을 찾을 수 없습니다."
    exit 1
fi

# .env 파일에서 환경변수 로드
while IFS='=' read -r key value; do
    # 빈 줄과 주석 무시
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    # 키에서 공백 제거
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    # 따옴표 제거
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    export "$key=$value"
done < "$ENV_FILE"

# 환경변수 확인
if [[ -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_CHAT_ID" ]]; then
    echo "❌ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다."
    exit 1
fi

# 메시지 설정
if [[ -n "$1" ]]; then
    MESSAGE="$*"
else
    MESSAGE="🔧 작업이 완료되었습니다."
fi

# JSON 페이로드 생성(따옴표/개행/백슬래시 안전 처리)
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

# 텔레그램 API 호출
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "$JSON_PAYLOAD" \
    --connect-timeout 10 \
    --max-time 30)

# HTTP 상태 코드 추출
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ "$HTTP_CODE" -eq 200 ]]; then
    echo "✅ 텔레그램 메시지 전송 완료!"
    exit 0
else
    echo "❌ 텔레그램 전송 실패 (HTTP ${HTTP_CODE}): ${BODY}"
    exit 1
fi
