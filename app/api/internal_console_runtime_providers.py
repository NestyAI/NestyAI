from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.errors import APIError
from app.core.runtime_gateway_state import record_runtime_config_audit, set_provider_runtime_disabled
from app.core.runtime_providers.models import (
    RuntimeOpenAIProviderCreateRequest,
    RuntimeOpenAIProviderUpdateRequest,
    RuntimeProviderTestRequest,
    runtime_provider_to_safe_dict,
)
from app.core.runtime_providers.service import (
    apply_update,
    build_create_record,
    remove_runtime_provider,
    runtime_set_enabled,
    secret_status_for_row,
    run_runtime_provider_test,
)
from app.core.runtime_providers.storage import create_runtime_provider, get_runtime_provider
from app.deps import clear_runtime_model_config_caches, get_settings
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.providers.registry import list_provider_capabilities
from app.security.console_client_auth import require_console_client
from app.security.internal_auth import require_internal_admin
from app.security.secret_redaction import sanitize_config_response


router = APIRouter(
    prefix="/internal/console/runtime",
    tags=["internal-console-runtime-providers"],
    dependencies=[Depends(require_internal_admin), Depends(require_console_client)],
)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _console_id(request: Request) -> str | None:
    value = str(request.headers.get("X-Nesty-Console-ID") or "").strip()
    return value or None


def _provider_response(
    request: Request,
    *,
    ok: bool,
    provider_id: str | None,
    provider_type: str | None,
    changed_fields: list[str],
    secret_status: str | None = None,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "request_id": _request_id(request),
        "provider_id": provider_id,
        "provider_type": provider_type,
        "changed_fields": changed_fields,
        "secret_status": secret_status,
        "warnings": warnings or [],
    }
    if extra:
        payload.update(sanitize_config_response(extra))
    return sanitize_config_response(payload)


def _audit(action: str, provider_id: str, request: Request, changed_fields: list[str], result: str = "ok") -> None:
    record_runtime_config_audit(
        config_area="runtime_provider",
        action=f"runtime_provider.{action}",
        changed_fields=changed_fields,
        actor_type="internal_console",
        console_id=_console_id(request),
        validation_result=result,
    )


@router.get("/providers")
async def list_runtime_providers_endpoint(request: Request) -> dict[str, Any]:
    settings = get_settings()
    return _provider_response(
        request,
        ok=True,
        provider_id=None,
        provider_type=None,
        changed_fields=[],
        extra={"providers": list_provider_capabilities(settings)},
    )


@router.post("/providers/openai-compatible")
async def create_openai_compatible_provider(
    body: RuntimeOpenAIProviderCreateRequest,
    request: Request,
) -> dict[str, Any]:
    settings = get_settings()
    record, error = build_create_record(body, settings)
    if error:
        raise APIError(code="runtime_provider_invalid", message=error, status_code=400)
    if get_runtime_provider(record["provider_id"]) is not None:
        raise APIError(code="runtime_provider_conflict", message="Provider already exists.", status_code=409)
    created = create_runtime_provider(record)
    clear_runtime_model_config_caches()
    _audit("created", created["provider_id"], request, sorted(record.keys()))
    return _provider_response(
        request,
        ok=True,
        provider_id=created["provider_id"],
        provider_type="openai_compatible",
        changed_fields=sorted(record.keys()),
        secret_status=secret_status_for_row(settings, created),
    )


@router.get("/providers/{provider_id}")
async def get_runtime_provider_endpoint(provider_id: str, request: Request) -> dict[str, Any]:
    settings = get_settings()
    provider = str(provider_id or "").strip().lower()
    if provider in BUILTIN_PROVIDER_IDS:
        caps = next((item for item in list_provider_capabilities(settings) if item.get("provider_id") == provider), None)
        if caps is None:
            raise APIError(code="runtime_provider_not_found", message="Provider not found.", status_code=404)
        return _provider_response(
            request,
            ok=True,
            provider_id=provider,
            provider_type="builtin",
            changed_fields=[],
            extra={"provider": caps},
        )
    row = get_runtime_provider(provider)
    if row is None:
        raise APIError(code="runtime_provider_not_found", message="Provider not found.", status_code=404)
    return _provider_response(
        request,
        ok=True,
        provider_id=provider,
        provider_type="openai_compatible",
        changed_fields=[],
        secret_status=secret_status_for_row(settings, row),
        extra={"provider": runtime_provider_to_safe_dict(row, secret_status=secret_status_for_row(settings, row))},
    )


