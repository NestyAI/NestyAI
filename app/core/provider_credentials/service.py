from __future__ import annotations

from typing import Any

from app.core.errors import MissingAPIKeyError, ProviderError
from app.core.provider_credentials.backends.sqlite_file import SQLiteFileCredentialBackend
from app.core.provider_credentials.resolver import (
    credential_status_for_provider,
    credentials_feature_enabled,
    resolve_builtin_provider_api_key,
)
from app.core.provider_credentials.secrets import delete_builtin_provider_secret
from app.core.provider_credentials.store import get_provider_credential, list_provider_credentials
from app.providers.constants import BUILTIN_PROVIDER_IDS
from app.providers.registry import PROVIDER_CAPABILITIES, build_builtin_chat_providers
from app.schemas.chat import ChatMessage
from app.security.secret_redaction import redact_secret_text


def _require_builtin_provider(provider_id: str) -> None:
    normalized = str(provider_id or "").strip().lower()
    if normalized not in BUILTIN_PROVIDER_IDS:
        raise KeyError("builtin_provider_not_found")
    if normalized not in PROVIDER_CAPABILITIES:
        raise KeyError("builtin_provider_not_found")


def _require_credentials_enabled(settings: Any) -> None:
    if not credentials_feature_enabled(settings):
        raise PermissionError("provider_credentials_disabled")


def builtin_provider_to_safe_dict(provider_id: str, settings: Any) -> dict[str, Any]:
    _require_builtin_provider(provider_id)
    caps = PROVIDER_CAPABILITIES[provider_id]
    cred_meta = credential_status_for_provider(provider_id, settings)
    return {
        "provider_id": caps.provider_id,
        "source": "builtin",
        "provider_type": "native" if provider_id in {"google_gemini", "anthropic_claude"} else "openai_compatible",
        "display_name": caps.display_name,
        "supports_streaming": caps.supports_streaming,
        "supports_chat_completions": caps.supports_chat_completions,
        "supports_tools": caps.supports_tools,
        "supports_json_mode": caps.supports_json_mode,
        "supports_reasoning_effort": caps.supports_reasoning_effort,
        "default_timeout_seconds": caps.default_timeout_seconds,
        "health_check_model": caps.health_check_model,
        "api_base_env_name": caps.api_base_env_name,
        "api_key_env_name": caps.api_key_env_name,
        **cred_meta,
    }


def list_builtin_providers_safe(settings: Any) -> list[dict[str, Any]]:
    return [builtin_provider_to_safe_dict(provider_id, settings) for provider_id in sorted(PROVIDER_CAPABILITIES)]


def list_builtin_credentials_safe(provider_id: str, settings: Any) -> list[dict[str, Any]]:
    _require_builtin_provider(provider_id)
    cred_meta = credential_status_for_provider(provider_id, settings)
    records = list_provider_credentials(provider_id, settings=settings)
    items: list[dict[str, Any]] = []
    for record in records:
        items.append(
            {
                **record.to_safe_dict(),
                "secret_status": cred_meta["secret_status"],
            }
        )
    if not items:
        items.append(
            {
                "provider_id": provider_id,
                "credential_name": "api_key",
                "source": cred_meta["credential_source"],
                "secret_ref": None,
                "enabled": True,
                "secret_status": cred_meta["secret_status"],
            }
        )
    return items


def put_managed_api_key(provider_id: str, api_key: str, settings: Any) -> dict[str, Any]:
    _require_credentials_enabled(settings)
    _require_builtin_provider(provider_id)
    normalized_key = str(api_key or "").strip()
    if not normalized_key:
        raise ValueError("provider_credential_invalid")
    backend = SQLiteFileCredentialBackend(settings)
    record = backend.upsert_managed(provider_id, normalized_key)
    return {
        "provider_id": provider_id,
        "credential_name": record.credential_name,
        "source": record.source,
        "secret_ref": record.secret_ref,
        **credential_status_for_provider(provider_id, settings),
    }


def delete_managed_api_key(provider_id: str, settings: Any) -> bool:
    _require_credentials_enabled(settings)
    _require_builtin_provider(provider_id)
    record = get_provider_credential(provider_id, settings=settings)
    backend = SQLiteFileCredentialBackend(settings)
    deleted = backend.delete(provider_id)
    if record and record.secret_ref:
        delete_builtin_provider_secret(settings, provider_id, record.secret_ref)
    else:
        delete_builtin_provider_secret(settings, provider_id)
    return deleted


def rotate_managed_api_key(provider_id: str, api_key: str, settings: Any) -> dict[str, Any]:
    _require_credentials_enabled(settings)
    _require_builtin_provider(provider_id)
    normalized_key = str(api_key or "").strip()
    if not normalized_key:
        raise ValueError("provider_credential_invalid")
    backend = SQLiteFileCredentialBackend(settings)
    record = backend.upsert_managed(provider_id, normalized_key, rotated=True)
    return {
        "provider_id": provider_id,
        "credential_name": record.credential_name,
        "source": record.source,
        "secret_ref": record.secret_ref,
        "last_rotated_at": record.last_rotated_at,
        **credential_status_for_provider(provider_id, settings),
    }


async def test_builtin_provider_api_key(
    provider_id: str,
    settings: Any,
    *,
    model: str | None = None,
    message: str = "Reply with exactly: OK",
) -> dict[str, Any]:
    _require_builtin_provider(provider_id)
    caps = PROVIDER_CAPABILITIES[provider_id]
    api_key, status = resolve_builtin_provider_api_key(provider_id, settings)
    if not api_key:
        return {"ok": False, "error_code": "missing_api_key", "secret_status": status}
    providers = build_builtin_chat_providers(settings)
    provider = providers.get(provider_id)
    if provider is None:
        return {"ok": False, "error_code": "builtin_provider_unavailable"}
    test_model = model or caps.health_check_model
    if not test_model:
        return {"ok": False, "error_code": "health_check_model_not_configured"}
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
        return {"ok": False, "error_code": "builtin_provider_test_failed", "status": "failed"}
    preview = (result.content or "").strip()[:80]
    return {
        "ok": True,
        "status": "ok",
        "secret_status": "configured",
        "output_chars": len(preview),
        "output_preview": preview,
    }
