#!/usr/bin/env bash
set -euo pipefail

# --- 설정 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${DB_PATH:-"$SCRIPT_DIR/portfolio.db"}"
BACKUP_DIR="${BACKUP_DIR:-/mnt/one-touch/personal-portfolio-backend-backup}"

# --- 사전 점검 ---
if [[ ! -f "$DB_PATH" ]]; then
  echo "ERROR: DB 파일을 찾을 수 없습니다: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

timestamp="$(date +'%Y%m%d_%H%M%S')"
backup_db="$BACKUP_DIR/portfolio_${timestamp}.db"

# --- 백업 로직 ---
if command -v sqlite3 >/dev/null 2>&1; then
  echo "INFO: sqlite3 도구를 사용하여 핫 백업을 수행합니다."
  sqlite3 "$DB_PATH" ".backup '$backup_db'"
  echo "백업 완료 (Single File): $backup_db"
else
  echo "WARN: sqlite3 도구가 없어 단순 복사(cp)를 수행합니다."
  cp "$DB_PATH" "$backup_db"
  
  db_wal="${DB_PATH}-wal"
  db_shm="${DB_PATH}-shm"
  
  if [[ -f "$db_wal" ]]; then cp "$db_wal" "${backup_db}-wal"; fi
  if [[ -f "$db_shm" ]]; then cp "$db_shm" "${backup_db}-shm"; fi
  
  echo "백업 완료 (CP Mode): $backup_db"
fi

# 삭제 로직(find ... -delete)은 제거했습니다.
# 2TB 외장하드에 투자의 역사를 영원히 저장하세요!