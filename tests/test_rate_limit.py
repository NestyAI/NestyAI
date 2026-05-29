from __future__ import annotations

from app.security.rate_limit import InMemoryRateLimiter


def test_rate_limit_allows_within_limit() -> None:
    limiter = InMemoryRateLimiter(window_seconds=60)
    assert limiter.check("api_key:key1", 2).allowed is True
    assert limiter.check("api_key:key1", 2).allowed is True


def test_rate_limit_blocks_after_limit() -> None:
    limiter = InMemoryRateLimiter(window_seconds=60)
    limiter.check("api_key:key1", 1)
    blocked = limiter.check("api_key:key1", 1)
    assert blocked.allowed is False
    assert blocked.retry_after_seconds >= 1


def test_rate_limit_isolated_per_key() -> None:
    limiter = InMemoryRateLimiter(window_seconds=60)
    assert limiter.check("api_key:key1", 1).allowed is True
    assert limiter.check("api_key:key2", 1).allowed is True
    assert limiter.check("api_key:key1", 1).allowed is False
