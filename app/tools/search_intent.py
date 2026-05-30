from __future__ import annotations

import re


_SEARCH_TERMS = [
    "latest",
    "newest",
    "today",
    "current",
    "recent",
    "now",
    "price",
    "weather",
    "news",
    "release",
    "version",
    "update",
    "changelog",
    "schedule",
    "event",
    "who is currently",
    "where is",
    "when is",
    "stock",
    "crypto",
    "exchange rate",
    "hôm nay",
    "mới nhất",
    "hiện tại",
    "bây giờ",
    "gần đây",
    "giá",
    "thời tiết",
    "tin tức",
    "lịch",
    "phiên bản",
    "cập nhật",
    "tỷ giá",
]

_NO_SEARCH_TERMS = [
    "write a poem",
    "viết thơ",
    "translate",
    "dịch câu này",
    "dịch sang",
    "tóm tắt đoạn văn",
    "summarize",
    "summarise",
    "casual chat",
    "trò chuyện",
    "introduce yourself",
    "hello",
    "how are you",
]

_HIGH_AGGRESSIVENESS_TERMS = [
    "compare",
    "comparison",
    "benchmark",
    "verify",
    "fact check",
    "documentation",
    "docs",
    "api reference",
    "breaking changes",
    "security advisory",
    "cve",
    "release notes",
    "best model",
]


def _has_search_signal(normalized: str, terms: list[str]) -> bool:
    for phrase in terms:
        if phrase in normalized:
            return True
    return False


def _is_direct_current_question(normalized: str) -> bool:
    return bool(re.search(r"\b(what|who|when|where).*(current|today|latest|now)\b", normalized))


def should_use_search(
    message: str,
    model_config: dict,
    explicit_search_mode: str | None = None,
) -> bool:
    explicit = (explicit_search_mode or "").strip().lower()
    if explicit == "off":
        return False
    if explicit == "on":
        return True

    model_search_mode = str(model_config.get("search_mode", "off")).strip().lower()
    if model_search_mode == "off":
        return False
    if model_search_mode != "auto":
        return False

    normalized = re.sub(r"\s+", " ", message.strip().lower())
    if not normalized:
        return False

    for phrase in _NO_SEARCH_TERMS:
        if phrase in normalized:
            return False

    aggressiveness = str(model_config.get("search_aggressiveness", "auto")).strip().lower()
    has_base_signal = _has_search_signal(normalized, _SEARCH_TERMS)
    has_current_question = _is_direct_current_question(normalized)
    if aggressiveness == "low":
        strong_terms = [
            "latest",
            "today",
            "current",
            "price",
            "weather",
            "news",
            "version",
            "update",
            "exchange rate",
            "mới nhất",
            "hôm nay",
            "hiện tại",
            "giá",
            "thời tiết",
            "tin tức",
            "phiên bản",
            "tỷ giá",
        ]
        return _has_search_signal(normalized, strong_terms) or has_current_question
    if aggressiveness == "high_when_needed":
        return has_base_signal or has_current_question or _has_search_signal(normalized, _HIGH_AGGRESSIVENESS_TERMS)

    return has_base_signal or has_current_question
