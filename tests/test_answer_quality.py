from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
from app.core.answer_quality import evaluate_answer_quality
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatCompletionRequest, ChatMessage, OutputSafetyInfo
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
    def __init__(self, content: str, stream_content: str | None = None) -> None:
        self.content = content
        self.stream_content = stream_content if stream_content is not None else content

    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        return _RouteResult(
            provider_result=ProviderChatResult(
                provider="openrouter",
                content=self.content,
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
            provider_used="openrouter",
        )

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        async def _events():
            yield ProviderStreamChunk(delta=self.stream_content)
            yield ProviderStreamChunk(
                finish_reason="stop",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        return _StreamRouteResult(provider_used="openrouter", stream=_events())


def _orchestrator(db_path: str, router: _Router) -> ChatOrchestrator:
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
        logger=get_logger("test.answer_quality"),
    )


def test_evaluate_answer_quality_flags_claimed_search_without_search() -> None:
    final_text, info = evaluate_answer_quality(
        "I searched the web and found it online.",
        retrieval={"search_used": False},
        tools={"search": {"enabled": False}, "used": []},
        sources=[],
    )
    assert final_text == "I searched the web and found it online."
    assert info.checked is True
    assert info.flags == ["claimed_search_without_search"]
    assert info.action == "none"


def test_evaluate_answer_quality_ignores_generic_search_words() -> None:
    final_text, info = evaluate_answer_quality(
        "The search results were inconclusive, so I will answer from what we already know.",
        retrieval={"search_used": False},
        tools={"search": {"enabled": False}, "used": []},
        sources=[],
    )
    assert final_text == "The search results were inconclusive, so I will answer from what we already know."
    assert info.flags == []
    assert info.action == "none"


def test_evaluate_answer_quality_flags_claim_when_search_is_only_enabled_not_used() -> None:
    final_text, info = evaluate_answer_quality(
        "I checked online and found the answer.",
        retrieval={"search_used": False},
        tools={"search": {"enabled": True, "query": None, "results_count": 0, "failed": False}, "used": []},
        sources=[],
    )
    assert final_text == "I checked online and found the answer."
    assert info.checked is True
    assert info.flags == ["claimed_search_without_search"]
    assert info.action == "none"


def test_evaluate_answer_quality_flags_vietnamese_search_claim_without_search() -> None:
    final_text, info = evaluate_answer_quality(
        "Mình đã tra trên web và thấy kết quả rồi.",
        retrieval={"search_used": False},
        tools={"search": {"enabled": False}, "used": []},
        sources=[],
    )
    assert final_text == "Mình đã tra trên web và thấy kết quả rồi."
    assert info.checked is True
    assert info.flags == ["claimed_search_without_search"]
    assert info.action == "none"


def test_evaluate_answer_quality_ignores_generic_vietnamese_search_words() -> None:
    final_text, info = evaluate_answer_quality(
        "Kết quả tìm kiếm và tra cứu vẫn chưa đủ, nên em sẽ trả lời từ ngữ cảnh sẵn có.",
        retrieval={"search_used": False},
        tools={"search": {"enabled": False}, "used": []},
        sources=[],
    )
    assert final_text == "Kết quả tìm kiếm và tra cứu vẫn chưa đủ, nên em sẽ trả lời từ ngữ cảnh sẵn có."
    assert info.flags == []
    assert info.action == "none"


def test_evaluate_answer_quality_reuses_output_safety_markup_flag() -> None:
    final_text, info = evaluate_answer_quality(
        "Plain answer text.",
        output_safety=OutputSafetyInfo(internal_tool_markup_detected=True, internal_tool_markup_removed=True),
    )
    assert final_text == "Plain answer text."
    assert info.checked is True
    assert info.flags == ["internal_markup_detected"]
    assert info.action == "cleaned_internal_markup"


@pytest.mark.asyncio
async def test_non_stream_empty_answer_uses_fallback_and_metadata(tmp_path) -> None:
    db_path = str(tmp_path / "answer_quality_empty.db")
    orchestrator = _orchestrator(db_path, _Router("   "))
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="hi")],
        search="off",
        tools="off",
        semantic_recall="off",
        store=False,
    )

    response = await orchestrator.create_chat_completion("req_aq_1", request)
    assert response.choices[0].message.content == (
        "I'm sorry, I couldn't generate a useful response for that request. Please try again or rephrase."
    )
    assert response.answer_quality.checked is True
    assert "empty_answer" in response.answer_quality.flags
    assert response.answer_quality.action == "fallback_empty"


@pytest.mark.asyncio
async def test_non_stream_normal_answer_has_quality_metadata(tmp_path) -> None:
    db_path = str(tmp_path / "answer_quality_normal.db")
    orchestrator = _orchestrator(db_path, _Router("A concise, direct answer."))
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="hi")],
        search="off",
        tools="off",
        semantic_recall="off",
        store=False,
    )

    response = await orchestrator.create_chat_completion("req_aq_2", request)
    assert response.choices[0].message.content == "A concise, direct answer."
    assert response.answer_quality.checked is True
    assert response.answer_quality.flags == []
    assert response.answer_quality.action == "none"


@pytest.mark.asyncio
async def test_streaming_metadata_includes_answer_quality(tmp_path) -> None:
    db_path = str(tmp_path / "answer_quality_stream.db")
    orchestrator = _orchestrator(db_path, _Router("I searched the web and found it online."))
    request = ChatCompletionRequest(
        model="nesty-combined-1.0",
        messages=[ChatMessage(role="user", content="hi")],
        search="off",
        tools="off",
        semantic_recall="off",
        stream=True,
        store=False,
    )

    stream_handle = await orchestrator.create_chat_completion_stream("req_aq_3", request)
    events: list[dict] = []
    async for line in stream_handle.events:
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if raw == "[DONE]":
            continue
        events.append(json.loads(raw))

    metadata_event = next(event for event in events if event.get("object") == "chat.completion.metadata")
    answer_quality = metadata_event["answer_quality"]
    assert answer_quality["checked"] is True
    assert "claimed_search_without_search" in answer_quality["flags"]
    assert answer_quality["action"] == "metadata_only"
    assert "I searched the web" not in json.dumps(answer_quality, ensure_ascii=False)
