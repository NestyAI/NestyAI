from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.tools.freshness_intent import FreshnessDecision, detect_freshness_intent
from app.tools.package_version import extract_package_name
from app.tools.text_normalize import normalize_message_text
from app.tools.tool_intent_signals import (
    has_calculator_intent,
    has_exchange_intent,
    has_package_intent,
    has_weather_intent,
    has_wikipedia_intent,
)
from app.tools.tool_validation import validate_tool_args
from app.tools.validators.currency import (
    extract_exchange_request_with_validation,
    extract_validated_exchange_request,
    has_explicit_fx_intent,
)
from app.tools.weather import extract_weather_location
from app.tools.calculator import extract_calculator_expression

Confidence = Literal["high", "medium", "low"]

_RECOVERABLE_TOOL_ERRORS = frozenset(
    {
        "lookup_failed",
        "invalid_tool_args",
        "invalid_currency_code",
        "unsupported_currency",
        "provider_error",
        "unsupported_query",
        "no_results",
        "tool_timeout",
        "low_confidence_intent",
        "missing_location",
    }
)


@dataclass(slots=True)
class ToolIntentDecision:
    primary_tool: str | None = None
    fallback_tools: list[str] = field(default_factory=list)
    confidence: Confidence = "low"
    reason_code: str = "no_match"
    requires_freshness: bool = False
    extracted_args: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    eligible: bool = False


def _evaluate_exchange(message: str, freshness: FreshnessDecision) -> ToolIntentDecision:
    decision = ToolIntentDecision(primary_tool="exchange_rate", requires_freshness=freshness.requires_freshness)
    if freshness.commodity_or_market_price and not has_explicit_fx_intent(message):
        decision.reason_code = "commodity_not_fx"
        decision.confidence = "low"
        decision.eligible = False
        decision.warnings.append("freshness_query_not_fx")
        return decision
    if not has_explicit_fx_intent(message):
        decision.reason_code = "low_confidence_intent"
        decision.confidence = "low"
        decision.eligible = False
        return decision

    validated = extract_validated_exchange_request(message)
    if validated is not None:
        decision.confidence = "high"
        decision.eligible = True
        decision.reason_code = "matched_exchange_rate"
        decision.extracted_args = {
            "amount": validated.amount,
            "base": validated.base,
            "target": validated.target,
        }
        return decision

    _, validation = extract_exchange_request_with_validation(message)
    if validation and validation.error_code == "unsupported_currency":
        decision.reason_code = "unsupported_currency"
        decision.confidence = "medium"
        decision.eligible = False
        decision.warnings.append("iso_valid_provider_unsupported")
        return decision

    decision.reason_code = "exchange_pair_missing"
    decision.confidence = "medium"
    decision.eligible = False
    decision.warnings.append("fx_intent_without_valid_pair")
    return decision


def _evaluate_weather(message: str, normalized: str, freshness: FreshnessDecision) -> ToolIntentDecision:
    decision = ToolIntentDecision(primary_tool="weather_lookup", requires_freshness=freshness.requires_freshness)
    if not has_weather_intent(normalized):
        decision.reason_code = "no_match"
        return decision
    location = extract_weather_location(message, None)
    if location:
        decision.confidence = "high"
        decision.eligible = True
        decision.reason_code = "matched_weather_lookup"
        decision.extracted_args = {"location": location}
    else:
        decision.confidence = "medium"
        decision.reason_code = "weather_location_missing"
    return decision


def _evaluate_calculator(message: str, normalized: str, freshness: FreshnessDecision) -> ToolIntentDecision:
    decision = ToolIntentDecision(primary_tool="calculator", requires_freshness=freshness.requires_freshness)
    if freshness.commodity_or_market_price or freshness.news_or_current_events:
        decision.reason_code = "unsupported_query"
        return decision
    if not has_calculator_intent(message, normalized):
        return decision
    expression = extract_calculator_expression(message)
    if expression:
        decision.confidence = "high"
        decision.eligible = True
        decision.reason_code = "matched_calculator"
        decision.extracted_args = {"expression": expression}
    else:
        decision.confidence = "medium"
        decision.reason_code = "calculator_expression_missing"
    return decision


def _evaluate_package(message: str, normalized: str) -> ToolIntentDecision:
    decision = ToolIntentDecision(primary_tool="package_version_lookup")
    if not has_package_intent(normalized):
        return decision
    package = extract_package_name(message)
    if package:
        decision.confidence = "high"
        decision.eligible = True
        decision.reason_code = "matched_package_version_lookup"
        decision.extracted_args = {"package": package}
    else:
        decision.confidence = "medium"
        decision.reason_code = "package_name_missing"
    return decision


def _evaluate_wikipedia(normalized: str, freshness: FreshnessDecision) -> ToolIntentDecision:
    decision = ToolIntentDecision(primary_tool="wikipedia_lookup", requires_freshness=freshness.requires_freshness)
    if freshness.requires_freshness:
        decision.reason_code = "freshness_prefers_search"
        return decision
    if has_wikipedia_intent(normalized):
        decision.confidence = "medium"
        decision.eligible = True
        decision.reason_code = "matched_wikipedia_lookup"
    return decision


