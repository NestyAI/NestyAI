from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
from app.core.orchestrator import ChatOrchestrator
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage
from app.schemas.tools import SearchResult, ToolResult
from app.tools.calculator import execute_calculator
from app.tools.planner import plan_tools_decision
from app.tools.search_intent import plan_search_intent
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.exchange_rate import extract_exchange_request
from app.tools.package_version import extract_package_name
from app.tools.weather import extract_weather_location
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
                content="Tool-aware answer.",
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


def _tool_result(
    name: str,
    *,
    success: bool,
    content: str,
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        name=name,
        success=success,
        content=content,
        error=error,
        confidence="high" if success else "low",
        latency_ms=1,
    )


async def _weather_stub(message: str, context: dict) -> ToolResult:
    location = extract_weather_location(message, None)
    if not location:
        return _tool_result("weather_lookup", success=False, content="Could not detect location.", error="location_not_detected")
    return _tool_result("weather_lookup", success=True, content=f"Weather for {location}")


async def _package_stub(message: str, context: dict) -> ToolResult:
    package_name = extract_package_name(message)
    if not package_name:
        return _tool_result("package_version_lookup", success=False, content="Could not detect package.", error="package_not_detected")
    return _tool_result("package_version_lookup", success=True, content=f"Package {package_name} version 1.0.0")


async def _exchange_stub(message: str, context: dict) -> ToolResult:
    parsed = extract_exchange_request(message)
    if not parsed:
        return _tool_result("exchange_rate", success=False, content="Could not parse pair.", error="invalid_currency_pair")
    amount, base, target = parsed
    return _tool_result("exchange_rate", success=True, content=f"{amount} {base} -> {target}")


async def _wikipedia_stub(message: str, context: dict) -> ToolResult:
    if "what is" not in message.lower() and "who is" not in message.lower():
        return _tool_result("wikipedia_lookup", success=False, content="Not a definition query.", error="invalid_query")
    return _tool_result("wikipedia_lookup", success=True, content="Wikipedia summary")


def _build_registry(web_search_handler: Callable[..., tuple[list[SearchResult], bool]]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tool(
        ToolSpec(
            name="calculator",
            description="calc",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=execute_calculator,
        )
    )
    registry.register_tool(
        ToolSpec(
            name="weather_lookup",
            description="weather",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=_weather_stub,
        )
    )
    registry.register_tool(
        ToolSpec(
            name="package_version_lookup",
            description="package",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=_package_stub,
        )
    )
    registry.register_tool(
        ToolSpec(
            name="exchange_rate",
            description="exchange",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=_exchange_stub,
        )
    )
    registry.register_tool(
        ToolSpec(
            name="wikipedia_lookup",
            description="wiki",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=_wikipedia_stub,
        )
    )
    registry.register_helper("datetime.now", lambda: {"iso": "2026-06-10T08:00:00+07:00", "date": "2026-06-10", "time": "08:00:00", "timezone": "Asia/Ho_Chi_Minh"})
    registry.register_helper("web.search", web_search_handler)

    async def web_search_multi_handler(
        queries,
        max_results,
        timeout_seconds,
        cache_enabled,
        cache_ttl_seconds,
    ):
        from app.tools.web_search import WebSearchMeta

        primary_query = queries[0] if queries else ""
        results, failed = await web_search_handler(
            primary_query,
            max_results,
            timeout_seconds,
            cache_enabled,
            cache_ttl_seconds,
        )
        return results, WebSearchMeta(
            queries=list(queries),
            failed=failed,
            result_count=len(results),
            filtered_result_count=0,
        )

    registry.register_helper("web.search.multi", web_search_multi_handler)
    return registry


def _model_config() -> ModelsConfig:
    return ModelsConfig(
        models={
            "test-planner-1.0": ModelProfile(
                display_name="Test Planner 1.0",
                description="test",
                strategy="balanced",
                search_mode="auto",
                tool_aggressiveness="auto",
                search_aggressiveness="auto",
                allowed_tools=["calculator", "weather_lookup", "package_version_lookup", "exchange_rate", "wikipedia_lookup"],
                max_tool_calls=4,
                max_search_results=3,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="dummy-model")],
            )
        }
    )


def _orchestrator(tmp_path, web_search_handler):
    settings = Settings(
        nesty_db_path=str(tmp_path / "planner.db"),
        rate_limit_enabled=False,
        require_api_key=False,
        semantic_recall_enabled=False,
        embeddings_enabled=False,
    )
    return ChatOrchestrator(
        router=_Router(),
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=_model_config(),
        tool_registry=_build_registry(web_search_handler),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=settings,
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.planner.quality"),
    )


def test_search_and_tool_planners_stay_conservative() -> None:
    search_cfg = {"search_mode": "auto", "search_aggressiveness": "auto"}
    tool_cfg = {"allowed_tools": ["calculator", "package_version_lookup", "weather_lookup"], "max_tool_calls": 4, "tool_aggressiveness": "auto"}

    search_decision = plan_search_intent("What is the current price of Bitcoin?", search_cfg)
    assert search_decision.should_use is True
    assert search_decision.decision == "current_info_needed"

    tool_decision = plan_tools_decision("calculate 2+2 and the latest version of fastapi", tool_cfg)
    assert tool_decision.decision == "tool_selected"
    assert tool_decision.tools_planned == ["calculator", "package_version_lookup"]
    assert all(isinstance(name, str) for name in tool_decision.tools_planned)


