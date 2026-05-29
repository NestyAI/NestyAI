from __future__ import annotations

import pytest

from app.tools import web_search as ws_module


@pytest.mark.asyncio
async def test_web_search_uses_cache_on_second_call(monkeypatch) -> None:
    await ws_module._SEARCH_CACHE.clear()
    calls = {"count": 0}

    def fake_run_ddgs_search(query: str, max_results: int, timeout_seconds: float):
        calls["count"] += 1
        return [
            {
                "title": "A",
                "href": "https://example.com/a",
                "body": "Snippet A",
                "source": "example",
            }
        ]

    monkeypatch.setattr(ws_module, "_run_ddgs_search", fake_run_ddgs_search)

    first, failed1 = await ws_module.web_search_with_meta(
        query="fastapi latest version",
        max_results=5,
        timeout_seconds=5,
        cache_enabled=True,
        cache_ttl_seconds=600,
    )
    second, failed2 = await ws_module.web_search_with_meta(
        query="fastapi latest version",
        max_results=5,
        timeout_seconds=5,
        cache_enabled=True,
        cache_ttl_seconds=600,
    )
    assert not failed1 and not failed2
    assert calls["count"] == 1
    assert first and second
    assert first[0].url == second[0].url

