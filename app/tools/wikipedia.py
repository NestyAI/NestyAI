from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.schemas.tools import ToolResult


def _looks_vietnamese(text: str) -> bool:
    if re.search(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", text.lower()):
        return True
    vi_keywords = ["là gì", "định nghĩa", "khái niệm", "ai là", "ở đâu"]
    lowered = text.lower()
    return any(keyword in lowered for keyword in vi_keywords)


async def execute_wikipedia_lookup(message: str, context: dict[str, Any] | None = None) -> ToolResult:
    started = time.perf_counter()
    timeout_seconds = float((context or {}).get("timeout_seconds", 6))
    query = message.strip()
    if not query:
        return ToolResult(
            name="wikipedia_lookup",
            success=False,
            content="Empty query.",
            error="invalid_query",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    lang = "vi" if _looks_vietnamese(query) else "en"
    search_url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": query,
        "srlimit": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            search_resp = await client.get(search_url, params=params)
            if search_resp.status_code >= 400:
                raise ValueError("search_failed")
            search_data = search_resp.json()
            search_items = search_data.get("query", {}).get("search", [])
            if not search_items:
                raise ValueError("not_found")
            title = str(search_items[0].get("title", "")).strip()
            if not title:
                raise ValueError("not_found")

            summary_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
            summary_resp = await client.get(summary_url)
            if summary_resp.status_code >= 400:
                raise ValueError("summary_failed")
            summary_data = summary_resp.json()
    except Exception:
        return ToolResult(
            name="wikipedia_lookup",
            success=False,
            content="Wikipedia lookup failed.",
            error="lookup_failed",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    title = str(summary_data.get("title", title)).strip() or title
    extract = str(summary_data.get("extract", "")).strip()
    page_url = (
        summary_data.get("content_urls", {})
        .get("desktop", {})
        .get("page")
        or f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
    )
    if not extract:
        return ToolResult(
            name="wikipedia_lookup",
            success=False,
            content="No summary available.",
            error="empty_summary",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    return ToolResult(
        name="wikipedia_lookup",
        success=True,
        content=f"Title: {title}\nSummary: {extract}\nSource: {page_url}",
        data={"title": title, "summary": extract, "url": page_url, "language": lang},
        sources=[{"title": title, "url": page_url, "snippet": extract}],
        confidence="medium",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