def test_vietnamese_current_info_triggers_search() -> None:
    search_cfg = {"search_mode": "auto", "search_aggressiveness": "auto"}
    decision = plan_search_intent("Tin moi nhat ve Groq Cloud hom nay la gi?", search_cfg)
    assert decision.should_use is True
    assert decision.decision == "current_info_needed"


def test_followup_prefers_memory_when_available() -> None:
    search_cfg = {"search_mode": "auto", "search_aggressiveness": "auto"}
    decision = plan_search_intent(
        "Can you remind me what we said about that thing?",
        search_cfg,
        memory_context_available=True,
    )
    assert decision.should_use is False
    assert decision.decision == "memory_context_sufficient"


def test_missing_weather_location_requests_clarification() -> None:
    tool_cfg = {
        "allowed_tools": ["calculator", "weather_lookup", "package_version_lookup", "exchange_rate", "wikipedia_lookup"],
        "max_tool_calls": 4,
        "tool_aggressiveness": "auto",
    }
    decision = plan_tools_decision("weather today", tool_cfg)
    assert decision.decision == "missing_required_parameters"
    assert decision.clarification_needed is True
    assert decision.clarification_reason == "weather_location_missing"
    assert decision.tools_planned == []


@pytest.mark.asyncio
async def test_orchestrator_keeps_search_and_tool_signals_separate(tmp_path) -> None:
    calls: dict[str, int] = {"web_search": 0, "calculator": 0, "weather": 0}

    async def web_search_handler(query, max_results, timeout_seconds, cache_enabled, cache_ttl_seconds):
        calls["web_search"] += 1
        return (
            [
                SearchResult(
                    title="Bitcoin price",
                    url="https://example.com/bitcoin",
                    snippet="Bitcoin is trading at a fake test price.",
                )
            ],
            False,
        )

    orchestrator = _orchestrator(tmp_path, web_search_handler)
    request = ChatCompletionRequest(
        model="test-planner-1.0",
        messages=[ChatMessage(role="user", content="weather today and calculate 2+2")],
        search="auto",
        tools="auto",
        store=False,
    )

    response = await orchestrator.create_chat_completion("req_planner_1", request)
    assert response.planner.search_planned is True
    assert response.planner.search_used is True
    assert response.planner.tool_decision == "tool_selected"
    assert response.planner.tools_planned == ["calculator"]
    assert response.planner.tools_used == ["calculator"]
    assert response.planner.clarification_needed is True
    assert response.planner.clarification_reason == "weather_location_missing"
    assert response.tools.search.used is True
    assert response.retrieval.search_used is True
    assert "calculator" in response.tools.used
    assert "weather_lookup" not in response.tools.used
    assert calls["web_search"] == 1


@pytest.mark.asyncio
async def test_orchestrator_distinguishes_planned_search_from_used_search(tmp_path) -> None:
    async def web_search_handler(query, max_results, timeout_seconds, cache_enabled, cache_ttl_seconds):
        return ([], False)

    orchestrator = _orchestrator(tmp_path, web_search_handler)
    request = ChatCompletionRequest(
        model="test-planner-1.0",
        messages=[ChatMessage(role="user", content="What is the current price of Bitcoin?")],
        search="auto",
        tools="off",
        store=False,
    )

    response = await orchestrator.create_chat_completion("req_planner_2", request)
    assert response.planner.search_planned is True
    assert response.planner.search_used is False
    assert response.tools.search.enabled is True
    assert response.tools.search.used is False
    assert response.retrieval.search_used is False


@pytest.mark.asyncio
async def test_streaming_metadata_includes_planner(tmp_path) -> None:
    async def web_search_handler(query, max_results, timeout_seconds, cache_enabled, cache_ttl_seconds):
        return (
            [
                SearchResult(
                    title="Bitcoin price",
                    url="https://example.com/bitcoin",
                    snippet="Bitcoin is trading at a fake test price.",
                )
            ],
            False,
        )

    orchestrator = _orchestrator(tmp_path, web_search_handler)
    request = ChatCompletionRequest(
        model="test-planner-1.0",
        messages=[ChatMessage(role="user", content="weather today and calculate 2+2")],
        search="auto",
        tools="auto",
        stream=True,
        store=False,
    )

    stream_handle = await orchestrator.create_chat_completion_stream("req_planner_3", request)
    events: list[dict] = []
    async for line in stream_handle.events:
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if raw == "[DONE]":
            continue
        events.append(json.loads(raw))

    metadata_event = next(event for event in events if event.get("object") == "chat.completion.metadata")
    planner = metadata_event["planner"]
    assert planner["search_planned"] is True
    assert planner["search_used"] is True
    assert planner["tool_decision"] == "tool_selected"
    assert planner["tools_planned"] == ["calculator"]
    assert planner["tools_used"] == ["calculator"]
    assert planner["clarification_needed"] is True
    assert planner["clarification_reason"] == "weather_location_missing"
