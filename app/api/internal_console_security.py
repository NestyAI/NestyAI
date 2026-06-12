from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.bootstrap.internal_admin_token import admin_token_status, rotate_file_backed_admin_token
from app.core.errors import APIError
from app.core.runtime_gateway_state import record_runtime_config_audit
from app.deps import get_settings, set_runtime_settings
from app.security.console_client_auth import require_console_client
from app.security.internal_auth import require_internal_admin
from app.security.secret_redaction import sanitize_config_response


router = APIRouter(
    prefix="/internal/console/security",
    tags=["internal-console-security"],
    dependencies=[Depends(require_internal_admin), Depends(require_console_client)],
)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _console_id(request: Request) -> str | None:
    value = str(request.headers.get("X-Nesty-Console-ID") or "").strip()
    return value or None


def _response(request: Request, *, ok: bool, extra: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "request_id": _request_id(request),
        **sanitize_config_response(extra),
    }
    return sanitize_config_response(payload)


@router.get("/admin-token/status")
async def get_admin_token_status(request: Request) -> dict[str, Any]:
    settings = get_settings()
    status = admin_token_status(settings)
    return _response(request, ok=True, extra={"admin_auth_metadata": status})


@router.post("/admin-token/rotate")
async def rotate_admin_token(request: Request) -> dict[str, Any]:
    settings = get_settings()
    try:
        result = rotate_file_backed_admin_token(settings)
    except ValueError as exc:
        code = str(exc.args[0] if exc.args else "admin_token_rotation_failed")
        message = "Admin token rotation is not supported for the current token mode."
        if code == "admin_token_rotation_unsupported_env":
            message = "Env-mode admin tokens cannot be rotated via API. Update NESTY_INTERNAL_ADMIN_TOKEN manually."
        elif code == "admin_token_rotation_unsupported_ephemeral":
            message = "Ephemeral admin tokens cannot be rotated via API. Switch to file mode for rotation support."
        elif code == "internal_admin_disabled":
            message = "Internal admin is disabled."
        raise APIError(code=code, message=message, status_code=400) from exc

    updated = settings.model_copy(
        update={
            "nesty_internal_admin_token": result.token,
            "internal_admin_token_source": result.source,
            "internal_admin_token_file_resolved": result.file_path,
        }
    )
    set_runtime_settings(updated)
    record_runtime_config_audit(
        config_area="admin_token",
        action="admin_token.rotate",
        changed_fields=["admin_token"],
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result="ok",
    )
    status = admin_token_status(updated)
    return _response(
        request,
        ok=True,
        extra={
            "admin_auth_metadata": status,
            "rotated": True,
            "changed_fields": ["admin_token"],
        },
    )
