from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.core.errors import MissingAPIKeyError, ProviderError
from app.core.http_client import get_shared_async_client
from app.providers.base import BaseProvider
from app.providers.content_extract import extract_choice_message_content, extract_delta_content
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage


class OpenRouterProvider(BaseProvider):
    provider_name = "openrouter"

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"

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
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
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
        content = extract_choice_message_content(first_choice if isinstance(first_choice, dict) else {})
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
        if not self.api_key:
            raise MissingAPIKeyError(self.provider_name)

        payload = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
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

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw_data = line[len("data:") :].strip()
                    if raw_data == "[DONE]":
                        break
                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue

                    usage_raw = data.get("usage")
                    if isinstance(usage_raw, dict):
                        yield ProviderStreamChunk(
                            usage=ProviderUsage(
                                prompt_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
                                completion_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
                                total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
                            )
                        )

                    choices = data.get("choices") or []
                    for choice in choices:
                        delta_obj = choice.get("delta") or {}
                        content = extract_delta_content(delta_obj if isinstance(delta_obj, dict) else {})
                        finish_reason = choice.get("finish_reason")
                        yield ProviderStreamChunk(
                            delta=content,
                            finish_reason=str(finish_reason) if finish_reason else None,
                        )
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
