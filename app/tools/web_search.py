from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from ddgs import DDGS

from app.schemas.tools import SearchResult
from app.utils.cache_keys import make_tool_cache_key
from app.utils.ttl_cache import TTLCache


_SEARCH_CACHE: TTLCache[list[SearchResult]] = TTLCache(max_size=512)
_SEARCH_PROVIDER = "ddgs"

_LOW_VALUE_SNIPPET_MARKERS = (
    "click here",
    "sign in",
    "subscribe",
    "cookie policy",
    "access denied",
    "enable javascript",
)


@dataclass(slots=True)
class WebSearchMeta:
    queries: list[str]
    provider: str = _SEARCH_PROVIDER
    latency_ms: int = 0
    result_count: int = 0
    filtered_result_count: int = 0
    failed: bool = False
    error_code: str | None = None
    cache_hit: bool = False


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return f"{scheme}://{netloc}{path}"


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip().lower())


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _is_low_value_result(title: str, snippet: str) -> bool:
    combined = f"{title} {snippet}".lower()
    if len(f"{title} {snippet}".strip()) < 24:
        return True
    return any(marker in combined for marker in _LOW_VALUE_SNIPPET_MARKERS)


def _score_result(result: SearchResult, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    title_tokens = _tokenize(result.title)
    snippet_tokens = _tokenize(result.snippet)
    overlap = len(query_tokens & (title_tokens | snippet_tokens))
    score = overlap / max(1, len(query_tokens))
    url_lower = result.url.lower()
    if any(domain in url_lower for domain in ("wikipedia.org", "github.com", "docs.", ".gov", "arxiv.org")):
        score += 0.15
    if result.source:
        score += 0.05
    return score


def rank_and_filter_results(
    results: list[SearchResult],
    queries: list[str],
    *,
    max_results: int,
) -> tuple[list[SearchResult], int]:
    query_tokens: set[str] = set()
    for query in queries:
        query_tokens.update(_tokenize(query))

    scored: list[tuple[float, SearchResult]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    filtered_count = 0

    for item in results:
        title = str(item.title or "").strip()
        url = str(item.url or "").strip()
        snippet = str(item.snippet or "").strip()
        if not title or not url or not snippet:
            filtered_count += 1
            continue
        if not url.startswith("http://") and not url.startswith("https://"):
            filtered_count += 1
            continue
        if _is_low_value_result(title, snippet):
            filtered_count += 1
            continue
        url_key = _normalize_url(url)
        title_key = _normalize_title(title)
        if url_key in seen_urls or title_key in seen_titles:
            filtered_count += 1
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        scored.append((_score_result(item, query_tokens), item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [item for _score, item in scored[: max(1, max_results)]]
    return ranked, filtered_count


def _run_ddgs_search(query: str, max_results: int, timeout_seconds: float) -> list[dict]:
    with DDGS(timeout=timeout_seconds) as ddgs:
        return list(ddgs.text(query, max_results=max_results))


def _raw_to_results(raw_results: list[dict]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in raw_results:
        title = str(item.get("title", "") or "").strip()
        url = str(item.get("href", "") or "").strip()
        snippet = str(item.get("body", "") or "").strip()
        source = str(item.get("source", "") or "").strip() or None
        if not title or not url or not snippet:
            continue
        results.append(SearchResult(title=title, url=url, snippet=snippet, source=source))
    return results


async def web_search_with_meta(
    query: str,
    max_results: int = 5,
    timeout_seconds: float = 8.0,
    cache_enabled: bool = True,
    cache_ttl_seconds: int = 600,
) -> tuple[list[SearchResult], bool]:
    results, meta = await web_search_multi_with_meta(
        queries=[query],
        max_results=max_results,
        timeout_seconds=timeout_seconds,
        cache_enabled=cache_enabled,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    return results, meta.failed


async def web_search_multi_with_meta(
    queries: list[str],
    max_results: int = 5,
    timeout_seconds: float = 8.0,
    cache_enabled: bool = True,
    cache_ttl_seconds: int = 600,
) -> tuple[list[SearchResult], WebSearchMeta]:
    cleaned_queries = [query.strip() for query in queries if str(query or "").strip()]
    if not cleaned_queries:
        return [], WebSearchMeta(queries=[], failed=False, error_code="empty_query")

    limit = max(1, min(max_results, 8))
    started = time.perf_counter()
    cache_key = make_tool_cache_key(
        "web_search_multi",
        {"queries": cleaned_queries, "max_results": limit},
    )
    if cache_enabled and cache_ttl_seconds > 0:
        cached = await _SEARCH_CACHE.get(cache_key)
        if cached is not None:
            elapsed = int((time.perf_counter() - started) * 1000)
            return [item.model_copy(deep=True) for item in cached], WebSearchMeta(
                queries=cleaned_queries,
                latency_ms=elapsed,
                result_count=len(cached),
                filtered_result_count=0,
                failed=False,
                cache_hit=True,
            )

    failed = False
    error_code: str | None = None
    merged_raw: list[SearchResult] = []
    per_query_timeout = max(2.0, timeout_seconds / max(1, len(cleaned_queries)))

    for query in cleaned_queries[:3]:
        try:
            raw_results = await asyncio.wait_for(
                asyncio.to_thread(_run_ddgs_search, query, limit * 2, per_query_timeout),
                timeout=per_query_timeout,
            )
            merged_raw.extend(_raw_to_results(raw_results))
        except Exception:
            failed = True
            error_code = error_code or "search_provider_error"

    ranked, filtered_count = rank_and_filter_results(merged_raw, cleaned_queries, max_results=limit)
    elapsed = int((time.perf_counter() - started) * 1000)

    if cache_enabled and cache_ttl_seconds > 0 and ranked:
        await _SEARCH_CACHE.set(cache_key, [item.model_copy(deep=True) for item in ranked], cache_ttl_seconds)

    return ranked, WebSearchMeta(
        queries=cleaned_queries,
        latency_ms=elapsed,
        result_count=len(merged_raw),
        filtered_result_count=filtered_count,
        failed=failed and not ranked,
        error_code=error_code if failed and not ranked else None,
    )


async def web_search(query: str, max_results: int = 5) -> list[SearchResult]:
    results, _meta = await web_search_multi_with_meta(queries=[query], max_results=max_results)
    return results
