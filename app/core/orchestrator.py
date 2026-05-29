from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.config import ModelsConfig, Settings
from app.core.errors import APIError
from app.core.prompt_builder import append_external_context, append_tool_context, ensure_system_message
from app.core.router import ProviderRouter
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    GuardInfo,
    Usage,
)
from app.schemas.tools import SearchResult, SourceItem, ToolExecutionMetadata, ToolMetadata
from app.tools.planner import plan_tools
from app.tools.registry import ToolRegistry
from app.tools.search_intent import should_use_search
from app.utils.ids import generate_chat_completion_id
from app.utils.logging import log_safe


@dataclass
class StreamOutcome:
    provider: str = ""
    usage: Usage = field(default_factory=Usage)
    guard: GuardInfo = field(default_factory=GuardInfo)
    tools: ToolMetadata = field(default_factory=ToolMetadata)
    sources: list[SourceItem] = field(default_factory=list)
    status: str = "error"
    error_code: str = ""


@dataclass
class StreamHandle:
    events: AsyncIterator[str]
    outcome: StreamOutcome


class ChatOrchestrator:
    def __init__(
        self,
        router: ProviderRouter,
        input_guard: InputGuard,
        output_guard: OutputGuard,
        context_guard: ContextGuard,
        models_config: ModelsConfig,
        tool_registry: ToolRegistry,
        guard_rules: dict[str, Any],
        settings: Settings,
        enable_input_guard: bool,
        enable_output_guard: bool,
        logger: Any,
    ) -> None:
        self.router = router
        self.input_guard = input_guard
        self.output_guard = output_guard
        self.context_guard = context_guard
        self.models_config = models_config
        self.tool_registry = tool_registry
        self.guard_rules = guard_rules
        self.settings = settings
        self.enable_input_guard = enable_input_guard
        self.enable_output_guard = enable_output_guard
        self.logger = logger

    async def create_chat_completion(
        self,
        request_id: str,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        if request.stream:
            raise APIError(
                code="stream_provider_failed",
                message="Use streaming endpoint flow for stream=true.",
                status_code=400,
            )

        started_at = time.perf_counter()
        tools_mode = self._normalize_and_validate_request(request)
        model_profile, messages, input_guard_info, tools_meta, sources = await self._prepare_chat_context(
            request_id=request_id,
            request=request,
            tools_mode=tools_mode,
        )

        try:
            route_result = await self.router.route_chat(
                request_id=request_id,
                model_alias=request.model,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            output_guard_info = GuardInfo()
            response_text = route_result.provider_result.content
            if self.enable_output_guard:
                response_text, output_guard_info = self.output_guard.scan_text(response_text)

            combined_guard = self._combine_guard_info(input_guard_info, output_guard_info)
            usage = Usage(
                prompt_tokens=route_result.provider_result.usage.prompt_tokens,
                completion_tokens=route_result.provider_result.usage.completion_tokens,
                total_tokens=route_result.provider_result.usage.total_tokens,
            )
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            log_safe(
                self.logger,
                "chat_completed",
                request_id=request_id,
                model_alias=request.model,
                provider_used=route_result.provider_used,
                latency_ms=latency_ms,
                redaction_count=combined_guard.redaction_count,
                error_code="",
            )

            return ChatCompletionResponse(
                id=generate_chat_completion_id(),
                created=int(time.time()),
                model=request.model,
                provider=route_result.provider_used,
                choices=[
                    ChatChoice(
                        index=0,
                        message=ChatMessage(role="assistant", content=response_text),
                        finish_reason="stop",
                    )
                ],
                usage=usage,
                guard=combined_guard,
                tools=tools_meta,
                sources=self._dedupe_sources(sources),
            )
        except APIError as exc:
            log_safe(
                self.logger,
                "chat_failed",
                request_id=request_id,
                model_alias=request.model,
                provider="",
                error_code=exc.code,
            )
            raise

    async def create_chat_completion_stream(
        self,
        request_id: str,
        request: ChatCompletionRequest,
    ) -> StreamHandle:
        tools_mode = self._normalize_and_validate_request(request)
        model_profile, messages, input_guard_info, tools_meta, sources = await self._prepare_chat_context(
            request_id=request_id,
            request=request,
            tools_mode=tools_mode,
        )

        stream_result = await self.router.route_chat_stream(
            request_id=request_id,
            model_alias=request.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        completion_id = generate_chat_completion_id()
        created = int(time.time())
        outcome = StreamOutcome(
            provider=stream_result.provider_used,
            tools=tools_meta,
            sources=self._dedupe_sources(sources),
        )

        async def stream_events() -> AsyncIterator[str]:
            provider_finish_reason = "stop"
            output_guard_info = GuardInfo()
            full_output_parts: list[str] = []

            yield self._to_sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": request.model,
                    "provider": stream_result.provider_used,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant"},
                            "finish_reason": None,
                        }
                    ],
                }
            )

            try:
                async for provider_chunk in stream_result.stream:
                    if provider_chunk.usage is not None:
                        outcome.usage = Usage(
                            prompt_tokens=provider_chunk.usage.prompt_tokens,
                            completion_tokens=provider_chunk.usage.completion_tokens,
                            total_tokens=provider_chunk.usage.total_tokens,
                        )

                    if provider_chunk.finish_reason:
                        provider_finish_reason = provider_chunk.finish_reason

                    if provider_chunk.delta:
                        full_output_parts.append(provider_chunk.delta)
                        yield self._to_sse(
                            {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": request.model,
                                "provider": stream_result.provider_used,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": provider_chunk.delta},
                                        "finish_reason": None,
                                    }
                                ],
                            }
                        )
            except Exception:
                outcome.status = "error"
                outcome.error_code = "stream_interrupted"
                yield self._to_sse(
                    {
                        "object": "chat.completion.error",
                        "error": {
                            "code": "stream_interrupted",
                            "message": "The streaming response was interrupted.",
                        },
                    }
                )
                yield self._done_sse()
                return

            if self.enable_output_guard:
                _sanitized_text, output_guard_info = self.output_guard.scan_text("".join(full_output_parts))
                if output_guard_info.output_redacted:
                    yield self._to_sse(
                        {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": request.model,
                            "provider": stream_result.provider_used,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": "\n[Output was sanitized by NestyAI Guard.]"},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )

            outcome.guard = self._combine_guard_info(input_guard_info, output_guard_info)
            outcome.status = "success"
            outcome.error_code = ""

            yield self._to_sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": request.model,
                    "provider": stream_result.provider_used,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": provider_finish_reason or "stop",
                        }
                    ],
                }
            )
            yield self._to_sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.metadata",
                    "created": created,
                    "model": request.model,
                    "provider": stream_result.provider_used,
                    "guard": outcome.guard.model_dump(),
                    "tools": outcome.tools.model_dump(),
                    "sources": [item.model_dump() for item in outcome.sources],
                    "usage": outcome.usage.model_dump(),
                }
            )
            yield self._done_sse()

        return StreamHandle(events=stream_events(), outcome=outcome)

    def _normalize_and_validate_request(self, request: ChatCompletionRequest) -> str | list[str]:
        if request.search not in {"auto", "on", "off"}:
            raise APIError(
                code="invalid_search_mode",
                message="Search mode must be one of: auto, on, off.",
                status_code=400,
            )
        return self._normalize_tools_mode(request.tools)

    async def _prepare_chat_context(
        self,
        request_id: str,
        request: ChatCompletionRequest,
        tools_mode: str | list[str],
    ) -> tuple[Any, list[ChatMessage], GuardInfo, ToolMetadata, list[SourceItem]]:
        model_profile = self.models_config.models.get(request.model)
        if not model_profile:
            raise APIError(
                code="invalid_model",
                message=f"Model '{request.model}' is not supported.",
                status_code=400,
            )

        messages: list[ChatMessage] = ensure_system_message(request.messages)
        input_guard_info = GuardInfo()
        tools_meta = ToolMetadata()
        sources: list[SourceItem] = []

        if self.enable_input_guard:
            messages, input_guard_info = self.input_guard.scan_messages(messages)

        latest_user_message = self._latest_user_message(messages)
        messages, search_sources, search_used_tools = await self._maybe_apply_search_context(
            messages=messages,
            request=request,
            latest_user_message=latest_user_message,
            model_profile=model_profile.model_dump(),
            tools_meta=tools_meta,
            request_id=request_id,
        )
        sources.extend(search_sources)
        tools_meta.used.extend(search_used_tools)

        planned_tools = self._plan_tools(
            message=latest_user_message,
            model_profile=model_profile.model_dump(),
            tools_mode=tools_mode,
        )
        tool_context_text, tool_sources, tool_used, executions = await self._execute_planned_tools(
            message=latest_user_message,
            planned_tools=planned_tools,
            tools_mode=tools_mode,
            model_alias=request.model,
            request_id=request_id,
        )
        tools_meta.used.extend(tool_used)
        tools_meta.executions = executions
        sources.extend(tool_sources)
        if tool_context_text:
            messages = append_tool_context(messages, tool_context_text)

        return model_profile, messages, input_guard_info, tools_meta, sources

    def _normalize_tools_mode(self, tools_field: str | list[str]) -> str | list[str]:
        if isinstance(tools_field, str):
            mode = tools_field.strip().lower()
            if mode not in {"auto", "off"}:
                raise APIError(
                    code="invalid_tools_mode",
                    message="Tools mode must be 'auto', 'off', or list[str].",
                    status_code=400,
                )
            return mode
        if isinstance(tools_field, list) and all(isinstance(item, str) for item in tools_field):
            unknown = [name for name in tools_field if not self.tool_registry.get_tool(name)]
            if unknown:
                raise APIError(
                    code="unknown_tool",
                    message=f"Unknown tool(s): {', '.join(unknown)}",
                    status_code=400,
                    details={"unknown_tools": unknown},
                )
            return tools_field
        raise APIError(
            code="invalid_tools_mode",
            message="Tools mode must be 'auto', 'off', or list[str].",
            status_code=400,
        )

    async def _maybe_apply_search_context(
        self,
        messages: list[ChatMessage],
        request: ChatCompletionRequest,
        latest_user_message: str,
        model_profile: dict[str, Any],
        tools_meta: ToolMetadata,
        request_id: str,
    ) -> tuple[list[ChatMessage], list[SourceItem], list[str]]:
        use_search = should_use_search(
            latest_user_message,
            model_profile,
            explicit_search_mode=request.search,
        )
        if not use_search:
            return messages, [], []

        search_sources: list[SourceItem] = []
        used_tools: list[str] = ["current_datetime", "web_search"]
        tools_meta.search.enabled = True
        tools_meta.search.query = latest_user_message
        datetime_context = self._get_current_datetime_context()
        search_results, search_failed = await self._run_web_search(
            query=latest_user_message,
            max_results=int(model_profile.get("max_search_results", 5)),
        )
        tools_meta.search.failed = search_failed
        tools_meta.search.results_count = len(search_results)

        if search_failed and request.search == "on":
            raise APIError(
                code="search_failed",
                message="Web search failed while search mode is forced on.",
                status_code=502,
            )

        if search_results:
            context_text, context_meta = self.context_guard.sanitize_external_context(
                search_results=search_results,
                max_context_chars=int(model_profile.get("max_context_chars", 6000)),
            )
            if context_text:
                if datetime_context:
                    context_text = f"{datetime_context}\n\n{context_text}"
                messages = append_external_context(messages, context_text)
                search_sources.extend(
                    [SourceItem(title=item.title, url=item.url, snippet=item.snippet) for item in search_results]
                )
            log_safe(
                self.logger,
                "context_sanitized",
                request_id=request_id,
                model_alias=request.model,
                sanitized=context_meta.sanitized,
                removed_injection_count=context_meta.removed_injection_count,
                context_chars=context_meta.context_chars,
                sources_count=context_meta.sources_count,
            )
        elif search_failed and request.search == "auto":
            messages = append_external_context(
                messages,
                (
                    f"{datetime_context}\n\n[Search Notice]\nCurrent information could not be retrieved from web search. "
                    "Answer using existing knowledge and clearly mention possible uncertainty."
                ),
            )

        return messages, search_sources, used_tools

    def _plan_tools(
        self,
        message: str,
        model_profile: dict[str, Any],
        tools_mode: str | list[str],
    ) -> list[str]:
        return plan_tools(
            message=message,
            model_config=model_profile,
            explicit_tools=tools_mode,
        )

    async def _execute_planned_tools(
        self,
        message: str,
        planned_tools: list[str],
        tools_mode: str | list[str],
        model_alias: str,
        request_id: str,
    ) -> tuple[str, list[SourceItem], list[str], list[ToolExecutionMetadata]]:
        if not planned_tools:
            return "", [], [], []

        sources: list[SourceItem] = []
        used: list[str] = []
        executions: list[ToolExecutionMetadata] = []
        context_blocks: list[str] = []

        for tool_name in planned_tools:
            result = await self.tool_registry.execute_tool(
                name=tool_name,
                message=message,
                context={
                    "timeout_seconds": float(self.guard_rules.get("tools", {}).get("search_timeout_seconds", 8)),
                    "weather_api_key": self.settings.weather_provider_api_key or "",
                    "exchange_rate_api_key": self.settings.exchange_rate_api_key or "",
                },
            )
            used.append(tool_name)
            executions.append(
                ToolExecutionMetadata(
                    name=tool_name,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    cache_hit=result.cache_hit,
                    confidence=result.confidence,
                    error=result.error if not result.success else None,
                )
            )
            if result.sources:
                for source in result.sources:
                    sources.append(
                        SourceItem(
                            title=str(source.get("title", tool_name)),
                            url=str(source.get("url", "")),
                            snippet=str(source.get("snippet", "")),
                        )
                    )

            if result.success and result.content.strip():
                tool_context, _meta = self.context_guard.sanitize_external_context(
                    search_results=[
                        SearchResult(
                            title=f"Tool: {tool_name}",
                            url=f"tool://{tool_name}",
                            snippet=result.content,
                        )
                    ],
                    max_context_chars=int(self.guard_rules.get("tool_context", {}).get("max_chars", 4000)),
                )
                if tool_context.strip():
                    context_blocks.append(f"[Tool: {tool_name}]\nResult: {tool_context}")
            elif isinstance(tools_mode, list):
                context_blocks.append(
                    f"[Tool: {tool_name}]\nStatus: failed\nError: {result.error or 'tool_execution_failed'}"
                )

            log_safe(
                self.logger,
                "tool_executed",
                request_id=request_id,
                model_alias=model_alias,
                provider=tool_name,
                error_code="" if result.success else (result.error or "tool_execution_failed"),
            )

        return "\n\n".join(context_blocks).strip(), self._dedupe_sources(sources), used, executions

    async def _run_web_search(self, query: str, max_results: int) -> tuple[list[SearchResult], bool]:
        tool = self.tool_registry.get_helper("web.search")
        if tool is None:
            return [], True
        tools_config = self.guard_rules.get("tools", {})
        cache_config = self.guard_rules.get("tool_cache", {}).get("web_search", {})
        timeout_seconds = float(tools_config.get("search_timeout_seconds", 8))
        results, failed = await tool(
            query=query,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            cache_enabled=bool(cache_config.get("cache_enabled", True)),
            cache_ttl_seconds=int(cache_config.get("cache_ttl_seconds", 600)),
        )
        return results, failed

    def _get_current_datetime_context(self) -> str:
        datetime_tool = self.tool_registry.get_helper("datetime.now")
        if datetime_tool is None:
            return ""
        try:
            data = datetime_tool()
        except Exception:
            return ""
        if not isinstance(data, dict):
            return ""
        iso_value = str(data.get("iso", "")).strip()
        tz_value = str(data.get("timezone", "")).strip()
        if not iso_value:
            return ""
        return f"[Current Datetime]\nISO: {iso_value}\nTimezone: {tz_value}"

    @staticmethod
    def _latest_user_message(messages: list[ChatMessage]) -> str:
        for message in reversed(messages):
            if message.role == "user":
                return message.content
        return messages[-1].content if messages else ""

    @staticmethod
    def _dedupe_sources(sources: list[SourceItem]) -> list[SourceItem]:
        deduped: list[SourceItem] = []
        seen: set[str] = set()
        for item in sources:
            key = f"{item.title}|{item.url}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _combine_guard_info(input_guard_info: GuardInfo, output_guard_info: GuardInfo) -> GuardInfo:
        combined_categories = sorted(set(input_guard_info.categories).union(set(output_guard_info.categories)))
        return GuardInfo(
            input_redacted=input_guard_info.input_redacted,
            output_redacted=output_guard_info.output_redacted,
            redaction_count=input_guard_info.redaction_count + output_guard_info.redaction_count,
            categories=combined_categories,
        )

    @staticmethod
    def _to_sse(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _done_sse() -> str:
        return "data: [DONE]\n\n"
