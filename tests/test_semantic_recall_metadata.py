from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


@dataclass
class _RouteResult:
    provider_result: ProviderChatResult
    provider_used: str


@dataclass
class _StreamRouteResult:
    provider_used: str
    stream: object


class _Router:
    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        return _RouteResult(
            provider_result=ProviderChatResult(
                provider="openrouter",
                content="ok",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
            provider_used="openrouter",
        )

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        async def _events():
            yield ProviderStreamChunk(delta="hello")
            yield ProviderStreamChunk(
                finish_reason="stop",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        return _StreamRouteResult(provider_used="openrouter", stream=_events())


def _orchestrator(db_path: str) -> ChatOrchestrator:
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
        semantic_recall_scope="conversation",
    )
    return ChatOrchestrator(
        router=_Router(),
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=models,
        tool_registry=ToolRegistry(),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=settings,
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.semantic.metadata"),
    )


def _mock_semantic_result():
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
                "content": "Earlier memory text",
                "score": 0.91,
                "raw_score": 0.84,
                "pinned": True,
                "excluded": False,
                "tags": ["important"],
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "context_text": "[Memory 1 | score=0.91 | pinned | role=user | date=2026-01-01T00:00:00+00:00]\nEarlier memory text",
        "pinned_matches_count": 1,
        "excluded_matches_count": 0,
        "deduped_count": 2,
        "max_score": 0.91,
        "min_returned_score": 0.91,
        "scope": "conversation",
        "candidate_count": 8,
        "used_context_chars": 120,
    }


@pytest.mark.asyncio
async def test_semantic_recall_metadata_in_non_stream_response(monkeypatch, tmp_path) -> None:
    orchestrator = _orchestrator(str(tmp_path / "semantic_meta_nonstream.db"))
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
        return _mock_semantic_result()

    monkeypatch.setattr("app.core.orchestrator.retrieve_semantic_memories", _mock_retrieve)
    response = await orchestrator.create_chat_completion(
        "req_sem_meta_1",
        ChatCompletionRequest(
            model="nesty-combined-1.0",
            messages=[ChatMessage(role="user", content="remember this")],
            search="off",
            tools="off",
            store=True,
            conversation_id="conv_1",
            semantic_recall="auto",
        ),
    )
    assert response.semantic_recall is not None
    assert response.semantic_recall.pinned_matches_count == 1
    assert response.semantic_recall.deduped_count == 2
    assert response.semantic_recall.scope == "conversation"
    assert response.semantic_recall.candidate_count == 8
    assert response.semantic_recall.used_context_chars > 0


@pytest.mark.asyncio
async def test_semantic_recall_metadata_in_stream_metadata_event(monkeypatch, tmp_path) -> None:
    orchestrator = _orchestrator(str(tmp_path / "semantic_meta_stream.db"))
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
        return _mock_semantic_result()

    monkeypatch.setattr("app.core.orchestrator.retrieve_semantic_memories", _mock_retrieve)
    handle = await orchestrator.create_chat_completion_stream(
        "req_sem_meta_2",
        ChatCompletionRequest(
            model="nesty-combined-1.0",
            messages=[ChatMessage(role="user", content="remember this")],
            stream=True,
            search="off",
            tools="off",
            store=True,
            conversation_id="conv_1",
            semantic_recall="auto",
        ),
    )

    payload = ""
    async for event in handle.events:
        payload += event
    metadata_lines = [
        line
        for line in payload.splitlines()
        if '"object":"chat.completion.metadata"' in line or '"object": "chat.completion.metadata"' in line
    ]
    assert metadata_lines
    data = json.loads(metadata_lines[0].split("data:", 1)[1].strip())
    semantic = data["semantic_recall"]
    assert semantic["pinned_matches_count"] == 1
    assert semantic["deduped_count"] == 2
    assert semantic["candidate_count"] == 8
