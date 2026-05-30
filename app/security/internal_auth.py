from __future__ import annotations

from fastapi import Request

from app.core.errors import APIError
from app.deps import get_settings


def require_internal_admin(request: Request) -> None:
    settings = get_settings()
    enabled = bool(getattr(settings, "internal_admin_enabled", False))
    token = str(getattr(settings, "nesty_internal_admin_token", "") or "").strip()
    if not enabled or not token:
        raise APIError(
            code="internal_admin_disabled",
            message="Not Found.",
            status_code=404,
        )

    auth_header = (request.headers.get("Authorization") or "").strip()
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise APIError(
            code="internal_admin_unauthorized",
            message="Unauthorized internal admin request.",
            status_code=401,
        )
    provided_token = parts[1].strip()
    if not provided_token or provided_token != token:
        raise APIError(
            code="internal_admin_unauthorized",
            message="Unauthorized internal admin request.",
            status_code=401,
        )
