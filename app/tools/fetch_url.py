from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.schemas.tools import FetchResult

try:
    import trafilatura
except Exception:  # pragma: no cover - optional fallback
    trafilatura = None


_BLOCKED_HOSTNAMES = {
    "localhost",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",
    "169.254.169.254",
}

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]


def _is_private_or_blocked_ip(ip_text: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    for network in _BLOCKED_NETWORKS:
        if ip_obj in network:
            return True
    return ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local


def _is_safe_public_url(url: str) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, "unsafe_url_blocked"
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "unsafe_url_blocked"
    if hostname in _BLOCKED_HOSTNAMES:
        return False, "unsafe_url_blocked"

    try:
        ipaddress.ip_address(hostname)
        if _is_private_or_blocked_ip(hostname):
            return False, "unsafe_url_blocked"
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "fetch_failed"

    for entry in addresses:
        ip_text = entry[4][0]
        if _is_private_or_blocked_ip(ip_text):
            return False, "unsafe_url_blocked"
    return True, None


def _extract_readable_text(html_text: str) -> tuple[str | None, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if trafilatura is not None:
        extracted = trafilatura.extract(html_text) or ""
        extracted = " ".join(extracted.split())
        if extracted:
            return title, extracted
    text = soup.get_text(separator=" ", strip=True)
    return title, " ".join(text.split())


async def fetch_url_text(
    url: str,
    timeout_seconds: float = 8.0,
    max_response_size_bytes: int = 2 * 1024 * 1024,
) -> FetchResult:
    is_safe, error_code = await asyncio.to_thread(_is_safe_public_url, url)
    if not is_safe:
        return FetchResult(
            url=url,
            error=error_code or "unsafe_url_blocked",
            blocked_reason=error_code or "unsafe_url_blocked",
        )

    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            response = await client.get(url, headers={"User-Agent": "NestyAI/0.2.0"})
    except Exception:
        return FetchResult(url=url, error="fetch_failed", blocked_reason="fetch_failed")

    content = response.content[: max_response_size_bytes + 1]
    if len(content) > max_response_size_bytes:
        return FetchResult(
            url=url,
            final_url=str(response.url),
            error="fetch_failed",
            status_code=response.status_code,
            blocked_reason="response_too_large",
        )

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" in content_type:
        html = content.decode(response.encoding or "utf-8", errors="ignore")
        title, text = _extract_readable_text(html)
        return FetchResult(
            url=url,
            final_url=str(response.url),
            title=title,
            text=text,
            error=None,
            status_code=response.status_code,
            content_chars=len(text),
        )

    text = content.decode(response.encoding or "utf-8", errors="ignore")
    normalized = " ".join(text.split())
    return FetchResult(
        url=url,
        final_url=str(response.url),
        title=None,
        text=normalized,
        error=None,
        status_code=response.status_code,
        content_chars=len(normalized),
    )
