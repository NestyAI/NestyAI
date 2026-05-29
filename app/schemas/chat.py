from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.tools import SourceItem, ToolMetadata

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0)
    stream: bool = False
    search: str = "auto"
    tools: str | list[str] = "auto"


class ChatChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class GuardInfo(BaseModel):
    input_redacted: bool = False
    output_redacted: bool = False
    redaction_count: int = 0
    categories: list[str] = Field(default_factory=list)


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    provider: str
    choices: list[ChatChoice]
    usage: Usage
    guard: GuardInfo
    tools: ToolMetadata = Field(default_factory=ToolMetadata)
    sources: list[SourceItem] = Field(default_factory=list)
