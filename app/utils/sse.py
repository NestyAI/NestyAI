from __future__ import annotations

import json
from typing import Any


def format_sse_data(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        body = payload
    else:
        body = json.dumps(payload, ensure_ascii=False)
    return f"data: {body}\n\n"


def parse_sse_data_line(line: str) -> str | None:
    if not isinstance(line, str):
        return None
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    return stripped[len("data:") :].strip()
