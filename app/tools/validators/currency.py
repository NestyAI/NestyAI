from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.tools.text_normalize import normalize_message_text


# ISO 4217 common codes (subset used by Gateway).
ISO_CURRENCY_CODES: frozenset[str] = frozenset(
    {
        "USD",
        "VND",
        "EUR",
        "JPY",
        "GBP",
        "AUD",
        "CAD",
        "CHF",
        "CNY",
        "SGD",
        "THB",
        "KRW",
        "INR",
        "IDR",
        "MYR",
        "PHP",
        "HKD",
        "NZD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "BGN",
        "HRK",
        "ISK",
        "MXN",
        "BRL",
        "ZAR",
        "TRY",
        "ILS",
        "RUB",
    }
)

# Frankfurter provider-supported codes (subset; both legs must be supported).
FRANKFURTER_SUPPORTED_CURRENCIES: frozenset[str] = frozenset(
    {
        "USD",
        "VND",
        "EUR",
        "JPY",
        "GBP",
        "AUD",
        "CAD",
        "CHF",
        "CNY",
        "SGD",
        "THB",
        "KRW",
        "INR",
        "IDR",
        "MYR",
        "PHP",
        "HKD",
        "NZD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "BGN",
        "HRK",
        "ISK",
        "MXN",
        "BRL",
        "ZAR",
        "TRY",
    }
)

# Vietnamese/English tokens that must never become currency codes.
_REJECTED_CURRENCY_TOKENS: frozenset[str] = frozenset(
    {
        "NAY",
        "NAM",
        "GIA",
        "HOM",
        "TAI",
        "VIE",
        "TRI",
        "GAS",
        "XAN",
        "TIN",
        "THE",
        "GIO",
        "BAY",
        "MOI",
        "HOM",
        "NAY",
        "TUC",
        "QUO",
        "TEK",
        "DOC",
        "AND",
        "FOR",
        "NOT",
        "ARE",
        "WAS",
        "HAD",
        "HAS",
        "CAN",
        "MAY",
        "NEW",
        "OLD",
        "TOP",
        "ALL",
        "DAY",
        "NOW",
    }
)

_FX_INTENT_TERMS = [
    "exchange rate",
    "ty gia",
    "doi tien",
    "convert ",
    "currency",
    " sang ",
    " to ",
    " bang bao nhieu",
    " equals ",
    "/vnd",
    "/usd",
    "/eur",
    "/jpy",
    "/gbp",
]

_FX_PAIR_PATTERN = re.compile(
    r"(?P<base>[A-Z]{3})\s*(?:/|\bto\b|\bsang\b|->)\s*(?P<target>[A-Z]{3})",
    flags=re.IGNORECASE,
)
_AMOUNT_CURRENCY_PATTERN = re.compile(
    r"(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<code>[A-Za-z$]{3})\s*(?:to|sang|->)\s*(?P<target>[A-Za-z]{3})",
    flags=re.IGNORECASE,
)
_DOLLAR_AMOUNT_PATTERN = re.compile(
    r"\$\s*(?P<amount>\d+(?:[.,]\d+)?)\s*(?:to|sang|->)\s*(?P<target>[A-Za-z]{3})",
    flags=re.IGNORECASE,
)
_WHITELIST_TOKEN_PATTERN = re.compile(r"\b([A-Z]{3})\b")


@dataclass(frozen=True, slots=True)
class ExchangeRequest:
    amount: float
    base: str
    target: str


@dataclass(frozen=True, slots=True)
class CurrencyValidationResult:
    ok: bool
    error_code: str | None = None
    iso_valid: bool = False
    provider_supported: bool = False


def _fx_pair_match_is_valid(base: str | None, target: str | None) -> bool:
    sanitized_base = _sanitize_code(base or "")
    sanitized_target = _sanitize_code(target or "")
    if not sanitized_base or not sanitized_target:
        return False
    return sanitized_base in ISO_CURRENCY_CODES and sanitized_target in ISO_CURRENCY_CODES


def has_explicit_fx_intent(message: str) -> bool:
    normalized = f" {normalize_message_text(message)} "
    if any(term in normalized for term in _FX_INTENT_TERMS):
        return True
    upper = message.upper()
    pair_match = _FX_PAIR_PATTERN.search(upper)
    if pair_match and _fx_pair_match_is_valid(pair_match.group("base"), pair_match.group("target")):
        return True
    if _AMOUNT_CURRENCY_PATTERN.search(message):
        return True
    if _DOLLAR_AMOUNT_PATTERN.search(message):
        return True
    if re.search(r"\b\d+\s*(usd|eur|gbp|jpy|vnd)\b", normalized):
        if re.search(r"\b(sang|to|->|bang bao nhieu)\b", normalized):
            return True
    return False


def _normalize_amount(text: str) -> float | None:
    cleaned = text.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def _sanitize_code(raw: str) -> str | None:
    code = str(raw or "").strip().upper().replace("$", "USD")
    if len(code) != 3 or not code.isalpha():
        return None
    if code in _REJECTED_CURRENCY_TOKENS:
        return None
    return code


def _is_iso_currency(code: str) -> bool:
    return code in ISO_CURRENCY_CODES


def _is_provider_supported(code: str) -> bool:
    return code in FRANKFURTER_SUPPORTED_CURRENCIES


