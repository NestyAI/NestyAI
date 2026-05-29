from __future__ import annotations

import pytest

from app.tools.wikipedia import execute_wikipedia_lookup


@pytest.mark.asyncio
async def test_wikipedia_lookup_parses_summary(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://en.wikipedia.org/w/api.php?action=query&format=json&list=search&srsearch=Who+is+Alan+Turing%3F&srlimit=1",
        json={"query": {"search": [{"title": "Alan Turing"}]}},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://en.wikipedia.org/api/rest_v1/page/summary/Alan%20Turing",
        json={
            "title": "Alan Turing",
            "extract": "Alan Turing was an English mathematician.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Alan_Turing"}},
        },
    )

    result = await execute_wikipedia_lookup("Who is Alan Turing?", {"timeout_seconds": 5})
    assert result.success is True
    assert result.data is not None
    assert result.data["title"] == "Alan Turing"
    assert "mathematician" in result.content
    assert result.sources

