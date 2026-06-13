from __future__ import annotations

import re
import unicodedata


def normalize_message_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized.lower()).strip()
    return normalized