def validate_currency_pair_for_provider(base: str, target: str) -> CurrencyValidationResult:
    base_u = base.upper()
    target_u = target.upper()
    if base_u in _REJECTED_CURRENCY_TOKENS or target_u in _REJECTED_CURRENCY_TOKENS:
        return CurrencyValidationResult(ok=False, error_code="invalid_currency_code", iso_valid=False)
    iso_base = _is_iso_currency(base_u)
    iso_target = _is_iso_currency(target_u)
    if not iso_base or not iso_target:
        return CurrencyValidationResult(
            ok=False,
            error_code="invalid_currency_code",
            iso_valid=iso_base or iso_target,
            provider_supported=False,
        )
    provider_base = _is_provider_supported(base_u)
    provider_target = _is_provider_supported(target_u)
    if not provider_base or not provider_target:
        return CurrencyValidationResult(
            ok=False,
            error_code="unsupported_currency",
            iso_valid=True,
            provider_supported=False,
        )
    return CurrencyValidationResult(ok=True, iso_valid=True, provider_supported=True)


def extract_validated_exchange_request(message: str) -> ExchangeRequest | None:
    if not has_explicit_fx_intent(message):
        return None

    text = " ".join(message.strip().split())
    upper = text.upper()

    amount = 1.0
    base: str | None = None
    target: str | None = None

    dollar_match = _DOLLAR_AMOUNT_PATTERN.search(text)
    if dollar_match:
        parsed_amount = _normalize_amount(dollar_match.group("amount"))
        if parsed_amount is not None:
            amount = parsed_amount
        base = "USD"
        target = _sanitize_code(dollar_match.group("target"))

    if base is None or target is None:
        amount_match = _AMOUNT_CURRENCY_PATTERN.search(text)
        if amount_match:
            parsed_amount = _normalize_amount(amount_match.group("amount"))
            if parsed_amount is not None:
                amount = parsed_amount
            raw_code = amount_match.group("code")
            base = _sanitize_code(raw_code)
            target = _sanitize_code(amount_match.group("target"))

    if base is None or target is None:
        pair_match = _FX_PAIR_PATTERN.search(upper)
        if pair_match:
            base = _sanitize_code(pair_match.group("base"))
            target = _sanitize_code(pair_match.group("target"))
            explicit_amount = re.search(r"(\d+(?:[.,]\d+)?)\s*[A-Za-z$]{3}", text, flags=re.IGNORECASE)
            if explicit_amount:
                parsed_amount = _normalize_amount(explicit_amount.group(1))
                if parsed_amount is not None:
                    amount = parsed_amount

    if base is None or target is None:
        whitelist_hits = [
            _sanitize_code(code)
            for code in _WHITELIST_TOKEN_PATTERN.findall(upper)
            if _sanitize_code(code) and _sanitize_code(code) in ISO_CURRENCY_CODES
        ]
        whitelist_hits = [code for code in whitelist_hits if code]
        if len(whitelist_hits) >= 2:
            base = whitelist_hits[0]
            target = whitelist_hits[1]
            explicit_amount = re.search(r"(\d+(?:[.,]\d+)?)", text)
            if explicit_amount:
                parsed_amount = _normalize_amount(explicit_amount.group(1))
                if parsed_amount is not None:
                    amount = parsed_amount

    if base is None or target is None:
        return None

    validation = validate_currency_pair_for_provider(base, target)
    if not validation.ok:
        return None

    return ExchangeRequest(amount=amount, base=base, target=target)


def extract_exchange_request_with_validation(
    message: str,
) -> tuple[ExchangeRequest | None, CurrencyValidationResult | None]:
    """Return parsed request and validation outcome (including unsupported ISO-valid codes)."""
    if not has_explicit_fx_intent(message):
        return None, CurrencyValidationResult(ok=False, error_code="low_confidence_intent")

    text = " ".join(message.strip().split())
    upper = text.upper()
    amount = 1.0
    base: str | None = None
    target: str | None = None

    for pattern in (_DOLLAR_AMOUNT_PATTERN, _AMOUNT_CURRENCY_PATTERN):
        match = pattern.search(text)
        if match:
            if "amount" in match.groupdict() and match.group("amount"):
                parsed_amount = _normalize_amount(match.group("amount"))
                if parsed_amount is not None:
                    amount = parsed_amount
            if pattern is _DOLLAR_AMOUNT_PATTERN:
                base = "USD"
                target = _sanitize_code(match.group("target"))
            else:
                base = _sanitize_code(match.group("code"))
                target = _sanitize_code(match.group("target"))
            break

    if base is None or target is None:
        pair_match = _FX_PAIR_PATTERN.search(upper)
        if pair_match:
            base = _sanitize_code(pair_match.group("base"))
            target = _sanitize_code(pair_match.group("target"))

    if base is None or target is None:
        whitelist_hits = [
            code
            for raw in _WHITELIST_TOKEN_PATTERN.findall(upper)
            if (code := _sanitize_code(raw)) and code in ISO_CURRENCY_CODES
        ]
        if len(whitelist_hits) >= 2:
            base = whitelist_hits[0]
            target = whitelist_hits[1]

    if base is None or target is None:
        return None, CurrencyValidationResult(ok=False, error_code="invalid_tool_args")

    validation = validate_currency_pair_for_provider(base, target)
    if not validation.ok:
        return None, validation
    return ExchangeRequest(amount=amount, base=base, target=target), validation
