from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, OrchestrationRoleConfig, ProviderTarget, Settings
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderUsage
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


@dataclass
class _RouteResult:
    provider_result: ProviderChatResult
    provider_used: str


class _MetadataRouter:
    def __init__(self, fail_internal: bool = False) -> None:
        self.fail_internal = fail_internal
        self.route_chat_calls = 0

    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        self.route_chat_calls += 1
        return _RouteResult(
            provider_result=ProviderChatResult(provider="single", content="single fallback", usage=ProviderUsage(total_tokens=2)),
            provider_used="single",
        )

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        raise AssertionError("stream path not used in this test")

    async def generate_with_provider_chain(
        self,
        request_id,
        provider_chain,
        messages,
        temperature,
        max_tokens,
        trace_label="custom_chain",
    ):
        if self.fail_internal:
            raise RuntimeError("forced_internal_error")
        role = trace_label.split(":")[-1]
        return _RouteResult(
            provider_result=ProviderChatResult(
                provider="internal",
                content=f"{role} private output block",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
            provider_used="internal",
        )


def _orchestrator(router: _MetadataRouter, include_latency: bool = True) -> ChatOrchestrator:
    roles = {
        "planner": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="planner")]),
        "researcher": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="researcher")]),
        "critic": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="critic")]),
        "finalizer": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="finalizer")]),
    }
    models = ModelsConfig(
        models={
            "nesty-pro-1.0": ModelProfile(
                display_name="pro",
                description="pro",
                strategy="quality",
                search_mode="off",
                orchestration_enabled=True,
                orchestration_mode="multi_model_synthesis",
                max_tool_calls=0,
                max_search_results=0,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="base")],
                orchestration_roles=roles,
            )
        }
    )
    settings = Settings(
        nesty_pro_orchestration_enabled=True,
        nesty_pro_orchestration_max_internal_calls=4,
        nesty_pro_orchestration_complexity_min_score=1,
        nesty_pro_orchestration_include_role_latency=include_latency,
        rate_limit_enabled=False,
    )
    return ChatOrchestrator(
        router=router,
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=models,
        tool_registry=ToolRegistry(),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=settings,
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.orchestration.metadata"),
    )


@pytest.mark.asyncio
async def test_metadata_contains_decision_reason_complexity_and_role_latency() -> None:
    orchestrator = _orchestrator(_MetadataRouter(), include_latency=True)
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="Analyze and compare architecture plan and debug risks")],
        orchestration="force",
        search="off",
        tools="off",
    )
    response = await orchestrator.create_chat_completion("req_meta_1", request)
    assert response.orchestration is not None
    assert response.orchestration.decision_reason == "request_force"
    assert response.orchestration.complexity_score >= 0
    assert response.orchestration.used is True
    assert response.orchestration.role_latency_ms is not None


@pytest.mark.asyncio
async def test_metadata_does_not_expose_internal_prompts_or_role_outputs() -> None:
    orchestrator = _orchestrator(_MetadataRouter(), include_latency=True)
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="force complex request please")],
        orchestration="force",
        search="off",
        tools="off",
    )
    response = await orchestrator.create_chat_completion("req_meta_2", request)
    payload = response.orchestration.model_dump_json() if response.orchestration else ""
    assert "private output block" not in payload
    assert "Internal NestyAI synthesis step" not in payload


@pytest.mark.asyncio
async def test_orchestration_failure_falls_back_to_single_model() -> None:
    router = _MetadataRouter(fail_internal=True)
    orchestrator = _orchestrator(router, include_latency=True)
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="force fallback path")],
        orchestration="force",
        search="off",
        tools="off",
    )
    response = await orchestrator.create_chat_completion("req_meta_3", request)
    assert response.provider == "single"
    assert response.orchestration is not None
    assert response.orchestration.fallback_used is True
    assert response.orchestration.used is False
    assert response.orchestration.mode == "fallback"
    assert response.orchestration.reason == "fallback_to_single_model"
    assert response.orchestration.completed_roles == []
    assert response.orchestration.failed_roles == ["planner"]
    assert response.orchestration.skipped_roles == ["researcher", "critic", "finalizer"]
    assert response.orchestration.fallback_reason == "orchestration_error"
    # Ensure raw exception/traceback/key is not exposed
    payload = response.orchestration.model_dump_json()
    assert "forced_internal_error" not in payload
    assert router.route_chat_calls == 1


@pytest.mark.asyncio
async def test_orchestration_reduced_mode() -> None:
    router = _MetadataRouter()
    roles = {
        "planner": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="planner")]),
        "researcher": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="researcher")]),
        "critic": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="critic")]),
        "finalizer": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="finalizer")]),
    }
    models = ModelsConfig(
        models={
            "nesty-pro-1.0": ModelProfile(
                display_name="pro",
                description="pro",
                strategy="quality",
                search_mode="off",
                orchestration_enabled=True,
                orchestration_mode="multi_model_synthesis",
                max_tool_calls=0,
                max_search_results=0,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="base")],
                orchestration_roles=roles,
            )
        }
    )
    settings = Settings(
        nesty_pro_orchestration_enabled=True,
        nesty_pro_orchestration_max_internal_calls=2,
        nesty_pro_orchestration_complexity_min_score=1,
        nesty_pro_orchestration_include_role_latency=True,
        rate_limit_enabled=False,
    )
    orchestrator = ChatOrchestrator(
        router=router,
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=models,
        tool_registry=ToolRegistry(),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=settings,
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.orchestration.metadata"),
    )
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="Analyze this architecture plan")],
        orchestration="force",
        search="off",
        tools="off",
    )
    response = await orchestrator.create_chat_completion("req_meta_reduced", request)
    assert response.orchestration is not None
    assert response.orchestration.used is True
    assert response.orchestration.mode == "reduced"
    assert response.orchestration.roles == ["planner", "finalizer"]
    assert response.orchestration.completed_roles == ["planner", "finalizer"]
    assert response.orchestration.skipped_roles == ["researcher", "critic"]
    assert response.orchestration.fallback_used is False


@pytest.mark.asyncio
async def test_orchestration_disabled_and_off_metadata() -> None:
    router = _MetadataRouter()
    orchestrator = _orchestrator(router, include_latency=True)
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="Analyze and compare architecture plan")],
        orchestration="off",
        search="off",
        tools="off",
    )
    response = await orchestrator.create_chat_completion("req_meta_off", request)
    assert response.orchestration is not None
    assert response.orchestration.used is False
    assert response.orchestration.mode == "off"
    assert response.orchestration.requested == "off"
    assert response.orchestration.fallback_used is False
    assert response.orchestration.fallback_reason is None

    settings = Settings(
        nesty_pro_orchestration_enabled=False,
        rate_limit_enabled=False,
    )
    orchestrator.settings = settings
    request_force = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="Analyze and compare")],
        orchestration="force",
        search="off",
        tools="off",
    )
    response_disabled = await orchestrator.create_chat_completion("req_meta_disabled", request_force)
    assert response_disabled.orchestration is not None
    assert response_disabled.orchestration.used is False
    assert response_disabled.orchestration.mode == "off"
    assert response_disabled.orchestration.requested == "force"
    assert response_disabled.orchestration.fallback_used is True
    assert response_disabled.orchestration.fallback_reason == "orchestration_disabled"