def route_tool_intents(message: str, allowed_tools: set[str]) -> list[ToolIntentDecision]:
    normalized = f" {normalize_message_text(message)} "
    freshness = detect_freshness_intent(message)
    candidates: list[ToolIntentDecision] = []

    if "exchange_rate" in allowed_tools:
        candidates.append(_evaluate_exchange(message, freshness))
    if "weather_lookup" in allowed_tools:
        candidates.append(_evaluate_weather(message, normalized, freshness))
    if "calculator" in allowed_tools:
        candidates.append(_evaluate_calculator(message, normalized, freshness))
    if "package_version_lookup" in allowed_tools:
        candidates.append(_evaluate_package(message, normalized))
    if "wikipedia_lookup" in allowed_tools:
        candidates.append(_evaluate_wikipedia(normalized, freshness))

    return candidates


def select_executable_tools(
    message: str,
    allowed_tools: set[str],
    max_tool_calls: int,
    *,
    aggressiveness: str = "auto",
) -> tuple[list[str], list[ToolIntentDecision], FreshnessDecision]:
    freshness = detect_freshness_intent(message)
    decisions = route_tool_intents(message, allowed_tools)
    selected: list[str] = []

    allowed_confidence = {"high"}
    if aggressiveness == "high_when_needed":
        allowed_confidence.add("medium")

    ranked = sorted(
        [
            d
            for d in decisions
            if d.primary_tool and d.eligible and d.confidence in allowed_confidence
        ],
        key=lambda item: 0 if item.confidence == "high" else 1,
    )
    for decision in ranked:
        tool = decision.primary_tool
        if not tool or tool in selected:
            continue
        validation = validate_tool_args(tool, message)
        if not validation.ok:
            decision.eligible = False
            decision.reason_code = validation.error_code or decision.reason_code
            continue
        selected.append(tool)
        if len(selected) >= max_tool_calls:
            break

    return selected, decisions, freshness


def _freshness_requires_web_search(
    freshness: FreshnessDecision,
    planned_tools: list[str],
    intent_decisions: list[ToolIntentDecision],
    message: str,
) -> bool:
    if not freshness.requires_freshness:
        return False
    if freshness.commodity_or_market_price or freshness.news_or_current_events:
        return True

    planned = set(planned_tools)
    normalized = f" {normalize_message_text(message)} "
    if "weather_lookup" in planned and has_weather_intent(normalized):
        high_weather = any(
            decision.primary_tool == "weather_lookup"
            and decision.eligible
            and decision.confidence == "high"
            for decision in intent_decisions
        )
        if high_weather or not intent_decisions:
            return False
    if "exchange_rate" in planned and has_explicit_fx_intent(message):
        high_exchange = any(
            decision.primary_tool == "exchange_rate"
            and decision.eligible
            and decision.confidence == "high"
            for decision in intent_decisions
        )
        if high_exchange:
            return False
    return True


def should_skip_web_search_for_tool_plan(
    planned_tools: list[str],
    intent_decisions: list[ToolIntentDecision],
    explicit_search_mode: str,
    message: str,
    freshness: FreshnessDecision,
) -> bool:
    if str(explicit_search_mode or "auto").strip().lower() == "on":
        return False
    if not planned_tools:
        return False

    if _freshness_requires_web_search(freshness, planned_tools, intent_decisions, message):
        return False

    if not intent_decisions:
        normalized = f" {normalize_message_text(message)} "
        planned = set(planned_tools)
        if has_weather_intent(normalized) and "weather_lookup" not in planned:
            return False
        if has_exchange_intent(message) and "exchange_rate" not in planned:
            return False
        if has_package_intent(normalized) and "package_version_lookup" not in planned:
            return False
        if has_wikipedia_intent(normalized) and "wikipedia_lookup" not in planned:
            return False
        if has_calculator_intent(message, normalized) and "calculator" not in planned:
            return False
        return True

    eligible_high = [
        d
        for d in intent_decisions
        if d.primary_tool in planned_tools and d.eligible and d.confidence == "high"
    ]
    if not eligible_high:
        return False

    normalized = f" {normalize_message_text(message)} "
    planned = set(planned_tools)
    if has_weather_intent(normalized) and "weather_lookup" not in planned:
        return False
    if has_exchange_intent(message) and "exchange_rate" not in planned:
        return False
    if has_package_intent(normalized) and "package_version_lookup" not in planned:
        return False
    if has_wikipedia_intent(normalized) and "wikipedia_lookup" not in planned:
        return False
    if has_calculator_intent(message, normalized) and "calculator" not in planned:
        return False
    return True


def is_recoverable_tool_error(error_code: str | None) -> bool:
    return str(error_code or "").strip().lower() in _RECOVERABLE_TOOL_ERRORS
