from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.schemas.tools import ToolResult


_VI_WEATHER_PATTERNS = [
    re.compile(r"thời\s*tiết\s*(?:ở\s*)?([a-zA-ZÀ-ỹ0-9 .,'-]{2,60})", flags=re.IGNORECASE),
]
_EN_WEATHER_PATTERNS = [
    re.compile(r"weather\s*(?:in\s*)?([a-zA-Z0-9 .,'-]{2,60})", flags=re.IGNORECASE),
]


def extract_weather_location(message: str, default_location: str | None = None) -> str | None:
    cleaned = " ".join(message.strip().split())
    if not cleaned:
        return default_location

    for pattern in _VI_WEATHER_PATTERNS + _EN_WEATHER_PATTERNS:
        matched = pattern.search(cleaned)
        if matched:
            location = matched.group(1).strip(" .?!,")
            location = re.sub(
                r"\b(hôm nay|ngày mai|now|today|tomorrow|forecast|dự báo)\b.*$",
                "",
                location,
                flags=re.IGNORECASE,
            ).strip(" .?!,")
            if location:
                return location
    return default_location


def _weather_code_text(code: int | None) -> str:
    mapping = {
        0: "clear",
        1: "mainly_clear",
        2: "partly_cloudy",
        3: "overcast",
        45: "fog",
        48: "depositing_rime_fog",
        51: "light_drizzle",
        53: "moderate_drizzle",
        55: "dense_drizzle",
        61: "slight_rain",
        63: "moderate_rain",
        65: "heavy_rain",
        71: "slight_snow",
        73: "moderate_snow",
        75: "heavy_snow",
        80: "rain_showers",
        95: "thunderstorm",
    }
    return mapping.get(code, "unknown")


async def execute_weather_lookup(message: str, context: dict[str, Any] | None = None) -> ToolResult:
    started = time.perf_counter()
    ctx = context or {}
    timeout_seconds = float(ctx.get("timeout_seconds", 6))
    allow_default = bool(ctx.get("allow_default_weather_location", False))
    default_location = str(ctx.get("default_weather_location", "")).strip() or None
    location = extract_weather_location(message, default_location if allow_default else None)
    if not location:
        return ToolResult(
            name="weather_lookup",
            success=False,
            content="Could not detect location for weather lookup.",
            error="location_not_detected",
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    geo_params = {"name": location, "count": 1}
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?{urlencode(geo_params)}"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            geo_resp = await client.get("https://geocoding-api.open-meteo.com/v1/search", params=geo_params)
            if geo_resp.status_code >= 400:
                raise ValueError("geocoding_failed")
            geo_data = geo_resp.json()
            results = geo_data.get("results", [])
            if not results:
                raise ValueError("location_not_found")

            place = results[0]
            lat = place.get("latitude")
            lon = place.get("longitude")
            if lat is None or lon is None:
                raise ValueError("location_not_found")

            forecast_params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,weather_code",
                "timezone": "auto",
            }
            forecast_resp = await client.get("https://api.open-meteo.com/v1/forecast", params=forecast_params)
            if forecast_resp.status_code >= 400:
                raise ValueError("forecast_failed")
            forecast_data = forecast_resp.json()
    except Exception as exc:
        error_code = str(exc) if str(exc) in {"location_not_found"} else "lookup_failed"
        return ToolResult(
            name="weather_lookup",
            success=False,
            content="Weather lookup failed.",
            error=error_code,
            confidence="low",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    current = forecast_data.get("current", {})
    temperature = current.get("temperature_2m")
    wind_speed = current.get("wind_speed_10m")
    weather_code = current.get("weather_code")
    timezone = str(forecast_data.get("timezone", ""))
    place_name = str(place.get("name", location))
    admin = str(place.get("admin1", "") or "")
    country = str(place.get("country", "") or "")
    forecast_url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,weather_code",
                "timezone": "auto",
            }
        )
    )

    summary = (
        f"Location: {place_name}"
        + (f", {admin}" if admin else "")
        + (f", {country}" if country else "")
        + f"\nCoordinates: {lat}, {lon}"
        + f"\nTemperature: {temperature} C"
        + f"\nWind speed: {wind_speed} km/h"
        + f"\nCondition: {_weather_code_text(weather_code)} (code {weather_code})"
        + f"\nTimezone: {timezone}"
        + f"\nSource: {forecast_url}"
    )
    return ToolResult(
        name="weather_lookup",
        success=True,
        content=summary,
        data={
            "location": place_name,
            "admin": admin,
            "country": country,
            "latitude": lat,
            "longitude": lon,
            "temperature_c": temperature,
            "wind_speed_kmh": wind_speed,
            "weather_code": weather_code,
            "condition": _weather_code_text(weather_code),
            "timezone": timezone,
            "geocoding_source": geo_url,
            "source_url": forecast_url,
        },
        sources=[
            {
                "title": f"Open-Meteo Weather: {place_name}",
                "url": forecast_url,
                "snippet": f"{_weather_code_text(weather_code)}, {temperature}C, wind {wind_speed}km/h",
            }
        ],
        confidence="medium",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
