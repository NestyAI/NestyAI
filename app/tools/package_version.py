from __future__ import annotations

import re
import time
from typing import Any

import httpx

from app.schemas.tools import ToolResult


_STOPWORDS = {
    "latest",
    "version",
    "release",
    "changelog",
    "npm",
    "pypi",
    "pip",
    "package",
    "python",
    "node",
    "what",
    "is",
    "the",
    "of",
    "ban",
    "moi",
    "nhat",
    "phien",
}


def _detect_ecosystem(message: str, package_name: str) -> str:
    lowered = message.lower()
    if "npm" in lowered or package_name.startswith("@"):
        return "npm"
    if any(token in lowered for token in ("pip", "pypi", "python")):
        return "pypi"
    return "auto"


def _extract_package_name(message: str) -> str | None:
    backtick = re.search(r"`([^`]+)`", message)
    if backtick:
        return backtick.group(1).strip()

    scoped = re.search(r"(@[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+)", message)
    if scoped:
        return scoped.group(1).strip()

    candidates = re.findall(r"\b[a-zA-Z0-9][a-zA-Z0-9._-]{1,80}\b", message)
    for candidate in candidates:
        if candidate.lower() in _STOPWORDS:
            continue
        if candidate.isdigit():
            continue
        return candidate
    return None


def extract_package_name(message: str) -> str | None:
    return _extract_package_name(message)


async def _lookup_pypi(client: httpx.AsyncClient, package_name: str) -> ToolResult | None:
    response = await client.get(f"https://pypi.org/pypi/{package_name}/json")
    if response.status_code >= 400:
        return None
    data = response.json()
    info = data.get("info", {})
    latest = str(info.get("version", "")).strip()
    summary = str(info.get("summary", "")).strip()
    package_url = f"https://pypi.org/project/{package_name}/"
    release_date = None
    releases = data.get("releases", {}).get(latest, [])
    if releases:
        release_date = releases[-1].get("upload_time_iso_8601")

    content = (
        f"Package: {package_name}\n"
        f"Ecosystem: pypi\n"
        f"Latest version: {latest}\n"
        f"Summary: {summary or 'N/A'}\n"
        f"Release date: {release_date or 'N/A'}\n"
        f"Source: {package_url}"
    )
    return ToolResult(
        name="package_version_lookup",
        success=True,
        content=content,
        data={
            "package": package_name,
            "ecosystem": "pypi",
            "latest_version": latest,
            "summary": summary,
            "release_date": release_date,
            "url": package_url,
        },
        sources=[{"title": f"PyPI: {package_name}", "url": package_url, "snippet": summary or latest}],
        confidence="high",
    )


async def _lookup_npm(client: httpx.AsyncClient, package_name: str) -> ToolResult | None:
    response = await client.get(f"https://registry.npmjs.org/{package_name}")
    if response.status_code >= 400:
        return None
    data = response.json()
    latest = str(data.get("dist-tags", {}).get("latest", "")).strip()
    description = str(data.get("description", "")).strip()
    homepage = data.get("homepage") or f"https://www.npmjs.com/package/{package_name}"
    release_date = None
    if latest:
        release_date = data.get("time", {}).get(latest)

    content = (
        f"Package: {package_name}\n"
        f"Ecosystem: npm\n"
        f"Latest version: {latest}\n"
        f"Description: {description or 'N/A'}\n"
        f"Release date: {release_date or 'N/A'}\n"
        f"Source: {homepage}"
    )
    return ToolResult(
        name="package_version_lookup",
        success=True,
        content=content,
        data={
            "package": package_name,
            "ecosystem": "npm",
            "latest_version": latest,
            "summary": description,
            "release_date": release_date,
            "url": homepage,
        },
        sources=[{"title": f"npm: {package_name}", "url": str(homepage), "snippet": description or latest}],
        confidence="high",
    )


async def execute_package_version_lookup(message: str, context: dict[str, Any] | None = None) -> ToolResult:
    started = time.perf_counter()
    timeout_seconds = float((context or {}).get("timeout_seconds", 6))
    package_name = extract_package_name(message)
    if not package_name:
        return ToolResult(
            name="package_version_lookup",
            success=False,
            content="Could not detect package name.",
            error="package_not_detected",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    ecosystem = _detect_ecosystem(message, package_name)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            result: ToolResult | None = None
            if ecosystem == "npm":
                result = await _lookup_npm(client, package_name)
            elif ecosystem == "pypi":
                result = await _lookup_pypi(client, package_name)
            else:
                result = await _lookup_pypi(client, package_name)
                if not result:
                    result = await _lookup_npm(client, package_name)
    except Exception:
        return ToolResult(
            name="package_version_lookup",
            success=False,
            content="Package version lookup failed.",
            error="lookup_failed",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    if not result:
        return ToolResult(
            name="package_version_lookup",
            success=False,
            content=f"Package '{package_name}' was not found in registry lookups.",
            error="package_not_found",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    result.latency_ms = int((time.perf_counter() - started) * 1000)
    return result

