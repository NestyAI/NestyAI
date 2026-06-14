from __future__ import annotations

from app.providers.constants import Z_AI_DEFAULT_BASE_URL, openai_compatible_chat_url
from app.providers.openai_compatible import OpenAICompatibleChatProvider


class ZAIProvider(OpenAICompatibleChatProvider):
    def __init__(self, api_key: str | None, timeout_seconds: float, base_url: str | None = None) -> None:
        normalized_base = str(base_url or Z_AI_DEFAULT_BASE_URL).rstrip("/")
        super().__init__(
            provider_name="z_ai",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            endpoint=openai_compatible_chat_url(normalized_base),
        )
