from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.providers.constants import ANTHROPIC_MESSAGES_URL
from app.core.errors import MissingAPIKeyError, ProviderError, StreamingNotSupportedError
from app.core.http_client import get_shared_async_client
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage


class AnthropicProvider(BaseProvider):
    provider_name = "anthropic_claude"
    supports_streaming = True

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.endpoint = ANTHROPIC_MESSAGES_URL

    def _require_api_key(self) -> str:
        if not self.api_key:
            raise MissingAPIKeyError(self.provider_name)
        return self.api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self._require_api_key(),
            "anthropic-version": "2023-06-01",
        }

    @staticmethod
    def _split_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, str]]]:
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, str]] = []
        for message in messages:
            role = message.role
            text = str(message.content or "")
            if role == "system":
                if text.strip():
                    system_parts.append(text.strip())
                continue
            if role == "assistant":
                mapped_role = "assistant"
            else:
                mapped_role = "user"
            anthropic_messages.append({"role": mapped_role, "content": text})
        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, anthropic_messages

    def _build_payload(
        self,
        messages: list[ChatMessage],
        model: str,
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, object]:
        system_instruction, anthropic_messages = self._split_messages(messages)
        payload: dict[str, object] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if system_instruction:
            payload["system"] = system_instruction
        return payload

    @staticmethod
    def _extract_text(data: dict[str, object]) -> str:
        content = data.get("content") or []
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if text:
                    chunks.append(str(text))
        return "".join(chunks)

    @staticmethod
    def _extract_usage(data: dict[str, object]) -> ProviderUsage:
        usage_raw = data.get("usage") or {}
        if not isinstance(usage_raw, dict):
            usage_raw = {}
        prompt_tokens = int(usage_raw.get("input_tokens", 0) or 0)
        completion_tokens = int(usage_raw.get("output_tokens", 0) or 0)
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    def _raise_provider_error(self, *, status_code: int, retryable: bool, message: str) -> None:
        raise ProviderError(
            provider=self.provider_name,
            message=message,
            retryable=retryable,
            status_code=status_code,
        )

    def _handle_response_status(self, status_code: int) -> None:
        if status_code in {401, 403}:
            self._raise_provider_error(
                status_code=status_code,
                retryable=False,
                message="Provider authentication failed.",
            )
        if status_code == 429 or status_code >= 500:
            self._raise_provider_error(
                status_code=status_code,
                retryable=True,
                message="Provider temporarily unavailable.",
            )
        if status_code >= 400:
            self._raise_provider_error(
                status_code=status_code,
                retryable=False,
                message="Provider rejected request.",
            )

    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        payload = self._build_payload(
            messages,
            model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            response = await client.post(self.endpoint, json=payload, headers=self._headers())
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

        self._handle_response_status(response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                provider=self.provider_name,
                message="Invalid provider response format.",
                retryable=True,
                status_code=response.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                provider=self.provider_name,
                message="Invalid provider response format.",
                retryable=True,
                status_code=response.status_code,
            )
        return ProviderChatResult(
            provider=self.provider_name,
            content=self._extract_text(data),
            usage=self._extract_usage(data),
        )

    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[ProviderStreamChunk]:
        if not self.supports_streaming:
            raise StreamingNotSupportedError(self.provider_name)
        payload = self._build_payload(
            messages,
            model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            async with client.stream("POST", self.endpoint, json=payload, headers=self._headers()) as response:
                self._handle_response_status(response.status_code)
                current_event: str | None = None
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line[len("event:") :].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    event_type = str(data.get("type") or current_event or "")
                    if event_type == "content_block_delta":
                        delta = data.get("delta") or {}
                        if isinstance(delta, dict):
                            text = delta.get("text")
                            if text:
                                yield ProviderStreamChunk(delta=str(text))
                    elif event_type == "message_delta":
                        usage = self._extract_usage(data)
                        if usage.total_tokens > 0:
                            yield ProviderStreamChunk(usage=usage)
                        stop_reason = data.get("delta", {}).get("stop_reason") if isinstance(data.get("delta"), dict) else None
                        if stop_reason:
                            yield ProviderStreamChunk(finish_reason=str(stop_reason))
                    elif event_type == "message_stop":
                        yield ProviderStreamChunk(finish_reason="stop")
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
