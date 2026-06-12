from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas.chat import AnswerQualityInfo, GuardInfo, OutputSafetyInfo, PlannerInfo, RetrievalInfo
from app.schemas.tools import SourceItem, ToolMetadata


_EMPTY_FALLBACK_MESSAGE = (
    "I'm sorry, I couldn't generate a useful response for that request. Please try again or rephrase."
)

_SEARCH_CLAIM_PATTERNS = (
    "i searched",
    "i looked up",
    "i checked the web",
    "i checked online",
    "i found online",
    "i browsed",
    "mình đã tìm",
    "tôi đã tìm",
    "mình vừa tra",
    "tôi vừa tra",
    "mình đã tra",
    "tôi đã tra",
    "mình đã kiểm tra trên web",
    "tôi đã kiểm tra trên web",
    "mình đã kiểm tra trên mạng",
    "tôi đã kiểm tra trên mạng",
)

_WEAK_ANSWER_PATTERNS = (
    "don't have enough information",
    "do not have enough information",
    "insufficient information",
    "unable to find relevant",
    "unable to find any relevant",
    "cannot find relevant",
    "can't find relevant",
    "without more context",
    "without additional context",
    "please provide more context",
    "please provide more details",
    "need more information to answer",
    "need more context to answer",
    "khong du thong tin",
    "khong co du thong tin",
    "không đủ thông tin",
    "không có đủ thông tin",
    "thieu thong tin",
    "thiếu thông tin",
)

_SAFETY_REFUSAL_PATTERNS = (
    "i can't help with",
    "i cannot help with",
    "i can't assist with",
    "i cannot assist with",
    "i'm not able to provide",
    "i am not able to provide",
    "i cannot provide",
    "against my guidelines",
    "against my policy",
    "violates my policy",
    "gateway policy",
    "can't override system",
    "cannot override system",
    "i must decline",
    "i won't help with",
    "i will not help with",
    "toi khong the ho tro",
    "tôi không thể hỗ trợ",
    "khong the giup",
    "không thể giúp",
    "vi pham chinh sach",
    "vi phạm chính sách",
)

_VAGUE_APOLOGY_PREFIXES = (
    "i'm sorry",
    "i am sorry",
    "i apologize",
    "sorry,",
    "xin loi",
    "xin lỗi",
)


@dataclass(slots=True)
class ContextSignals:
    context_available: bool = False
    context_signal_count: int = 0


@dataclass(slots=True)
class QualityRetryAssessment:
    should_retry: bool = False
    retry_reason: str | None = None
    weak_answer_before_retry: bool = False
    sanitized_empty: bool = False
    context_available: bool = False
    context_signal_count: int = 0


def _normalized_text(text: str | None) -> str:
    return " ".join(str(text or "").lower().split()).strip()


