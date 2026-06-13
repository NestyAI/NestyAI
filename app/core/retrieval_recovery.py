from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.freshness_intent import FreshnessDecision
from app.tools.intent_router import is_recoverable_tool_error


@dataclass(slots=True)
class RetrievalRecoveryDecision:
    should_run: bool
    reason_code: str | None = None
    fallback_from_tool: str | None = None


def should_attempt_retrieval_fallback(
    *,
    freshness: FreshnessDecision,
    search_already_used: bool,
    search_context_present: bool,
    high_confidence_tool_succeeded: bool,
    tool_failures: list[dict[str, Any]],
    ineligible_tool_reasons: list[str],
) -> RetrievalRecoveryDecision:
    if search_already_used or search_context_present:
        return RetrievalRecoveryDecision(should_run=False, reason_code="search_already_present")

    if high_confidence_tool_succeeded:
        return RetrievalRecoveryDecision(should_run=False, reason_code="specialized_tool_succeeded")

    recoverable_failures = [
        item for item in tool_failures if is_recoverable_tool_error(str(item.get("error_code") or item.get("error") or ""))
    ]
    if recoverable_failures:
        tool_name = str(recoverable_failures[0].get("name") or recoverable_failures[0].get("tool") or "")
        return RetrievalRecoveryDecision(
            should_run=True,
            reason_code=str(recoverable_failures[0].get("error_code") or recoverable_failures[0].get("error") or "tool_failed"),
            fallback_from_tool=tool_name or None,
        )

    if freshness.requires_freshness and ineligible_tool_reasons:
        return RetrievalRecoveryDecision(
            should_run=True,
            reason_code=ineligible_tool_reasons[0],
            fallback_from_tool=None,
        )

    if freshness.requires_freshness and not tool_failures:
        return RetrievalRecoveryDecision(should_run=True, reason_code="freshness_no_eligible_tool")

    return RetrievalRecoveryDecision(should_run=False, reason_code="not_needed")


def build_tool_failure_notice(tool_name: str, error_code: str | None) -> str:
    safe_code = str(error_code or "tool_failed").strip().lower()
    return (
        f"[Retrieval Notice]\n"
        f"Tool '{tool_name}' could not be used ({safe_code}). "
        f"Answer using available retrieval context or state that retrieval was unavailable."
    )


def build_retrieval_unavailable_notice(reason_code: str | None = None) -> str:
    safe_reason = str(reason_code or "retrieval_unavailable").strip().lower()
    return (
        "[Retrieval Notice]\n"
        "Current information could not be retrieved from web search. "
        f"Reason: {safe_reason}. Answer using existing knowledge and state retrieval limitations clearly."
    )
