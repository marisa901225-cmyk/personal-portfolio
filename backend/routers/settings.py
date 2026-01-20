from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import SettingsRead, SettingsUpdate
from ..services import settings_service
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.get("/settings", response_model=SettingsRead)
def get_settings(db: Session = Depends(get_db)) -> SettingsRead:
    user = get_or_create_single_user(db)
    setting = settings_service.get_settings(db, user.id)
    return settings_service.to_settings_read(setting)


@router.put("/settings", response_model=SettingsRead)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
) -> SettingsRead:
    user = get_or_create_single_user(db)
    setting = settings_service.update_settings(db, user.id, payload)
    return settings_service.to_settings_read(setting)
