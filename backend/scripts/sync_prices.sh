#!/usr/bin/env bash
set -euo pipefail

# 시세 동기화 + 스냅샷 저장 스크립트
# - 포트폴리오 티커 목록 추출
# - KIS API로 시세 갱신
# - 스냅샷 저장
#
# 환경변수:
#   API_TOKEN (필수) - 백엔드 인증 토큰
#   BACKEND_URL (선택, 기본값: http://127.0.0.1:8000)

# --- Load .env ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
API_TOKEN="${API_TOKEN:-}"

if [[ -z "${API_TOKEN}" ]]; then
  echo "ERROR: API_TOKEN is not set" >&2
  exit 1
fi

# 1) 포트폴리오에서 보유 티커 목록 뽑기
portfolio_json="$(curl -fsS -H "X-API-Token: ${API_TOKEN}" "${BACKEND_URL%/}/api/portfolio")" || {
  echo "ERROR: Failed to fetch portfolio" >&2
  exit 1
}

# Python script to extract tickers
extract_tickers_py=$(cat <<'PY'
import json, sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.stderr.write("Error: Invalid JSON input\n")
    sys.exit(1)

tickers = []
for a in data.get("assets", []):
    t = a.get("ticker")
    if t and t.strip():
        tickers.append(t.strip())
# 중복 제거
tickers = sorted(set(tickers))
print(json.dumps({"tickers": tickers}, ensure_ascii=False))
PY
)

payload="$(echo "${portfolio_json}" | python3 -c "${extract_tickers_py}")"

# 2) 시세 동기화 (assets.current_price 갱신)
ticker_count="$(echo "${payload}" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('tickers',[])))")"
if [[ "${ticker_count}" -gt 0 ]]; then
  curl -fsS -X POST \
    -H "Content-Type: application/json" \
    -H "X-API-Token: ${API_TOKEN}" \
    -d "${payload}" \
    "${BACKEND_URL%/}/api/kis/prices" > /dev/null || {
      echo "ERROR: Failed to sync prices" >&2
      exit 1
    }
fi

# 3) 스냅샷 저장
curl -fsS -X POST \
  -H "X-API-Token: ${API_TOKEN}" \
  "${BACKEND_URL%/}/api/portfolio/snapshots" > /dev/null || {
    echo "ERROR: Failed to save snapshot" >&2
    exit 1
  }

echo "$(date -Is) close sync + snapshot OK"
sync_time="$(date +'%Y-%m-%d %H:%M:%S')"

# --- Telegram Notification ---
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  MSG="$(printf "💰 시세 업데이트 완료!\n- 총 %s개 종목\n- %s 기준" "$ticker_count" "$sync_time")"
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       -d chat_id="${TELEGRAM_CHAT_ID}" \
       -d text="${MSG}" > /dev/null
fi
