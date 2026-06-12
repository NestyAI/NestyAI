from __future__ import annotations

from app.providers.openai_compatible import OpenAICompatibleChatProvider


class DeepSeekProvider(OpenAICompatibleChatProvider):
    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        super().__init__(
            provider_name="deepseek",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            endpoint="https://api.deepseek.com/v1/chat/completions",
        )
