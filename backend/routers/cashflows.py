from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import os
import shutil
import tempfile

from ..db import get_db
from ..models import ExternalCashflow
from ..schemas import ExternalCashflowRead, ExternalCashflowCreate, ExternalCashflowUpdate
from ..services.brokerage_parser import get_parser

router = APIRouter(prefix="/api/cashflows", tags=["cashflows"])

@router.get("/", response_model=List[ExternalCashflowRead])
def get_cashflows(db: Session = Depends(get_db), user_id: int = 1):
    return db.query(ExternalCashflow).filter(ExternalCashflow.user_id == user_id).order_by(ExternalCashflow.date.desc()).all()

@router.post("/", response_model=ExternalCashflowRead)
def create_cashflow(item: ExternalCashflowCreate, db: Session = Depends(get_db), user_id: int = 1):
    db_item = ExternalCashflow(
        user_id=user_id,
        date=item.date,
        amount=item.amount,
        description=item.description,
        account_info=item.account_info
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@router.put("/{cashflow_id}", response_model=ExternalCashflowRead)
def update_cashflow(
    cashflow_id: int, 
    item: ExternalCashflowUpdate, 
    db: Session = Depends(get_db), 
    user_id: int = 1
):
    db_item = db.query(ExternalCashflow).filter(
        ExternalCashflow.id == cashflow_id, 
        ExternalCashflow.user_id == user_id
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Cashflow entry not found")
    
    for key, value in item.model_dump(exclude_unset=True).items():
        setattr(db_item, key, value)
        
    db.commit()
    db.refresh(db_item)
    return db_item

@router.delete("/{cashflow_id}")
def delete_cashflow(cashflow_id: int, db: Session = Depends(get_db), user_id: int = 1):
    db_item = db.query(ExternalCashflow).filter(
        ExternalCashflow.id == cashflow_id, 
        ExternalCashflow.user_id == user_id
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Cashflow entry not found")
    
    db.delete(db_item)
    db.commit()
    return {"message": "Cashflow entry deleted"}

@router.post("/upload")
async def upload_statement(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db), 
    user_id: int = 1
):
    parser = get_parser(file.filename)
    if not parser:
        raise HTTPException(status_code=400, detail="Unsupported brokerage or file format. Currently supporting '삼성' in filename.")
    
    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
        
    try:
        new_items = parser.parse(tmp_path, user_id)
        
        added_count = 0
        skipped_count = 0
        
        for item in new_items:
            # Simple deduplication: Check if same date, amount and description exists
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
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
