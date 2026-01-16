#!/bin/bash
# 텔레그램 채팅방 ID 확인 스크립트

echo "=== 텔레그램 채팅방 ID 확인 ==="
echo ""

# .env 파일에서 토큰 읽기
source /home/dlckdgn/personal-portfolio/backend/.env

echo "1. 시세 동기화/DB 백업용 봇 (TELEGRAM_BOT_TOKEN):"
if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
    echo "   봇 토큰: ${TELEGRAM_BOT_TOKEN:0:20}..."
    echo "   최근 업데이트 확인 중..."
    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates" | jq -r '.result[-1].message.chat.id // "메시지 없음"'
    echo ""
fi

echo "2. 알람 서비스용 봇 (ALARM_TELEGRAM_BOT_TOKEN):"
if [[ -n "$ALARM_TELEGRAM_BOT_TOKEN" ]]; then
    echo "   봇 토큰: ${ALARM_TELEGRAM_BOT_TOKEN:0:20}..."
    echo "   최근 업데이트 확인 중..."
    curl -s "https://api.telegram.org/bot${ALARM_TELEGRAM_BOT_TOKEN}/getUpdates" | jq -r '.result[-1].message.chat.id // "메시지 없음"'
    echo ""
fi

echo ""
echo "💡 각 봇에게 메시지를 보내고 다시 이 스크립트를 실행하면 채팅방 ID를 확인할 수 있습니다."
