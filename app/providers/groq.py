from __future__ import annotations

from app.providers.constants import GROQ_CHAT_COMPLETIONS_URL
from app.providers.openai_compatible import OpenAICompatibleChatProvider


class GroqProvider(OpenAICompatibleChatProvider):
    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        super().__init__(
            provider_name="groq",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            endpoint=GROQ_CHAT_COMPLETIONS_URL,
        )
