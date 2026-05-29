from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ProviderChatResult(BaseModel):
    provider: str
    content: str
    usage: ProviderUsage = Field(default_factory=ProviderUsage)


class ProviderStreamChunk(BaseModel):
    delta: str = ""
    finish_reason: str | None = None
    usage: ProviderUsage | None = None
