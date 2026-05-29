from __future__ import annotations

import socket

import pytest

from app.tools.fetch_url import _is_safe_public_url, fetch_url_text


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://127.0.0.1",
        "http://0.0.0.0",
        "http://[::1]",
        "http://192.168.1.1",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://169.254.169.254",
        "http://metadata.google.internal",
        "file:///etc/passwd",
        "ftp://example.com/file.txt",
    ],
)
@pytest.mark.asyncio
async def test_fetch_url_blocks_unsafe_targets(url: str) -> None:
    result = await fetch_url_text(url)
    assert result.error in {"unsafe_url_blocked", "fetch_failed"}


def test_is_safe_public_url_allows_example_dot_com(monkeypatch) -> None:
    def fake_getaddrinfo(host: str, port: int, type: int = socket.SOCK_STREAM):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr("app.tools.fetch_url.socket.getaddrinfo", fake_getaddrinfo)
    is_safe, error_code = _is_safe_public_url("https://example.com")
    assert is_safe is True
    assert error_code is None

