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

    for phrase in _SEARCH_TERMS:
        if phrase in normalized:
            return True

    # Direct "current status" style questions likely need search.
    if re.search(r"\b(what|who|when|where).*(current|today|latest|now)\b", normalized):
        return True

    return False
