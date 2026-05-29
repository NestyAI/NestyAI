from __future__ import annotations

import asyncio

import pytest

from app.utils.ttl_cache import TTLCache


@pytest.mark.asyncio
async def test_ttl_cache_set_get() -> None:
    cache = TTLCache[str](max_size=10)
    await cache.set("a", "hello", ttl_seconds=5)
    value = await cache.get("a")
    assert value == "hello"


@pytest.mark.asyncio
async def test_ttl_cache_expired() -> None:
    cache = TTLCache[str](max_size=10)
    await cache.set("a", "hello", ttl_seconds=1)
    await asyncio.sleep(1.1)
    value = await cache.get("a")
    assert value is None


@pytest.mark.asyncio
async def test_ttl_cache_clear() -> None:
    cache = TTLCache[str](max_size=10)
    await cache.set("a", "1", ttl_seconds=5)
    await cache.set("b", "2", ttl_seconds=5)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


@pytest.mark.asyncio
async def test_ttl_cache_max_size_enforced() -> None:
    cache = TTLCache[str](max_size=2)
    await cache.set("a", "1", ttl_seconds=5)
    await cache.set("b", "2", ttl_seconds=5)
    await cache.set("c", "3", ttl_seconds=5)
    assert await cache.get("a") is None
    assert await cache.get("b") == "2"
    assert await cache.get("c") == "3"

