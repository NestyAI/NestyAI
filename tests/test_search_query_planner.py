from __future__ import annotations

import pytest

from app.schemas.tools import SearchResult
from app.tools.planner import ToolPlanDecision, should_skip_web_search_for_tools
from app.tools.search_query_planner import plan_search_queries
from app.tools.web_search import rank_and_filter_results


def test_plan_search_queries_removes_filler_prefix() -> None:
    queries = plan_search_queries("Please tell me the latest FastAPI release notes")
    assert queries
    assert any("fastapi" in query.lower() for query in queries)
    assert not any(query.lower().startswith("please tell me") for query in queries)


def test_plan_search_queries_splits_compound_question() -> None:
    queries = plan_search_queries("What is the weather in Hanoi and what is the USD/VND exchange rate today?")
    assert 1 <= len(queries) <= 3
    assert all(len(query.split()) >= 2 for query in queries)


def test_plan_search_queries_avoids_single_vague_word() -> None:
    assert plan_search_queries("news") == []


def test_rank_and_filter_results_deduplicates_by_url_and_title() -> None:
    results = [
        SearchResult(title="Alpha", url="https://example.com/a", snippet="Alpha snippet with enough detail."),
        SearchResult(title="Alpha", url="https://example.com/a?utm=1", snippet="Duplicate alpha result content."),
        SearchResult(title="Beta", url="https://example.com/b", snippet="Beta snippet with enough useful detail."),
    ]
    ranked, filtered_count = rank_and_filter_results(
        results,
        ["alpha beta"],
        max_results=5,
    )
    assert len(ranked) == 2
    assert filtered_count >= 1


def test_rank_and_filter_results_prefers_title_overlap() -> None:
    results = [
        SearchResult(title="Unrelated topic", url="https://example.com/x", snippet="Generic unrelated snippet text."),
        SearchResult(
            title="FastAPI latest release",
            url="https://example.com/fastapi",
            snippet="FastAPI release notes and version details for developers.",
        ),
    ]
    ranked, _filtered = rank_and_filter_results(results, ["fastapi latest release"], max_results=2)
    assert ranked[0].title == "FastAPI latest release"


def test_should_skip_web_search_for_deterministic_tool_plan() -> None:
    tool_plan = ToolPlanDecision(decision="tool_selected", tools_planned=["weather_lookup"], reason="auto_planner")
    assert should_skip_web_search_for_tools(tool_plan, "auto", "weather in Hanoi today") is True
    assert should_skip_web_search_for_tools(tool_plan, "on", "weather in Hanoi today") is False


def test_should_not_skip_web_search_when_compound_intent_uncovered() -> None:
    tool_plan = ToolPlanDecision(decision="tool_selected", tools_planned=["calculator"], reason="auto_planner")
    assert should_skip_web_search_for_tools(tool_plan, "auto", "weather today and calculate 2+2") is False


def test_should_not_skip_web_search_without_tool_match() -> None:
    tool_plan = ToolPlanDecision(decision="no_tool_needed", tools_planned=[], reason="no_deterministic_tool_intent")
    assert should_skip_web_search_for_tools(tool_plan, "auto", "latest news") is False


@pytest.mark.asyncio
async def test_search_failure_does_not_force_empty_answer_fallback(tmp_path, monkeypatch) -> None:
    from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
    from app.core.orchestrator import ChatOrchestrator
    from app.guards.context_guard import ContextGuard
    from app.guards.input_guard import InputGuard
    from app.guards.output_guard import OutputGuard
    from app.schemas.chat import ChatCompletionRequest, ChatMessage, GuardInfo, PlannerInfo, RetrievalInfo, SemanticRecallInfo
    from app.schemas.provider import ProviderChatResult, ProviderUsage
    from app.schemas.tools import ToolMetadata
    from app.tools.registry import ToolRegistry
    from app.tools.web_search import WebSearchMeta
    from app.utils.logging import get_logger

    class _Router:
        async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
            return type(
                "RouteResult",
                (),
                {
                    "provider_result": ProviderChatResult(
                        provider="openrouter",
                        content="Answer without live search results.",
                        usage=ProviderUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
                    ),
                    "provider_used": "openrouter",
                },
            )()

    models = ModelsConfig(
        models={
            "nesty-combined-1.0": ModelProfile(
                display_name="combined",
                description="combined",
                strategy="balanced",
                search_mode="auto",
                behavior_profile="balanced",
                max_tool_calls=0,
                max_search_results=3,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="dummy-model")],
            )
        }
    )
    settings = Settings(
        nesty_db_path=str(tmp_path / "search_fail.db"),
        rate_limit_enabled=False,
        require_api_key=False,
        semantic_recall_enabled=False,
        embeddings_enabled=False,
    )
    orchestrator = ChatOrchestrator(
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
        logger=get_logger("test.search_failure"),
    )

    async def _failed_search(queries, max_results):
        return [], WebSearchMeta(queries=queries, failed=True, error_code="search_provider_error")

    async def _prepare_with_search_notice(request_id, request, tools_mode, lifecycle=None):
        messages = [ChatMessage(role="user", content="latest news today")]
        return (
            messages,
            GuardInfo(),
            ToolMetadata(),
            [],
            SemanticRecallInfo(),
            RetrievalInfo(context_used=True, search_used=False),
            PlannerInfo(search_planned=True, search_used=False),
        )

    monkeypatch.setattr(orchestrator, "_run_web_search", _failed_search)
    monkeypatch.setattr(orchestrator, "_prepare_chat_context", _prepare_with_search_notice)

    response = await orchestrator.create_chat_completion(
        "req_search_fail",
        ChatCompletionRequest(
            model="nesty-combined-1.0",
            messages=[ChatMessage(role="user", content="latest news today")],
            search="auto",
            tools="off",
            semantic_recall="off",
            store=False,
        ),
    )
    assert response.choices[0].message.content == "Answer without live search results."
    assert "empty_answer" not in response.answer_quality.flags
