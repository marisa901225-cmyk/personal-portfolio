import logging
import os
import re
import tempfile
from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException

from .brokerage_parser import get_parser
from ..core.models import ExternalCashflow

logger = logging.getLogger(__name__)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CHUNK_SIZE = 1024 * 1024

def _normalize_description(description: str | None) -> str:
    """Normalize description for consistent deduplication."""
    if not description:
        return ""
    # Trim and collapse consecutive whitespace
    return re.sub(r'\s+', ' ', description.strip())


def process_brokerage_upload(
    db: Session, 
    user_id: int, 
    file: UploadFile
) -> dict:
    """
    증권사 엑셀 파일을 받아서 ExternalCashflow 데이터를 생성합니다.
    
    NOTE: This function does NOT commit. The caller (router) is responsible for commit/rollback.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    parser = get_parser(file.filename)
    if not parser:
        raise HTTPException(
            status_code=400,
            detail="Unsupported brokerage or file format. Only Samsung Securities Excel files are supported."
        )

    tmp_path: str | None = None
    try:
        # 임시 파일 저장 (크기 제한 + 스트리밍)
        file.file.seek(0) # 안정성: 파일 포인터 리셋
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            total = 0
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File too large")
                tmp.write(chunk)

        new_items = parser.parse(tmp_path, user_id)
        if not new_items:
            return {"message": "No items found to import", "added": 0, "skipped": 0, "total_parsed": 0}

        # 1. 가성비 최적화: 기존 데이터 통째로 가져와서 메모리에서 비교 (N+1 방지)
        # 1인 서비스 + 최근 데이터 위주라면 이 방식이 훨씬 빠름
        # 모든 데이터를 다 가져오지 않고, 업로드된 날짜 범위만 가져오면 더 좋음
        dates = [item.date for item in new_items]
        min_date, max_date = min(dates), max(dates)
        
        existing_pool = db.query(ExternalCashflow).filter(
            ExternalCashflow.user_id == user_id,
            ExternalCashflow.date >= min_date,
            ExternalCashflow.date <= max_date
        ).all()
        
        # 중복 체크용 키 생성
        def _make_key(date, amount, desc):
            return f"{date.isoformat()}|{round(amount, 2)}|{_normalize_description(desc)}"
        
        existing_keys = {
            _make_key(e.date, e.amount, e.description) for e in existing_pool
        }

        added_count = 0
        skipped_count = 0
        
        for item in new_items:
            normalized_amount = round(item.amount, 2)
            normalized_description = _normalize_description(item.description)
            item_key = _make_key(item.date, normalized_amount, normalized_description)
            
            if item_key not in existing_keys:
                db_item = ExternalCashflow(
                    user_id=user_id,
                    date=item.date,
                    amount=normalized_amount,
                    description=normalized_description,
                    account_info=item.account_info
                )
                db.add(db_item)
                # 새로 추가된 아이템도 키 풀에 넣어 중복 방지 (같은 파일 내 중복)
                existing_keys.add(item_key)
                added_count += 1
            else:
                skipped_count += 1
        
        db.flush()  # Apply changes without committing
        return {
            "message": "Upload successful",
            "added": added_count,
            "skipped": skipped_count,
            "total_parsed": len(new_items)
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning("Validation error during import: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Import failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred during file processing. Please check the logs.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
