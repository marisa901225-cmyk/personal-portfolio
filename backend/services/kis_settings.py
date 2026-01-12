from __future__ import annotations

import logging
import os
from typing import Dict

from sqlalchemy.orm import Session

from ..core.models import Setting
from ..services.users import get_or_create_single_user

logger = logging.getLogger(__name__)

_KIS_FIELD_MAP: Dict[str, tuple[str, str]] = {
    "kis_app": ("KIS_MY_APP", "my_app"),
    "kis_sec": ("KIS_MY_SEC", "my_sec"),
    "kis_acct_stock": ("KIS_MY_ACCT_STOCK", "my_acct_stock"),
    "kis_prod": ("KIS_MY_PROD", "my_prod"),
    "kis_htsid": ("KIS_MY_HTSID", "my_htsid"),
    "kis_prod_url": ("KIS_PROD", "prod"),
    "kis_ops_url": ("KIS_OPS", "ops"),
    "kis_vps_url": ("KIS_VPS", "vps"),
    "kis_vops_url": ("KIS_VOPS", "vops"),
    "kis_agent": ("KIS_MY_AGENT", "my_agent"),
}


def apply_kis_config_from_setting(setting: Setting) -> None:
    if not setting:
        return

    updates: Dict[str, str] = {}
    for field, (env_key, cfg_key) in _KIS_FIELD_MAP.items():
        value = getattr(setting, field, None)
        if value is None:
            os.environ.pop(env_key, None)
            continue
        value_str = str(value).strip()
        if not value_str:
            os.environ.pop(env_key, None)
            continue
        os.environ[env_key] = value_str
        updates[cfg_key] = value_str

    if not updates:
        return

    try:
        from ..integrations.kis.open_trading import kis_auth_state as state

        state._cfg = {**state._cfg, **updates}
        if "my_agent" in updates:
            state._base_headers["User-Agent"] = updates["my_agent"]
    except Exception as exc:
        logger.warning("Failed to apply KIS config to runtime state: %s", exc)


def apply_kis_config_from_db(db: Session) -> None:
    user = get_or_create_single_user(db)
    setting = (
        db.query(Setting)
        .filter(Setting.user_id == user.id)
        .order_by(Setting.id.asc())
        .first()
    )
    if not setting:
        return
    apply_kis_config_from_setting(setting)
