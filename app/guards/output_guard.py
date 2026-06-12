from __future__ import annotations

from typing import Any

from app.core.internal_tool_markup import sanitize_internal_tool_markup
from app.guards.input_guard import InputGuard
from app.guards.safety_policy import SafetyPolicy
from app.schemas.chat import GuardInfo, OutputSafetyInfo


class OutputGuard:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self._rules = rules or {}
        self._redactor = InputGuard(rules=self._rules)
        self._safety_policy = SafetyPolicy(self._rules)

    def scan_text(self, text: str) -> tuple[str, GuardInfo, OutputSafetyInfo]:
        tool_sanitized_text, tool_meta = sanitize_internal_tool_markup(text)
        redaction = self._redactor.redact_text(text)
        categories = set(redaction.categories)
        if bool(tool_meta.get("internal_tool_markup_removed")):
            categories.add("internal_tool_markup")
        output_safety = OutputSafetyInfo(
            internal_tool_markup_detected=bool(tool_meta.get("internal_tool_markup_detected")),
            internal_tool_markup_removed=bool(tool_meta.get("internal_tool_markup_removed")),
        )
        if tool_sanitized_text != text:
            redaction = self._redactor.redact_text(tool_sanitized_text)
            categories = set(redaction.categories)
            categories.add("internal_tool_markup")
            output_safety.internal_tool_markup_detected = True
            output_safety.internal_tool_markup_removed = True
            response_text = redaction.text
        else:
            response_text = redaction.text

        output_decision = self._safety_policy.classify_output(response_text)
        if output_decision.action == "sanitize" and output_decision.user_safe_message:
            response_text = output_decision.user_safe_message
            output_safety.unsafe_output_blocked = True
            output_safety.output_guard_reason = output_decision.reason_code
            categories.add("unsafe_output_blocked")

        if redaction.redaction_count > 0:
            output_safety.output_redacted = True
            output_safety.redaction_count = redaction.redaction_count
        if output_safety.internal_tool_markup_removed:
            output_safety.output_redacted = True

        metadata = GuardInfo(
            input_redacted=False,
            output_redacted=output_safety.output_redacted or output_safety.unsafe_output_blocked,
            redaction_count=redaction.redaction_count
            + (1 if output_safety.internal_tool_markup_removed else 0),
            categories=sorted(categories),
        )
        return response_text, metadata, output_safety
