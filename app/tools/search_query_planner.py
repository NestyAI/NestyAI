from __future__ import annotations

import re
import unicodedata

_MAX_QUERY_LEN = 120
_MIN_QUERY_WORDS = 2

_FILLER_PREFIXES = (
    "please ",
    "can you ",
    "could you ",
    "tell me ",
    "help me ",
    "i want to know ",
    "what is ",
    "what are ",
    "who is ",
    "when is ",
    "where is ",
    "how much is ",
    "ban co the ",
    "hay cho biet ",
    "cho minh hoi ",
    "minh muon biet ",
)


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _clean_query(text: str) -> str:
    cleaned = _normalize_text(text)
    cleaned = cleaned.strip(" ?!.,;:")
    lowered = cleaned.lower()
    for prefix in _FILLER_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            lowered = cleaned.lower()
    return cleaned[:_MAX_QUERY_LEN].strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _split_compound_question(message: str) -> list[str]:
    parts = re.split(r"\s*(?:\band\b|\bor\b|\?|\;)\s*", message, flags=re.IGNORECASE)
    cleaned_parts = [_clean_query(part) for part in parts if _clean_query(part)]
    return [part for part in cleaned_parts if _word_count(part) >= _MIN_QUERY_WORDS]


def plan_search_queries(message: str, *, max_queries: int = 3) -> list[str]:
    """Build 1-3 focused web search queries from a user message."""
    limit = max(1, min(int(max_queries), 3))
    primary = _clean_query(message)
    if not primary:
        return []

    queries: list[str] = []
    if _word_count(primary) >= _MIN_QUERY_WORDS:
        queries.append(primary)

    for part in _split_compound_question(message):
        if part not in queries:
            queries.append(part)
        if len(queries) >= limit:
            break

    if not queries and _word_count(primary) >= _MIN_QUERY_WORDS:
        queries.append(primary)

    if len(queries) < limit:
        current_info_variant = _current_info_variant(primary)
        if current_info_variant and current_info_variant not in queries:
            queries.append(current_info_variant)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(query)
        if len(deduped) >= limit:
            break

    return deduped[:limit]


def _current_info_variant(query: str) -> str | None:
    lowered = query.lower()
    markers = ("latest", "current", "today", "recent", "newest", "moi nhat", "hom nay", "hien tai")
    if not any(marker in lowered for marker in markers):
        return None
    stripped = re.sub(
        r"\b(please|can you|could you|tell me|help me)\b",
        "",
        query,
        flags=re.IGNORECASE,
    )
    stripped = _clean_query(stripped)
    if stripped and stripped.lower() != query.lower() and _word_count(stripped) >= _MIN_QUERY_WORDS:
        return stripped
    return None
