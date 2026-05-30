from __future__ import annotations

import re


_TOOL_KEYWORDS: dict[str, list[str]] = {
    "calculator": [
        "calculate",
        "compute",
        "tính",
        "bao nhiêu",
        "%",
        "+",
        "-",
        "*",
        "/",
        " chia ",
        " nhân ",
    ],
    "wikipedia_lookup": [
        "là gì",
        "who is",
        "what is",
        "define",
        "khái niệm",
        "định nghĩa",
    ],
    "package_version_lookup": [
        "latest version",
        " version ",
        "release",
        "changelog",
        "npm",
        "pypi",
        "pip",
        "package",
        "phiên bản",
        "bản mới nhất",
    ],
    "weather_lookup": [
        "weather",
        "thời tiết",
        "nhiệt độ",
        "rain",
        "mưa",
        "forecast",
        "dự báo",
    ],
    "exchange_rate": [
        "exchange rate",
        "tỷ giá",
        "usd",
        "vnd",
        "eur",
        "jpy",
        "krw",
        "đổi tiền",
        "currency",
    ],
}


def _detect_tools_auto(message: str) -> list[str]:
    normalized = f" {re.sub(r'\\s+', ' ', message.lower()).strip()} "
    detected: list[str] = []
    for tool_name in (
        "calculator",
        "package_version_lookup",
        "weather_lookup",
        "exchange_rate",
        "wikipedia_lookup",
    ):
        for keyword in _TOOL_KEYWORDS[tool_name]:
            if keyword in normalized:
                detected.append(tool_name)
                break
    return detected


def _detect_tools_low(message: str) -> list[str]:
    normalized = f" {re.sub(r'\\s+', ' ', message.lower()).strip()} "
    detected: list[str] = []

    if any(keyword in normalized for keyword in ["calculate", "compute", "tính", "+", "-", "*", "/", " chia ", " nhân "]):
        detected.append("calculator")
    if any(keyword in normalized for keyword in ["weather", "thời tiết", "forecast", "dự báo", "temperature", "nhiệt độ"]):
        detected.append("weather_lookup")
    if any(keyword in normalized for keyword in ["exchange rate", "tỷ giá", "currency", "đổi tiền", " usd ", " eur ", " vnd "]):
        detected.append("exchange_rate")
    if any(keyword in normalized for keyword in ["latest version", " version ", "release", "changelog", "npm", "pypi", "pip", "package", "phiên bản"]):
        detected.append("package_version_lookup")
    return detected


def _detect_tools_high_when_needed(message: str) -> list[str]:
    normalized = f" {re.sub(r'\\s+', ' ', message.lower()).strip()} "
    detected = _detect_tools_auto(message)
    if any(keyword in normalized for keyword in ["compare", "comparison", "define", "what is", "who is", "là gì", "khái niệm"]):
        detected.append("wikipedia_lookup")
    return detected


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def plan_tools(
    message: str,
    model_config: dict,
    explicit_tools: str | list[str] | None = None,
) -> list[str]:
    allowed_tools = set(model_config.get("allowed_tools", []))
    max_tool_calls = int(model_config.get("max_tool_calls", 0))
    if max_tool_calls <= 0:
        return []

    explicit: str | list[str] | None = explicit_tools
    if isinstance(explicit, str):
        mode = explicit.strip().lower()
        if mode == "off":
            return []
        if mode == "auto" or mode == "":
            aggressiveness = str(model_config.get("tool_aggressiveness", "auto")).strip().lower()
            if aggressiveness == "low":
                planned = _detect_tools_low(message)
            elif aggressiveness == "high_when_needed":
                planned = _detect_tools_high_when_needed(message)
            else:
                planned = _detect_tools_auto(message)
            planned = [name for name in planned if name in allowed_tools]
            return _dedupe_preserve(planned)[:max_tool_calls]
        return []

    if isinstance(explicit, list):
        planned = [str(name) for name in explicit]
        planned = [name for name in planned if name in allowed_tools]
        return _dedupe_preserve(planned)[:max_tool_calls]

    aggressiveness = str(model_config.get("tool_aggressiveness", "auto")).strip().lower()
    if aggressiveness == "low":
        planned = _detect_tools_low(message)
    elif aggressiveness == "high_when_needed":
        planned = _detect_tools_high_when_needed(message)
    else:
        planned = _detect_tools_auto(message)
    planned = [name for name in planned if name in allowed_tools]
    return _dedupe_preserve(planned)[:max_tool_calls]
