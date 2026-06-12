from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.errors import APIError
from app.core.provider_credentials.service import (
    builtin_provider_to_safe_dict,
    delete_managed_api_key,
    list_builtin_credentials_safe,
    list_builtin_providers_safe,
    put_managed_api_key,
    rotate_managed_api_key,
    test_builtin_provider_api_key,
)
from app.core.runtime_gateway_state import record_runtime_config_audit
from app.deps import clear_runtime_model_config_caches, get_settings
from app.security.console_client_auth import require_console_client
from app.security.internal_auth import require_internal_admin
from app.security.secret_redaction import sanitize_config_response


router = APIRouter(
    prefix="/internal/console/runtime",
    tags=["internal-console-builtin-credentials"],
    dependencies=[Depends(require_internal_admin), Depends(require_console_client)],
)


class BuiltinApiKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)


class BuiltinApiKeyTestRequest(BaseModel):
    model: str | None = Field(default=None, max_length=200)
    message: str = Field(default="Reply with exactly: OK", max_length=500)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _console_id(request: Request) -> str | None:
    value = str(request.headers.get("X-Nesty-Console-ID") or "").strip()
    return value or None


def _response(
    request: Request,
    *,
    ok: bool,
    provider_id: str | None,
    changed_fields: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "request_id": _request_id(request),
        "provider_id": provider_id,
        "source": "builtin",
        "changed_fields": changed_fields,
    }
    if extra:
        payload.update(sanitize_config_response(extra))
    return sanitize_config_response(payload)


def _audit(action: str, provider_id: str, request: Request, changed_fields: list[str], result: str = "ok") -> None:
    record_runtime_config_audit(
        config_area="builtin_provider_credential",
        action=f"builtin_provider.{action}",
        changed_fields=changed_fields,
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result=result,
    )


def _map_service_error(exc: Exception) -> APIError:
    if isinstance(exc, KeyError):
        code = str(exc.args[0] if exc.args else "builtin_provider_not_found")
        return APIError(code=code, message="Built-in provider not found.", status_code=404)
    if isinstance(exc, PermissionError):
        return APIError(
            code="provider_credentials_disabled",
            message="Built-in provider credential management is disabled. Set NESTY_PROVIDER_CREDENTIALS_ENABLED=true.",
            status_code=400,
        )
    if isinstance(exc, ValueError):
        return APIError(code="provider_credential_invalid", message="Invalid credential payload.", status_code=400)
    return APIError(code="provider_credential_error", message="Credential operation failed.", status_code=500)


@router.get("/builtin-providers")
async def list_builtin_providers(request: Request) -> dict[str, Any]:
    settings = get_settings()
    return _response(
        request,
        ok=True,
        provider_id=None,
        changed_fields=[],
        extra={"providers": list_builtin_providers_safe(settings)},
    )


@router.get("/builtin-providers/{provider_id}")
async def get_builtin_provider(provider_id: str, request: Request) -> dict[str, Any]:
    settings = get_settings()
    try:
        provider = builtin_provider_to_safe_dict(provider_id, settings)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    return _response(
        request,
        ok=True,
        provider_id=provider["provider_id"],
        changed_fields=[],
        extra={"provider": provider},
    )


@router.get("/builtin-providers/{provider_id}/credentials")
async def list_builtin_provider_credentials(provider_id: str, request: Request) -> dict[str, Any]:
    settings = get_settings()
    try:
        credentials = list_builtin_credentials_safe(provider_id, settings)
        provider = builtin_provider_to_safe_dict(provider_id, settings)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    return _response(
        request,
        ok=True,
        provider_id=provider["provider_id"],
        changed_fields=[],
        extra={"provider": provider, "credentials": credentials},
    )


@router.put("/builtin-providers/{provider_id}/credentials/api-key")
async def put_builtin_provider_api_key(
    provider_id: str,
    body: BuiltinApiKeyRequest,
    request: Request,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        result = put_managed_api_key(provider_id, body.api_key, settings)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    clear_runtime_model_config_caches()
    _audit("credential.put", provider_id, request, ["api_key"])
    return _response(
        request,
        ok=True,
        provider_id=provider_id,
        changed_fields=["api_key"],
        extra={"credential": result},
    )


@router.delete("/builtin-providers/{provider_id}/credentials/api-key")
async def delete_builtin_provider_api_key(provider_id: str, request: Request) -> dict[str, Any]:
    settings = get_settings()
    try:
        delete_managed_api_key(provider_id, settings)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    clear_runtime_model_config_caches()
    _audit("credential.delete", provider_id, request, ["api_key"])
    return _response(
        request,
        ok=True,
        provider_id=provider_id,
        changed_fields=["api_key"],
        extra={"deleted": True},
    )


@router.post("/builtin-providers/{provider_id}/credentials/api-key/rotate")
async def rotate_builtin_provider_api_key(
    provider_id: str,
    body: BuiltinApiKeyRequest,
    request: Request,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        result = rotate_managed_api_key(provider_id, body.api_key, settings)
    except Exception as exc:
        raise _map_service_error(exc) from exc
    clear_runtime_model_config_caches()
    _audit("credential.rotate", provider_id, request, ["api_key"])
    return _response(
        request,
        ok=True,
        provider_id=provider_id,
        changed_fields=["api_key"],
        extra={"credential": result},
    )


@router.post("/builtin-providers/{provider_id}/credentials/api-key/test")
async def test_builtin_provider_api_key_endpoint(
    provider_id: str,
    request: Request,
    body: BuiltinApiKeyTestRequest | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    payload = body or BuiltinApiKeyTestRequest()
    try:
        result = await test_builtin_provider_api_key(
            provider_id,
            settings,
            model=payload.model,
            message=payload.message,
        )
    except Exception as exc:
        raise _map_service_error(exc) from exc
    return _response(
        request,
        ok=bool(result.get("ok")),
        provider_id=provider_id,
        changed_fields=[],
        extra={"test_result": result},
    )
