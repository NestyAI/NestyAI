from __future__ import annotations

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    source: str | None = None


class FetchResult(BaseModel):
    url: str
    final_url: str | None = None
    title: str | None = None
    text: str = ""
    error: str | None = None
    status_code: int | None = None
    content_chars: int | None = None
    blocked_reason: str | None = None


class SearchToolMetadata(BaseModel):
    enabled: bool = False
    query: str | None = None
    queries: list[str] = Field(default_factory=list)
    results_count: int = 0
    filtered_result_count: int | None = None
    failed: bool = False
    used: bool = False
    provider: str | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    cache_hit: bool = False
    context_chars: int | None = None
    decision_reason: str | None = None


class ToolMetadata(BaseModel):
    used: list[str] = Field(default_factory=list)
    search: SearchToolMetadata = Field(default_factory=SearchToolMetadata)
    executions: list["ToolExecutionMetadata"] = Field(default_factory=list)


class SourceItem(BaseModel):
    title: str
    url: str
    snippet: str


class ContextGuardMetadata(BaseModel):
    sanitized: bool = False
    removed_injection_count: int = 0
    context_chars: int = 0
    sources_count: int = 0


class ToolResult(BaseModel):
    name: str
    success: bool
    content: str
    data: dict | None = None
    error: str | None = None
    sources: list[dict] | None = None
    latency_ms: int | None = None
    cache_hit: bool = False
    confidence: str | None = None
    raw_truncated: bool = False


class ToolExecutionMetadata(BaseModel):
    name: str
    success: bool
    latency_ms: int | None = None
    cache_hit: bool = False
    confidence: str | None = None
    error: str | None = None
    error_code: str | None = None
    result_chars: int | None = None
