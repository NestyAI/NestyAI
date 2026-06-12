from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import Any

from urllib.parse import urlparse

from app.config import ModelProfile, ModelsConfig, Settings
from app.core.internal_tool_markup import sanitize_internal_tool_markup
from app.core.errors import APIError
from app.guards.safety_policy import build_policy_error_details, reason_to_api_code, user_refusal_message
from app.core.answer_quality import (
    answer_substance_score,
    assess_quality_retry,
    compute_context_signals,
    evaluate_answer_quality,
)
from app.core.lifecycle_events import LifecycleEventCollector
from app.core.model_config_loader import get_effective_model_config
from app.core.model_behavior import apply_behavior_defaults, build_behavior_system_instruction
from app.core.context_assembler import ContextItem, ContextAssemblyResult, assemble_hybrid_context, build_context_item
from app.core.multi_model_orchestrator import NestyProMultiModelOrchestrator, should_use_orchestration, MultiModelOrchestrationError
from app.core.prompt_builder import (
    append_clarification_instruction,
    append_behavior_instruction,
    append_quality_retry_instruction,
    append_retrieval_context,
    append_synthesis_when_context_present,
    ensure_system_message,
)
from app.core.router import ProviderRouter
from app.core.semantic_recall import retrieve_semantic_memories, should_use_semantic_recall
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ConversationInfo,
    GuardInfo,
    OrchestrationInfo,
    AnswerQualityInfo,
    OutputSafetyInfo,
    PlannerInfo,
    ProviderHealthInfo,
    RetrievalInfo,
    SemanticRecallInfo,
    LifecycleEventInfo,
    Usage,
)
from app.schemas.tools import SearchResult, SourceItem, ToolExecutionMetadata, ToolMetadata
from app.storage.db import get_connection
from app.tools.planner import ToolPlanDecision, plan_tools, plan_tools_decision, should_skip_web_search_for_tools
from app.tools.search_query_planner import plan_search_queries
from app.tools.registry import ToolRegistry
from app.tools.search_intent import SearchPlanDecision, plan_search_intent
from app.utils.ids import generate_chat_completion_id
from app.utils.logging import log_safe
from app.utils.sse import format_sse_data


