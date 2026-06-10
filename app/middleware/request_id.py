from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from app.utils.ids import generate_request_id

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_INCOMING_HEADERS = (b"x-request-id", b"x-correlation-id")


def _normalize_incoming_request_id(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate or len(candidate) > 64:
        return None
    if not _SAFE_REQUEST_ID.fullmatch(candidate):
        return None
    return candidate


def resolve_request_id_from_scope(scope: dict) -> str:
    headers = scope.get("headers") or []
    for header_name in _INCOMING_HEADERS:
        for name, value in headers:
            if name.lower() != header_name:
                continue
            try:
                decoded = value.decode("latin-1")
            except Exception:
                continue
            normalized = _normalize_incoming_request_id(decoded)
            if normalized:
                return normalized
    return generate_request_id()


class RequestIdMiddleware:
    """Assigns a public-safe ``X-Request-ID`` for every HTTP request/response."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict,
        receive: Callable[[], Awaitable[dict]],
        send: Callable[[dict], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id_from_scope(scope)
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id

        async def send_wrapper(message: dict) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"x-request-id" for k, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
