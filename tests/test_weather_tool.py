from __future__ import annotations

import re

import pytest

from app.tools.weather import execute_weather_lookup, extract_weather_location


def test_extract_weather_location_vi_en() -> None:
    assert extract_weather_location("thời tiết ở Hà Nội hôm nay", default_location=None) == "Hà Nội"
    assert extract_weather_location("weather in Tokyo now", default_location=None) == "Tokyo"


@pytest.mark.asyncio
async def test_weather_lookup_parses_mocked_api(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://geocoding-api\.open-meteo\.com/v1/search.*"),
        json={
            "results": [
                {
                    "name": "Ho Chi Minh City",
                    "admin1": "Ho Chi Minh",
                    "country": "Vietnam",
                    "latitude": 10.8231,
                    "longitude": 106.6297,
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://api\.open-meteo\.com/v1/forecast.*"),
        json={
            "timezone": "Asia/Ho_Chi_Minh",
            "current": {
                "temperature_2m": 31.2,
                "wind_speed_10m": 8.5,
                "weather_code": 1,
            },
        },
    )

    result = await execute_weather_lookup("thời tiết ở TP.HCM hôm nay", {"timeout_seconds": 5})
    assert result.success is True
    assert result.data is not None
    assert result.data["location"] == "Ho Chi Minh City"
    assert result.data["temperature_c"] == 31.2
    assert result.data["timezone"] == "Asia/Ho_Chi_Minh"
    assert result.confidence in {"medium", "high"}


@pytest.mark.asyncio
async def test_weather_lookup_missing_location_handled() -> None:
    result = await execute_weather_lookup(
        "thời tiết",
        {"allow_default_weather_location": False, "timeout_seconds": 5},
    )
    assert result.success is False
    assert result.error == "location_not_detected"


@pytest.mark.asyncio
async def test_weather_lookup_api_failure_returns_failed_result(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://geocoding-api\.open-meteo\.com/v1/search.*"),
        status_code=500,
        json={},
    )
    result = await execute_weather_lookup("weather in London", {"timeout_seconds": 5})
    assert result.success is False
    assert result.error in {"lookup_failed", "location_not_found"}