@router.patch("/providers/{provider_id}")
async def patch_runtime_provider_endpoint(
    provider_id: str,
    body: RuntimeOpenAIProviderUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    settings = get_settings()
    provider = str(provider_id or "").strip().lower()
    if provider in BUILTIN_PROVIDER_IDS:
        raise APIError(code="runtime_provider_conflict", message="Built-in providers cannot be modified.", status_code=400)
    updated, error = apply_update(provider, body, settings)
    if error == "runtime_provider_not_found":
        raise APIError(code="runtime_provider_not_found", message="Provider not found.", status_code=404)
    if error:
        raise APIError(code="runtime_provider_invalid", message=error, status_code=400)
    assert updated is not None
    clear_runtime_model_config_caches()
    changed_fields = sorted(body.model_dump(exclude_unset=True).keys())
    if "api_key" in changed_fields:
        changed_fields = [field for field in changed_fields if field != "api_key"] + ["api_key_secret_ref"]
    _audit("updated", provider, request, changed_fields)
    return _provider_response(
        request,
        ok=True,
        provider_id=provider,
        provider_type="openai_compatible",
        changed_fields=changed_fields,
        secret_status=secret_status_for_row(settings, updated),
    )


@router.delete("/providers/{provider_id}")
async def delete_runtime_provider_endpoint(provider_id: str, request: Request) -> dict[str, Any]:
    settings = get_settings()
    provider = str(provider_id or "").strip().lower()
    if provider in BUILTIN_PROVIDER_IDS:
        raise APIError(code="runtime_provider_conflict", message="Built-in providers cannot be deleted.", status_code=400)
    if not remove_runtime_provider(provider, settings):
        raise APIError(code="runtime_provider_not_found", message="Provider not found.", status_code=404)
    clear_runtime_model_config_caches()
    _audit("deleted", provider, request, ["provider_id"])
    return _provider_response(
        request,
        ok=True,
        provider_id=provider,
        provider_type="openai_compatible",
        changed_fields=["provider_id"],
        secret_status="none",
    )


@router.post("/providers/{provider_id}/test")
async def test_runtime_provider_endpoint(
    provider_id: str,
    body: RuntimeProviderTestRequest,
    request: Request,
) -> dict[str, Any]:
    settings = get_settings()
    provider = str(provider_id or "").strip().lower()
    if provider in BUILTIN_PROVIDER_IDS:
        raise APIError(code="runtime_provider_invalid", message="Use diagnostics endpoints for built-in providers.", status_code=400)
    result = await run_runtime_provider_test(
        provider,
        settings=settings,
        model=body.model,
        message=body.message,
        resolve_dns=True,
    )
    _audit("tested", provider, request, ["test"], result="ok" if result.get("ok") else "invalid")
    return _provider_response(
        request,
        ok=bool(result.get("ok")),
        provider_id=provider,
        provider_type="openai_compatible",
        changed_fields=["test"],
        warnings=list(result.get("warnings") or []),
        extra={
            "status": result.get("status"),
            "error_code": result.get("error_code"),
            "output_preview": result.get("output_preview"),
        },
    )


@router.post("/providers/{provider_id}/enable")
async def enable_provider_endpoint(provider_id: str, request: Request) -> dict[str, Any]:
    settings = get_settings()
    provider = str(provider_id or "").strip().lower()
    if provider in BUILTIN_PROVIDER_IDS:
        state = set_provider_runtime_disabled(provider, disabled=False)
        clear_runtime_model_config_caches()
        _audit("enabled", provider, request, ["disabled_providers"])
        return _provider_response(
            request,
            ok=True,
            provider_id=provider,
            provider_type="builtin",
            changed_fields=["disabled_providers"],
            extra={"disabled_providers": state.get("disabled_providers") or [], "semantics": "routing_only"},
        )
    row = get_runtime_provider(provider)
    if row is None:
        raise APIError(code="runtime_provider_not_found", message="Provider not found.", status_code=404)
    updated = runtime_set_enabled(provider, enabled=True)
    clear_runtime_model_config_caches()
    _audit("enabled", provider, request, ["enabled"])
    return _provider_response(
        request,
        ok=True,
        provider_id=provider,
        provider_type="openai_compatible",
        changed_fields=["enabled"],
        secret_status=secret_status_for_row(settings, updated),
        extra={"semantics": "persistent_enabled_flag"},
    )


@router.post("/providers/{provider_id}/disable")
async def disable_provider_endpoint(provider_id: str, request: Request) -> dict[str, Any]:
    settings = get_settings()
    provider = str(provider_id or "").strip().lower()
    if provider in BUILTIN_PROVIDER_IDS:
        state = set_provider_runtime_disabled(provider, disabled=True)
        clear_runtime_model_config_caches()
        _audit("disabled", provider, request, ["disabled_providers"])
        return _provider_response(
            request,
            ok=True,
            provider_id=provider,
            provider_type="builtin",
            changed_fields=["disabled_providers"],
            extra={"disabled_providers": state.get("disabled_providers") or [], "semantics": "routing_only"},
        )
    row = get_runtime_provider(provider)
    if row is None:
        raise APIError(code="runtime_provider_not_found", message="Provider not found.", status_code=404)
    updated = runtime_set_enabled(provider, enabled=False)
    clear_runtime_model_config_caches()
    _audit("disabled", provider, request, ["enabled"])
    return _provider_response(
        request,
        ok=True,
        provider_id=provider,
        provider_type="openai_compatible",
        changed_fields=["enabled"],
        secret_status=secret_status_for_row(settings, updated),
        extra={"semantics": "persistent_enabled_false"},
    )
