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
    orchestration: str = "auto"
    semantic_recall: str = "auto"
    conversation_id: str | None = None
    store: bool = False
    summary: str = "auto"
    request_api_key_id: str | None = Field(default=None, exclude=True)
    conversation_created: bool = Field(default=False, exclude=True)
    conversation_summary_used: bool = Field(default=False, exclude=True)
    conversation_summary_updated: bool = Field(default=False, exclude=True)
    conversation_summary_mode: str = Field(default="auto", exclude=True)


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


class AuthDebugInfo(BaseModel):
    api_key_id: str
    key_name: str


class ConversationInfo(BaseModel):
    id: str
    created: bool = False
    summary_mode: str = "auto"
    summary_used: bool = False
    summary_updated: bool = False


class OrchestrationInfo(BaseModel):
    enabled: bool = False
    requested: bool | str = "auto"
    used: bool = False
    mode: str = "single"
    decision_reason: str | None = None
    complexity_score: int = 0
    roles: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    internal_calls: int = 0
    role_latency_ms: dict[str, int] | None = None
    reason: str | None = None
    completed_roles: list[str] = Field(default_factory=list)
    failed_roles: list[str] = Field(default_factory=list)
    skipped_roles: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    streaming_fallback: bool = False
    total_latency_ms: int | None = None


class SemanticRecallInfo(BaseModel):
    enabled: bool = False
    requested: str = "auto"
    used: bool = False
    reason: str | None = None
    matches_count: int = 0
    pinned_matches_count: int = 0
    excluded_matches_count: int = 0
    deduped_count: int = 0
    top_k: int = 0
    min_score: float = 0.0
    max_score: float | None = None
    min_returned_score: float | None = None
    scope: str = "conversation"
    candidate_count: int = 0
    used_context_chars: int = 0


class ProviderHealthSkippedTarget(BaseModel):
    provider: str
    model: str
    reason: str


class ProviderHealthInfo(BaseModel):
    aware_routing: bool = False
    strict_mode: bool = False
    skipped_targets: list[ProviderHealthSkippedTarget] = Field(default_factory=list)
    fallback_to_unhealthy_allowed: bool = False
    all_targets_skipped: bool = False


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
    orchestration: OrchestrationInfo | None = None
    semantic_recall: SemanticRecallInfo | None = None
    provider_health: ProviderHealthInfo | None = None
    auth: AuthDebugInfo | None = None
    conversation: ConversationInfo | None = None
    model_alias: str | None = None
