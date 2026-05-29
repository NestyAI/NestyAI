from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from app.core.errors import MissingAPIKeyError, ProviderError, StreamingNotSupportedError
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage


class NvidiaProvider(BaseProvider):
    provider_name = "nvidia"

    def __init__(self, api_key: str | None, timeout_seconds: float, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = (base_url or "").rstrip("/")

    @property
    def endpoint(self) -> str:
        if not self.base_url:
            raise ProviderError(
                provider=self.provider_name,
                message="NVIDIA endpoint is not configured.",
                retryable=True,
            )
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        if not self.api_key:
            raise MissingAPIKeyError(self.provider_name)

        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider request timed out.",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Network error while calling provider.",
                retryable=True,
            ) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider temporarily unavailable.",
                retryable=True,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise ProviderError(
                provider=self.provider_name,
                message="Provider rejected request.",
                retryable=False,
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Invalid provider response format.",
                retryable=True,
                status_code=response.status_code,
            ) from exc
        choices = data.get("choices") or []
        first_choice = choices[0] if choices else {}
        content = first_choice.get("message", {}).get("content", "")
        if not isinstance(content, str):
            content = str(content)
        usage_raw = data.get("usage", {})
        usage = ProviderUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
            total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
        )
        return ProviderChatResult(provider=self.provider_name, content=content, usage=usage)

    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[ProviderStreamChunk]:
        raise StreamingNotSupportedError(self.provider_name)
        yield ProviderStreamChunk()
