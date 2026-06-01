from __future__ import annotations

from typing import Any

from app.core.internal_tool_markup import sanitize_internal_tool_markup
from app.guards.input_guard import InputGuard
from app.schemas.chat import GuardInfo


class OutputGuard:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self._redactor = InputGuard(rules=rules)

    def scan_text(self, text: str) -> tuple[str, GuardInfo]:
        tool_sanitized_text, tool_meta = sanitize_internal_tool_markup(text)
        redaction = self._redactor.redact_text(text)
        categories = set(redaction.categories)
        if bool(tool_meta.get("internal_tool_markup_removed")):
            categories.add("internal_tool_markup")
        metadata = GuardInfo(
            input_redacted=False,
            output_redacted=redaction.redaction_count > 0 or bool(tool_meta.get("internal_tool_markup_removed")),
            redaction_count=redaction.redaction_count + (1 if bool(tool_meta.get("internal_tool_markup_removed")) else 0),
            categories=sorted(categories),
        )
        # Internal tool markup is removed first, then normal redaction patterns run.
        if tool_sanitized_text != text:
            redaction = self._redactor.redact_text(tool_sanitized_text)
            categories = set(redaction.categories)
            categories.add("internal_tool_markup")
            metadata = GuardInfo(
                input_redacted=False,
                output_redacted=True,
                redaction_count=redaction.redaction_count + 1,
                categories=sorted(categories),
            )
            return redaction.text, metadata
        return redaction.text, metadata

