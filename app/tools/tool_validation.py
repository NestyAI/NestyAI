from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.calculator import extract_calculator_expression
from app.tools.freshness_intent import detect_freshness_intent
from app.tools.tool_intent_signals import (
    has_calculator_intent,
    has_exchange_intent,
    has_package_intent,
    has_weather_intent,
    has_wikipedia_intent,
)
from app.tools.package_version import extract_package_name
from app.tools.text_normalize import normalize_message_text
from app.tools.validators.currency import (
    extract_exchange_request_with_validation,
    extract_validated_exchange_request,
    validate_currency_pair_for_provider,
)
from app.tools.weather import extract_weather_location


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    error_code: str | None = None
    extracted_args: dict[str, Any] | None = None


def validate_tool_args(tool_name: str, message: str) -> ValidationResult:
    normalized = f" {normalize_message_text(message)} "
    freshness = detect_freshness_intent(message)

    if tool_name == "exchange_rate":
        if not has_exchange_intent(message):
            return ValidationResult(ok=False, error_code="low_confidence_intent")
        request, validation = extract_exchange_request_with_validation(message)
        if request is not None:
            return ValidationResult(
                ok=True,
                extracted_args={"amount": request.amount, "base": request.base, "target": request.target},
            )
        if validation and validation.error_code == "unsupported_currency":
            return ValidationResult(ok=False, error_code="unsupported_currency")
        return ValidationResult(ok=False, error_code="invalid_currency_code")

    if tool_name == "weather_lookup":
        if not has_weather_intent(normalized):
            return ValidationResult(ok=False, error_code="low_confidence_intent")
        location = extract_weather_location(message, None)
        if not location:
            return ValidationResult(ok=False, error_code="missing_location")
        return ValidationResult(ok=True, extracted_args={"location": location})

    if tool_name == "calculator":
        if freshness.commodity_or_market_price or freshness.news_or_current_events:
            return ValidationResult(ok=False, error_code="unsupported_query")
        if not has_calculator_intent(message, normalized):
            return ValidationResult(ok=False, error_code="low_confidence_intent")
        expression = extract_calculator_expression(message)
        if not expression:
            return ValidationResult(ok=False, error_code="invalid_tool_args")
        return ValidationResult(ok=True, extracted_args={"expression": expression})

    if tool_name == "package_version_lookup":
        package = extract_package_name(message)
        if not package:
            return ValidationResult(ok=False, error_code="invalid_tool_args")
        return ValidationResult(ok=True, extracted_args={"package": package})

    if tool_name == "wikipedia_lookup":
        if freshness.requires_freshness:
            return ValidationResult(ok=False, error_code="unsupported_query")
        return ValidationResult(ok=True, extracted_args={})

    return ValidationResult(ok=False, error_code="unsupported_query")


def preflight_exchange_rate(message: str) -> ValidationResult:
    return validate_tool_args("exchange_rate", message)
