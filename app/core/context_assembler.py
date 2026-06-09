from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence


_DEFAULT_DEDUP_SIMILARITY = 0.96
_SOURCE_PRIORITY: dict[str, int] = {
    "pinned_memory": 0,
    "semantic_recall": 10,
    "fts": 20,
    "search": 30,
    "tools": 40,
}


@dataclass(slots=True)
class ContextItem:
    source: str
    content: str
    title: str | None = None
    score: float | None = None
    pinned: bool = False
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextAssemblyResult:
    items: list[ContextItem] = field(default_factory=list)
    context_text: str = ""
    context_sources: list[str] = field(default_factory=list)
    context_items_count: int = 0
    context_truncated: bool = False
    context_budget_chars: int = 0
    context_used_chars: int = 0


def build_context_item(
    *,
    source: str,
    content: str,
    title: str | None = None,
    score: float | None = None,
    pinned: bool = False,
    created_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ContextItem:
    return ContextItem(
        source=_normalize_source(source),
        content=_normalize_context_text(content),
        title=_normalize_optional_text(title),
        score=float(score) if score is not None else None,
        pinned=bool(pinned),
        created_at=_normalize_optional_text(created_at),
        metadata=dict(metadata or {}),
    )


def assemble_hybrid_context(
    items: Sequence[ContextItem] | Iterable[ContextItem],
    *,
    summary_text: str = "",
    budget_chars: int,
    dedup_similarity: float = _DEFAULT_DEDUP_SIMILARITY,
) -> ContextAssemblyResult:
    normalized_items = [normalize_context_item(item) for item in items]
    summary_normalized = _normalize_for_dedup(summary_text)
    ordered_items = sorted(normalized_items, key=_context_sort_key)

    packed_items: list[ContextItem] = []
    context_blocks: list[str] = []
    seen_normalized: list[str] = []
    used_chars = 0
    context_budget_chars = max(1, int(budget_chars))
    truncated = False

    for item in ordered_items:
        normalized_content = _normalize_for_dedup(item.content)
        if not normalized_content:
            continue
        if _is_near_duplicate(normalized_content, summary_normalized, dedup_similarity):
            continue
        if any(_is_near_duplicate(normalized_content, existing, dedup_similarity) for existing in seen_normalized):
            continue

        block = _format_context_block(item=item, index=len(packed_items) + 1)
        remaining = context_budget_chars - used_chars
        if remaining <= 0:
            truncated = True
            break

        if len(block) > remaining:
            block = _truncate_context_block(item=item, index=len(packed_items) + 1, remaining_chars=remaining)
            truncated = True
            if not block:
                break

        packed_items.append(item)
        seen_normalized.append(normalized_content)
        context_blocks.append(block)
        used_chars += len(block)

    context_text = "\n\n".join(context_blocks).strip()
    context_sources: list[str] = []
    seen_sources: set[str] = set()
    for item in packed_items:
        source = item.source.strip().lower()
        if not source or source in seen_sources:
            continue
        seen_sources.add(source)
        context_sources.append(source)

    return ContextAssemblyResult(
        items=packed_items,
        context_text=context_text,
        context_sources=context_sources,
        context_items_count=len(packed_items),
        context_truncated=truncated,
        context_budget_chars=context_budget_chars,
        context_used_chars=used_chars,
    )


def normalize_context_item(item: ContextItem) -> ContextItem:
    return ContextItem(
        source=_normalize_source(item.source),
        content=_normalize_context_text(item.content),
        title=_normalize_optional_text(item.title),
        score=float(item.score) if item.score is not None else None,
        pinned=bool(item.pinned),
        created_at=_normalize_optional_text(item.created_at),
        metadata=dict(item.metadata or {}),
    )


def _context_sort_key(item: ContextItem) -> tuple[int, int, float, str, str]:
    priority = _SOURCE_PRIORITY.get(item.source, 50)
    pinned_rank = 0 if item.pinned else 1
    score = float(item.score or 0.0)
    title = item.title or ""
    created_at = item.created_at or ""
    return (pinned_rank, priority, -score, title.lower(), created_at)


def _format_context_block(item: ContextItem, index: int) -> str:
    header = _format_context_header(item=item, index=index)
    content = item.content.strip()
    if not content:
        return ""
    return f"{header}\n{content}"


def _truncate_context_block(item: ContextItem, index: int, remaining_chars: int) -> str:
    header = _format_context_header(item=item, index=index)
    if not header or remaining_chars <= len(header) + 4:
        return ""

    available_content = remaining_chars - len(header) - 1
    content = item.content.strip()
    if len(content) <= available_content:
        return f"{header}\n{content}"
    if available_content <= 0:
        return ""
    clipped = content[: max(0, available_content - 3)].rstrip()
    if not clipped:
        return ""
    return f"{header}\n{clipped}..."


def _format_context_header(item: ContextItem, index: int) -> str:
    header_parts = [f"[Retrieval {index}", f"source={item.source}"]
    if item.title:
        header_parts.append(f"title={item.title}")
    if item.score is not None:
        header_parts.append(f"score={item.score:.2f}")
    if item.pinned:
        header_parts.append("pinned")
    if item.created_at:
        header_parts.append(f"date={item.created_at}")
    return " | ".join(header_parts) + "]"


def _normalize_source(source: str) -> str:
    normalized = " ".join(str(source or "").replace("_", " ").split()).strip().lower()
    return normalized.replace(" ", "_")


def _normalize_optional_text(text: str | None) -> str | None:
    normalized = _normalize_context_text(text or "")
    return normalized or None


def _normalize_context_text(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in raw.split("\n")]
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
            continue
        if current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    normalized = "\n\n".join(blocks).strip()
    return normalized


def _normalize_for_dedup(text: str) -> str:
    return _normalize_context_text(text).lower()


def _is_near_duplicate(content_normalized: str, other_normalized: str, threshold: float) -> bool:
    if not content_normalized or not other_normalized:
        return False
    if content_normalized == other_normalized:
        return True

    len_a = len(content_normalized)
    len_b = len(other_normalized)
    shorter = min(len_a, len_b)
    longer = max(len_a, len_b)
    if shorter <= 0:
        return False
    length_ratio = shorter / longer
    if length_ratio < 0.82:
        return False

    return SequenceMatcher(a=content_normalized, b=other_normalized).ratio() >= threshold
