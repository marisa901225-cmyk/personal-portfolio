"""File upload endpoint for expense import"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db

logger = logging.getLogger(__name__)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CHUNK_SIZE = 1024 * 1024

router = APIRouter(
    prefix="/api/expenses",
    tags=["expenses"],
    dependencies=[Depends(verify_api_token)]
)


@router.post("/upload")
async def upload_expense_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Excel/CSV 파일 업로드하여 자동 임포트
    
    Returns:
        {
            "success": true,
            "total_rows": 100,
            "added": 95,
            "skipped": 5,
            "filename": "카드내역.xlsx"
        }
    """
    # 파일 확장자 확인
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ['.xlsx', '.xls', '.csv', '.txt']:
        raise HTTPException(
            status_code=400,
            detail="Only Excel (.xlsx, .xls), CSV (.csv), and NaverPay TXT (.txt) files are supported"
        )
    
    tmp_path: Path | None = None
    try:
        # 임시 파일로 저장 (크기 제한 + 스트리밍)
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            tmp_path = Path(tmp_file.name)
            total = 0
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File too large")
                tmp_file.write(chunk)

        # import_expenses 로직 호출
        from ..scripts.expenses.importer import import_expenses_from_file
        
        # DB 경로
        db_path = Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db"
        
        # 임포트 실행
        total_rows, added, skipped, skip_breakdown = import_expenses_from_file(
            db_path=str(db_path),
            file_path=tmp_path,
            dry_run=False,
            auto_category=True,
            original_filename=file.filename
        )
        
        return {
            "success": True,
            "total_rows": total_rows,
            "added": added,
            "skipped": skipped,
            "skip_breakdown": skip_breakdown,
            "filename": file.filename,
        }
    
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Expense upload failed")
        raise HTTPException(status_code=500, detail="Internal error during import")
    
    finally:
        # 임시 파일 삭제
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
