from __future__ import annotations

from app.tools.calculator import extract_calculator_expression
from app.tools.text_normalize import normalize_message_text
from app.tools.validators.currency import has_explicit_fx_intent

_PACKAGE_INTENT_TERMS = [
    "latest version",
    "release",
    "changelog",
    "npm",
    "pypi",
    "pip",
    "package",
    "phan ban",
    "ban moi nhat",
]

_WEATHER_INTENT_TERMS = [
    "weather",
    "thoi tiet",
    "forecast",
    "du bao",
    "temperature",
    "nhiet do",
    "rain",
    " mua ",
]

_WIKIPEDIA_INTENT_TERMS = [
    "what is",
    "who is",
    "define",
    "definition",
    "la gi",
    "dinh nghia",
    "khai niem",
    "ai la",
]

_REPO_OR_CODE_TERMS = [
    "repo",
    "repository",
    "project",
    "local",
    "file",
    "code",
    "bug",
    "error",
    "traceback",
    "stack trace",
    "debug",
    "troubleshoot",
    "fix",
]


def has_exchange_intent(message: str) -> bool:
    return has_explicit_fx_intent(message)


def has_weather_intent(normalized: str) -> bool:
    return any(term in normalized for term in _WEATHER_INTENT_TERMS)


def has_package_intent(normalized: str) -> bool:
    return any(term in normalized for term in _PACKAGE_INTENT_TERMS)


def has_wikipedia_intent(normalized: str) -> bool:
    if any(term in normalized for term in _REPO_OR_CODE_TERMS):
        return False
    return any(term in normalized for term in _WIKIPEDIA_INTENT_TERMS)


def has_calculator_intent(message: str, normalized: str | None = None) -> bool:
    norm = normalized if normalized is not None else f" {normalize_message_text(message)} "
    if extract_calculator_expression(message):
        return True
    if "tinh " in norm or norm.strip().startswith("tinh "):
        if any(op in message for op in "+-*/%()"):
            return True
    if " of " in norm and any(ch.isdigit() for ch in message):
        return True
    return False
