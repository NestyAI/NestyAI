from __future__ import annotations

import uuid


def generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def generate_chat_completion_id() -> str:
    return f"chatcmpl_{uuid.uuid4().hex[:16]}"

