from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult


class BaseProvider(ABC):
    provider_name: str

    @abstractmethod
    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        raise NotImplementedError

