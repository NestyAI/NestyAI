from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from ddgs import DDGS

from app.schemas.tools import SearchResult
from app.utils.cache_keys import make_tool_cache_key
from app.utils.ttl_cache import TTLCache


_SEARCH_CACHE: TTLCache[list[SearchResult]] = TTLCache(max_size=512)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return f"{scheme}://{netloc}{path}"


def _run_ddgs_search(query: str, max_results: int, timeout_seconds: float) -> list[dict]:
    with DDGS(timeout=timeout_seconds) as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def web_search_with_meta(
    query: str,
    max_results: int = 5,
    timeout_seconds: float = 8.0,
    cache_enabled: bool = True,
    cache_ttl_seconds: int = 600,
) -> tuple[list[SearchResult], bool]:
    if not query.strip():
        return [], False

    limit = max(1, min(max_results, 8))
    cache_key = make_tool_cache_key("web_search", {"query": query, "max_results": limit})
    if cache_enabled and cache_ttl_seconds > 0:
        cached = await _SEARCH_CACHE.get(cache_key)
        if cached is not None:
            return [item.model_copy(deep=True) for item in cached], False

    failed = False
    raw_results: list[dict] = []
    try:
        raw_results = await asyncio.wait_for(
            asyncio.to_thread(_run_ddgs_search, query, limit * 2, timeout_seconds),
            timeout=timeout_seconds,
        )
    except Exception:
        failed = True
        raw_results = []

    results: list[SearchResult] = []
    seen: set[str] = set()

    for item in raw_results:
        title = str(item.get("title", "") or "").strip()
        url = str(item.get("href", "") or "").strip()
        snippet = str(item.get("body", "") or "").strip()
        source = str(item.get("source", "") or "").strip() or None

        if not title or not url or not snippet:
            continue
        if not url.startswith("http://") and not url.startswith("https://"):
            continue
        dedupe_key = _normalize_url(url)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append(SearchResult(title=title, url=url, snippet=snippet, source=source))
        if len(results) >= limit:
            break

    if cache_enabled and cache_ttl_seconds > 0 and results:
        await _SEARCH_CACHE.set(cache_key, [item.model_copy(deep=True) for item in results], cache_ttl_seconds)

    return results, failed


async def web_search(query: str, max_results: int = 5) -> list[SearchResult]:
    results, _failed = await web_search_with_meta(query=query, max_results=max_results)
    return results
