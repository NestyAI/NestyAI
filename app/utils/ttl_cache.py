from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    def __init__(self, max_size: int = 512) -> None:
        self.max_size = max(1, int(max_size))
        self._entries: OrderedDict[str, _CacheEntry[T]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> T | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.time():
                self._entries.pop(key, None)
                return None
            # Refresh LRU position.
            self._entries.move_to_end(key, last=True)
            return entry.value

    async def set(self, key: str, value: T, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        expires_at = time.time() + int(ttl_seconds)
        async with self._lock:
            self._entries[key] = _CacheEntry(value=value, expires_at=expires_at)
            self._entries.move_to_end(key, last=True)
            self._evict_expired_locked()
            while len(self._entries) > self.max_size:
                self._entries.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._entries.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    async def size(self) -> int:
        async with self._lock:
            self._evict_expired_locked()
            return len(self._entries)

    def _evict_expired_locked(self) -> None:
        now = time.time()
        expired_keys = [key for key, item in self._entries.items() if item.expires_at <= now]
        for key in expired_keys:
            self._entries.pop(key, None)

