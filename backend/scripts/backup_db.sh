#!/usr/bin/env bash
set -euo pipefail

# --- 설정 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 백엔드 루트 (backend/)
BASE_DIR="$SCRIPT_DIR/.."
DB_PATH="${DB_PATH:-"$BASE_DIR/portfolio.db"}"

# 로컬 백업 경로 (안정성 확보를 위해 우선 로컬에 저장)
LOCAL_BACKUP_DIR="$BASE_DIR/backups"
# 외장하드 경로 (옵션)
EXTERNAL_BACKUP_DIR="${BACKUP_DIR:-/mnt/one-touch/personal-portfolio-backend-backup}"

# --- 사전 점검 ---
if [[ ! -f "$DB_PATH" ]]; then
  echo "ERROR: DB 파일을 찾을 수 없습니다: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$LOCAL_BACKUP_DIR"

timestamp="$(date +'%Y-%m-%d')"
backup_time="$(date +'%Y-%m-%d %H:%M:%S')"
base_name="portfolio_${timestamp}"
# 확장자
ext=".db"

# 순차적 파일명 생성 (예: portfolio_2025-12-23.db -> portfolio_2025-12-23(1).db)
backup_file_base="${base_name}${ext}"
count=1

while [[ -f "$LOCAL_BACKUP_DIR/$backup_file_base" || -f "$LOCAL_BACKUP_DIR/${backup_file_base}.gz" ]]; do
  backup_file_base="${base_name}(${count})${ext}"
  ((count++))
done

backup_path="$LOCAL_BACKUP_DIR/$backup_file_base"
compressed_path="${backup_path}.gz"

# --- 1. 로컬 백업 및 압축 ---
echo "INFO: 로컬 백업 시작 ($LOCAL_BACKUP_DIR)"

if command -v sqlite3 >/dev/null 2>&1; then
  # sqlite3 .backup 사용 (Hot Backup)
  sqlite3 "$DB_PATH" ".backup '$backup_path'"
else
  # 단순 복사
  cp "$DB_PATH" "$backup_path"
  if [[ -f "${DB_PATH}-wal" ]]; then cp "${DB_PATH}-wal" "${backup_path}-wal"; fi
  if [[ -f "${DB_PATH}-shm" ]]; then cp "${DB_PATH}-shm" "${backup_path}-shm"; fi
fi

# 압축 (gzip)
echo "INFO: 파일 압축 중..."
gzip -f -n "$backup_path"
echo "백업 및 압축 완료: $compressed_path"

# --- 2. 텔레그램 전송 (분할 전송 포함) ---
ENV_FILE="$BASE_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  echo "INFO: 텔레그램 전송 준비..."

  # 파일 크기 확인 (bytes)
  file_size=$(stat -c%s "$compressed_path")
  # 49MB (안전 마진 포함)
  MAX_SIZE=$((49 * 1024 * 1024))

  if [[ $file_size -le $MAX_SIZE ]]; then
    # 50MB 이하: 그냥 전송
    echo "INFO: 용량 적합 ($file_size bytes). 단일 파일 전송."
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
         -F chat_id="${TELEGRAM_CHAT_ID}" \
         -F document=@"${compressed_path}" \
         -F caption="📦 DB 백업 완료 (${backup_time})" > /dev/null
    echo "INFO: 전송 완료."
  else
    # 50MB 초과: 분할 전송
    echo "INFO: 용량 초과 ($file_size bytes). 49MB 단위로 분할하여 전송합니다..."
    
    # 임시 분할 폴더
    split_dir=$(mktemp -d)
    # 분할 수행 (파일명 뒤에 .partaa, .partab ... 붙음)
    split -b 49m "$compressed_path" "$split_dir/${backup_file_base}.gz.part"
    
    for part in "$split_dir"/*; do
      part_name=$(basename "$part")
      echo "  - 전송 중: $part_name ..."
      curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
           -F chat_id="${TELEGRAM_CHAT_ID}" \
           -F document=@"${part}" > /dev/null
    done
    
    # 임시 폴더 정리
    rm -rf "$split_dir"
    echo "INFO: 분할 전송 완료."
  fi
else
  echo "INFO: 텔레그램 설정(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)이 없어 전송을 건너뜁니다."
fi

# --- 3. 드롭박스 전송 (옵션) ---
dropbox_upload_ok="false"
if [[ -n "${DROPBOX_APP_KEY:-}" ]] && [[ -n "${DROPBOX_APP_SECRET:-}" ]] && [[ -n "${DROPBOX_REFRESH_TOKEN:-}" ]]; then
  echo "INFO: 드롭박스 전송 준비..."

  # 1) Access Token 발급 (Refresh Token 이용)
  # -u "APP_KEY:APP_SECRET" 로 Basic Auth 처리
  token_response=$(curl -s -X POST https://api.dropbox.com/oauth2/token \
    -u "${DROPBOX_APP_KEY}:${DROPBOX_APP_SECRET}" \
    -d grant_type=refresh_token \
    -d refresh_token="${DROPBOX_REFRESH_TOKEN}")

  # grep이 실패해도 스크립트가 죽지 않도록 || true 추가
  access_token=$(echo "$token_response" | grep -o '"access_token": *"[^"]*"' | cut -d'"' -f4 || true)

  if [[ -n "$access_token" ]]; then
    # 2) 파일 업로드
    # 드롭박스는 파일명이 경로에 포함됨. /폴더명/파일명
    dropbox_path="/marin-db-backup/${backup_file_base}.gz"
    
    # 50MB 이상 분할된 경우 폴더째로 올릴 수는 없으니, 여기선 단순화를 위해 원본 압축파일 하나만 올림
    # 요청당 150MB 미만 권장/제한. 그 이상은 upload session으로 분할 업로드(파일 전체는 훨씬 큰 용량까지 가능
    
    echo "  - 업로드 중: $dropbox_path ..."
    # Dropbox-API-Arg 헤더는 JSON 형태여야 함.
    upload_arg="{\"path\": \"${dropbox_path}\",\"mode\": \"add\",\"autorename\": true,\"mute\": false}"
    
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST https://content.dropboxapi.com/2/files/upload \
      -H "Authorization: Bearer $access_token" \
      -H "Dropbox-API-Arg: $upload_arg" \
      -H "Content-Type: application/octet-stream" \
      --data-binary @"$compressed_path")
      
    if [[ "$http_code" == "200" ]]; then
      echo "INFO: 드롭박스 업로드 성공"
      dropbox_upload_ok="true"
    else
      echo "ERROR: 드롭박스 업로드 실패 (HTTP $http_code)"
    fi
  else
    echo "ERROR: 드롭박스 Access Token 발급 실패"
    echo "RESPONSE: $token_response"
  fi
else
  echo "INFO: 드롭박스 설정이 없어 전송을 건너뜁니다."
fi


# --- 4. 외장하드 복사 (옵션) ---
if [[ -d "$EXTERNAL_BACKUP_DIR" ]]; then
  echo "INFO: 외장하드 감지됨. 백업 복사 중..."
  cp "$compressed_path" "$EXTERNAL_BACKUP_DIR/"
  echo "INFO: 외장하드 복사 완료."
else
  echo "WARN: 외장하드 경로($EXTERNAL_BACKUP_DIR)에 접근할 수 없어 복사를 건너뜁니다."
fi

# (선택) 로컬 백업 정리: 드롭박스 업로드 성공 시 2일 초과 파일 삭제
if [[ "$dropbox_upload_ok" == "true" ]]; then
  find "$LOCAL_BACKUP_DIR" -name "portfolio_*.db.gz" -mmin +2880 -delete
fi
