from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.schemas.tools import ToolResult
from app.tools.validators.currency import (
    ExchangeRequest,
    extract_exchange_request_with_validation,
    extract_validated_exchange_request,
    validate_currency_pair_for_provider,
)


def extract_exchange_request(message: str) -> tuple[float, str, str] | None:
    """Backward-compatible extractor; requires explicit FX intent and validated ISO/provider codes."""
    parsed = extract_validated_exchange_request(message)
    if parsed is None:
        return None
    return parsed.amount, parsed.base, parsed.target


async def execute_exchange_rate(message: str, context: dict[str, Any] | None = None) -> ToolResult:
    started = time.perf_counter()
    timeout_seconds = float((context or {}).get("timeout_seconds", 6))

    request, validation = extract_exchange_request_with_validation(message)
    if request is None:
        error = "invalid_currency_pair"
        if validation and validation.error_code:
            error = validation.error_code
        return ToolResult(
            name="exchange_rate",
            success=False,
            content="Could not parse a valid currency pair for exchange lookup.",
            error=error,
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    amount, base, target = request.amount, request.base, request.target
    pair_check = validate_currency_pair_for_provider(base, target)
    if not pair_check.ok:
        return ToolResult(
            name="exchange_rate",
            success=False,
            content="Currency pair is not supported by the exchange provider.",
            error=pair_check.error_code or "invalid_currency_code",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    query_params = {"from": base, "to": target, "amount": amount}
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get("https://api.frankfurter.app/latest", params=query_params)
            if response.status_code >= 400:
                raise ValueError("lookup_failed")
            payload = response.json()
    except Exception:
        return ToolResult(
            name="exchange_rate",
            success=False,
            content="Exchange rate lookup is temporarily unavailable.",
            error="lookup_failed",
            data={"base": base, "target": target, "amount": amount, "provider": "frankfurter"},
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    rates = payload.get("rates", {})
    if target not in rates:
        return ToolResult(
            name="exchange_rate",
            success=False,
            content="Target currency was not returned by provider.",
            error="invalid_currency_code",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    converted_amount = float(rates[target])
    rate = converted_amount / amount if amount else 0.0
    date = str(payload.get("date", ""))

    content = (
        f"Base: {base}\n"
        f"Target: {target}\n"
        f"Amount: {amount}\n"
        f"Rate: {rate}\n"
        f"Converted: {converted_amount}\n"
        f"Date: {date}\n"
        f"Source: frankfurter"
    )
    return ToolResult(
        name="exchange_rate",
        success=True,
        content=content,
        data={
            "base": base,
            "target": target,
            "amount": amount,
            "rate": rate,
            "converted_amount": converted_amount,
            "date": date,
            "provider": "frankfurter",
        },
        sources=[
            {
                "title": f"Frankfurter {base}->{target}",
                "url": "https://api.frankfurter.app",
                "snippet": f"{amount} {base} = {converted_amount} {target}",
            }
        ],
        confidence="high",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
