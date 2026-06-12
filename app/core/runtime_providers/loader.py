from __future__ import annotations

from typing import Any

from app.core.runtime_providers.secrets import resolve_runtime_provider_api_key
from app.core.runtime_providers.storage import list_runtime_providers
from app.providers.base import BaseProvider
from app.providers.openai_compatible import OpenAICompatibleChatProvider


def build_runtime_openai_providers(settings: Any, db_path: str | None = None) -> dict[str, BaseProvider]:
    if not bool(getattr(settings, "nesty_runtime_openai_providers_enabled", True)):
        return {}
    db_path = getattr(settings, "nesty_db_path", None)
    providers: dict[str, BaseProvider] = {}
    for row in list_runtime_providers(include_disabled=False, db_path=db_path):
        provider_id = str(row["provider_id"])
        api_key, _status = resolve_runtime_provider_api_key(
            settings=settings,
            provider_id=provider_id,
            api_key_mode=str(row.get("api_key_mode") or "none"),
            api_key_env_name=row.get("api_key_env_name"),
            api_key_secret_ref=row.get("api_key_secret_ref"),
        )
        api_key_mode = str(row.get("api_key_mode") or "none").strip().lower()
        endpoint = f"{str(row['base_url']).rstrip('/')}{row.get('chat_completions_path') or '/v1/chat/completions'}"
        capabilities = row.get("capabilities") or {}
        providers[provider_id] = OpenAICompatibleChatProvider(
            provider_name=provider_id,
            api_key=api_key,
            timeout_seconds=float(row.get("default_timeout_seconds") or settings.request_timeout_seconds),
            endpoint=endpoint,
            extra_headers=dict(row.get("default_headers") or {}),
            supports_streaming=bool(capabilities.get("supports_streaming", True)),
            require_api_key=api_key_mode != "none",
        )
    return providers
