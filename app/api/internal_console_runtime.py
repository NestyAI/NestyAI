from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.errors import APIError
from app.core.model_config_loader import (
    get_default_model_config,
    get_effective_model_config,
    list_effective_model_configs,
    validate_model_config_override,
)
from app.core.runtime_gateway_state import (
    get_runtime_gateway_state,
    record_runtime_config_audit,
)
from app.deps import clear_runtime_model_config_caches, get_settings
from app.providers.registry import list_provider_capabilities
from app.security.console_client_auth import require_console_client
from app.security.internal_auth import require_internal_admin
from app.security.secret_redaction import sanitize_config_response
from app.storage.model_configs import get_model_override, reset_model_override, upsert_model_override


router = APIRouter(
    prefix="/internal/console/runtime",
    tags=["internal-console-runtime"],
    dependencies=[Depends(require_internal_admin), Depends(require_console_client)],
)


class RuntimeValidateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=120)
    override: dict[str, Any]


class RuntimeModelConfigUpdateRequest(BaseModel):
    override: dict[str, Any]
    changed_by_label: str | None = Field(default="internal-console", max_length=120)


class RuntimeProviderChainUpdateRequest(BaseModel):
    provider_chain: list[dict[str, Any]]
    changed_by_label: str | None = Field(default="internal-console", max_length=120)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _console_id(request: Request) -> str | None:
    value = str(request.headers.get("X-Nesty-Console-ID") or "").strip()
    return value or None


def _safe_response(
    request: Request,
    *,
    ok: bool,
    config_area: str,
    changed_fields: list[str],
    validation_warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "request_id": _request_id(request),
        "config_area": config_area,
        "changed_fields": changed_fields,
        "validation_warnings": validation_warnings or [],
    }
    if extra:
        payload.update(sanitize_config_response(extra))
    return sanitize_config_response(payload)


def _changed_field_names(override: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in override.keys())


@router.get("/status")
async def runtime_status(request: Request) -> dict[str, Any]:
    state = get_runtime_gateway_state()
    models = [
        {
            "model_id": item.get("model_id"),
            "config_source": item.get("config_source"),
            "display_name": (item.get("effective_config") or {}).get("display_name"),
        }
        for item in list_effective_model_configs()
    ]
    return _safe_response(
        request,
        ok=True,
        config_area="status",
        changed_fields=[],
        extra={
            "disabled_providers": state.get("disabled_providers") or [],
            "runtime_state_updated_at": state.get("updated_at"),
            "provider_capabilities": list_provider_capabilities(get_settings()),
            "models": models,
        },
    )


@router.post("/validate")
async def runtime_validate(body: RuntimeValidateRequest, request: Request) -> dict[str, Any]:
    default_config = get_default_model_config(body.model_id)
    if default_config is None:
        raise APIError(
            code="model_config_not_found",
            message="Model config not found.",
            status_code=404,
        )
    valid, error = validate_model_config_override(body.model_id, body.override)
    validation_warnings: list[str] = []
    if not valid and error:
        validation_warnings.append(error)
    record_runtime_config_audit(
        config_area="model_config",
        action="validate",
        changed_fields=_changed_field_names(body.override),
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result="ok" if valid else "invalid",
    )
    return _safe_response(
        request,
        ok=valid,
        config_area="model_config",
        changed_fields=_changed_field_names(body.override),
        validation_warnings=validation_warnings,
        extra={"model_id": body.model_id, "validation_result": "ok" if valid else "invalid"},
    )


@router.post("/model-configs/{model_id}")
async def runtime_update_model_config(
    model_id: str,
    body: RuntimeModelConfigUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    default_config = get_default_model_config(model_id)
    if default_config is None:
        raise APIError(
            code="model_config_not_found",
            message="Model config not found.",
            status_code=404,
        )
    valid, error = validate_model_config_override(model_id, body.override)
    if not valid:
        raise APIError(
            code="model_config_invalid",
            message=error or "Invalid model config override.",
            status_code=400,
        )
    upsert_model_override(
        model_id=model_id,
        config=body.override,
        changed_by_api_key_id=None,
        changed_by_label=body.changed_by_label or "internal-console",
    )
    clear_runtime_model_config_caches()
    changed_fields = _changed_field_names(body.override)
    record_runtime_config_audit(
        config_area="model_config",
        action="update",
        changed_fields=changed_fields,
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result="ok",
    )
    return _safe_response(
        request,
        ok=True,
        config_area="model_config",
        changed_fields=changed_fields,
        extra={
            "model_id": model_id,
            "config_source": "override",
            "effective_config_summary": {
                "model_id": model_id,
                "display_name": (get_effective_model_config(model_id) or {}).get("display_name"),
            },
        },
    )


@router.post("/model-configs/{model_id}/reset")
async def runtime_reset_model_config(
    model_id: str,
    request: Request,
    changed_by_label: str = "internal-console",
) -> dict[str, Any]:
    default_config = get_default_model_config(model_id)
    if default_config is None:
        raise APIError(
            code="model_config_not_found",
            message="Model config not found.",
            status_code=404,
        )
    previous = get_model_override(model_id)
    reset_model_override(
        model_id=model_id,
        changed_by_api_key_id=None,
        changed_by_label=changed_by_label,
    )
    clear_runtime_model_config_caches()
    changed_fields = sorted((previous or {}).get("config", {}).keys()) if previous else []
    record_runtime_config_audit(
        config_area="model_config",
        action="reset",
        changed_fields=changed_fields,
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result="ok",
    )
    return _safe_response(
        request,
        ok=True,
        config_area="model_config",
        changed_fields=changed_fields,
        extra={"model_id": model_id, "config_source": "default"},
    )


@router.post("/provider-chain/{model_id}")
async def runtime_update_provider_chain(
    model_id: str,
    body: RuntimeProviderChainUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    override = {"provider_chain": body.provider_chain}
    default_config = get_default_model_config(model_id)
    if default_config is None:
        raise APIError(
            code="model_config_not_found",
            message="Model config not found.",
            status_code=404,
        )
    valid, error = validate_model_config_override(model_id, override)
    if not valid:
        raise APIError(
            code="model_config_invalid",
            message=error or "Invalid provider chain override.",
            status_code=400,
        )
    upsert_model_override(
        model_id=model_id,
        config=override,
        changed_by_api_key_id=None,
        changed_by_label=body.changed_by_label or "internal-console",
    )
    clear_runtime_model_config_caches()
    record_runtime_config_audit(
        config_area="provider_chain",
        action="update",
        changed_fields=["provider_chain"],
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result="ok",
    )
    return _safe_response(
        request,
        ok=True,
        config_area="provider_chain",
        changed_fields=["provider_chain"],
        extra={"model_id": model_id, "config_source": "override"},
    )


@router.post("/reload")
async def runtime_reload(request: Request) -> dict[str, Any]:
    clear_runtime_model_config_caches()
    record_runtime_config_audit(
        config_area="runtime",
        action="reload",
        changed_fields=["runtime_cache"],
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result="ok",
    )
    return _safe_response(
        request,
        ok=True,
        config_area="runtime",
        changed_fields=["runtime_cache"],
        extra={"reloaded": True},
    )
