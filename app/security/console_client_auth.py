from __future__ import annotations

from fastapi import Request

import app.deps as deps
from app.core.errors import APIError
from app.security.secret_compare import secrets_equal


def get_settings():
    return deps.get_settings()


def require_console_client(request: Request) -> None:
    settings = get_settings()
    if not bool(getattr(settings, "nesty_console_client_auth_required", False)):
        return

    expected_id = str(getattr(settings, "nesty_console_client_id", "default-console") or "default-console").strip()
    expected_secret = str(getattr(settings, "nesty_console_client_secret", "") or "").strip()
    if not expected_secret:
        raise APIError(
            code="console_client_misconfigured",
            message="Console client authentication is required but no console secret is configured.",
            status_code=503,
        )

    provided_id = str(request.headers.get("X-Nesty-Console-ID") or "").strip()
    provided_secret = str(request.headers.get("X-Nesty-Console-Secret") or "").strip()
    if not provided_id or not provided_secret:
        raise APIError(
            code="console_client_unauthorized",
            message="Unauthorized console client request.",
            status_code=401,
        )
    if provided_id != expected_id or not secrets_equal(provided_secret, expected_secret):
        raise APIError(
            code="console_client_unauthorized",
            message="Unauthorized console client request.",
            status_code=401,
        )
