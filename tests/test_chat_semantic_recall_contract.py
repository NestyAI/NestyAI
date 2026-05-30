from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
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


class _CaptureRouter:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []

    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        self.messages = list(messages)
        return _RouteResult(
            provider_result=ProviderChatResult(
                provider="openrouter",
                content="ok",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
            provider_used="openrouter",
        )

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        raise AssertionError("stream not used in this test")


def _orchestrator(router: _CaptureRouter, db_path: str) -> ChatOrchestrator:
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
        semantic_recall_enabled=True,
        embeddings_enabled=True,
        semantic_recall_top_k=5,
        semantic_recall_min_score=0.5,
        semantic_recall_max_context_chars=4000,
        semantic_recall_scope="conversation",
        semantic_recall_include_roles=["user", "assistant"],
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
        logger=get_logger("test.semantic.contract"),
    )


@pytest.mark.asyncio
async def test_chat_semantic_recall_injects_memory_context_and_metadata(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "chat_semantic_contract.db")
    router = _CaptureRouter()
    orchestrator = _orchestrator(router, db_path=db_path)

    monkeypatch.setattr(
        "app.core.orchestrator.should_use_semantic_recall",
        lambda request, model_config, context_metadata, config: {
            "enabled": True,
            "requested": "auto",
            "should_use": True,
            "reason": "semantic_recall_enabled",
        },
    )

    async def _mock_retrieve(**kwargs):
        return {
            "enabled": True,
            "requested": "auto",
            "used": True,
            "reason": "semantic_recall_enabled",
            "query_embedded": True,
            "top_k": 5,
            "min_score": 0.5,
            "matches": [
                {
                    "message_id": "msg_1",
                    "conversation_id": "conv_1",
                    "role": "user",
                    "content": "We discussed provider chain fallback.",
                    "score": 0.91,
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "context_text": "[Memory 1 | score=0.91 | role=user | date=2026-01-01T00:00:00+00:00]\nWe discussed provider chain fallback.",
        }

    monkeypatch.setattr("app.core.orchestrator.retrieve_semantic_memories", _mock_retrieve)

    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="What did I say earlier?")],
        store=True,
        conversation_id="conv_1",
        search="off",
        tools="off",
        semantic_recall="auto",
        request_api_key_id="key_1",
    )
    response = await orchestrator.create_chat_completion("req_semantic_1", request)
    assert response.semantic_recall is not None
    assert response.semantic_recall.used is True
    assert response.semantic_recall.matches_count == 1
    assert any("Relevant remembered conversation snippets below" in msg.content for msg in router.messages)


@pytest.mark.asyncio
async def test_chat_semantic_recall_off_keeps_disabled_metadata(tmp_path) -> None:
    db_path = str(tmp_path / "chat_semantic_off.db")
    router = _CaptureRouter()
    orchestrator = _orchestrator(router, db_path=db_path)
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="hello")],
        store=True,
        conversation_id="conv_1",
        search="off",
        tools="off",
        semantic_recall="off",
    )
    response = await orchestrator.create_chat_completion("req_semantic_2", request)
    assert response.semantic_recall is not None
    assert response.semantic_recall.used is False
    assert response.semantic_recall.reason == "request_off"


@pytest.mark.asyncio
async def test_chat_semantic_recall_failure_does_not_fail_chat(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "chat_semantic_fail_safe.db")
    router = _CaptureRouter()
    orchestrator = _orchestrator(router, db_path=db_path)
    monkeypatch.setattr(
        "app.core.orchestrator.should_use_semantic_recall",
        lambda request, model_config, context_metadata, config: {
            "enabled": True,
            "requested": "on",
            "should_use": True,
            "reason": "semantic_recall_enabled",
        },
    )

    async def _raise_retrieve(**kwargs):
        raise RuntimeError("semantic service down")

    monkeypatch.setattr("app.core.orchestrator.retrieve_semantic_memories", _raise_retrieve)
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="remember this")],
        store=True,
        conversation_id="conv_1",
        semantic_recall="on",
        search="off",
        tools="off",
    )
    response = await orchestrator.create_chat_completion("req_semantic_fail", request)
    assert response.choices[0].message.content == "ok"
    assert response.semantic_recall is not None
    assert response.semantic_recall.used is False
    assert response.semantic_recall.reason == "semantic_recall_failed"


def test_invalid_semantic_recall_mode_returns_error(client) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "search": "off",
            "tools": "off",
            "semantic_recall": "invalid_mode",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_semantic_recall_mode"
