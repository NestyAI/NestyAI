from __future__ import annotations

import re
from typing import Any


_LONGCAT_BLOCK_PATTERN = re.compile(
    r"<longcat_tool_call\b[^>]*>.*?</longcat_tool_call\s*>",
    re.IGNORECASE | re.DOTALL,
)
_LONGCAT_ARG_TAG_PATTERN = re.compile(
    r"</?longcat_arg_(?:key|value)\b[^>]*>",
    re.IGNORECASE,
)
_LONGCAT_TOOL_OPEN_PATTERN = re.compile(r"<longcat_tool_call\b", re.IGNORECASE)
_LONGCAT_TOOL_CLOSE_PATTERN = re.compile(r"</longcat_tool_call\s*>", re.IGNORECASE)


def contains_internal_tool_markup(text: str) -> bool:
    payload = str(text or "")
    return bool(
        _LONGCAT_TOOL_OPEN_PATTERN.search(payload)
        or _LONGCAT_TOOL_CLOSE_PATTERN.search(payload)
        or _LONGCAT_ARG_TAG_PATTERN.search(payload)
    )


def strip_internal_tool_markup(text: str) -> str:
    payload = str(text or "")
    payload = _LONGCAT_BLOCK_PATTERN.sub("", payload)
    payload = _LONGCAT_ARG_TAG_PATTERN.sub("", payload)
    payload = re.sub(r"\n{3,}", "\n\n", payload)
    return payload.strip()


def sanitize_internal_tool_markup(text: str) -> tuple[str, dict[str, Any]]:
    payload = str(text or "")
    detected = contains_internal_tool_markup(payload)
    if not detected:
        return payload, {
            "internal_tool_markup_detected": False,
            "internal_tool_markup_removed": False,
            "removed_blocks": 0,
        }

    removed_blocks = len(_LONGCAT_BLOCK_PATTERN.findall(payload))
    sanitized = strip_internal_tool_markup(payload)
    removed = sanitized != payload
    return sanitized, {
        "internal_tool_markup_detected": True,
        "internal_tool_markup_removed": removed,
        "removed_blocks": removed_blocks,
    }
