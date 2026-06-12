from __future__ import annotations

from app.providers.openai_compatible import OpenAICompatibleChatProvider


class ZAIProvider(OpenAICompatibleChatProvider):
    def __init__(self, api_key: str | None, timeout_seconds: float, base_url: str) -> None:
        normalized_base = str(base_url or "https://api.z.ai/v1").rstrip("/")
        super().__init__(
            provider_name="z_ai",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            endpoint=f"{normalized_base}/chat/completions",
        )
