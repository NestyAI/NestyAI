from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, OrchestrationRoleConfig, ProviderTarget, Settings
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


@dataclass
class _DummyRouteResult:
    provider_result: ProviderChatResult
    provider_used: str


@dataclass
class _DummyStreamRouteResult:
    provider_used: str
    stream: AsyncIterator[ProviderStreamChunk]


class _ProRouter:
    def __init__(self) -> None:
        self.route_chat_calls = 0
        self.generate_calls: list[str] = []

    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        self.route_chat_calls += 1
        return _DummyRouteResult(
            provider_result=ProviderChatResult(provider="fallback", content="fallback single model"),
            provider_used="fallback",
        )

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        async def _stream():
            yield ProviderStreamChunk(delta="hello")
            yield ProviderStreamChunk(finish_reason="stop", usage=ProviderUsage(total_tokens=2))

        return _DummyStreamRouteResult(provider_used="stream-provider", stream=_stream())

    async def generate_with_provider_chain(
        self,
        request_id,
        provider_chain,
        messages,
        temperature,
        max_tokens,
        trace_label="custom_chain",
    ):
        self.generate_calls.append(trace_label)
        role_name = trace_label.split(":")[-1]
        return _DummyRouteResult(
            provider_result=ProviderChatResult(
                provider="internal",
                content=f"{role_name} output",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
            provider_used="internal",
        )


def _pro_models_config() -> ModelsConfig:
    roles = {
        "planner": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="planner-model")]),
        "researcher": OrchestrationRoleConfig(
            provider_chain=[ProviderTarget(provider="dummy", model="researcher-model")]
        ),
        "critic": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="critic-model")]),
        "finalizer": OrchestrationRoleConfig(provider_chain=[ProviderTarget(provider="dummy", model="finalizer-model")]),
    }
    return ModelsConfig(
        models={
            "nesty-pro-1.0": ModelProfile(
                display_name="Nesty Pro 1.0",
                description="test pro",
                strategy="quality",
                search_mode="off",
                behavior_profile="pro",
                response_style="detailed",
                reasoning_depth="high",
                search_aggressiveness="high_when_needed",
                tool_aggressiveness="high_when_needed",
                default_temperature=0.5,
                default_max_tokens=4096,
                orchestration_enabled=True,
                orchestration_mode="multi_model_synthesis",
                max_tool_calls=0,
                max_search_results=0,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="base-model")],
                orchestration_roles=roles,
            )
        }
    )


def _build_orchestrator(router: _ProRouter) -> ChatOrchestrator:
    return ChatOrchestrator(
        router=router,
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=_pro_models_config(),
        tool_registry=ToolRegistry(),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=Settings(
            nesty_pro_orchestration_enabled=True,
            nesty_pro_orchestration_max_internal_calls=4,
            nesty_pro_orchestration_debug=False,
        ),
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.pro.orchestration"),
    )


@pytest.mark.asyncio
async def test_nesty_pro_non_stream_uses_multi_model_orchestration() -> None:
    router = _ProRouter()
    orchestrator = _build_orchestrator(router)
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="plan architecture")],
        search="off",
        tools="off",
        stream=False,
    )
    response = await orchestrator.create_chat_completion("req_pro_1", request)
    assert response.orchestration is not None
    assert response.orchestration.enabled is True
    assert response.orchestration.used is True
    assert response.orchestration.mode == "multi_model_synthesis"
    assert response.orchestration.internal_calls == 4
    assert response.orchestration.roles == ["planner", "researcher", "critic", "finalizer"]
    assert response.provider == "internal"
    assert router.route_chat_calls == 0
    assert len(router.generate_calls) == 4


@pytest.mark.asyncio
async def test_nesty_pro_stream_does_not_use_multi_model_orchestration() -> None:
    router = _ProRouter()
    orchestrator = _build_orchestrator(router)
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="stream test")],
        search="off",
        tools="off",
        stream=True,
    )
    handle = await orchestrator.create_chat_completion_stream("req_pro_stream", request)
    assert handle.outcome.orchestration.enabled is True
    assert handle.outcome.orchestration.used is False
    assert handle.outcome.orchestration.mode == "single_stream"
    assert handle.outcome.orchestration.reason == "streaming_not_supported_for_multi_model"