def _ascii_fold(text: str) -> str:
    normalized = _normalized_text(text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", str(text or ""), flags=re.UNICODE))


def _retrieval_value(retrieval: RetrievalInfo | dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if retrieval is None:
        return default
    if isinstance(retrieval, dict):
        return retrieval.get(key, default)
    return getattr(retrieval, key, default)


def _tool_meta_value(meta: ToolMetadata | dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if meta is None:
        return default
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def compute_context_signals(
    *,
    retrieval: RetrievalInfo | dict[str, Any] | None = None,
    tools: ToolMetadata | dict[str, Any] | None = None,
    sources: list[SourceItem] | list[dict[str, Any]] | None = None,
    planner: PlannerInfo | dict[str, Any] | None = None,
) -> ContextSignals:
    count = 0
    if bool(_retrieval_value(retrieval, "search_used", False)):
        count += 1
    if sources:
        count += 1
    if bool(_retrieval_value(retrieval, "semantic_recall_used", False)):
        count += 1
    if bool(_retrieval_value(retrieval, "fts_used", False)):
        count += 1
    if bool(_retrieval_value(retrieval, "pinned_memory_used", False)):
        count += 1

    used_tools = _tool_meta_value(tools, "used", []) or []
    deterministic_tools = {
        "calculator",
        "weather_lookup",
        "exchange_rate",
        "package_version_lookup",
        "wikipedia_lookup",
    }
    if any(str(name).strip() in deterministic_tools for name in used_tools):
        count += 1

    retrieval_tools = _retrieval_value(retrieval, "tools_used", []) or []
    if any(str(name).strip() in deterministic_tools for name in retrieval_tools):
        count += 1

    if isinstance(planner, dict):
        if planner.get("tools_used"):
            count += 1
    elif planner is not None and bool(getattr(planner, "tools_used", None)):
        count += 1

    return ContextSignals(context_available=count > 0, context_signal_count=count)


def is_safety_refusal(answer_text: str) -> bool:
    normalized = _ascii_fold(answer_text)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in _SAFETY_REFUSAL_PATTERNS)


def is_short_factual_answer(answer_text: str) -> bool:
    text = str(answer_text or "").strip()
    if not text:
        return False
    if len(text) <= 15:
        return True
    words = _word_count(text)
    if words <= 3 and re.search(r"\d", text):
        return True
    return False


def detect_weak_answer(answer_text: str, *, context_available: bool) -> tuple[bool, str | None]:
    if not context_available:
        return False, None
    text = str(answer_text or "").strip()
    if not text:
        return False, None
    if is_safety_refusal(text):
        return False, None
    if is_short_factual_answer(text):
        return False, None

    normalized = _ascii_fold(text)
    words = _word_count(text)
    if words > 20:
        return False, None

    for pattern in _WEAK_ANSWER_PATTERNS:
        if pattern in normalized:
            return True, "missing_info_despite_context"

    for prefix in _VAGUE_APOLOGY_PREFIXES:
        if normalized.startswith(prefix) and words <= 12:
            return True, "vague_apology_despite_context"

    return False, None


def answer_substance_score(answer_text: str) -> int:
    text = str(answer_text or "").strip()
    if not text:
        return 0
    return _word_count(text)


def assess_quality_retry(
    answer_text: str,
    *,
    retrieval: RetrievalInfo | dict[str, Any] | None = None,
    tools: ToolMetadata | dict[str, Any] | None = None,
    sources: list[SourceItem] | list[dict[str, Any]] | None = None,
    planner: PlannerInfo | dict[str, Any] | None = None,
    orchestration: Any | None = None,
    output_safety: OutputSafetyInfo | dict[str, Any] | None = None,
    output_guard_info: GuardInfo | None = None,
    sanitized_empty: bool = False,
) -> QualityRetryAssessment:
    signals = compute_context_signals(retrieval=retrieval, tools=tools, sources=sources, planner=planner)
    context_available = signals.context_available
    if bool(getattr(orchestration, "used", False)) and bool(_retrieval_value(retrieval, "context_used", False)):
        context_available = True
        signals = ContextSignals(
            context_available=True,
            context_signal_count=max(signals.context_signal_count, 1),
        )

    if not context_available:
        return QualityRetryAssessment(
            context_available=False,
            context_signal_count=signals.context_signal_count,
        )

    if output_guard_info is not None and bool(getattr(output_guard_info, "output_redacted", False)):
        return QualityRetryAssessment(
            context_available=True,
            context_signal_count=signals.context_signal_count,
        )

    text = str(answer_text or "").strip()
    if text and is_safety_refusal(text):
        return QualityRetryAssessment(
            context_available=True,
            context_signal_count=signals.context_signal_count,
        )

    if sanitized_empty:
        return QualityRetryAssessment(
            should_retry=True,
            retry_reason="sanitized_empty",
            sanitized_empty=True,
            context_available=True,
            context_signal_count=signals.context_signal_count,
        )

    if not text:
        return QualityRetryAssessment(
            should_retry=True,
            retry_reason="empty_answer",
            context_available=True,
            context_signal_count=signals.context_signal_count,
        )

    weak, weak_reason = detect_weak_answer(text, context_available=True)
    if weak:
        return QualityRetryAssessment(
            should_retry=True,
            retry_reason=weak_reason or "weak_answer",
            weak_answer_before_retry=True,
            context_available=True,
            context_signal_count=signals.context_signal_count,
        )

    return QualityRetryAssessment(
        context_available=True,
        context_signal_count=signals.context_signal_count,
    )


def _search_evidence_present(
    *,
    retrieval: RetrievalInfo | dict[str, Any] | None,
    tools: ToolMetadata | dict[str, Any] | None,
    sources: list[SourceItem] | list[dict[str, Any]] | None,
    planner: PlannerInfo | dict[str, Any] | None = None,
) -> bool:
    if isinstance(retrieval, dict):
        if bool(retrieval.get("search_used")):
            return True
    elif retrieval is not None and bool(getattr(retrieval, "search_used", False)):
        return True

    if isinstance(planner, dict):
        if bool(planner.get("search_used")):
            return True
    elif planner is not None and bool(getattr(planner, "search_used", False)):
        return True

    search_meta = _tool_meta_value(tools, "search", None)
    if search_meta is not None:
        if bool(_tool_meta_value(search_meta, "used", False)):
            return True

    used_tools = _tool_meta_value(tools, "used", []) or []
    if any(str(name).strip().lower() == "web_search" for name in used_tools):
        return True

    if sources:
        return True
    return False


def _claimed_search_without_search(
    answer_text: str,
    *,
    retrieval: RetrievalInfo | dict[str, Any] | None,
    tools: ToolMetadata | dict[str, Any] | None,
    sources: list[SourceItem] | list[dict[str, Any]] | None,
    planner: PlannerInfo | dict[str, Any] | None = None,
) -> bool:
    if _search_evidence_present(retrieval=retrieval, tools=tools, sources=sources, planner=planner):
        return False
    normalized = _normalized_text(answer_text)
    return any(pattern in normalized for pattern in _SEARCH_CLAIM_PATTERNS)


def evaluate_answer_quality(
    answer_text: str,
    *,
    retrieval: RetrievalInfo | dict[str, Any] | None = None,
    tools: ToolMetadata | dict[str, Any] | None = None,
    sources: list[SourceItem] | list[dict[str, Any]] | None = None,
    planner: PlannerInfo | dict[str, Any] | None = None,
    output_safety: OutputSafetyInfo | dict[str, Any] | None = None,
    streaming: bool = False,
    context_available: bool | None = None,
    context_signal_count: int | None = None,
) -> tuple[str, AnswerQualityInfo]:
    raw_text = str(answer_text or "")
    normalized_text = raw_text.strip()

    detected_markup = False
    if isinstance(output_safety, dict):
        detected_markup = bool(output_safety.get("internal_tool_markup_detected")) or bool(
            output_safety.get("internal_tool_markup_removed")
        )
    elif output_safety is not None:
        detected_markup = bool(getattr(output_safety, "internal_tool_markup_detected", False)) or bool(
            getattr(output_safety, "internal_tool_markup_removed", False)
        )

    signals = compute_context_signals(retrieval=retrieval, tools=tools, sources=sources, planner=planner)
    resolved_context_available = bool(context_available) if context_available is not None else signals.context_available
    resolved_context_signal_count = (
        int(context_signal_count) if context_signal_count is not None else signals.context_signal_count
    )

    flags: list[str] = []
    if detected_markup:
        flags.append("internal_markup_detected")
    if _claimed_search_without_search(raw_text, retrieval=retrieval, tools=tools, sources=sources, planner=planner):
        flags.append("claimed_search_without_search")

    if normalized_text and not streaming and resolved_context_available:
        weak, weak_reason = detect_weak_answer(normalized_text, context_available=True)
        if weak:
            flags.append("weak_answer")
            if weak_reason:
                flags.append(str(weak_reason))

    if not streaming and not normalized_text:
        flags.insert(0, "empty_answer")
        return _EMPTY_FALLBACK_MESSAGE, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="fallback_empty",
            context_available=resolved_context_available,
            context_signal_count=resolved_context_signal_count,
        )

    if streaming and not normalized_text:
        flags.insert(0, "empty_answer")
        return raw_text, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="skipped_streaming",
            context_available=resolved_context_available,
            context_signal_count=resolved_context_signal_count,
        )

    if not streaming and detected_markup:
        return raw_text, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="cleaned_internal_markup",
            context_available=resolved_context_available,
            context_signal_count=resolved_context_signal_count,
        )

    if streaming and flags:
        return raw_text, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="metadata_only",
            context_available=resolved_context_available,
            context_signal_count=resolved_context_signal_count,
        )

    return raw_text, AnswerQualityInfo(
        checked=True,
        flags=_dedupe_flags(flags),
        action="none",
        context_available=resolved_context_available,
        context_signal_count=resolved_context_signal_count,
    )


def _dedupe_flags(flags: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for flag in flags:
        normalized = str(flag or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
