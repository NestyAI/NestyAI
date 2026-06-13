from __future__ import annotations

from app.core.retrieval_recovery import should_attempt_retrieval_fallback
from app.tools.freshness_intent import detect_freshness_intent


def test_recovery_skips_when_search_context_already_present() -> None:
    freshness = detect_freshness_intent("giá xăng hôm nay")
    decision = should_attempt_retrieval_fallback(
        freshness=freshness,
        search_already_used=True,
        search_context_present=True,
        high_confidence_tool_succeeded=False,
        tool_failures=[],
        ineligible_tool_reasons=[],
    )
    assert decision.should_run is False
    assert decision.reason_code == "search_already_present"


def test_recovery_skips_when_high_confidence_tool_succeeded() -> None:
    freshness = detect_freshness_intent("đổi 100 USD sang VND")
    decision = should_attempt_retrieval_fallback(
        freshness=freshness,
        search_already_used=False,
        search_context_present=False,
        high_confidence_tool_succeeded=True,
        tool_failures=[{"name": "exchange_rate", "error_code": "lookup_failed"}],
        ineligible_tool_reasons=[],
    )
    assert decision.should_run is False


def test_recovery_runs_for_fresh_query_with_tool_failure() -> None:
    freshness = detect_freshness_intent("giá dầu thế giới hôm nay")
    decision = should_attempt_retrieval_fallback(
        freshness=freshness,
        search_already_used=False,
        search_context_present=False,
        high_confidence_tool_succeeded=False,
        tool_failures=[{"name": "exchange_rate", "error_code": "lookup_failed"}],
        ineligible_tool_reasons=[],
    )
    assert decision.should_run is True
    assert decision.fallback_from_tool == "exchange_rate"


def test_recovery_runs_for_fresh_query_without_eligible_tool() -> None:
    freshness = detect_freshness_intent("giá xăng hiện tại ở Việt Nam")
    decision = should_attempt_retrieval_fallback(
        freshness=freshness,
        search_already_used=False,
        search_context_present=False,
        high_confidence_tool_succeeded=False,
        tool_failures=[],
        ineligible_tool_reasons=["commodity_not_fx"],
    )
    assert decision.should_run is True
