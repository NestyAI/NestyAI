from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import get_settings
from app.security.auth import require_api_key


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    settings = get_settings()
    if settings.require_api_key and not settings.public_health:
        require_api_key(request)
    return {
        "status": "ok",
        "service": "nesty-ai",
        "version": settings.app_version,
    }

