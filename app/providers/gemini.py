from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.providers.constants import GEMINI_API_BASE_URL
from app.core.errors import MissingAPIKeyError, ProviderError, StreamingNotSupportedError
from app.core.http_client import get_shared_async_client
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage


class GeminiProvider(BaseProvider):
    provider_name = "google_gemini"
    supports_streaming = True

    def __init__(self, api_key: str | None, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = GEMINI_API_BASE_URL

    def _require_api_key(self) -> str:
        if not self.api_key:
            raise MissingAPIKeyError(self.provider_name)
        return self.api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self._require_api_key(),
        }

    @staticmethod
    def _split_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, object]]]:
        system_parts: list[str] = []
        contents: list[dict[str, object]] = []
        for message in messages:
            role = message.role
            text = str(message.content or "")
            if role == "system":
                if text.strip():
                    system_parts.append(text.strip())
                continue
            if role == "assistant":
                gemini_role = "model"
            elif role == "user":
                gemini_role = "user"
            else:
                gemini_role = "user"
            contents.append({"role": gemini_role, "parts": [{"text": text}]})
        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, object]:
        system_instruction, contents = self._split_messages(messages)
        payload: dict[str, object] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        return payload

    @staticmethod
    def _extract_text(data: dict[str, object]) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else []
        chunks: list[str] = []
        for part in parts or []:
            if isinstance(part, dict):
                text = part.get("text")
                if text:
                    chunks.append(str(text))
        return "".join(chunks)

    @staticmethod
    def _extract_usage(data: dict[str, object]) -> ProviderUsage:
        usage_raw = data.get("usageMetadata") or {}
        if not isinstance(usage_raw, dict):
            usage_raw = {}
        prompt_tokens = int(usage_raw.get("promptTokenCount", 0) or 0)
        completion_tokens = int(usage_raw.get("candidatesTokenCount", 0) or 0)
        total_tokens = int(usage_raw.get("totalTokenCount", 0) or (prompt_tokens + completion_tokens))
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
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

    def _generate_url(self, model: str, *, stream: bool) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        suffix = "?alt=sse" if stream else ""
        return f"{self.base_url}/models/{model}:{action}{suffix}"

    async def generate_chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> ProviderChatResult:
        payload = self._build_payload(messages, temperature=temperature, max_tokens=max_tokens)
        url = self._generate_url(model, stream=False)
        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            response = await client.post(url, json=payload, headers=self._headers())
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
        payload = self._build_payload(messages, temperature=temperature, max_tokens=max_tokens)
        url = self._generate_url(model, stream=True)
        try:
            client = get_shared_async_client(timeout_seconds=self.timeout_seconds)
            async with client.stream("POST", url, json=payload, headers=self._headers()) as response:
                self._handle_response_status(response.status_code)
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    raw = line.strip()
                    if raw.startswith("data:"):
                        raw = raw[len("data:") :].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    usage = self._extract_usage(data)
                    if usage.total_tokens > 0:
                        yield ProviderStreamChunk(usage=usage)
                    text = self._extract_text(data)
                    if text:
                        yield ProviderStreamChunk(delta=text)
                    candidates = data.get("candidates") or []
                    if candidates and isinstance(candidates[0], dict):
                        finish_reason = candidates[0].get("finishReason")
                        if finish_reason:
                            yield ProviderStreamChunk(finish_reason=str(finish_reason))
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
