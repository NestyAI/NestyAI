from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.schemas.tools import ToolResult


_CURRENCY_PATTERN = re.compile(r"\b([A-Za-z]{3})\b")
_AMOUNT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)")


def _normalize_amount(text: str) -> float | None:
    cleaned = text.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_exchange_request(message: str) -> tuple[float, str, str] | None:
    text = " ".join(message.strip().split())
    if not text:
        return None

    upper = text.upper()
    currencies = _CURRENCY_PATTERN.findall(upper)
    if len(currencies) < 2:
        return None

    base = currencies[0].upper()
    target = currencies[1].upper()
    if not (len(base) == 3 and len(target) == 3):
        return None

    amount = 1.0
    # e.g. "100 USD to VND", "đổi 100 usd sang vnd"
    explicit_amount_match = re.search(r"(\d+(?:[.,]\d+)?)\s*[A-Za-z]{3}", upper)
    if explicit_amount_match:
        parsed = _normalize_amount(explicit_amount_match.group(1))
        if parsed is not None:
            amount = parsed
    else:
        first_num = _AMOUNT_PATTERN.search(text)
        if first_num:
            parsed = _normalize_amount(first_num.group(1))
            if parsed is not None:
                amount = parsed

    if amount <= 0:
        return None
    return amount, base, target


async def execute_exchange_rate(message: str, context: dict[str, Any] | None = None) -> ToolResult:
    started = time.perf_counter()
    timeout_seconds = float((context or {}).get("timeout_seconds", 6))
    parsed = extract_exchange_request(message)
    if not parsed:
        return ToolResult(
            name="exchange_rate",
            success=False,
            content="Could not parse currency pair and amount.",
            error="invalid_currency_pair",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    amount, base, target = parsed
    if not (base.isalpha() and target.isalpha() and len(base) == 3 and len(target) == 3):
        return ToolResult(
            name="exchange_rate",
            success=False,
            content="Invalid currency code format.",
            error="invalid_currency_code",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    query_params = {"from": base, "to": target, "amount": amount}
    source_url = f"https://api.frankfurter.app/latest?{urlencode(query_params)}"
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
        f"Source: {source_url}"
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
            "source_url": source_url,
        },
        sources=[
            {
                "title": f"Frankfurter {base}->{target}",
                "url": source_url,
                "snippet": f"{amount} {base} = {converted_amount} {target}",
            }
        ],
        confidence="high",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )

