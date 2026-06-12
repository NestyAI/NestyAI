from __future__ import annotations

from typing import Any

from app.core.errors import MissingAPIKeyError, ProviderError
from app.core.runtime_providers.loader import build_runtime_openai_providers
from app.core.runtime_providers.models import RuntimeOpenAIProviderCreateRequest, RuntimeOpenAIProviderUpdateRequest
from app.core.runtime_providers.secrets import (
    delete_provider_secret_file,
    resolve_runtime_provider_api_key,
    write_provider_secret,
)
from app.core.runtime_providers.storage import (
    create_runtime_provider,
    delete_runtime_provider,
    get_runtime_provider,
    set_runtime_provider_enabled,
    update_runtime_provider,
)
from app.core.runtime_providers.validation import (
    normalize_base_url_and_path,
    validate_provider_id,
    validate_runtime_provider_payload,
)
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.security.secret_redaction import redact_secret_text
from app.schemas.chat import ChatMessage


def _capabilities_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "supports_streaming": bool(payload.get("supports_streaming", True)),
        "supports_chat_completions": True,
        "supports_json_mode": bool(payload.get("supports_json_mode", False)),
        "supports_tools": bool(payload.get("supports_tools", False)),
        "supports_reasoning_effort": bool(payload.get("supports_reasoning_effort", False)),
    }


def secret_status_for_row(settings: Any, row: dict[str, Any]) -> str:
    _, status = resolve_runtime_provider_api_key(
        settings=settings,
        provider_id=str(row["provider_id"]),
        api_key_mode=str(row.get("api_key_mode") or "none"),
        api_key_env_name=row.get("api_key_env_name"),
        api_key_secret_ref=row.get("api_key_secret_ref"),
    )
    return status


def build_create_record(body: RuntimeOpenAIProviderCreateRequest, settings: Any) -> tuple[dict[str, Any], str | None]:
    base_url, path, split_error = normalize_base_url_and_path(body.base_url, body.chat_completions_path)
    if split_error:
        return {}, split_error
    record: dict[str, Any] = {
        "provider_id": body.provider_id.strip().lower(),
        "provider_type": "openai_compatible",
        "display_name": body.display_name.strip(),
        "enabled": body.enabled,
        "base_url": base_url,
        "chat_completions_path": path,
        "models_path": body.models_path,
        "api_key_mode": body.api_key_mode,
        "api_key_env_name": body.api_key_env_name,
        "api_key_secret_ref": None,
        "default_headers": dict(body.default_headers or {}),
        "default_timeout_seconds": body.default_timeout_seconds,
        "capabilities": _capabilities_from_payload(body.model_dump()),
        "health_check_model": body.health_check_model,
    }
    valid, error = validate_runtime_provider_payload(record, settings=settings)
    if not valid:
        return {}, error
    if record["api_key_mode"] == "secret_file" and body.api_key:
        record["api_key_secret_ref"] = write_provider_secret(settings, record["provider_id"], body.api_key)
    elif record["api_key_mode"] == "secret_file":
        return {}, "runtime_provider_invalid: api_key is required for secret_file mode"
    return record, None


