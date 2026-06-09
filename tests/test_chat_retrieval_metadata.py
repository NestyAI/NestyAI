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
        semantic_recall_enabled=False,
        embeddings_enabled=False,
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
        logger=get_logger("test.retrieval.metadata"),
    )


@pytest.mark.asyncio
async def test_chat_retrieval_metadata_in_non_stream_response(tmp_path) -> None:
    db_path = str(tmp_path / "retrieval_metadata.db")
    orchestrator = _orchestrator(db_path)
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="Remember the previous summary?")],
        search="off",
        tools="off",
        semantic_recall="off",
        store=True,
        conversation_id="conv_1",
        conversation_history_used=True,
        conversation_summary_used=True,
    )

    response = await orchestrator.create_chat_completion("req_retrieval_1", request)
    assert response.retrieval is not None
    assert response.retrieval.context_used is True
    assert response.retrieval.context_sources == ["recent", "summary"]
    assert response.retrieval.retrieval_decision == "conversation"
    assert response.retrieval.retrieval_reason == "conversation_context"
    payload = response.retrieval.model_dump_json()
    assert "Remember the previous summary?" not in payload


@pytest.mark.asyncio
async def test_chat_retrieval_metadata_in_streaming_final_metadata(tmp_path) -> None:
    db_path = str(tmp_path / "retrieval_stream_metadata.db")
    orchestrator = _orchestrator(db_path)
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="Nhắc lại phần trước đó.")],
        search="off",
        tools="off",
        semantic_recall="off",
        stream=True,
        store=True,
        conversation_id="conv_1",
        conversation_history_used=True,
        conversation_summary_used=True,
    )

    stream_handle = await orchestrator.create_chat_completion_stream("req_retrieval_2", request)
    events: list[dict] = []
    async for line in stream_handle.events:
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if raw == "[DONE]":
            continue
        events.append(json.loads(raw))

    metadata_event = next(event for event in events if event.get("object") == "chat.completion.metadata")
    assert "retrieval" in metadata_event
    retrieval = metadata_event["retrieval"]
    assert retrieval["context_used"] is True
    assert retrieval["context_sources"] == ["recent", "summary"]
    assert retrieval["retrieval_decision"] == "conversation"
    assert retrieval["retrieval_reason"] == "conversation_context"
    assert "Nhắc lại phần trước đó." not in json.dumps(retrieval, ensure_ascii=False)