@dataclass
class StreamOutcome:
    provider: str = ""
    usage: Usage = field(default_factory=Usage)
    guard: GuardInfo = field(default_factory=GuardInfo)
    tools: ToolMetadata = field(default_factory=ToolMetadata)
    sources: list[SourceItem] = field(default_factory=list)
    status: str = "error"
    error_code: str = ""
    assistant_content: str = ""
    conversation_id: str | None = None
    conversation_created: bool = False
    conversation_summary_mode: str = "auto"
    conversation_summary_used: bool = False
    conversation_summary_updated: bool = False
    orchestration: OrchestrationInfo = field(default_factory=OrchestrationInfo)
    semantic_recall: SemanticRecallInfo = field(default_factory=SemanticRecallInfo)
    provider_health: ProviderHealthInfo | None = None
    output_safety: OutputSafetyInfo = field(default_factory=OutputSafetyInfo)
    answer_quality: AnswerQualityInfo = field(default_factory=AnswerQualityInfo)
    planner: PlannerInfo = field(default_factory=PlannerInfo)
    retrieval: RetrievalInfo = field(default_factory=RetrievalInfo)
    lifecycle_events: list[LifecycleEventInfo] = field(default_factory=list)


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
        self.multi_model_orchestrator = NestyProMultiModelOrchestrator(
            router=self.router,
        )

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

        model_profile_obj = self._resolve_model_profile(request.model)
        if not model_profile_obj:
            raise APIError(
                code="invalid_model",
                message=f"Model '{request.model}' is not supported.",
                status_code=400,
            )
        request = request.model_copy(update=apply_behavior_defaults(request, model_profile_obj.model_dump()))

        started_at = time.perf_counter()
        lifecycle = LifecycleEventCollector(request_id=request_id, model_alias=request.model)
        lifecycle.emit("chat.request_started")
        tools_mode = self._normalize_and_validate_request(request)
        messages, input_guard_info, tools_meta, sources, semantic_recall, retrieval, planner = await self._prepare_chat_context(
            request_id=request_id,
            request=request,
            tools_mode=tools_mode,
            lifecycle=lifecycle,
        )

        try:
            context_metadata = self._build_orchestration_context_metadata(
                request=request,
                messages=messages,
                tools_meta=tools_meta,
                sources=sources,
            )
            context_metadata["retrieval"] = retrieval
            context_metadata["planner"] = planner
            decision = should_use_orchestration(
                model_alias=request.model,
                request=request,
                model_config=model_profile_obj.model_dump(),
                context_metadata=context_metadata,
                config=self.settings,
            )
            orchestration = self._orchestration_info_from_decision(decision)
            response_text = ""
            provider_used = ""
            usage = Usage()
            provider_health_info: ProviderHealthInfo | None = None
            orchestration_markup_removed = False

            if decision.get("should_use"):
                start_orch = time.perf_counter()
                try:
                    synthesis = await self.multi_model_orchestrator.run(
                        request_id=request_id,
                        user_message=self._latest_user_message(messages),
                        prepared_messages=messages,
                        model_alias=request.model,
                        model_profile=model_profile_obj,
                        selected_roles=list(decision.get("roles") or []),
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                        role_timeout_seconds=self.settings.nesty_pro_orchestration_role_timeout_seconds,
                        max_context_chars=self.settings.nesty_pro_orchestration_max_context_chars,
                        include_role_latency=self.settings.nesty_pro_orchestration_include_role_latency,
                        context_metadata=context_metadata,
                    )
                    orch_elapsed = int((time.perf_counter() - start_orch) * 1000)
                    response_text = synthesis.content
                    provider_used = synthesis.provider
                    usage = Usage(
                        prompt_tokens=synthesis.usage.prompt_tokens,
                        completion_tokens=synthesis.usage.completion_tokens,
                        total_tokens=synthesis.usage.total_tokens,
                    )
                    orchestration_markup_removed = bool(getattr(synthesis, "internal_tool_markup_removed", False))
                    all_possible_roles = ["planner", "researcher", "critic", "finalizer"]
                    is_full = all(r in synthesis.roles for r in all_possible_roles)
                    mode_val = "full" if is_full else "reduced"
                    skipped_roles = [r for r in all_possible_roles if r not in synthesis.roles]
                    
                    evidence_sources_used = retrieval.context_sources if retrieval else []
                    pro_context_budget_chars = retrieval.context_budget_chars if retrieval else None
                    pro_context_truncated = retrieval.context_truncated if retrieval else None

                    orchestration = OrchestrationInfo(
                        enabled=bool(decision.get("enabled")),
                        requested=str(decision.get("requested") or request.orchestration),
                        used=True,
                        mode=mode_val,
                        decision_reason=str(decision.get("reason") or "complex_request"),
                        complexity_score=int(decision.get("complexity_score") or 0),
                        roles=synthesis.roles,
                        completed_roles=synthesis.roles,
                        failed_roles=[],
                        skipped_roles=skipped_roles,
                        fallback_used=False,
                        fallback_reason=None,
                        streaming_fallback=False,
                        internal_calls=synthesis.internal_calls,
                        role_latency_ms=synthesis.role_latency_ms or None,
                        total_latency_ms=orch_elapsed,
                        reason=None,
                        evidence_sources_used=evidence_sources_used,
                        planner_metadata_used=planner is not None,
                        retrieval_metadata_used=retrieval is not None,
                        quality_guard_applied=True,
                        pro_context_budget_chars=pro_context_budget_chars,
                        pro_context_truncated=pro_context_truncated,
                    )
                    orchestration = self._sanitize_orchestration_metadata(orchestration)
                except MultiModelOrchestrationError as exc:
                    orch_elapsed = int((time.perf_counter() - start_orch) * 1000)
                    all_possible_roles = ["planner", "researcher", "critic", "finalizer"]
                    failed_roles = [exc.failed_role] if exc.failed_role else []
                    completed_roles = exc.completed_roles
                    skipped_roles = [r for r in all_possible_roles if r not in completed_roles and r not in failed_roles]
                    
                    orchestration = OrchestrationInfo(
                        enabled=bool(decision.get("enabled")),
                        requested=str(decision.get("requested") or request.orchestration),
                        used=False,
                        mode="fallback",
                        decision_reason=str(decision.get("reason") or "complex_request"),
                        complexity_score=int(decision.get("complexity_score") or 0),
                        roles=list(decision.get("roles") or []),
                        completed_roles=completed_roles,
                        failed_roles=failed_roles,
                        skipped_roles=skipped_roles,
                        fallback_used=True,
                        fallback_reason=exc.fallback_reason,
                        streaming_fallback=False,
                        internal_calls=len(completed_roles),
                        role_latency_ms=exc.role_latency_ms or None,
                        total_latency_ms=orch_elapsed,
                        reason="fallback_to_single_model",
                    )
                    orchestration = self._sanitize_orchestration_metadata(orchestration)
                except Exception:
                    orch_elapsed = int((time.perf_counter() - start_orch) * 1000)
                    all_possible_roles = ["planner", "researcher", "critic", "finalizer"]
                    orchestration = OrchestrationInfo(
                        enabled=bool(decision.get("enabled")),
                        requested=str(decision.get("requested") or request.orchestration),
                        used=False,
                        mode="fallback",
                        decision_reason=str(decision.get("reason") or "complex_request"),
                        complexity_score=int(decision.get("complexity_score") or 0),
                        roles=list(decision.get("roles") or []),
                        completed_roles=[],
                        failed_roles=[],
                        skipped_roles=all_possible_roles,
                        fallback_used=True,
                        fallback_reason="orchestration_error",
                        streaming_fallback=False,
                        internal_calls=0,
                        role_latency_ms=None,
                        total_latency_ms=orch_elapsed,
                        reason="fallback_to_single_model",
                    )
                    orchestration = self._sanitize_orchestration_metadata(orchestration)

            if not str(response_text or "").strip():
                route_result = await self.router.route_chat(
                    request_id=request_id,
                    model_alias=request.model,
                    messages=messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                response_text = route_result.provider_result.content
                provider_used = route_result.provider_used
                raw_provider_health = getattr(route_result, "provider_health", None)
                if isinstance(raw_provider_health, dict):
                    provider_health_info = ProviderHealthInfo.model_validate(raw_provider_health)
                usage = Usage(
                    prompt_tokens=route_result.provider_result.usage.prompt_tokens,
                    completion_tokens=route_result.provider_result.usage.completion_tokens,
                    total_tokens=route_result.provider_result.usage.total_tokens,
                )

            output_guard_info = GuardInfo()
            response_text, output_safety, output_guard_info, sanitized_empty = self._finalize_response_text(
                response_text,
                orchestration_markup_removed=orchestration_markup_removed,
            )

            quality_retry_attempted = False
            quality_retry_reason: str | None = None
            weak_answer_before_retry = False
            empty_before_quality_check = not str(response_text or "").strip()
            first_response_text = response_text
            first_output_safety = output_safety
            first_output_guard_info = output_guard_info
            first_sanitized_empty = sanitized_empty

            retry_assessment = assess_quality_retry(
                response_text,
                retrieval=retrieval,
                tools=tools_meta,
                sources=sources,
                planner=planner,
                orchestration=orchestration,
                output_safety=output_safety,
                output_guard_info=output_guard_info,
                sanitized_empty=sanitized_empty,
            )
            if retry_assessment.should_retry:
                quality_retry_attempted = True
                quality_retry_reason = retry_assessment.retry_reason
                weak_answer_before_retry = retry_assessment.weak_answer_before_retry
                retry_messages = append_quality_retry_instruction(list(messages))
                route_result = await self.router.route_chat(
                    request_id=request_id,
                    model_alias=request.model,
                    messages=retry_messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                )
                retry_text = route_result.provider_result.content
                retry_provider = route_result.provider_used
                retry_text, retry_output_safety, retry_output_guard_info, retry_sanitized_empty = self._finalize_response_text(
                    retry_text,
                    orchestration_markup_removed=False,
                )
                retry_substance = answer_substance_score(retry_text)
                first_substance = answer_substance_score(first_response_text)
                keep_retry = retry_substance > 0 and (
                    first_substance == 0 or retry_substance >= first_substance
                )
                if keep_retry:
                    response_text = retry_text
                    output_safety = retry_output_safety
                    output_guard_info = retry_output_guard_info
                    sanitized_empty = retry_sanitized_empty
                    provider_used = retry_provider
                    raw_provider_health = getattr(route_result, "provider_health", None)
                    if isinstance(raw_provider_health, dict):
                        provider_health_info = ProviderHealthInfo.model_validate(raw_provider_health)
                    usage = Usage(
                        prompt_tokens=usage.prompt_tokens + route_result.provider_result.usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens + route_result.provider_result.usage.completion_tokens,
                        total_tokens=usage.total_tokens + route_result.provider_result.usage.total_tokens,
                    )
                else:
                    response_text = first_response_text
                    output_safety = first_output_safety
                    output_guard_info = first_output_guard_info
                    sanitized_empty = first_sanitized_empty
                log_safe(
                    self.logger,
                    "quality_answer_retry",
                    request_id=request_id,
                    model_alias=request.model,
                    provider_used=provider_used,
                    error_code=quality_retry_reason or "",
                )
                lifecycle.emit(
                    "answer_quality.retry",
                    status="retry",
                    error_code=quality_retry_reason,
                )

            if provider_used:
                lifecycle.emit(
                    "chat.provider_selected",
                    provider=provider_used,
                    status="retry" if quality_retry_attempted else "ok",
                )

            context_signals = compute_context_signals(
                retrieval=retrieval,
                tools=tools_meta,
                sources=sources,
                planner=planner,
            )
            response_text, answer_quality = evaluate_answer_quality(
                response_text,
                retrieval=retrieval,
                tools=tools_meta,
                sources=sources,
                planner=planner,
                output_safety=output_safety,
                streaming=False,
                context_available=context_signals.context_available,
                context_signal_count=context_signals.context_signal_count,
            )
            answer_quality = answer_quality.model_copy(
                update={
                    "retry_attempted": quality_retry_attempted,
                    "retry_reason": quality_retry_reason,
                    "weak_answer_before_retry": weak_answer_before_retry,
                    "sanitized_empty": sanitized_empty,
                    "empty_before_fallback": empty_before_quality_check and answer_quality.action == "fallback_empty",
                    "context_available": context_signals.context_available,
                    "context_signal_count": context_signals.context_signal_count,
                }
            )
            if quality_retry_attempted:
                answer_quality = answer_quality.model_copy(
                    update={
                        "flags": self._merge_quality_flags(
                            answer_quality.flags,
                            ["quality_retry_attempted"],
                        ),
                    }
                )
            if answer_quality.flags:
                lifecycle.emit(
                    "answer_quality.flagged",
                    status="flagged",
                    error_code=answer_quality.flags[0],
                    count=len(answer_quality.flags),
                )

            combined_guard = self._combine_guard_info(input_guard_info, output_guard_info)
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            lifecycle.emit("chat.completed", latency_ms=latency_ms, provider=provider_used or None)
            log_safe(
                self.logger,
                "chat_completed",
                request_id=request_id,
                model_alias=request.model,
                provider_used=provider_used,
                latency_ms=latency_ms,
                redaction_count=combined_guard.redaction_count,
                error_code="",
            )

            return ChatCompletionResponse(
                id=generate_chat_completion_id(),
                created=int(time.time()),
                model=request.model,
                provider=provider_used,
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
                orchestration=orchestration,
                semantic_recall=semantic_recall,
                provider_health=provider_health_info,
                output_safety=output_safety,
                answer_quality=answer_quality,
                planner=planner,
                retrieval=retrieval,
                lifecycle_events=self._lifecycle_event_models(lifecycle),
                model_alias=request.model,
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
        model_profile_obj = self._resolve_model_profile(request.model)
        if not model_profile_obj:
            raise APIError(
                code="invalid_model",
                message=f"Model '{request.model}' is not supported.",
                status_code=400,
            )
        request = request.model_copy(update=apply_behavior_defaults(request, model_profile_obj.model_dump()))
        tools_mode = self._normalize_and_validate_request(request)
        lifecycle = LifecycleEventCollector(request_id=request_id, model_alias=request.model)
        lifecycle.emit("chat.request_started")
        messages, input_guard_info, tools_meta, sources, semantic_recall, retrieval, planner = await self._prepare_chat_context(
            request_id=request_id,
            request=request,
            tools_mode=tools_mode,
            lifecycle=lifecycle,
        )
        context_metadata = self._build_orchestration_context_metadata(
            request=request,
            messages=messages,
            tools_meta=tools_meta,
            sources=sources,
        )
        decision = should_use_orchestration(
            model_alias=request.model,
            request=request,
            model_config=model_profile_obj.model_dump(),
            context_metadata=context_metadata,
            config=self.settings,
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
            conversation_id=request.conversation_id if request.store else None,
            conversation_created=request.conversation_created if request.store else False,
            conversation_summary_mode=request.conversation_summary_mode if request.store else "auto",
            conversation_summary_used=request.conversation_summary_used if request.store else False,
            conversation_summary_updated=request.conversation_summary_updated if request.store else False,
            orchestration=self._orchestration_info_from_decision(decision),
            semantic_recall=semantic_recall,
            planner=planner,
            retrieval=retrieval,
            provider_health=(
                ProviderHealthInfo.model_validate(getattr(stream_result, "provider_health"))
                if isinstance(getattr(stream_result, "provider_health", None), dict)
                else None
            ),
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
                safe_stream_text, stream_output_safety = self._sanitize_internal_tool_markup_response("".join(full_output_parts))
                outcome.output_safety = stream_output_safety
                sanitized_text, output_guard_info, policy_output_safety = self.output_guard.scan_text(safe_stream_text)
                outcome.output_safety.output_redacted = policy_output_safety.output_redacted
                outcome.output_safety.unsafe_output_blocked = policy_output_safety.unsafe_output_blocked
                outcome.output_safety.redaction_count = policy_output_safety.redaction_count
                outcome.output_safety.output_guard_reason = policy_output_safety.output_guard_reason
                if output_guard_info.output_redacted or policy_output_safety.unsafe_output_blocked:
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
                outcome.assistant_content = sanitized_text
            else:
                safe_stream_text, stream_output_safety = self._sanitize_internal_tool_markup_response("".join(full_output_parts))
                outcome.output_safety = stream_output_safety
                outcome.assistant_content = safe_stream_text

            outcome.assistant_content, outcome.answer_quality = evaluate_answer_quality(
                outcome.assistant_content,
                retrieval=outcome.retrieval,
                tools=outcome.tools,
                sources=outcome.sources,
                planner=outcome.planner,
                output_safety=outcome.output_safety,
                streaming=True,
                context_available=compute_context_signals(
                    retrieval=outcome.retrieval,
                    tools=outcome.tools,
                    sources=outcome.sources,
                    planner=outcome.planner,
                ).context_available,
                context_signal_count=compute_context_signals(
                    retrieval=outcome.retrieval,
                    tools=outcome.tools,
                    sources=outcome.sources,
                    planner=outcome.planner,
                ).context_signal_count,
            )

            outcome.guard = self._combine_guard_info(input_guard_info, output_guard_info)
            outcome.status = "success"
            outcome.error_code = ""
            lifecycle.emit("chat.provider_selected", provider=stream_result.provider_used)
            lifecycle.emit("chat.completed", provider=stream_result.provider_used)
            outcome.lifecycle_events = self._lifecycle_event_models(lifecycle)

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
                    "orchestration": outcome.orchestration.model_dump(),
                    "semantic_recall": outcome.semantic_recall.model_dump(),
                    "provider_health": outcome.provider_health.model_dump() if outcome.provider_health else None,
                    "output_safety": outcome.output_safety.model_dump(),
                    "answer_quality": outcome.answer_quality.model_dump(),
                    "planner": outcome.planner.model_dump(),
                    "retrieval": outcome.retrieval.model_dump(),
                    "lifecycle_events": [item.model_dump(exclude_none=True) for item in outcome.lifecycle_events],
                    "conversation": (
                        ConversationInfo(
                            id=outcome.conversation_id,
                            created=outcome.conversation_created,
                            summary_mode=outcome.conversation_summary_mode,
                            summary_used=outcome.conversation_summary_used,
                            summary_updated=outcome.conversation_summary_updated,
                        ).model_dump()
                        if outcome.conversation_id
                        else None
                    ),
                    "model_alias": request.model,
                }
            )
            yield self._done_sse()

        return StreamHandle(events=stream_events(), outcome=outcome)

    @staticmethod
    def _lifecycle_event_models(collector: LifecycleEventCollector | None) -> list[LifecycleEventInfo]:
        if collector is None:
            return []
        return [LifecycleEventInfo.model_validate(item) for item in collector.to_metadata()]

    @staticmethod
    def _compact_search_source_labels(sources: list[SourceItem], *, limit: int = 8) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for item in sources:
            title = str(item.title or "").strip()
            domain = urlparse(str(item.url or "")).netloc.strip().lower()
            label = title[:80] if title else domain
            if domain and title:
                label = f"{title[:60]} ({domain})"
            key = label.lower()
            if not label or key in seen:
                continue
            seen.add(key)
            labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    @staticmethod
    def _merge_quality_flags(existing: list[str], extra: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for flag in [*extra, *existing]:
            normalized = str(flag or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _finalize_response_text(
        self,
        response_text: str,
        *,
        orchestration_markup_removed: bool,
    ) -> tuple[str, OutputSafetyInfo, GuardInfo, bool]:
        output_guard_info = GuardInfo()
        sanitized_text, safety_meta = sanitize_internal_tool_markup(response_text)
        detected = bool(safety_meta.get("internal_tool_markup_detected"))
        removed = bool(safety_meta.get("internal_tool_markup_removed"))
        sanitized_empty = detected and not str(sanitized_text or "").strip()
        response_text, output_safety = self._sanitize_internal_tool_markup_response(response_text)
        if orchestration_markup_removed:
            output_safety.internal_tool_markup_detected = True
            output_safety.internal_tool_markup_removed = True
        if self.enable_output_guard:
            response_text, output_guard_info, policy_output_safety = self.output_guard.scan_text(response_text)
            output_safety.output_redacted = policy_output_safety.output_redacted
            output_safety.unsafe_output_blocked = policy_output_safety.unsafe_output_blocked
            output_safety.redaction_count = policy_output_safety.redaction_count
            output_safety.output_guard_reason = policy_output_safety.output_guard_reason
        return response_text, output_safety, output_guard_info, sanitized_empty

    def _enforce_input_safety(self, latest_user_message: str, *, request_id: str) -> None:
        policy_mode = str(getattr(self.settings, "nesty_safety_policy_mode", "enforce") or "enforce").strip().lower()
        if policy_mode not in {"enforce", "audit"}:
            policy_mode = "enforce"
        decision = self.input_guard.safety_policy.classify_user_input(latest_user_message, mode=policy_mode)
        if decision.action != "refuse":
            return
        api_code = reason_to_api_code(decision.reason_code)
        raise APIError(
            code=api_code,
            message=decision.user_safe_message or user_refusal_message(decision.reason_code),
            status_code=400,
            details=build_policy_error_details(decision, request_id=request_id),
        )

    def _sanitize_retrieval_items(self, items: list[ContextItem]) -> list[ContextItem]:
        sanitized: list[ContextItem] = []
        for item in items:
            clean_text, _removed = self.context_guard.sanitize_untrusted_text(item.content)
            sanitized.append(replace(item, content=clean_text))
        return sanitized

    @staticmethod
    def _sanitize_internal_tool_markup_response(text: str) -> tuple[str, OutputSafetyInfo]:
        sanitized_text, safety_meta = sanitize_internal_tool_markup(text)
        detected = bool(safety_meta.get("internal_tool_markup_detected"))
        removed = bool(safety_meta.get("internal_tool_markup_removed"))
        normalized = str(sanitized_text or "").strip()
        if detected and not normalized:
            normalized = (
                "I could not complete the tool/search request safely. "
                "Please try again with tools disabled or provide the data directly."
            )
            removed = True
        return normalized, OutputSafetyInfo(
            internal_tool_markup_detected=detected,
            internal_tool_markup_removed=removed,
        )

    def _normalize_and_validate_request(self, request: ChatCompletionRequest) -> str | list[str]:
        if request.search not in {"auto", "on", "off"}:
            raise APIError(
                code="invalid_search_mode",
                message="Search mode must be one of: auto, on, off.",
                status_code=400,
            )
        orchestration_mode = str(request.orchestration or "auto").strip().lower()
        if orchestration_mode not in {"auto", "off", "force"}:
            raise APIError(
                code="invalid_orchestration_mode",
                message="Orchestration mode must be one of: auto, off, force.",
                status_code=400,
            )
        semantic_recall_mode = str(request.semantic_recall or "auto").strip().lower()
        if semantic_recall_mode not in {"auto", "off", "on"}:
            raise APIError(
                code="invalid_semantic_recall_mode",
                message="Semantic recall mode must be one of: auto, off, on.",
                status_code=400,
            )
        return self._normalize_tools_mode(request.tools)

    async def _prepare_chat_context(
        self,
        request_id: str,
        request: ChatCompletionRequest,
        tools_mode: str | list[str],
        lifecycle: LifecycleEventCollector | None = None,
    ) -> tuple[list[ChatMessage], GuardInfo, ToolMetadata, list[SourceItem], SemanticRecallInfo, RetrievalInfo, PlannerInfo]:
        model_profile = self._resolve_model_profile(request.model)
        if not model_profile:
            raise APIError(
                code="invalid_model",
                message=f"Model '{request.model}' is not supported.",
                status_code=400,
            )

        model_profile_dict = model_profile.model_dump()
        behavior_instruction = build_behavior_system_instruction(request.model, model_profile_dict)
        messages: list[ChatMessage] = ensure_system_message(request.messages)
        messages = append_behavior_instruction(messages, behavior_instruction)
        input_guard_info = GuardInfo()
        tools_meta = ToolMetadata()
        sources: list[SourceItem] = []
        retrieval_items: list[ContextItem] = []
        semantic_recall_info = SemanticRecallInfo(
            enabled=bool(getattr(self.settings, "semantic_recall_enabled", False)),
            requested=str(request.semantic_recall or "auto"),
            used=False,
            reason="disabled_global",
            matches_count=0,
            pinned_matches_count=0,
            excluded_matches_count=0,
            deduped_count=0,
            top_k=max(1, int(getattr(self.settings, "semantic_recall_top_k", 5))),
            min_score=float(getattr(self.settings, "semantic_recall_min_score", 0.72)),
            max_score=None,
            min_returned_score=None,
            scope=str(getattr(self.settings, "semantic_recall_scope", "conversation")),
            candidate_count=0,
            used_context_chars=0,
        )
        summary_text = ""

        if self.enable_input_guard:
            messages, input_guard_info = self.input_guard.scan_messages(messages)

        latest_user_message = self._latest_user_message(messages)
        self._enforce_input_safety(latest_user_message, request_id=request_id)
        for item in messages:
            if item.role != "system":
                continue
            if "Conversation summary so far" not in item.content:
                continue
            summary_text = item.content[:4000]
            break

        semantic_decision = should_use_semantic_recall(
            request=request,
            model_config=model_profile_dict,
            context_metadata={"latest_user_message": latest_user_message},
            config=self.settings,
        )
        semantic_recall_info = SemanticRecallInfo(
            enabled=bool(semantic_decision.get("enabled")),
            requested=str(semantic_decision.get("requested") or request.semantic_recall or "auto"),
            used=False,
            reason=str(semantic_decision.get("reason") or "disabled_global"),
            matches_count=0,
            pinned_matches_count=0,
            excluded_matches_count=0,
            deduped_count=0,
            top_k=max(1, int(getattr(self.settings, "semantic_recall_top_k", 5))),
            min_score=float(getattr(self.settings, "semantic_recall_min_score", 0.72)),
            max_score=None,
            min_returned_score=None,
            scope=str(getattr(self.settings, "semantic_recall_scope", "conversation")),
            candidate_count=0,
            used_context_chars=0,
        )
        if semantic_decision.get("should_use"):
            exclude_message_ids: list[str] = []
            if bool(getattr(self.settings, "semantic_recall_exclude_current_conversation_recent", True)):
                conversation_id = str(request.conversation_id or "").strip()
                if conversation_id:
                    try:
                        exclude_message_ids = self._get_recent_message_ids(
                            conversation_id=conversation_id,
                            limit=max(1, int(getattr(self.settings, "conversation_history_max_messages", 20))),
                        )
                    except Exception:
                        exclude_message_ids = []
            try:
                recall_result = await retrieve_semantic_memories(
                    latest_user_message=latest_user_message,
                    api_key_id=request.request_api_key_id,
                    conversation_id=request.conversation_id,
                    config=self.settings,
                    request_semantic_recall=request.semantic_recall,
                exclude_message_ids=exclude_message_ids,
                summary_text=summary_text,
                include_pinned_boost=True,
            )
            except Exception:
                recall_result = {
                    "enabled": bool(semantic_decision.get("enabled")),
                    "requested": str(semantic_decision.get("requested") or request.semantic_recall or "auto"),
                    "used": False,
                    "reason": "semantic_recall_failed",
                    "top_k": max(1, int(getattr(self.settings, "semantic_recall_top_k", 5))),
                    "min_score": float(getattr(self.settings, "semantic_recall_min_score", 0.72)),
                    "matches": [],
                    "context_text": "",
                    "pinned_matches_count": 0,
                    "excluded_matches_count": 0,
                    "deduped_count": 0,
                    "max_score": None,
                    "min_returned_score": None,
                    "scope": str(getattr(self.settings, "semantic_recall_scope", "conversation")),
                    "candidate_count": 0,
                    "used_context_chars": 0,
                }
            matches = list(recall_result.get("matches") or [])
            if recall_result.get("used") and matches:
                retrieval_items.extend(self._build_semantic_recall_items(matches))
                semantic_recall_info = SemanticRecallInfo(
                    enabled=bool(recall_result.get("enabled")),
                    requested=str(recall_result.get("requested") or request.semantic_recall or "auto"),
                    used=True,
                    reason=str(recall_result.get("reason") or "semantic_recall_enabled"),
                    matches_count=len(matches),
                    pinned_matches_count=int(recall_result.get("pinned_matches_count") or 0),
                    excluded_matches_count=int(recall_result.get("excluded_matches_count") or 0),
                    deduped_count=int(recall_result.get("deduped_count") or 0),
                    top_k=int(recall_result.get("top_k") or semantic_recall_info.top_k),
                    min_score=float(recall_result.get("min_score") or semantic_recall_info.min_score),
                    max_score=(
                        float(recall_result.get("max_score"))
                        if recall_result.get("max_score") is not None
                        else None
                    ),
                    min_returned_score=(
                        float(recall_result.get("min_returned_score"))
                        if recall_result.get("min_returned_score") is not None
                        else None
                    ),
                    scope=str(recall_result.get("scope") or semantic_recall_info.scope),
                    candidate_count=int(recall_result.get("candidate_count") or 0),
                    used_context_chars=int(recall_result.get("used_context_chars") or 0),
                )
            else:
                semantic_recall_info = SemanticRecallInfo(
                    enabled=bool(recall_result.get("enabled")),
                    requested=str(recall_result.get("requested") or request.semantic_recall or "auto"),
                    used=False,
                    reason=str(recall_result.get("reason") or "no_matches"),
                    matches_count=0,
                    pinned_matches_count=int(recall_result.get("pinned_matches_count") or 0),
                    excluded_matches_count=int(recall_result.get("excluded_matches_count") or 0),
                    deduped_count=int(recall_result.get("deduped_count") or 0),
                    top_k=int(recall_result.get("top_k") or semantic_recall_info.top_k),
                    min_score=float(recall_result.get("min_score") or semantic_recall_info.min_score),
                    max_score=(
                        float(recall_result.get("max_score"))
                        if recall_result.get("max_score") is not None
                        else None
                    ),
                    min_returned_score=(
                        float(recall_result.get("min_returned_score"))
                        if recall_result.get("min_returned_score") is not None
                        else None
                    ),
                    scope=str(recall_result.get("scope") or semantic_recall_info.scope),
                    candidate_count=int(recall_result.get("candidate_count") or 0),
                    used_context_chars=int(recall_result.get("used_context_chars") or 0),
                )

        fts_context_items: list[ContextItem] = []
        fts_used = False
        if self._should_use_memory_fts(request, latest_user_message):
            try:
                from app.storage.conversations import search_messages

                fts_result = search_messages(
                    api_key_id=request.request_api_key_id,
                    query=latest_user_message,
                    limit=max(1, int(getattr(self.settings, "conversation_history_max_messages", 20))),
                    offset=0,
                    backend="auto",
                    conversation_id=str(request.conversation_id or "").strip() or None,
                    exclude_memory_excluded=True,
                    db_path=getattr(self.settings, "nesty_db_path", None),
                )
                fts_rows = list(fts_result.get("data") or [])
                fts_used = bool(fts_rows)
                if fts_rows:
                    fts_context_items = self._build_memory_search_items(fts_rows)
            except Exception:
                fts_context_items = []
                fts_used = False

        memory_context_available = bool(
            summary_text.strip()
            or bool(request.conversation_history_used)
            or semantic_recall_info.used
            or fts_used
        )
        search_plan = plan_search_intent(
            latest_user_message,
            model_profile_dict,
            explicit_search_mode=request.search,
            memory_context_available=memory_context_available,
        )
        tool_plan = self._plan_tools_decision(
            message=latest_user_message,
            model_profile=model_profile_dict,
            tools_mode=tools_mode,
        )
        planner_info = PlannerInfo(
            search_decision=search_plan.decision,
            search_planned=bool(search_plan.search_planned),
            search_used=False,
            search_reason=search_plan.reason,
            tool_decision=tool_plan.decision,
            tools_planned=list(tool_plan.tools_planned),
            tools_used=[],
            tool_reason=tool_plan.reason,
            clarification_needed=bool(tool_plan.clarification_needed),
            clarification_reason=tool_plan.clarification_reason,
        )

        search_sources, search_used_tools, search_context_items, search_used = await self._maybe_apply_search_context(
            request=request,
            latest_user_message=latest_user_message,
            model_profile=model_profile_dict,
            tools_meta=tools_meta,
            request_id=request_id,
            search_plan=search_plan,
            tool_plan=tool_plan,
            lifecycle=lifecycle,
        )
        sources.extend(search_sources)
        tools_meta.used.extend(search_used_tools)
        retrieval_items.extend(search_context_items)
        retrieval_items.extend(fts_context_items)

        if tool_plan.clarification_needed and tool_plan.clarification_reason:
            messages = append_clarification_instruction(messages, tool_plan.clarification_reason)

        planned_tools = list(tool_plan.tools_planned)
        tool_sources, tool_used, executions, tool_context_items = await self._execute_planned_tools(
            message=latest_user_message,
            planned_tools=planned_tools,
            tools_mode=tools_mode,
            model_alias=request.model,
            request_id=request_id,
            lifecycle=lifecycle,
        )
        tools_meta.used.extend(tool_used)
        tools_meta.executions = executions
        sources.extend(tool_sources)
        retrieval_items.extend(tool_context_items)
        tools_meta.search.used = bool(search_used)
        planner_info.search_used = bool(search_used)
        planner_info.tools_used = list(tool_used)

        assembly = assemble_hybrid_context(
            self._sanitize_retrieval_items(retrieval_items),
            summary_text=summary_text,
            budget_chars=max(1, int(model_profile_dict.get("max_context_chars", 6000))),
        )
        if assembly.context_text:
            messages = append_retrieval_context(messages, assembly.context_text)
            if search_used or tool_used or sources or semantic_recall_info.used or fts_used:
                messages = append_synthesis_when_context_present(messages)

        retrieval_info = self._build_retrieval_info(
            request=request,
            assembly=assembly,
            semantic_recall_info=semantic_recall_info,
            summary_text=summary_text,
            search_used=bool(search_used),
            fts_used=fts_used,
            tool_context_used=bool(tool_context_items),
            tools_meta=tools_meta,
            sources=sources,
        )

        return messages, input_guard_info, tools_meta, sources, semantic_recall_info, retrieval_info, planner_info

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
        request: ChatCompletionRequest,
        latest_user_message: str,
        model_profile: dict[str, Any],
        tools_meta: ToolMetadata,
        request_id: str,
        search_plan: SearchPlanDecision,
        tool_plan: ToolPlanDecision,
        lifecycle: LifecycleEventCollector | None = None,
    ) -> tuple[list[SourceItem], list[str], list[ContextItem], bool]:
        if not search_plan.should_use:
            tools_meta.search.enabled = bool(search_plan.search_planned)
            tools_meta.search.used = False
            tools_meta.search.query = None
            tools_meta.search.queries = []
            tools_meta.search.decision_reason = search_plan.reason
            return [], [], [], False

        if should_skip_web_search_for_tools(tool_plan, str(request.search or "auto"), latest_user_message):
            tools_meta.search.enabled = True
            tools_meta.search.used = False
            tools_meta.search.query = None
            tools_meta.search.queries = []
            tools_meta.search.decision_reason = "skipped_deterministic_tool"
            if lifecycle is not None:
                lifecycle.emit("search.started", status="skipped", count=0)
            return [], [], [], False

        search_sources: list[SourceItem] = []
        used_tools: list[str] = ["current_datetime", "web_search"]
        context_items: list[ContextItem] = []
        tools_meta.search.enabled = True
        planned_queries = plan_search_queries(latest_user_message)
        if not planned_queries:
            planned_queries = [latest_user_message.strip()]
        tools_meta.search.query = planned_queries[0]
        tools_meta.search.queries = planned_queries
        tools_meta.search.used = False
        tools_meta.search.decision_reason = search_plan.reason
        if lifecycle is not None:
            lifecycle.emit("search.started", count=len(planned_queries))
        datetime_context = self._get_current_datetime_context()
        search_results, search_meta = await self._run_web_search(
            queries=planned_queries,
            max_results=int(model_profile.get("max_search_results", 5)),
        )
        tools_meta.search.failed = search_meta.failed
        tools_meta.search.results_count = len(search_results)
        tools_meta.search.filtered_result_count = search_meta.filtered_result_count
        tools_meta.search.provider = search_meta.provider
        tools_meta.search.latency_ms = search_meta.latency_ms
        tools_meta.search.error_code = search_meta.error_code
        tools_meta.search.cache_hit = search_meta.cache_hit
        actual_search_used = False

        if search_meta.failed and request.search == "on":
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
            tools_meta.search.context_chars = context_meta.context_chars
            if context_text:
                if datetime_context:
                    context_text = f"{datetime_context}\n\n{context_text}"
                search_sources.extend(
                    [SourceItem(title=item.title, url=item.url, snippet=item.snippet) for item in search_results]
                )
                context_items.append(
                    build_context_item(
                        source="search",
                        content=context_text,
                        title="Web search context",
                        score=0.9,
                        metadata={
                            "result_count": len(search_results),
                            "queries": planned_queries,
                            "provider": search_meta.provider,
                        },
                    )
                )
                actual_search_used = True
            if lifecycle is not None:
                lifecycle.emit(
                    "search.completed",
                    count=len(search_results),
                    latency_ms=search_meta.latency_ms,
                    provider=search_meta.provider,
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
        elif search_meta.failed and request.search == "auto":
            if lifecycle is not None:
                lifecycle.emit(
                    "search.failed",
                    status="failed",
                    error_code=search_meta.error_code or "search_failed",
                    latency_ms=search_meta.latency_ms,
                )
            context_items.append(
                build_context_item(
                    source="search",
                    content=(
                        f"{datetime_context}\n\n[Search Notice]\nCurrent information could not be retrieved from web search. "
                        "Answer using existing knowledge and clearly mention possible uncertainty."
                    ),
                    title="Search notice",
                    score=0.5,
                    metadata={"failed": True, "error_code": search_meta.error_code or "search_failed"},
                )
            )

        tools_meta.search.used = actual_search_used
        return search_sources, used_tools, context_items, actual_search_used

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

    def _plan_tools_decision(
        self,
        message: str,
        model_profile: dict[str, Any],
        tools_mode: str | list[str],
    ) -> ToolPlanDecision:
        return plan_tools_decision(
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
        lifecycle: LifecycleEventCollector | None = None,
    ) -> tuple[list[SourceItem], list[str], list[ToolExecutionMetadata], list[ContextItem]]:
        if not planned_tools:
            return [], [], [], []

        sources: list[SourceItem] = []
        used: list[str] = []
        executions: list[ToolExecutionMetadata] = []
        context_items: list[ContextItem] = []

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
            if lifecycle is not None:
                lifecycle.emit(
                    "tool.called" if result.success else "tool.failed",
                    status="ok" if result.success else "failed",
                    tool=tool_name,
                    error_code=result.error if not result.success else None,
                    latency_ms=result.latency_ms,
                )
            executions.append(
                ToolExecutionMetadata(
                    name=tool_name,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    cache_hit=result.cache_hit,
                    confidence=result.confidence,
                    error=result.error if not result.success else None,
                    error_code=result.error if not result.success else None,
                    result_chars=len(str(result.content or "")),
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
                    context_items.append(
                        build_context_item(
                            source="tools",
                            content=f"[Tool: {tool_name}]\nResult: {tool_context}",
                            title=tool_name,
                            score=0.95,
                            metadata={"success": True},
                        )
                    )
            elif isinstance(tools_mode, list):
                context_items.append(
                    build_context_item(
                        source="tools",
                        content=f"[Tool: {tool_name}]\nStatus: failed\nError: {result.error or 'tool_execution_failed'}",
                        title=tool_name,
                        metadata={"success": False},
                    )
                )

            log_safe(
                self.logger,
                "tool_executed",
                request_id=request_id,
                model_alias=model_alias,
                provider=tool_name,
                error_code="" if result.success else (result.error or "tool_execution_failed"),
            )

        return self._dedupe_sources(sources), used, executions, context_items

    async def _run_web_search(self, queries: list[str], max_results: int):
        from app.tools.web_search import WebSearchMeta

        tool = self.tool_registry.get_helper("web.search.multi")
        if tool is None:
            return [], WebSearchMeta(queries=queries, failed=True, error_code="search_unavailable")
        tools_config = self.guard_rules.get("tools", {})
        cache_config = self.guard_rules.get("tool_cache", {}).get("web_search", {})
        timeout_seconds = float(tools_config.get("search_timeout_seconds", 8))
        cleaned_queries = [query.strip() for query in queries if str(query or "").strip()]
        if not cleaned_queries:
            return [], WebSearchMeta(queries=[], failed=True, error_code="empty_query")
        results, meta = await tool(
            queries=cleaned_queries,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            cache_enabled=bool(cache_config.get("cache_enabled", True)),
            cache_ttl_seconds=int(cache_config.get("cache_ttl_seconds", 600)),
        )
        return results, meta

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
    def _build_semantic_recall_items(matches: list[dict[str, Any]]) -> list[ContextItem]:
        items: list[ContextItem] = []
        for index, item in enumerate(matches, start=1):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            items.append(
                build_context_item(
                    source="semantic_recall",
                    content=content,
                    title=f"Memory {index}",
                    score=float(item.get("score") or 0.0),
                    pinned=bool(item.get("pinned")),
                    created_at=str(item.get("created_at") or ""),
                    metadata={
                        "message_id": str(item.get("message_id") or ""),
                        "conversation_id": str(item.get("conversation_id") or ""),
                    },
                )
            )
        return items

    @staticmethod
    def _build_memory_search_items(rows: list[dict[str, Any]]) -> list[ContextItem]:
        items: list[ContextItem] = []
        for index, row in enumerate(rows, start=1):
            content = str(row.get("snippet") or row.get("content") or "").strip()
            if not content:
                continue
            title = str(row.get("conversation_title") or f"Memory search {index}")
            rank_value = row.get("rank")
            items.append(
                build_context_item(
                    source="fts",
                    content=content,
                    title=title,
                    score=float(rank_value) if rank_value is not None else None,
                    pinned=bool(row.get("memory_pinned")),
                    created_at=str(row.get("created_at") or ""),
                    metadata={
                        "message_id": str(row.get("id") or ""),
                        "conversation_id": str(row.get("conversation_id") or ""),
                        "search_backend": str(row.get("search_backend") or ""),
                    },
                )
            )
        return items

    @staticmethod
    def _should_use_memory_fts(request: ChatCompletionRequest, latest_user_message: str) -> bool:
        if not str(request.conversation_id or "").strip():
            return False
        requested = str(request.semantic_recall or "auto").strip().lower()
        if requested == "on":
            return True
        normalized = " ".join(str(latest_user_message or "").lower().split())
        followup_markers = (
            "trước đó",
            "hồi nãy",
            "vừa rồi",
            "phần đó",
            "cái đó",
            "như đã nói",
        )
        return any(marker in normalized for marker in followup_markers)

    def _build_retrieval_info(
        self,
        *,
        request: ChatCompletionRequest,
        assembly: ContextAssemblyResult,
        semantic_recall_info: SemanticRecallInfo,
        summary_text: str,
        search_used: bool,
        fts_used: bool,
        tool_context_used: bool,
        tools_meta: ToolMetadata,
        sources: list[SourceItem] | None = None,
    ) -> RetrievalInfo:
        context_sources: list[str] = []

        def add_source(source_name: str) -> None:
            source = str(source_name or "").strip().lower()
            if not source or source in context_sources:
                return
            context_sources.append(source)

        if bool(request.conversation_history_used):
            add_source("recent")
        if bool(request.conversation_summary_used) or bool(summary_text.strip()):
            add_source("summary")
        if any(item.pinned for item in assembly.items) or semantic_recall_info.pinned_matches_count > 0:
            add_source("pinned_memory")
        if semantic_recall_info.used:
            add_source("semantic_recall")
        if fts_used:
            add_source("fts")
        if search_used:
            add_source("search")
        if tool_context_used or bool(tools_meta.used):
            add_source("tools")

        supplemental_sources = [source for source in context_sources if source not in {"recent", "summary"}]
        if not context_sources:
            retrieval_decision = "none"
        elif len(context_sources) == 1:
            retrieval_decision = context_sources[0]
        elif supplemental_sources:
            retrieval_decision = "hybrid"
        else:
            retrieval_decision = "conversation"

        retrieval_reason = None
        if semantic_recall_info.used:
            retrieval_reason = semantic_recall_info.reason or "semantic_recall_enabled"
        elif fts_used:
            retrieval_reason = "followup_reference"
        elif search_used:
            retrieval_reason = "search_enabled"
        elif tool_context_used:
            retrieval_reason = "tool_context_available"
        elif context_sources:
            retrieval_reason = "conversation_context"

        used_chars = assembly.context_used_chars
        if bool(request.conversation_summary_used):
            used_chars += len(summary_text)

        context_items_count = assembly.context_items_count
        if bool(request.conversation_history_used):
            context_items_count += 1
        if bool(request.conversation_summary_used):
            context_items_count += 1

        return RetrievalInfo(
            context_used=bool(context_sources),
            context_sources=context_sources,
            context_items_count=context_items_count,
            context_truncated=assembly.context_truncated,
            context_budget_chars=assembly.context_budget_chars,
            context_used_chars=used_chars,
            summary_used=bool(request.conversation_summary_used),
            pinned_memory_used=any(item.pinned for item in assembly.items) or semantic_recall_info.pinned_matches_count > 0,
            fts_used=fts_used,
            semantic_recall_used=semantic_recall_info.used,
            search_used=search_used,
            tools_used=list(tools_meta.used),
            retrieval_decision=retrieval_decision,
            retrieval_reason=retrieval_reason,
            search_sources=self._compact_search_source_labels(list(sources or [])),
        )

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

    def _build_orchestration_context_metadata(
        self,
        request: ChatCompletionRequest,
        messages: list[ChatMessage],
        tools_meta: ToolMetadata,
        sources: list[SourceItem],
    ) -> dict[str, Any]:
        summary_text = ""
        for item in messages:
            if item.role != "system":
                continue
            if "Conversation summary so far" in item.content:
                summary_text = item.content[:2000]
                break
        return {
            "latest_user_message": self._latest_user_message(messages),
            "search_enabled": bool(tools_meta.search.enabled),
            "tools_used_count": len(tools_meta.used),
            "sources_count": len(sources),
            "conversation_summary_used": bool(request.conversation_summary_used),
            "has_conversation_context": bool(request.store and request.conversation_id),
            "conversation_summary_text": summary_text,
        }

    def _resolve_model_profile(self, model_alias: str) -> ModelProfile | None:
        try:
            effective = get_effective_model_config(model_alias)
            if isinstance(effective, dict):
                return ModelProfile.model_validate(effective)
        except Exception:
            pass
        return self.models_config.models.get(model_alias)

    @staticmethod
    def _orchestration_info_from_decision(decision: dict[str, Any]) -> OrchestrationInfo:
        reason = str(decision.get("reason") or "")
        requested = str(decision.get("requested") or "auto")
        enabled = bool(decision.get("enabled"))
        complexity_score = int(decision.get("complexity_score") or 0)
        
        used = False
        mode_val = "single"
        fallback_used = False
        fallback_reason = None
        streaming_fallback = False
        
        if reason == "streaming_not_supported":
            mode_val = "single"
            fallback_used = True
            fallback_reason = "streaming_fallback"
            streaming_fallback = True
        elif reason == "request_off":
            mode_val = "off"
        elif reason in ("global_disabled", "config_disabled"):
            mode_val = "off"
            if requested != "off":
                fallback_used = True
                fallback_reason = "orchestration_disabled"
        elif reason == "simple_request":
            mode_val = "single"
            
        all_roles = ["planner", "researcher", "critic", "finalizer"]
        skipped = [r for r in all_roles] if requested != "off" else []
        
        info = OrchestrationInfo(
            enabled=enabled,
            requested=requested,
            used=used,
            mode=mode_val,
            decision_reason=reason or None,
            complexity_score=complexity_score,
            roles=[],
            completed_roles=[],
            failed_roles=[],
            skipped_roles=skipped,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            streaming_fallback=streaming_fallback,
            internal_calls=0,
            role_latency_ms=None,
            total_latency_ms=None,
            reason=reason or None,
        )
        return ChatOrchestrator._sanitize_orchestration_metadata(info)

    @staticmethod
    def _sanitize_orchestration_metadata(info: OrchestrationInfo) -> OrchestrationInfo:
        allowed_roles = {"planner", "researcher", "critic", "finalizer"}
        
        roles = [r for r in info.roles if r in allowed_roles]
        completed_roles = [r for r in info.completed_roles if r in allowed_roles]
        failed_roles = [r for r in info.failed_roles if r in allowed_roles]
        skipped_roles = [r for r in info.skipped_roles if r in allowed_roles]
        
        role_latency_ms = None
        if info.role_latency_ms is not None:
            role_latency_ms = {
                k: max(0, int(v))
                for k, v in info.role_latency_ms.items()
                if k in allowed_roles
            }
            
        total_latency_ms = None
        if info.total_latency_ms is not None:
            total_latency_ms = max(0, int(info.total_latency_ms))
            
        allowed_fallback_reasons = {
            "role_timeout",
            "provider_unavailable",
            "internal_call_limit",
            "orchestration_error",
            "streaming_fallback",
            "orchestration_disabled",
        }
        fallback_reason = info.fallback_reason
        if fallback_reason is not None and fallback_reason not in allowed_fallback_reasons:
            fallback_reason = "orchestration_error"
            
        allowed_modes = {"off", "single", "reduced", "full", "fallback", "unknown"}
        mode = info.mode if info.mode in allowed_modes else "unknown"
        
        decision_reason = info.decision_reason
        safe_decision_reasons = {
            "not_pro_model",
            "global_disabled",
            "config_disabled",
            "streaming_not_supported",
            "internal_call_limit_too_low",
            "missing_roles",
            "request_off",
            "simple_request",
            "request_force",
            "complex_request",
        }
        if decision_reason not in safe_decision_reasons:
            if decision_reason:
                if len(decision_reason) > 60 or "\n" in decision_reason or "traceback" in decision_reason.lower():
                    decision_reason = "orchestration_error"
            else:
                decision_reason = None

        return OrchestrationInfo(
            enabled=bool(info.enabled),
            requested=info.requested,
            used=bool(info.used),
            mode=mode,
            decision_reason=decision_reason,
            complexity_score=int(info.complexity_score or 0),
            roles=roles,
            completed_roles=completed_roles,
            failed_roles=failed_roles,
            skipped_roles=skipped_roles,
            fallback_used=bool(info.fallback_used),
            fallback_reason=fallback_reason,
            streaming_fallback=bool(info.streaming_fallback),
            internal_calls=int(info.internal_calls or 0),
            role_latency_ms=role_latency_ms,
            total_latency_ms=total_latency_ms,
            reason=info.reason,
            evidence_sources_used=info.evidence_sources_used,
            planner_metadata_used=info.planner_metadata_used,
            retrieval_metadata_used=info.retrieval_metadata_used,
            quality_guard_applied=info.quality_guard_applied,
            pro_context_budget_chars=info.pro_context_budget_chars,
            pro_context_truncated=info.pro_context_truncated,
        )

    @staticmethod
    def _rebuild_memory_context(matches: list[dict[str, Any]], sanitized_block: str) -> str:
        # Keep deterministic memory labels/scores while using sanitized snippet text.
        lines = [line.strip() for line in sanitized_block.splitlines() if line.strip()]
        rebuilt: list[str] = []
        snippet_index = 0
        for idx, item in enumerate(matches, start=1):
            score = float(item.get("score") or 0.0)
            role = str(item.get("role") or "unknown")
            created_at = str(item.get("created_at") or "")
            pinned = bool(item.get("pinned"))
            snippet = ""
            while snippet_index < len(lines):
                line = lines[snippet_index]
                snippet_index += 1
                if line.startswith("Snippet:"):
                    snippet = line.replace("Snippet:", "", 1).strip()
                    break
            if not snippet:
                snippet = " "
            pinned_text = " | pinned" if pinned else ""
            rebuilt.append(f"[Memory {idx} | score={score:.2f}{pinned_text} | role={role} | date={created_at}]\n{snippet}")
        return "\n\n".join(rebuilt).strip()

    def _get_recent_message_ids(self, conversation_id: str, limit: int) -> list[str]:
        with get_connection(self.settings.nesty_db_path) as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (conversation_id, max(1, int(limit))),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    @staticmethod
    def _to_sse(payload: dict[str, Any]) -> str:
        return format_sse_data(payload)

    @staticmethod
    def _done_sse() -> str:
        return format_sse_data("[DONE]")
