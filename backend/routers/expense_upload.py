"""File upload endpoint for expense import"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db

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
    if file_ext not in ['.xlsx', '.xls', '.csv']:
        raise HTTPException(
            status_code=400,
            detail="Only Excel (.xlsx, .xls) and CSV (.csv) files are supported"
        )
    
    # 임시 파일로 저장
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
        tmp_path = Path(tmp_file.name)
        content = await file.read()
        tmp_file.write(content)
    
    try:
        # import_expenses 로직 호출
        from ..scripts.expenses.importer import import_expenses_from_file
        
        # DB 경로
        db_path = Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db"
        
        # 임포트 실행
        total_rows, added, skipped = import_expenses_from_file(
            db_path=str(db_path),
            file_path=tmp_path,
            dry_run=False,
            auto_category=True
        )
        
        return {
            "success": True,
            "total_rows": total_rows,
            "added": added,
            "skipped": skipped,
            "filename": file.filename,
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # 임시 파일 삭제
        if tmp_path.exists():
            tmp_path.unlink()
