from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import YearlyCashflow
from ..schemas import YearlyCashflowCreate, YearlyCashflowRead, YearlyCashflowUpdate
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api/cashflows", tags=["cashflows"], dependencies=[Depends(verify_api_token)])


def to_cashflow_read(record: YearlyCashflow) -> YearlyCashflowRead:
    """YearlyCashflow 모델을 Read 스키마로 변환 (net 계산 포함)"""
    return YearlyCashflowRead(
        id=record.id,
        year=record.year,
        deposit=record.deposit,
        withdrawal=record.withdrawal,
        net=record.deposit - record.withdrawal,
        note=record.note,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=List[YearlyCashflowRead])
def list_cashflows(db: Session = Depends(get_db)) -> List[YearlyCashflowRead]:
    """연도별 입출금 내역 전체 조회 (연도 오름차순)"""
    user = get_or_create_single_user(db)
    records = (
        db.query(YearlyCashflow)
        .filter(YearlyCashflow.user_id == user.id)
        .order_by(YearlyCashflow.year.asc())
        .all()
    )
    return [to_cashflow_read(r) for r in records]


@router.post("", response_model=YearlyCashflowRead)
def create_cashflow(payload: YearlyCashflowCreate, db: Session = Depends(get_db)) -> YearlyCashflowRead:
    """새 연도별 입출금 내역 생성"""
    user = get_or_create_single_user(db)
    
    # 같은 연도가 이미 있는지 확인
    existing = (
        db.query(YearlyCashflow)
        .filter(YearlyCashflow.user_id == user.id, YearlyCashflow.year == payload.year)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"Year {payload.year} already exists. Use PATCH to update.")
    
    record = YearlyCashflow(
        user_id=user.id,
        year=payload.year,
        deposit=payload.deposit,
        withdrawal=payload.withdrawal,
        note=payload.note,
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(record)
    return to_cashflow_read(record)


@router.patch("/{cashflow_id}", response_model=YearlyCashflowRead)
def update_cashflow(
    cashflow_id: int,
    payload: YearlyCashflowUpdate,
    db: Session = Depends(get_db),
) -> YearlyCashflowRead:
    """연도별 입출금 내역 수정"""
    user = get_or_create_single_user(db)
    record = (
        db.query(YearlyCashflow)
        .filter(YearlyCashflow.id == cashflow_id, YearlyCashflow.user_id == user.id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Cashflow record not found")
    
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(record, field, value)
    record.updated_at = datetime.utcnow()
    
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(record)
    return to_cashflow_read(record)


@router.delete("/{cashflow_id}")
def delete_cashflow(cashflow_id: int, db: Session = Depends(get_db)) -> dict:
    """연도별 입출금 내역 삭제"""
    user = get_or_create_single_user(db)
    record = (
        db.query(YearlyCashflow)
        .filter(YearlyCashflow.id == cashflow_id, YearlyCashflow.user_id == user.id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Cashflow record not found")
    
    db.delete(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"status": "ok"}
