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
    PlannerInfo,
    RetrievalInfo,
    SemanticRecallInfo,
)
from app.schemas.provider import ProviderChatResult, ProviderUsage
from app.schemas.tools import SourceItem, ToolMetadata
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


class _CountingRouter:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.last_messages = None

    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        self.last_messages = messages
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
        logger=get_logger("test.quality_answer_retry"),
    )


@pytest.mark.asyncio
async def test_weak_answer_with_context_triggers_one_quality_retry(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "weak_retry.db")
    router = _CountingRouter(
        [
            "I don't have enough information to answer that.",
            "Based on the provided context, the release includes improved streaming reliability.",
        ]
    )
    orchestrator = _orchestrator(db_path, router)

    async def _prepare_with_context(request_id, request, tools_mode, lifecycle=None):
        messages = [ChatMessage(role="user", content="Summarize the latest release notes.")]
        return (
            messages,
            GuardInfo(),
            ToolMetadata(),
            [SourceItem(title="Release notes", url="https://example.com/r", snippet="Improved streaming reliability.")],
            SemanticRecallInfo(),
            RetrievalInfo(context_used=True, search_used=True, context_items_count=1),
            PlannerInfo(search_used=True, search_planned=True),
        )

    monkeypatch.setattr(orchestrator, "_prepare_chat_context", _prepare_with_context)

    response = await orchestrator.create_chat_completion(
        "req_weak_retry",
        ChatCompletionRequest(
            model="nesty-combined-1.0",
            messages=[ChatMessage(role="user", content="Summarize the latest release notes.")],
            search="off",
            tools="off",
            semantic_recall="off",
            store=False,
        ),
    )

    assert router.calls == 2
    assert "improved streaming reliability" in response.choices[0].message.content.lower()
    assert response.answer_quality.retry_attempted is True
    assert response.answer_quality.retry_reason is not None
    assert response.answer_quality.weak_answer_before_retry is True
    assert response.answer_quality.context_available is True


@pytest.mark.asyncio
async def test_useful_concise_answer_does_not_retry(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "no_weak_retry.db")
    router = _CountingRouter(["FastAPI 0.115 improves streaming reliability."])
    orchestrator = _orchestrator(db_path, router)

    async def _prepare_with_context(request_id, request, tools_mode, lifecycle=None):
        return (
            [ChatMessage(role="user", content="What changed?")],
            GuardInfo(),
            ToolMetadata(),
            [SourceItem(title="Notes", url="https://example.com/n", snippet="Streaming reliability improved.")],
            SemanticRecallInfo(),
            RetrievalInfo(context_used=True, search_used=True),
            PlannerInfo(search_used=True),
        )

    monkeypatch.setattr(orchestrator, "_prepare_chat_context", _prepare_with_context)

    response = await orchestrator.create_chat_completion(
        "req_no_weak_retry",
        ChatCompletionRequest(
            model="nesty-combined-1.0",
            messages=[ChatMessage(role="user", content="What changed?")],
            search="off",
            tools="off",
            semantic_recall="off",
            store=False,
        ),
    )

    assert router.calls == 1
    assert response.answer_quality.retry_attempted is False


@pytest.mark.asyncio
async def test_retry_keeps_first_non_empty_when_retry_is_empty(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "keep_first.db")
    router = _CountingRouter(
        [
            "I don't have enough information to answer.",
            "   ",
        ]
    )
    orchestrator = _orchestrator(db_path, router)

    async def _prepare_with_context(request_id, request, tools_mode, lifecycle=None):
        return (
            [ChatMessage(role="user", content="Summarize")],
            GuardInfo(),
            ToolMetadata(),
            [SourceItem(title="Notes", url="https://example.com/n", snippet="Details here.")],
            SemanticRecallInfo(),
            RetrievalInfo(context_used=True, search_used=True),
            PlannerInfo(search_used=True),
        )

    monkeypatch.setattr(orchestrator, "_prepare_chat_context", _prepare_with_context)

    response = await orchestrator.create_chat_completion(
        "req_keep_first",
        ChatCompletionRequest(
            model="nesty-combined-1.0",
            messages=[ChatMessage(role="user", content="Summarize")],
            search="off",
            tools="off",
            semantic_recall="off",
            store=False,
        ),
    )

    assert router.calls == 2
    assert "don't have enough information" in response.choices[0].message.content.lower()
    assert response.answer_quality.retry_attempted is True


@pytest.mark.asyncio
async def test_safety_refusal_does_not_trigger_retry(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "no_safety_retry.db")
    router = _CountingRouter(["I can't help with creating malware or exploits."])
    orchestrator = _orchestrator(db_path, router)

    async def _prepare_with_context(request_id, request, tools_mode, lifecycle=None):
        return (
            [ChatMessage(role="user", content="bad request")],
            GuardInfo(),
            ToolMetadata(),
            [SourceItem(title="Notes", url="https://example.com/n", snippet="Details here.")],
            SemanticRecallInfo(),
            RetrievalInfo(context_used=True, search_used=True),
            PlannerInfo(search_used=True),
        )

    monkeypatch.setattr(orchestrator, "_prepare_chat_context", _prepare_with_context)

    response = await orchestrator.create_chat_completion(
        "req_safety_no_retry",
        ChatCompletionRequest(
            model="nesty-combined-1.0",
            messages=[ChatMessage(role="user", content="bad request")],
            search="off",
            tools="off",
            semantic_recall="off",
            store=False,
        ),
    )

    assert router.calls == 1
    assert response.answer_quality.retry_attempted is False
