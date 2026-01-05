import os
import shutil
import tempfile
from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException

from .brokerage_parser import get_parser
from ..models import ExternalCashflow

def process_brokerage_upload(
    db: Session, 
    user_id: int, 
    file: UploadFile
) -> dict:
    """
    증권사 엑셀 파일을 받아서 ExternalCashflow 데이터를 생성합니다.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    parser = get_parser(file.filename)
    if not parser:
        raise HTTPException(
            status_code=400,
            detail="Unsupported brokerage or file format. Only Samsung Securities Excel files are supported."
        )

    # 임시 파일 저장
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        new_items = parser.parse(tmp_path, user_id)
        
        added_count = 0
        skipped_count = 0
        
        # 중복 방지 로직 (Batch Insert 개선 가능하지만 일단 기존 로직 유지)
        for item in new_items:
            exists = db.query(ExternalCashflow).filter(
                ExternalCashflow.user_id == user_id,
                ExternalCashflow.date == item.date,
                ExternalCashflow.amount == item.amount,
                ExternalCashflow.description == item.description
            ).first()
            
            if not exists:
                db_item = ExternalCashflow(
                    user_id=user_id,
                    date=item.date,
                    amount=item.amount,
                    description=item.description,
                    account_info=item.account_info
                )
                db.add(db_item)
                added_count += 1
            else:
                skipped_count += 1
        
        db.commit()
        return {
            "message": "Upload successful",
            "added": added_count,
            "skipped": skipped_count,
            "total_parsed": len(new_items)
        }
        
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
