from __future__ import annotations

import secrets


def secrets_equal(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_text = str(left)
    right_text = str(right)
    if len(left_text) != len(right_text):
        return False
    return secrets.compare_digest(left_text, right_text)
