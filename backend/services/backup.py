
import os
import shutil
import sqlite3
import zipfile
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

class BackupService:
    @staticmethod
    def create_hot_backup(db_path: Path, backup_path: Path):
        """
        서비스 중단 없이 SQLite DB 파일을 안전하게 백업합니다.
        """
        logger.info(f"Starting hot backup of {db_path} to {backup_path}")
        try:
            # sqlite3 .backup 명령과 동일한 기능
            src_conn = sqlite3.connect(db_path)
            dst_conn = sqlite3.connect(backup_path)
            with dst_conn:
                src_conn.backup(dst_conn)
            src_conn.close()
            dst_conn.close()
            logger.info("Hot backup completed.")
        except Exception as e:
            logger.error(f"Failed to create hot backup: {e}")
            # SQLite가 없는 경우 단순 복사 폴백
            shutil.copy2(db_path, backup_path)
            logger.warning("Simple copy fallback used for backup.")

    @staticmethod
    def compress_with_password(src_file: Path, zip_file: Path, password: Optional[str] = None):
        """
        파일을 압축합니다. 비밀번호가 있으면 암호화된 ZIP으로 생성합니다.
        (pyminizip 등이 필요할 수 있으나, 기본 zipfile은 읽기 전용 암호화만 지원하므로 
        보안이 중요하다면 별도 라이브러리 활용 권장. 여기선 기본 구현 후 보완)
        """
        logger.info(f"Compressing {src_file} into {zip_file}")
        # Note: python's zipfile doesn't support writing encrypted zips easily without 3rd party
        # We'll use standard zip for now, or use subprocess if 'zip' command is available on linux
        if password:
            try:
                import subprocess
                subprocess.run(["zip", "-j", "-P", password, str(zip_file), str(src_file)], check=True)
                logger.info("Password protected zip created via subprocess.")
                return
            except Exception as e:
                logger.error(f"Subprocess zip failed: {e}. Falling back to standard zip (unencrypted).")
        
        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(src_file, arcname=src_file.name)
        logger.info("Standard zip created.")

    @staticmethod
    def split_file(file_path: Path, chunk_size_mb: int = 49) -> list[Path]:
        """
        텔레그램 전송 제한을 위해 파일을 분할합니다.
        """
        chunk_size = chunk_size_mb * 1024 * 1024
        file_size = file_path.stat().st_size
        if file_size <= chunk_size:
            return [file_path]

        logger.info(f"File size {file_size} exceeds limit, splitting into {chunk_size_mb}MB parts.")
        parts = []
        with open(file_path, "rb") as f:
            chunk_idx = 0
            while True:
                chunk_data = f.read(chunk_size)
                if not chunk_data:
                    break
                part_path = file_path.with_suffix(f"{file_path.suffix}.part{chunk_idx}")
                with open(part_path, "wb") as pf:
                    pf.write(chunk_data)
                parts.append(part_path)
                chunk_idx += 1
        return parts

    @staticmethod
    def cleanup_old_backups(backup_dir: Path, days: int = 2, max_count: int = 5):
        """
        오래된 백업 파일을 정리합니다.
        """
        logger.info(f"Cleaning up backups in {backup_dir} (older than {days} days, max {max_count} files)")
        now = datetime.now().timestamp()
        
        # Get all backup files
        files = []
        for f in backup_dir.glob("portfolio_*.db.*"):
            files.append((f, f.stat().st_mtime))
        
        # Sort by mtime (oldest first)
        files.sort(key=lambda x: x[1])

        # Delete by age
        for f, mtime in files:
            if (now - mtime) > (days * 86400):
                f.unlink()
                logger.info(f"Deleted old backup: {f.name}")
                files.remove((f, mtime))

        # Delete by count if still too many
        while len(files) > max_count:
            f, _ = files.pop(0)
            f.unlink()
            logger.info(f"Deleted backup to stay below limit: {f.name}")
