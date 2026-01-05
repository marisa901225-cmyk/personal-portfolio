from __future__ import annotations

from fastapi import APIRouter

from .report_ai import router as report_ai_router
from .report_core import router as report_core_router
from .report_saved import router as report_saved_router

router = APIRouter()
router.include_router(report_core_router)
router.include_router(report_ai_router)
router.include_router(report_saved_router)
