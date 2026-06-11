from __future__ import annotations

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatMessage,
    GuardInfo,
    OrchestrationInfo,
    PlannerInfo,
    RetrievalInfo,
    SemanticRecallInfo,
)
from app.schemas.provider import ProviderChatResult, ProviderUsage
from app.schemas.tools import ToolMetadata
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


class _CountingRouter:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return type(
            "RouteResult",
            (),
            {
                "provider_result": ProviderChatResult(
                    provider="openrouter",
                    content=self.responses[index],
                    usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                ),
                "provider_used": "openrouter",
            },
        )()


def _orchestrator(db_path: str, router: _CountingRouter) -> ChatOrchestrator:
    models = ModelsConfig(
        models={
            "nesty-combined-1.0": ModelProfile(
                display_name="combined",
                description="combined",
                strategy="balanced",
                search_mode="off",
                behavior_profile="balanced",
                max_tool_calls=0,
                max_search_results=0,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="dummy-model")],
            )
        }
    )
    settings = Settings(
        nesty_db_path=db_path,
        rate_limit_enabled=False,
        require_api_key=False,
        semantic_recall_enabled=False,
        embeddings_enabled=False,
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
        logger=get_logger("test.empty_answer_retry"),
    )


def test_should_retry_empty_answer_when_retrieval_context_used() -> None:
    assert (
        ChatOrchestrator._should_retry_empty_answer(
            retrieval=RetrievalInfo(context_used=True),
            tools_meta=ToolMetadata(),
            planner=PlannerInfo(),
            orchestration=OrchestrationInfo(),
        )
        is True
    )


def test_should_not_retry_empty_answer_without_context_or_tools() -> None:
    assert (
        ChatOrchestrator._should_retry_empty_answer(
            retrieval=RetrievalInfo(),
            tools_meta=ToolMetadata(),
            planner=PlannerInfo(),
            orchestration=OrchestrationInfo(),
        )
        is False
    )


@pytest.mark.asyncio
async def test_empty_answer_retry_when_retrieval_context_used(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "empty_retry.db")
    router = _CountingRouter(["", "Retried useful answer."])
    orchestrator = _orchestrator(db_path, router)

    async def _prepare_with_retrieval(request_id, request, tools_mode, lifecycle=None):
        messages = [ChatMessage(role="user", content="What is the latest news?")]
        return (
            messages,
            GuardInfo(),
            ToolMetadata(),
            [],
            SemanticRecallInfo(),
            RetrievalInfo(context_used=True, search_used=True, context_items_count=2, context_used_chars=500),
            PlannerInfo(search_used=True, search_planned=True),
        )

    monkeypatch.setattr(orchestrator, "_prepare_chat_context", _prepare_with_retrieval)

    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="What is the latest news?")],
        search="off",
        tools="off",
        semantic_recall="off",
        store=False,
    )

    response = await orchestrator.create_chat_completion("req_retry_1", request)
    assert response.choices[0].message.content == "Retried useful answer."
    assert router.calls == 2
    assert "empty_retry_attempted" in response.answer_quality.flags


@pytest.mark.asyncio
async def test_empty_answer_no_retry_without_retrieval_context(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "empty_no_retry.db")
    router = _CountingRouter(["", "Should not be used."])
    orchestrator = _orchestrator(db_path, router)

    async def _prepare_without_retrieval(request_id, request, tools_mode, lifecycle=None):
        messages = [ChatMessage(role="user", content="hi")]
        return (
            messages,
            GuardInfo(),
            ToolMetadata(),
            [],
            SemanticRecallInfo(),
            RetrievalInfo(),
            PlannerInfo(),
        )

    monkeypatch.setattr(orchestrator, "_prepare_chat_context", _prepare_without_retrieval)

    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="hi")],
        search="off",
        tools="off",
        semantic_recall="off",
        store=False,
    )

    response = await orchestrator.create_chat_completion("req_retry_2", request)
    assert "couldn't generate a useful response" in response.choices[0].message.content
    assert router.calls == 1
    assert "empty_retry_attempted" not in response.answer_quality.flags
