from __future__ import annotations

from typing import Any

from app.guards.input_guard import InputGuard
from app.schemas.chat import GuardInfo


class OutputGuard:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self._redactor = InputGuard(rules=rules)

    def scan_text(self, text: str) -> tuple[str, GuardInfo]:
        redaction = self._redactor.redact_text(text)
        metadata = GuardInfo(
            input_redacted=False,
            output_redacted=redaction.redaction_count > 0,
            redaction_count=redaction.redaction_count,
            categories=sorted(redaction.categories),
        )
        return redaction.text, metadata

