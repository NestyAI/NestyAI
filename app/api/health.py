from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_settings


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": "nesty-ai",
        "version": settings.app_version,
    }

