from __future__ import annotations

import pytest

from app.tools.freshness_intent import detect_freshness_intent
from app.tools.intent_router import route_tool_intents, select_executable_tools
from app.tools.planner import plan_tools_decision
from app.tools.exchange_rate import extract_exchange_request
from app.tools.validators.currency import (
    FRANKFURTER_SUPPORTED_CURRENCIES,
    ISO_CURRENCY_CODES,
    extract_validated_exchange_request,
    validate_currency_pair_for_provider,
)


@pytest.mark.parametrize(
    "message",
    [
        "giá xăng hiện tại ở Việt Nam",
        "giá dầu thế giới hôm nay",
        "giá vàng hôm nay",
        "current gasoline prices Vietnam",
    ],
)
def test_fuel_price_queries_do_not_extract_exchange(message: str) -> None:
    assert extract_exchange_request(message) is None
    assert extract_validated_exchange_request(message) is None


@pytest.mark.parametrize(
    "token",
    ["NAY", "NAM", "GIA", "HOM", "TAI"],
)
def test_rejected_currency_tokens_blocked(token: str) -> None:
    result = validate_currency_pair_for_provider("USD", token)
    assert result.ok is False
    assert result.error_code == "invalid_currency_code"


def test_hom_nay_and_viet_nam_do_not_parse_as_currency_pair() -> None:
    assert extract_exchange_request("hôm nay Việt Nam") is None
    assert extract_exchange_request("tỷ giá hôm nay") is None
    assert extract_exchange_request("weather in Hanoi today") is None


def test_weather_today_skips_web_search_when_weather_tool_planned() -> None:
    from app.tools.planner import should_skip_web_search_for_tools

    model_config = {
        "allowed_tools": ["weather_lookup", "exchange_rate"],
        "max_tool_calls": 2,
        "tool_aggressiveness": "auto",
    }
    decision = plan_tools_decision("weather in Hanoi today", model_config)
    assert "weather_lookup" in decision.tools_planned
    assert should_skip_web_search_for_tools(decision, "auto", "weather in Hanoi today") is True


@pytest.mark.parametrize(
    "message,expected",
    [
        ("đổi 100 USD sang VND", (100.0, "USD", "VND")),
        ("tỷ giá USD/VND hôm nay", (1.0, "USD", "VND")),
        ("1 EUR bằng bao nhiêu VND", (1.0, "EUR", "VND")),
        ("convert 50 usd to jpy", (50.0, "USD", "JPY")),
        ("exchange rate USD to VND", (1.0, "USD", "VND")),
    ],
)
def test_explicit_fx_queries_still_work(message: str, expected: tuple[float, str, str]) -> None:
    parsed = extract_exchange_request(message)
    assert parsed == expected


def test_iso_valid_but_provider_unsupported() -> None:
    # ISO list is broader than Frankfurter support in tests; use a code outside provider set if present.
    unsupported = next((code for code in ISO_CURRENCY_CODES if code not in FRANKFURTER_SUPPORTED_CURRENCIES), None)
    if unsupported is None:
        pytest.skip("No ISO-only currency difference configured")
    result = validate_currency_pair_for_provider("USD", unsupported)
    assert result.iso_valid is True
    assert result.provider_supported is False
    assert result.error_code == "unsupported_currency"


def test_freshness_detects_fuel_price_vi() -> None:
    decision = detect_freshness_intent("giá xăng hiện tại ở Việt Nam")
    assert decision.requires_freshness is True
    assert decision.commodity_or_market_price is True


def test_intent_router_rejects_exchange_for_fuel_query() -> None:
    decisions = route_tool_intents("giá xăng hiện tại ở Việt Nam", {"exchange_rate", "calculator"})
    exchange = next(item for item in decisions if item.primary_tool == "exchange_rate")
    assert exchange.eligible is False


def test_planner_auto_does_not_select_exchange_for_fuel_query() -> None:
    model_config = {
        "allowed_tools": ["exchange_rate", "calculator", "weather_lookup"],
        "max_tool_calls": 3,
        "tool_aggressiveness": "auto",
    }
    decision = plan_tools_decision("giá xăng hiện tại ở Việt Nam", model_config)
    assert "exchange_rate" not in decision.tools_planned
    assert decision.retrieval_required is True


def test_weather_positive_and_fuel_negative() -> None:
    model_config = {
        "allowed_tools": ["weather_lookup", "exchange_rate"],
        "max_tool_calls": 2,
        "tool_aggressiveness": "auto",
    }
    weather = plan_tools_decision("thời tiết Hà Nội hôm nay", model_config)
    assert "weather_lookup" in weather.tools_planned
    fuel = plan_tools_decision("giá xăng hôm nay", model_config)
    assert "weather_lookup" not in fuel.tools_planned


def test_calculator_positive_and_price_number_negative() -> None:
    model_config = {
        "allowed_tools": ["calculator", "exchange_rate"],
        "max_tool_calls": 2,
        "tool_aggressiveness": "auto",
    }
    calc = plan_tools_decision("tính 15% của 200", model_config)
    assert "calculator" in calc.tools_planned
    price = plan_tools_decision("giá xăng 25000 hôm nay", model_config)
    assert "calculator" not in price.tools_planned
