from __future__ import annotations

from dataclasses import dataclass, field

from app.tools.freshness_intent import FreshnessDecision, detect_freshness_intent
from app.tools.intent_router import (
    ToolIntentDecision,
    route_tool_intents,
    select_executable_tools,
    should_skip_web_search_for_tool_plan,
)
from app.tools.text_normalize import normalize_message_text
from app.tools.tool_intent_signals import (
    has_calculator_intent,
    has_exchange_intent,
    has_package_intent,
    has_weather_intent,
    has_wikipedia_intent,
)
from app.tools.calculator import extract_calculator_expression
from app.tools.exchange_rate import extract_exchange_request
from app.tools.package_version import extract_package_name
from app.tools.weather import extract_weather_location


@dataclass(slots=True)
class ToolPlanDecision:
    decision: str = "unknown"
    tools_planned: list[str] = field(default_factory=list)
    reason: str | None = None
    clarification_needed: bool = False
    clarification_reason: str | None = None
    intent_decisions: list[ToolIntentDecision] = field(default_factory=list)
    requires_freshness: bool = False
    tool_intent_confidence: str | None = None
    retrieval_required: bool = False


_DETERMINISTIC_TOOLS = frozenset(
    {
        "calculator",
        "weather_lookup",
        "exchange_rate",
        "package_version_lookup",
        "wikipedia_lookup",
    }
)


def _tool_match_reason(tools: list[str]) -> str:
    if not tools:
        return "no_deterministic_tool_intent"
    if len(tools) == 1:
        return f"matched_{tools[0]}"
    return "matched_multiple_tools"


def _normalize_text(text: str) -> str:
    return normalize_message_text(text)


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def should_skip_web_search_for_tools(
    tool_plan: ToolPlanDecision,
    explicit_search_mode: str,
    message: str = "",
) -> bool:
    freshness = detect_freshness_intent(message) if message.strip() else FreshnessDecision(
        requires_freshness=tool_plan.requires_freshness
    )
    return should_skip_web_search_for_tool_plan(
        tool_plan.tools_planned,
        tool_plan.intent_decisions,
        explicit_search_mode,
        message,
        freshness,
    )


def _missing_required_tool_reason(message: str, normalized: str, allowed_tools: set[str]) -> str | None:
    if "calculator" in allowed_tools and has_calculator_intent(message, normalized) and not extract_calculator_expression(message):
        return "calculator_expression_missing"
    if "weather_lookup" in allowed_tools and has_weather_intent(normalized) and not extract_weather_location(message, None):
        return "weather_location_missing"
    if "exchange_rate" in allowed_tools and has_exchange_intent(message) and extract_exchange_request(message) is None:
        return "exchange_pair_missing"
    if "package_version_lookup" in allowed_tools and has_package_intent(normalized) and not extract_package_name(message):
        return "package_name_missing"
    if "wikipedia_lookup" in allowed_tools and has_wikipedia_intent(normalized) and not has_wikipedia_intent(normalized):
        return "wikipedia_entity_missing"
    return None


def _plan_with_router(
    message: str,
    allowed_tools: set[str],
    max_tool_calls: int,
    aggressiveness: str = "auto",
) -> ToolPlanDecision:
    planned, intent_decisions, freshness = select_executable_tools(
        message,
        allowed_tools,
        max_tool_calls,
        aggressiveness=aggressiveness,
    )
    normalized = f" {_normalize_text(message)} "
    missing_reason = _missing_required_tool_reason(message, normalized, allowed_tools)
    confidence = None
    if planned:
        for decision in intent_decisions:
            if decision.primary_tool in planned:
                confidence = decision.confidence
                break

    if planned:
        return ToolPlanDecision(
            decision="tool_selected",
            tools_planned=planned,
            reason=_tool_match_reason(planned),
            clarification_needed=bool(missing_reason),
            clarification_reason=missing_reason,
            intent_decisions=intent_decisions,
            requires_freshness=freshness.requires_freshness,
            tool_intent_confidence=confidence,
            retrieval_required=freshness.requires_freshness,
        )

    if missing_reason:
        return ToolPlanDecision(
            decision="missing_required_parameters",
            tools_planned=[],
            reason=missing_reason,
            clarification_needed=True,
            clarification_reason=missing_reason,
            intent_decisions=intent_decisions,
            requires_freshness=freshness.requires_freshness,
            retrieval_required=freshness.requires_freshness,
        )

    return ToolPlanDecision(
        decision="no_tool_needed",
        tools_planned=[],
        reason="no_deterministic_tool_intent",
        intent_decisions=intent_decisions,
        requires_freshness=freshness.requires_freshness,
        retrieval_required=freshness.requires_freshness,
    )


def _detect_tools_with_validation(message: str, model_config: dict, explicit_tools: str | list[str] | None = None) -> ToolPlanDecision:
    allowed_tools = set(model_config.get("allowed_tools", []))
    max_tool_calls = int(model_config.get("max_tool_calls", 0))
    if max_tool_calls <= 0:
        return ToolPlanDecision(decision="forced_off", tools_planned=[], reason="max_tool_calls_disabled")

    explicit: str | list[str] | None = explicit_tools
    if isinstance(explicit, str):
        mode = explicit.strip().lower()
        if mode == "off":
            return ToolPlanDecision(decision="forced_off", tools_planned=[], reason="forced_off")
        if mode not in {"auto", ""}:
            return ToolPlanDecision(decision="unknown", tools_planned=[], reason="unknown_tools_mode")

    if isinstance(explicit, list):
        planned = [str(name) for name in explicit if str(name) in allowed_tools]
        planned = _dedupe_preserve(planned)[:max_tool_calls]
        freshness = detect_freshness_intent(message)
        if planned:
            return ToolPlanDecision(
                decision="tool_selected",
                tools_planned=planned,
                reason=_tool_match_reason(planned),
                intent_decisions=route_tool_intents(message, set(planned)),
                requires_freshness=freshness.requires_freshness,
                retrieval_required=freshness.requires_freshness,
            )
        return ToolPlanDecision(decision="explicit_tools_no_match", tools_planned=[], reason="explicit_tools_no_match")

    aggressiveness = str(model_config.get("tool_aggressiveness", "auto")).strip().lower()
    return _plan_with_router(message, allowed_tools, max_tool_calls, aggressiveness=aggressiveness)


def plan_tools(
    message: str,
    model_config: dict,
    explicit_tools: str | list[str] | None = None,
) -> list[str]:
    return plan_tools_decision(message, model_config, explicit_tools=explicit_tools).tools_planned


def plan_tools_decision(
    message: str,
    model_config: dict,
    explicit_tools: str | list[str] | None = None,
) -> ToolPlanDecision:
    return _detect_tools_with_validation(message, model_config, explicit_tools=explicit_tools)
