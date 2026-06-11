from __future__ import annotations

from typing import Any


_TEXT_PART_TYPES = frozenset({"text", "output_text", "input_text"})


def extract_text_content(value: Any) -> str:
    """Extract user-facing text from OpenAI-compatible provider content fields."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            part_type = str(item.get("type") or "").strip().lower()
            if part_type and part_type not in _TEXT_PART_TYPES:
                continue
            text_value = item.get("text")
            if text_value is None:
                text_value = item.get("content")
            if isinstance(text_value, str) and text_value:
                parts.append(text_value)
        return "".join(parts)
    if isinstance(value, dict):
        text_value = value.get("text")
        if isinstance(text_value, str):
            return text_value
        nested = value.get("content")
        if nested is not value:
            return extract_text_content(nested)
    return ""


def extract_choice_message_content(choice: dict[str, Any] | None) -> str:
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if not isinstance(message, dict):
        message = {}
    content = extract_text_content(message.get("content"))
    if content.strip():
        return content
    text_field = message.get("text")
    if isinstance(text_field, str) and text_field.strip():
        return text_field
    return content


def extract_delta_content(delta: dict[str, Any] | None) -> str:
    if not isinstance(delta, dict):
        return ""
    content = extract_text_content(delta.get("content"))
    if content:
        return content
    text_field = delta.get("text")
    if isinstance(text_field, str):
        return text_field
    return ""
