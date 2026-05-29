from __future__ import annotations

import re

import pytest

from app.tools.exchange_rate import execute_exchange_rate, extract_exchange_request


def test_extract_exchange_request_en_vi() -> None:
    assert extract_exchange_request("1 USD to VND") == (1.0, "USD", "VND")
    assert extract_exchange_request("đổi 100 USD sang VND") == (100.0, "USD", "VND")


@pytest.mark.asyncio
async def test_exchange_rate_lookup_parses_mocked_api(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://api\.frankfurter\.app/latest.*"),
        json={
            "amount": 100.0,
            "base": "USD",
            "date": "2026-05-29",
            "rates": {"VND": 2550000.0},
        },
    )
    result = await execute_exchange_rate("đổi 100 USD sang VND", {"timeout_seconds": 5})
    assert result.success is True
    assert result.data is not None
    assert result.data["base"] == "USD"
    assert result.data["target"] == "VND"
    assert result.data["converted_amount"] == 2550000.0
    assert result.confidence == "high"


@pytest.mark.asyncio
async def test_exchange_rate_invalid_currency_rejected() -> None:
    result = await execute_exchange_rate("convert USDT to VND", {"timeout_seconds": 5})
    assert result.success is False
    assert result.error in {"invalid_currency_pair", "invalid_currency_code"}


@pytest.mark.asyncio
async def test_exchange_rate_api_failure_returns_failed_result(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://api\.frankfurter\.app/latest.*"),
        status_code=500,
        json={},
    )
    result = await execute_exchange_rate("1 USD to VND", {"timeout_seconds": 5})
    assert result.success is False
    assert result.error == "lookup_failed"

