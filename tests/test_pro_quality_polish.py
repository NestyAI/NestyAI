from __future__ import annotations

import pytest
from typing import Any

from app.schemas.chat import ChatMessage, ChatCompletionRequest, PlannerInfo, RetrievalInfo
from app.core.multi_model_orchestrator import NestyProMultiModelOrchestrator
from tests.test_nesty_pro_orchestration import _build_orchestrator, _ProRouter


def test_planner_role_receives_compact_inventory() -> None:
    # Set up retrieval and planner metadata objects
    retrieval = RetrievalInfo(
        context_used=True,
        context_sources=["fts", "semantic_recall"],
        context_items_count=3,
        context_truncated=True,
    )
    planner_meta = PlannerInfo(
        search_decision="memory_context_sufficient",
        tool_decision="no_tool_needed",
        clarification_needed=False,
    )
    context_meta = {
        "retrieval": retrieval,
        "planner": planner_meta,
    }

    messages = NestyProMultiModelOrchestrator._build_role_messages(
        role="planner",
        user_message="Find current weather information",
        context_summary="VERY LONG DETAILED RETRIEVED CONTEXT EVIDENCE BLOCK",
        outputs={},
        context_metadata=context_meta,
    )

    user_content = next(m.content for m in messages if m.role == "user")
    # Compact inventory should not contain the detailed context summary
    assert "VERY LONG DETAILED RETRIEVED CONTEXT" not in user_content
    # Compact inventory must contain source names and counts
    assert "TASK FRAMING & INVENTORY" in user_content
    assert "fts, semantic_recall" in user_content
    assert "Context Items Count: 3" in user_content
    assert "Context is Truncated: Yes" in user_content
    assert "Search Decision: memory_context_sufficient" in user_content


def test_role_messages_inject_planner_guides() -> None:
    planner_meta = PlannerInfo(
        search_decision="memory_context_sufficient",
        search_planned=True,
        search_used=False,
        tool_decision="tool_selected",
        clarification_needed=True,
        clarification_reason="weather_location_missing",
    )
    context_meta = {
        "planner": planner_meta,
    }

    messages = NestyProMultiModelOrchestrator._build_role_messages(
        role="finalizer",
        user_message="Tell me the weather",
        context_summary="Safe context summary text",
        outputs={},
        context_metadata=context_meta,
    )

    system_msgs = [m.content for m in messages if m.role == "system"]
    combined_instruction = "\n".join(system_msgs)

    # Key guidelines should be injected
    assert "weather_location_missing" in combined_instruction
    assert "memory context is sufficient" in combined_instruction
    assert "Web search was planned but NOT used" in combined_instruction


def test_critic_receives_draft_and_evidence_summary() -> None:
    retrieval = RetrievalInfo(
        context_used=True,
        context_sources=["fts", "search"],
        context_items_count=2,
    )
    context_meta = {"retrieval": retrieval}
    outputs = {"researcher": "This is a detailed draft answer prepared by the researcher."}

    messages = NestyProMultiModelOrchestrator._build_role_messages(
        role="critic",
        user_message="test query",
        context_summary="A very long full context summary text that shouldn't be duplicated",
        outputs=outputs,
        context_metadata=context_meta,
    )

    user_content = next(m.content for m in messages if m.role == "user")
    # Critic should receive the draft answer and checklist, not the full context_summary
    assert "A very long full context summary text" not in user_content
    assert "VERIFICATION CHECKLIST & EVIDENCE SUMMARY" in user_content
    assert "fts, search" in user_content
    assert "This is a detailed draft answer" in user_content


def test_finalizer_receives_capped_notes() -> None:
    long_researcher = "Draft: " + ("abc " * 1000)
    outputs = {
        "planner": "Plan notes",
        "critic": "Critique feedback",
        "researcher": long_researcher,
    }

    messages = NestyProMultiModelOrchestrator._build_role_messages(
        role="finalizer",
        user_message="test query",
        context_summary="Context summary evidence block",
        outputs=outputs,
        context_metadata=None,
    )

    user_content = next(m.content for m in messages if m.role == "user")
    # Outputs should be structured with tags and capped
    assert "[Orchestration Note: Planner Plan]" in user_content
    assert "[Orchestration Note: Critic Feedback]" in user_content
    assert "[Orchestration Note: Draft Candidate Answer]" in user_content
    assert len(user_content) < 5000  # Defensive length capping check


@pytest.mark.asyncio
async def test_orchestrator_synthesis_returns_additive_metadata() -> None:
    router = _ProRouter()
    orchestrator = _build_orchestrator(router)
    request = ChatCompletionRequest(
        model="nesty-pro-1.0",
        messages=[ChatMessage(role="user", content="Analyze debug plan architecture and verify comparison")],
        search="off",
        tools="off",
        stream=False,
    )
    response = await orchestrator.create_chat_completion("req_pro_meta_test", request)
    assert response.orchestration is not None
    # Additive orchestration fields must be populated
    assert response.orchestration.used is True
    assert response.orchestration.evidence_sources_used == []
    assert response.orchestration.planner_metadata_used is True
    assert response.orchestration.retrieval_metadata_used is True
    assert response.orchestration.quality_guard_applied is True
    assert response.orchestration.pro_context_budget_chars is not None
    assert response.orchestration.pro_context_truncated is False
