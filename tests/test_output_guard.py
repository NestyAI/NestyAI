from __future__ import annotations

from app.guards.output_guard import OutputGuard


def test_output_guard_redacts_sensitive_output() -> None:
    guard = OutputGuard()
    text = (
        "Here is key sk-ABCDEFGHIJKLMNOPQRSTUV123456 and "
        "contact user@example.com or +84901234567."
    )

    sanitized, metadata = guard.scan_text(text)

    assert metadata.output_redacted is True
    assert metadata.redaction_count > 0
    assert "sk-ABCDEFGHIJKLMNOPQRSTUV123456" not in sanitized
    assert "user@example.com" not in sanitized
    assert "+84901234567" not in sanitized

