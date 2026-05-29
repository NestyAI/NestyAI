from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.core.errors import StreamingNotSupportedError
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk


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

    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[ProviderStreamChunk]:
        raise StreamingNotSupportedError(self.provider_name)
        yield ProviderStreamChunk()

