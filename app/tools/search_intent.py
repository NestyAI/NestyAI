from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(slots=True)
class SearchPlanDecision:
    decision: str = "unknown"
    should_use: bool = False
    reason: str | None = None
    search_planned: bool = False
    current_info_needed: bool = False
    memory_context_sufficient: bool = False


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
    "hom nay",
    "moi nhat",
    "hien tai",
    "bay gio",
    "gan day",
    "gia",
    "thoi tiet",
    "tin tuc",
    "lich",
    "phien ban",
    "cap nhat",
    "ty gia",
    "status",
]

_NO_SEARCH_TERMS = [
    "write a poem",
    "viet tho",
    "translate",
    "dich cau nay",
    "dich sang",
    "tom tat doan van",
    "summarize",
    "summarise",
    "casual chat",
    "tro chuyen",
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

_FOLLOWUP_TERMS = [
    "previous",
    "earlier",
    "that one",
    "that thing",
    "the one above",
    "same thing",
    "follow up",
    "followup",
    "truoc do",
    "hoi nay",
    "vua roi",
    "phan do",
    "cai do",
    "nhu da noi",
]

_STABLE_KNOWLEDGE_TERMS = [
    "why",
    "how",
    "explain",
    "compare",
    "difference",
    "debug",
    "fix",
    "error",
    "bug",
    "code",
    "function",
    "class",
    "api",
    "json",
    "sql",
    "python",
    "fastapi",
    "asyncio",
    "regex",
    "thread",
    "algorithm",
    "architecture",
    "troubleshoot",
]


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized.lower()).strip()
    return normalized


def _has_search_signal(normalized: str, terms: list[str]) -> bool:
    return any(phrase in normalized for phrase in terms)


def _is_direct_current_question(normalized: str) -> bool:
    return bool(re.search(r"\b(what|who|when|where|which|how)\b.*\b(current|today|latest|now|recent|price|weather|news|version|update|schedule|status)\b", normalized))


def _has_stable_knowledge_signal(normalized: str) -> bool:
    return any(term in normalized for term in _STABLE_KNOWLEDGE_TERMS)


def _has_followup_signal(normalized: str) -> bool:
    return any(term in normalized for term in _FOLLOWUP_TERMS)


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

    normalized = _normalize_text(message)
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
            "moi nhat",
            "hom nay",
            "hien tai",
            "gia",
            "thoi tiet",
            "tin tuc",
            "phien ban",
            "ty gia",
        ]
        return _has_search_signal(normalized, strong_terms) or has_current_question
    if aggressiveness == "high_when_needed":
        return has_base_signal or has_current_question or _has_search_signal(normalized, _HIGH_AGGRESSIVENESS_TERMS)

    return has_base_signal or has_current_question


def plan_search_intent(
    message: str,
    model_config: dict,
    explicit_search_mode: str | None = None,
    *,
    memory_context_available: bool = False,
) -> SearchPlanDecision:
    explicit = (explicit_search_mode or "").strip().lower()
    if explicit == "off":
        return SearchPlanDecision(decision="forced_off", should_use=False, reason="forced_off", search_planned=False)
    if explicit == "on":
        return SearchPlanDecision(decision="forced_on", should_use=True, reason="forced_on", search_planned=True)

    model_search_mode = str(model_config.get("search_mode", "off")).strip().lower()
    if model_search_mode == "off":
        return SearchPlanDecision(decision="forced_off", should_use=False, reason="model_search_off", search_planned=False)
    if model_search_mode != "auto":
        return SearchPlanDecision(decision="unknown", should_use=False, reason="unknown_search_mode", search_planned=False)

    normalized = _normalize_text(message)
    if not normalized:
        return SearchPlanDecision(decision="no_search_needed", should_use=False, reason="empty_message", search_planned=False)

    for phrase in _NO_SEARCH_TERMS:
        if phrase in normalized:
            return SearchPlanDecision(decision="no_search_needed", should_use=False, reason="no_search_signal", search_planned=False)

    if memory_context_available and _has_followup_signal(normalized) and not _has_search_signal(normalized, _SEARCH_TERMS):
        return SearchPlanDecision(
            decision="memory_context_sufficient",
            should_use=False,
            reason="memory_followup",
            search_planned=False,
            memory_context_sufficient=True,
        )

    aggressiveness = str(model_config.get("search_aggressiveness", "auto")).strip().lower()
    has_current_question = _is_direct_current_question(normalized)
    has_base_signal = _has_search_signal(normalized, _SEARCH_TERMS)
    has_high_signal = _has_search_signal(normalized, _HIGH_AGGRESSIVENESS_TERMS)
    has_current_info_signal = has_current_question or has_base_signal or has_high_signal

    if has_current_info_signal:
        if aggressiveness == "low" and not has_current_question and not _has_search_signal(normalized, _SEARCH_TERMS):
            return SearchPlanDecision(
                decision="no_search_needed",
                should_use=False,
                reason="low_aggressiveness",
                search_planned=False,
            )
        reason = "current_info_signal"
        if has_high_signal and not has_base_signal:
            reason = "high_aggressiveness_signal"
        return SearchPlanDecision(
            decision="current_info_needed",
            should_use=True,
            reason=reason,
            search_planned=True,
            current_info_needed=True,
        )

    if _has_stable_knowledge_signal(normalized):
        return SearchPlanDecision(
            decision="stable_knowledge",
            should_use=False,
            reason="stable_knowledge",
            search_planned=False,
        )

    if aggressiveness == "high_when_needed" and _has_search_signal(normalized, _HIGH_AGGRESSIVENESS_TERMS):
        return SearchPlanDecision(
            decision="current_info_needed",
            should_use=True,
            reason="high_aggressiveness_signal",
            search_planned=True,
            current_info_needed=True,
        )

    return SearchPlanDecision(decision="no_search_needed", should_use=False, reason="no_search_signal", search_planned=False)

