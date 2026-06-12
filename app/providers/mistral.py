from __future__ import annotations

from app.providers.openai_compatible import OpenAICompatibleChatProvider


class MistralProvider(OpenAICompatibleChatProvider):
    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        super().__init__(
            provider_name="mistral",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            endpoint="https://api.mistral.ai/v1/chat/completions",
        )
