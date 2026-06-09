from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.errors import APIError
from app.core.model_config_loader import (
    get_default_model_config,
    get_effective_model_config,
    list_effective_model_configs,
    validate_model_config_override,
)
from app.deps import clear_runtime_model_config_caches, get_provider_router
from app.schemas.chat import ChatMessage
from app.security.internal_auth import require_internal_admin
from app.storage.model_configs import (
    get_model_config_audit_logs,
    get_model_override,
    record_model_config_audit,
    reset_model_override,
    upsert_model_override,
)


router = APIRouter(
    prefix="/internal/model-configs",
    tags=["internal-model-configs"],
    dependencies=[Depends(require_internal_admin)],
)


class ModelOverridePatchRequest(BaseModel):
    override: dict[str, Any]
    changed_by_label: str | None = Field(default="internal-admin", max_length=120)


class ModelConfigTestRequest(BaseModel):
    message: str = Field(default="Reply with only: OK", min_length=1, max_length=200)
    stream: bool = False
    changed_by_label: str | None = Field(default="internal-admin", max_length=120)


@router.get("")
async def list_internal_model_configs() -> dict[str, Any]:
    return {
        "object": "list",
        "data": list_effective_model_configs(),
    }


@router.get("/audit")
async def get_model_config_audit_endpoint(model_id: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    rows = get_model_config_audit_logs(model_id=model_id, limit=max(1, int(limit)), offset=max(0, int(offset)))
    return {"object": "list", "data": rows}


@router.get("/{model_id}")
async def get_internal_model_config(model_id: str) -> dict[str, Any]:
    default_config = get_default_model_config(model_id)
    if default_config is None:
        raise APIError(
            code="model_config_not_found",
            message="Model config not found.",
            status_code=404,
        )
    override = get_model_override(model_id)
    effective = get_effective_model_config(model_id)
    return {
        "model_id": model_id,
        "default_config": default_config,
        "override_config": override["config"] if override else None,
        "effective_config": effective or default_config,
        "config_source": "override" if override else "default",
    }


@router.patch("/{model_id}")
async def patch_internal_model_config(model_id: str, body: ModelOverridePatchRequest) -> dict[str, Any]:
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
    updated = upsert_model_override(
        model_id=model_id,
        config=body.override,
        changed_by_api_key_id=None,
        changed_by_label=body.changed_by_label or "internal-admin",
    )
    clear_runtime_model_config_caches()
    effective = get_effective_model_config(model_id) or default_config
    return {
        "ok": True,
        "model_id": model_id,
        "override_config": updated.get("config"),
        "effective_config": effective,
        "config_source": "override",
    }


@router.post("/{model_id}/reset")
async def reset_internal_model_config(model_id: str, changed_by_label: str = "internal-admin") -> dict[str, Any]:
    default_config = get_default_model_config(model_id)
    if default_config is None:
        raise APIError(
            code="model_config_not_found",
            message="Model config not found.",
            status_code=404,
        )
    _ = reset_model_override(
        model_id=model_id,
        changed_by_api_key_id=None,
        changed_by_label=changed_by_label,
    )
    clear_runtime_model_config_caches()
    effective = get_effective_model_config(model_id) or default_config
    return {
        "ok": True,
        "model_id": model_id,
        "effective_config": effective,
        "config_source": "default",
    }


@router.post("/{model_id}/test")
async def test_internal_model_config(model_id: str, body: ModelConfigTestRequest) -> dict[str, Any]:
    default_config = get_default_model_config(model_id)
    if default_config is None:
        raise APIError(
            code="model_config_not_found",
            message="Model config not found.",
            status_code=404,
        )
    effective = get_effective_model_config(model_id) or default_config
    provider_chain = effective.get("provider_chain") or []
    if not isinstance(provider_chain, list) or not provider_chain:
        raise APIError(
            code="model_config_invalid",
            message="Effective model config has invalid provider_chain.",
            status_code=400,
        )

    router_obj = get_provider_router()
    started_at = time.perf_counter()
    try:
        result = await router_obj.generate_with_provider_chain(
            request_id=f"internal-model-test:{model_id}",
            provider_chain=provider_chain,
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "This is an internal model config test request. "
                        "Reply briefly and do not include sensitive details."
                    ),
                ),
                ChatMessage(role="user", content=body.message),
            ],
            temperature=float(effective.get("default_temperature", 0.3)),
            max_tokens=max(16, min(256, int(effective.get("default_max_tokens", 128)))),
            trace_label=f"internal_test:{model_id}",
        )
    except APIError:
        raise
    except Exception as exc:
        raise APIError(
            code="model_config_test_failed",
            message="Model config test failed.",
            status_code=502,
            details={},
        ) from exc

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    preview = (result.provider_result.content or "").strip()[:160]
    record_model_config_audit(
        model_id=model_id,
        action="test_config",
        old_config=None,
        new_config=None,
        changed_by_api_key_id=None,
        changed_by_label=body.changed_by_label or "internal-admin",
    )
    return {
        "ok": True,
        "model_id": model_id,
        "provider": result.provider_used,
        "latency_ms": latency_ms,
        "content_preview": preview,
    }