def apply_update(
    provider_id: str,
    body: RuntimeOpenAIProviderUpdateRequest,
    settings: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    existing = get_runtime_provider(provider_id, db_path=_db_path())
    if existing is None:
        return None, "runtime_provider_not_found"
    updates = body.model_dump(exclude_unset=True)
    api_key = updates.pop("api_key", None)
    merged = dict(existing)
    if "base_url" in updates or "chat_completions_path" in updates:
        base_url, path, split_error = normalize_base_url_and_path(
            str(updates.get("base_url") or merged["base_url"]),
            str(updates.get("chat_completions_path") or merged.get("chat_completions_path") or "/v1/chat/completions"),
        )
        if split_error:
            return None, split_error
        updates["base_url"] = base_url
        updates["chat_completions_path"] = path
    for key, value in updates.items():
        if key.startswith("supports_"):
            continue
        merged[key] = value
    caps = dict(merged.get("capabilities") or {})
    for cap_key in ("supports_streaming", "supports_json_mode", "supports_tools", "supports_reasoning_effort"):
        if cap_key in updates:
            caps[cap_key] = updates[cap_key]
    merged["capabilities"] = caps
    valid, error = validate_runtime_provider_payload(merged, settings=settings)
    if not valid:
        return None, error
    if api_key and str(merged.get("api_key_mode") or "") == "secret_file":
        merged["api_key_secret_ref"] = write_provider_secret(settings, provider_id, str(api_key))
    elif str(updates.get("api_key_mode") or merged.get("api_key_mode") or "") == "secret_file" and api_key:
        merged["api_key_secret_ref"] = write_provider_secret(settings, provider_id, str(api_key))
    updated = update_runtime_provider(provider_id, merged, db_path=_db_path())
    return updated, None


def _db_path() -> str | None:
    from app.core.runtime_providers.storage import get_settings as storage_get_settings

    return storage_get_settings().nesty_db_path


async def run_runtime_provider_test(
    provider_id: str,
    *,
    settings: Any,
    model: str | None = None,
    message: str = "Reply with exactly: OK",
    resolve_dns: bool = True,
) -> dict[str, Any]:
    if not bool(getattr(settings, "nesty_runtime_openai_providers_enabled", True)):
        return {
            "ok": False,
            "error_code": "runtime_providers_disabled",
            "warnings": ["Runtime OpenAI providers are disabled; enable NESTY_RUNTIME_OPENAI_PROVIDERS_ENABLED to route traffic."],
        }
    row = get_runtime_provider(provider_id, db_path=_db_path())
    if row is None:
        return {"ok": False, "error_code": "runtime_provider_not_found"}
    valid, error = validate_runtime_provider_payload(row, settings=settings, resolve_dns=resolve_dns)
    if not valid:
        return {"ok": False, "error_code": "runtime_provider_invalid", "warnings": [error or "invalid provider"]}
    providers = build_runtime_openai_providers(settings)
    provider = providers.get(provider_id)
    if provider is None:
        return {"ok": False, "error_code": "runtime_provider_unavailable"}
    test_model = model or row.get("health_check_model") or "gpt-3.5-turbo"
    try:
        result = await provider.generate_chat_completion(
            messages=[ChatMessage(role="user", content=message)],
            model=str(test_model),
            temperature=0.0,
            max_tokens=16,
        )
    except MissingAPIKeyError:
        return {"ok": False, "error_code": "missing_api_key", "status": "failed"}
    except ProviderError as exc:
        warning = redact_secret_text(str(exc.message or "Provider test failed.")[:120])
        return {
            "ok": False,
            "error_code": "provider_failed",
            "status": "failed",
            "warnings": [warning],
        }
    except Exception:
        return {"ok": False, "error_code": "runtime_provider_test_failed", "status": "failed"}
    preview = (result.content or "").strip()[:80]
    return {"ok": True, "status": "ok", "output_chars": len(preview), "output_preview": preview}


def remove_runtime_provider(provider_id: str, settings: Any) -> bool:
    db_path = _db_path()
    row = get_runtime_provider(provider_id, db_path=db_path)
    if row is None:
        return False
    if provider_id in BUILTIN_PROVIDER_IDS:
        return False
    delete_provider_secret_file(settings, provider_id, row.get("api_key_secret_ref"))
    return delete_runtime_provider(provider_id, db_path=db_path)


def runtime_set_enabled(provider_id: str, *, enabled: bool) -> dict[str, Any]:
    return set_runtime_provider_enabled(provider_id, enabled=enabled, db_path=_db_path())


def validate_new_provider_id(provider_id: str) -> tuple[bool, str | None]:
    return validate_provider_id(provider_id)
