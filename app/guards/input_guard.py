from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.guards.patterns import GUARD_PATTERNS
from app.schemas.chat import ChatMessage, GuardInfo


@dataclass
class RedactionResult:
    text: str
    redaction_count: int
    categories: set[str]


class InputGuard:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        redaction = (rules or {}).get("redaction", {})
        self.secret_placeholder = redaction.get("secret_placeholder", "[REDACTED_SECRET]")
        self.pii_placeholder = redaction.get("pii_placeholder", "[REDACTED_PII]")
        self.default_placeholder = redaction.get("default_placeholder", "[REDACTED]")

    def _placeholder_for_category(self, category: str) -> str:
        if category == "secret":
            return self.secret_placeholder
        if category == "pii":
            return self.pii_placeholder
        return self.default_placeholder

    def redact_text(self, text: str) -> RedactionResult:
        redacted_text = text
        redaction_count = 0
        categories: set[str] = set()

        for pattern in GUARD_PATTERNS:
            replacement = self._placeholder_for_category(pattern.category)
            redacted_text, count = pattern.regex.subn(replacement, redacted_text)
            if count:
                redaction_count += count
                categories.add(pattern.name)

        return RedactionResult(
            text=redacted_text,
            redaction_count=redaction_count,
            categories=categories,
        )

    def scan_messages(self, messages: list[ChatMessage]) -> tuple[list[ChatMessage], GuardInfo]:
        safe_messages: list[ChatMessage] = []
        total_redactions = 0
        categories: set[str] = set()

        for message in messages:
            redaction = self.redact_text(message.content)
            safe_messages.append(message.model_copy(update={"content": redaction.text}))
            total_redactions += redaction.redaction_count
            categories.update(redaction.categories)

        metadata = GuardInfo(
            input_redacted=total_redactions > 0,
            output_redacted=False,
            redaction_count=total_redactions,
            categories=sorted(categories),
        )
        return safe_messages, metadata

