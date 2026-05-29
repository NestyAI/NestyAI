from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock

from fastapi import Request

from app.security.auth import AuthContext


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class InMemoryRateLimiter:
    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, limit: int) -> RateLimitDecision:
        if limit <= 0:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

        now = time.time()
        oldest_allowed = now - self.window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= oldest_allowed:
                events.popleft()

            if len(events) >= limit:
                retry_after = max(1, int(math.ceil(self.window_seconds - (now - events[0]))))
                return RateLimitDecision(allowed=False, retry_after_seconds=retry_after)

            events.append(now)
            return RateLimitDecision(allowed=True, retry_after_seconds=0)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_limiter = InMemoryRateLimiter()


def get_rate_limiter() -> InMemoryRateLimiter:
    return _limiter


def build_rate_limit_key(request: Request, auth_context: AuthContext | None) -> str:
    if auth_context is not None:
        return f"api_key:{auth_context.api_key_id}"

    forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return f"ip:{first_ip}"

    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"
