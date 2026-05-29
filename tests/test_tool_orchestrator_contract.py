from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.provider import ProviderChatResult
from app.tools.registry import ToolRegistry, ToolSpec
from app.utils.logging import get_logger


@dataclass
class DummyRouteResult:
    provider_result: ProviderChatResult
    provider_used: str


class DummyRouter:
    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        return DummyRouteResult(
            provider_result=ProviderChatResult(provider="dummy", content="Tool-aware answer"),
            provider_used="dummy",
        )


async def _tool_success(message: str, context: dict):
    from app.schemas.tools import ToolResult

    return ToolResult(
        name="calculator",
        success=True,
        content="2 + 2 = 4",
        data={"result": 4},
        latency_ms=1,
    )


async def _tool_failure(message: str, context: dict):
    from app.schemas.tools import ToolResult

    return ToolResult(
        name="calculator",
        success=False,
        content="failed",
        error="tool_execution_failed",
        latency_ms=1,
    )


def _model_config() -> ModelsConfig:
    return ModelsConfig(
        models={
            "nesty-combined-1.0": ModelProfile(
                display_name="Nesty Combined 1.0",
                description="test",
                strategy="balanced",
                search_mode="off",
                tools_mode="auto",
                max_tool_calls=3,
                allowed_tools=["calculator"],
                max_search_results=0,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="dummy-model")],
            )
        }
    )


def _build_orchestrator(tool_execute) -> ChatOrchestrator:
    registry = ToolRegistry()
    registry.register_tool(
        ToolSpec(
            name="calculator",
            description="calc",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=tool_execute,
        )
    )
    return ChatOrchestrator(
        router=DummyRouter(),
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=_model_config(),
        tool_registry=registry,
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=Settings(),
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.tool.orchestrator"),
    )


@pytest.mark.asyncio
async def test_orchestrator_includes_tool_executions() -> None:
    orchestrator = _build_orchestrator(_tool_success)
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="calculate 2+2")],
        search="off",
        tools="auto",
    )

    response = await orchestrator.create_chat_completion("req_test", request)
    assert response.tools.executions
    assert response.tools.executions[0].name == "calculator"
    assert response.tools.executions[0].success is True


@pytest.mark.asyncio
async def test_orchestrator_tool_failure_does_not_crash_in_auto_mode() -> None:
    orchestrator = _build_orchestrator(_tool_failure)
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="calculate 2+2")],
        search="off",
        tools="auto",
    )

    response = await orchestrator.create_chat_completion("req_test", request)
    assert response.choices[0].message.content
    assert response.tools.executions
    assert response.tools.executions[0].success is False

