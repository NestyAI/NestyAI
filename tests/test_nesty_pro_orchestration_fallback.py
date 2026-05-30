from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, OrchestrationRoleConfig, ProviderTarget, Settings
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.provider import ProviderChatResult
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


@dataclass
class _DummyRouteResult:
    provider_result: ProviderChatResult
    provider_used: str


class _FallbackRouter:
    def __init__(self) -> None:
        self.route_chat_calls = 0
        self.generate_calls = 0

    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        self.route_chat_calls += 1
        return _DummyRouteResult(
            provider_result=ProviderChatResult(provider="fallback", content="single fallback answer"),
            provider_used="fallback",
        )

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        raise AssertionError("streaming path not used in this test")

    async def generate_with_provider_chain(
        self,
        request_id,
        provider_chain,
        messages,
        temperature,
        max_tokens,
        trace_label="custom_chain",
    ):
        self.generate_calls += 1
        raise RuntimeError("forced_internal_failure")


def _models_config() -> ModelsConfig:
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


@pytest.mark.asyncio
async def test_nesty_pro_orchestration_falls_back_to_single_model() -> None:
    router = _FallbackRouter()
    orchestrator = ChatOrchestrator(
        router=router,
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=_models_config(),
        tool_registry=ToolRegistry(),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=Settings(
            nesty_pro_orchestration_enabled=True,
            nesty_pro_orchestration_max_internal_calls=4,
            nesty_pro_orchestration_debug=False,
        ),
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.pro.orchestration.fallback"),
    )
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="fallback case")],
        search="off",
        tools="off",
        stream=False,
    )
    response = await orchestrator.create_chat_completion("req_pro_fallback", request)
    assert response.provider == "fallback"
    assert response.choices[0].message.content == "single fallback answer"
    assert response.orchestration is not None
    assert response.orchestration.enabled is True
    assert response.orchestration.used is False
    assert response.orchestration.fallback_used is True
    assert response.orchestration.mode == "multi_model_synthesis"
    assert response.orchestration.reason == "fallback_to_single_model"
    assert router.generate_calls >= 1
    assert router.route_chat_calls == 1
