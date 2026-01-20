from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import ExternalCashflowRead, ExternalCashflowCreate, ExternalCashflowUpdate
from ..services import cashflow_service
from ..services.import_service import process_brokerage_upload
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api/cashflows", tags=["cashflows"], dependencies=[Depends(verify_api_token)])


@router.get("/", response_model=List[ExternalCashflowRead])
def get_cashflows(db: Session = Depends(get_db)):
    user = get_or_create_single_user(db)
    return cashflow_service.get_cashflows(db, user.id)


@router.post("/", response_model=ExternalCashflowRead)
def create_cashflow(item: ExternalCashflowCreate, db: Session = Depends(get_db)):
    user = get_or_create_single_user(db)
    return cashflow_service.create_cashflow(db, user.id, item)


@router.put("/{cashflow_id}", response_model=ExternalCashflowRead)
def update_cashflow(
    cashflow_id: int, 
    item: ExternalCashflowUpdate, 
    db: Session = Depends(get_db)
):
    user = get_or_create_single_user(db)
    return cashflow_service.update_cashflow(db, user.id, cashflow_id, item)


@router.delete("/{cashflow_id}")
def delete_cashflow(cashflow_id: int, db: Session = Depends(get_db)):
    user = get_or_create_single_user(db)
    cashflow_service.delete_cashflow(db, user.id, cashflow_id)
    return {"message": "Cashflow entry deleted"}


@router.post("/upload")
async def upload_statement(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db)
):
    user = get_or_create_single_user(db)
    return process_brokerage_upload(db, user.id, file)
