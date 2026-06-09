from __future__ import annotations

from typing import Any

from app.schemas.chat import AnswerQualityInfo, OutputSafetyInfo, RetrievalInfo
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


def _normalized_text(text: str | None) -> str:
    return " ".join(str(text or "").lower().split()).strip()


def _tool_meta_value(meta: ToolMetadata | dict[str, Any] | None, key: str, default: Any = None) -> Any:
    if meta is None:
        return default
    if isinstance(meta, dict):
        return meta.get(key, default)
    return getattr(meta, key, default)


def _search_evidence_present(
    *,
    retrieval: RetrievalInfo | dict[str, Any] | None,
    tools: ToolMetadata | dict[str, Any] | None,
    sources: list[SourceItem] | list[dict[str, Any]] | None,
) -> bool:
    if isinstance(retrieval, dict):
        if bool(retrieval.get("search_used")):
            return True
    elif retrieval is not None and bool(getattr(retrieval, "search_used", False)):
        return True

    search_meta = _tool_meta_value(tools, "search", None)
    if search_meta is not None:
        if bool(_tool_meta_value(search_meta, "query", None)) or int(_tool_meta_value(search_meta, "results_count", 0) or 0) > 0:
            return True
        if bool(_tool_meta_value(search_meta, "failed", False)) and bool(_tool_meta_value(search_meta, "enabled", False)):
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
) -> bool:
    if _search_evidence_present(retrieval=retrieval, tools=tools, sources=sources):
        return False
    normalized = _normalized_text(answer_text)
    return any(pattern in normalized for pattern in _SEARCH_CLAIM_PATTERNS)


def evaluate_answer_quality(
    answer_text: str,
    *,
    retrieval: RetrievalInfo | dict[str, Any] | None = None,
    tools: ToolMetadata | dict[str, Any] | None = None,
    sources: list[SourceItem] | list[dict[str, Any]] | None = None,
    output_safety: OutputSafetyInfo | dict[str, Any] | None = None,
    streaming: bool = False,
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

    flags: list[str] = []
    if detected_markup:
        flags.append("internal_markup_detected")
    if _claimed_search_without_search(raw_text, retrieval=retrieval, tools=tools, sources=sources):
        flags.append("claimed_search_without_search")

    if not streaming and not normalized_text:
        flags.insert(0, "empty_answer")
        return _EMPTY_FALLBACK_MESSAGE, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="fallback_empty",
        )

    if streaming and not normalized_text:
        flags.insert(0, "empty_answer")
        return raw_text, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="skipped_streaming",
        )

    if not streaming and detected_markup:
        return raw_text, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="cleaned_internal_markup",
        )

    if streaming and flags:
        return raw_text, AnswerQualityInfo(
            checked=True,
            flags=_dedupe_flags(flags),
            action="metadata_only",
        )

    return raw_text, AnswerQualityInfo(
        checked=True,
        flags=_dedupe_flags(flags),
        action="none",
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
