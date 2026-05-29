from __future__ import annotations

from app.utils.cache_keys import make_tool_cache_key


def test_cache_key_same_params_same_key() -> None:
    a = make_tool_cache_key("weather_lookup", {"location": "Hanoi", "units": "metric"})
    b = make_tool_cache_key("weather_lookup", {"location": "Hanoi", "units": "metric"})
    assert a == b


def test_cache_key_param_order_irrelevant() -> None:
    a = make_tool_cache_key("exchange_rate", {"from": "USD", "to": "VND", "amount": 100})
    b = make_tool_cache_key("exchange_rate", {"amount": 100, "to": "VND", "from": "USD"})
    assert a == b


def test_cache_key_different_params_different_keys() -> None:
    a = make_tool_cache_key("exchange_rate", {"from": "USD", "to": "VND", "amount": 100})
    b = make_tool_cache_key("exchange_rate", {"from": "USD", "to": "EUR", "amount": 100})
    assert a != b


def test_cache_key_redacts_secret_fields_from_identity() -> None:
    a = make_tool_cache_key("demo", {"query": "x", "api_key": "secret1"})
    b = make_tool_cache_key("demo", {"query": "x", "api_key": "secret2"})
    # secret values should not affect hash identity
    assert a == b

