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
from app.schemas.provider import ProviderStreamChunk, ProviderUsage
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


@dataclass
class _StreamRouteResult:
    provider_used: str
    stream: object


class _StreamRouter:
    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        raise AssertionError("non-stream path not used")

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        async def _events():
            yield ProviderStreamChunk(delta="Hello")
            yield ProviderStreamChunk(finish_reason="stop", usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

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
        router=_StreamRouter(),
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=models,
        tool_registry=ToolRegistry(),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=settings,
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.semantic.stream"),
    )


@pytest.mark.asyncio
async def test_streaming_metadata_includes_semantic_recall(monkeypatch, tmp_path) -> None:
    orchestrator = _orchestrator(str(tmp_path / "stream_semantic.db"))
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
                    "content": "Earlier memory text",
                    "score": 0.82,
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "context_text": "[Memory 1 | score=0.82 | role=user | date=2026-01-01T00:00:00+00:00]\nEarlier memory text",
        }

    monkeypatch.setattr("app.core.orchestrator.retrieve_semantic_memories", _mock_retrieve)

    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="continue this project")],
        stream=True,
        store=True,
        conversation_id="conv_1",
        semantic_recall="auto",
        search="off",
        tools="off",
    )
    handle = await orchestrator.create_chat_completion_stream("req_stream_semantic", request)
    payload = ""
    async for event in handle.events:
        payload += event

    metadata_lines = [
        line
        for line in payload.splitlines()
        if '"object":"chat.completion.metadata"' in line or '"object": "chat.completion.metadata"' in line
    ]
    assert metadata_lines
    raw = metadata_lines[0].split("data:", 1)[1].strip()
    data = json.loads(raw)
    assert "semantic_recall" in data
    assert data["semantic_recall"]["used"] is True
