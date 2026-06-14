from __future__ import annotations

from app.providers.constants import OPENAI_CHAT_COMPLETIONS_URL
from app.providers.openai_compatible import OpenAICompatibleChatProvider


class OpenAIBuiltinProvider(OpenAICompatibleChatProvider):
    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        super().__init__(
            provider_name="openai",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            endpoint=OPENAI_CHAT_COMPLETIONS_URL,
        )
