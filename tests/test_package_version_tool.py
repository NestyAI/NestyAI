from __future__ import annotations

import pytest

from app.tools.package_version import execute_package_version_lookup


@pytest.mark.asyncio
async def test_package_version_lookup_pypi(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://pypi.org/pypi/fastapi/json",
        json={
            "info": {"version": "1.2.3", "summary": "FastAPI framework"},
            "releases": {"1.2.3": [{"upload_time_iso_8601": "2026-01-01T00:00:00Z"}]},
        },
    )
    result = await execute_package_version_lookup("latest version of fastapi on pypi", {"timeout_seconds": 5})
    assert result.success is True
    assert result.data is not None
    assert result.data["ecosystem"] == "pypi"
    assert result.data["latest_version"] == "1.2.3"


@pytest.mark.asyncio
async def test_package_version_lookup_npm(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://registry.npmjs.org/react",
        json={
            "dist-tags": {"latest": "19.0.0"},
            "description": "React package",
            "homepage": "https://react.dev",
            "time": {"19.0.0": "2026-02-01T00:00:00Z"},
        },
    )
    result = await execute_package_version_lookup("npm react latest version", {"timeout_seconds": 5})
    assert result.success is True
    assert result.data is not None
    assert result.data["ecosystem"] == "npm"
    assert result.data["latest_version"] == "19.0.0"

