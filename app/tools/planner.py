from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from app.tools.calculator import extract_calculator_expression
from app.tools.exchange_rate import extract_exchange_request
from app.tools.package_version import extract_package_name
from app.tools.weather import extract_weather_location


@dataclass(slots=True)
class ToolPlanDecision:
    decision: str = "unknown"
    tools_planned: list[str] = field(default_factory=list)
    reason: str | None = None
    clarification_needed: bool = False
    clarification_reason: str | None = None


_TOOL_KEYWORDS: dict[str, list[str]] = {
    "calculator": [
        "calculate",
        "compute",
        "tinh",
        "bao nhieu",
        "%",
        "+",
        "-",
        "*",
        "/",
        " chia ",
        " nhan ",
    ],
    "wikipedia_lookup": [
        "what is",
        "who is",
        "define",
        "definition",
        "la gi",
        "dinh nghia",
        "khai niem",
        "ai la",
    ],
    "package_version_lookup": [
        "latest version",
        "version",
        "release",
        "changelog",
        "npm",
        "pypi",
        "pip",
        "package",
        "phan ban",
        "ban moi nhat",
    ],
    "weather_lookup": [
        "weather",
        "thoi tiet",
        "nhiet do",
        "rain",
        "mua",
        "forecast",
        "du bao",
    ],
    "exchange_rate": [
        "exchange rate",
        "ty gia",
        "doi tien",
        "currency",
        "convert",
    ],
}

_PACKAGE_INTENT_TERMS = [
    "latest version",
    "release",
    "changelog",
    "npm",
    "pypi",
    "pip",
    "package",
    "phan ban",
    "ban moi nhat",
]

_WEATHER_INTENT_TERMS = [
    "weather",
    "thoi tiet",
    "forecast",
    "du bao",
    "temperature",
    "nhiet do",
    "rain",
    "mua",
]

_EXCHANGE_INTENT_TERMS = [
    "exchange rate",
    "ty gia",
    "doi tien",
    "currency",
    "convert",
]

_WIKIPEDIA_INTENT_TERMS = [
    "what is",
    "who is",
    "define",
    "definition",
    "la gi",
    "dinh nghia",
    "khai niem",
    "ai la",
]

_REPO_OR_CODE_TERMS = [
    "repo",
    "repository",
    "project",
    "local",
    "file",
    "code",
    "bug",
    "error",
    "traceback",
    "stack trace",
    "debug",
    "troubleshoot",
    "fix",
]


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\s+", " ", normalized.lower()).strip()
    return normalized


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _has_any(normalized: str, phrases: list[str]) -> bool:
    return any(phrase in normalized for phrase in phrases)


def _looks_like_wikipedia_intent(normalized: str) -> bool:
    if _has_any(normalized, _REPO_OR_CODE_TERMS):
        return False
    return _has_any(normalized, _WIKIPEDIA_INTENT_TERMS)


def _looks_like_package_intent(normalized: str) -> bool:
    return _has_any(normalized, _PACKAGE_INTENT_TERMS)


def _looks_like_weather_intent(normalized: str) -> bool:
    return _has_any(normalized, _WEATHER_INTENT_TERMS)


def _looks_like_exchange_intent(normalized: str) -> bool:
    return _has_any(normalized, _EXCHANGE_INTENT_TERMS)


def _looks_like_calculator_intent(normalized: str) -> bool:
    if not bool(re.search(r"[0-9]", normalized)):
        return False
    return bool(re.search(r"[+\-*/%()]", normalized)) or " of " in normalized


def _detect_tools_auto(message: str) -> list[str]:
    normalized = f" {_normalize_text(message)} "
    detected: list[str] = []
    expression = extract_calculator_expression(message)
    if expression:
        detected.append("calculator")
    package_name = extract_package_name(message)
    if package_name and _looks_like_package_intent(normalized):
        detected.append("package_version_lookup")
    if _looks_like_weather_intent(normalized) and extract_weather_location(message, None):
        detected.append("weather_lookup")
    if extract_exchange_request(message) is not None or _looks_like_exchange_intent(normalized):
        if extract_exchange_request(message) is not None:
            detected.append("exchange_rate")
    if _looks_like_wikipedia_intent(normalized):
        detected.append("wikipedia_lookup")
    return detected


def _missing_required_tool_reason(message: str, normalized: str, allowed_tools: set[str]) -> str | None:
    if "calculator" in allowed_tools and _looks_like_calculator_intent(normalized) and not extract_calculator_expression(message):
        return "calculator_expression_missing"
    if "weather_lookup" in allowed_tools and _looks_like_weather_intent(normalized) and not extract_weather_location(message, None):
        return "weather_location_missing"
    if "exchange_rate" in allowed_tools and _looks_like_exchange_intent(normalized) and extract_exchange_request(message) is None:
        return "exchange_pair_missing"
    if "package_version_lookup" in allowed_tools and _looks_like_package_intent(normalized) and not extract_package_name(message):
        return "package_name_missing"
    if "wikipedia_lookup" in allowed_tools and _looks_like_wikipedia_intent(normalized) and not _has_any(normalized, _WIKIPEDIA_INTENT_TERMS):
        return "wikipedia_entity_missing"
    return None


def _detect_tools_low(message: str) -> list[str]:
    normalized = f" {_normalize_text(message)} "
    detected: list[str] = []

    if extract_calculator_expression(message):
        detected.append("calculator")
    if _looks_like_weather_intent(normalized) and extract_weather_location(message, None):
        detected.append("weather_lookup")
    if _looks_like_exchange_intent(normalized) and extract_exchange_request(message) is not None:
        detected.append("exchange_rate")
    if _looks_like_package_intent(normalized) and extract_package_name(message):
        detected.append("package_version_lookup")
    return detected


def _detect_tools_high_when_needed(message: str) -> list[str]:
    normalized = f" {_normalize_text(message)} "
    detected = _detect_tools_auto(message)
    if _looks_like_wikipedia_intent(normalized):
        detected.append("wikipedia_lookup")
    return detected


def _detect_tools_with_validation(message: str, model_config: dict, explicit_tools: str | list[str] | None = None) -> ToolPlanDecision:
    allowed_tools = set(model_config.get("allowed_tools", []))
    max_tool_calls = int(model_config.get("max_tool_calls", 0))
    if max_tool_calls <= 0:
        return ToolPlanDecision(decision="forced_off", tools_planned=[], reason="max_tool_calls_disabled")

    explicit: str | list[str] | None = explicit_tools
    if isinstance(explicit, str):
        mode = explicit.strip().lower()
        if mode == "off":
            return ToolPlanDecision(decision="forced_off", tools_planned=[], reason="forced_off")
        if mode not in {"auto", ""}:
            return ToolPlanDecision(decision="unknown", tools_planned=[], reason="unknown_tools_mode")

    normalized = f" {_normalize_text(message)} "
    selected: list[str] = []
    clarification_needed = False
    clarification_reason: str | None = None

    if isinstance(explicit, list):
        candidates = [str(name) for name in explicit if str(name) in allowed_tools]
        for tool_name in candidates:
            if tool_name == "calculator":
                if extract_calculator_expression(message):
                    selected.append(tool_name)
                elif _looks_like_calculator_intent(normalized):
                    clarification_needed = True
                    clarification_reason = clarification_reason or "calculator_expression_missing"
            elif tool_name == "weather_lookup":
                if extract_weather_location(message, None):
                    selected.append(tool_name)
                elif _looks_like_weather_intent(normalized):
                    clarification_needed = True
                    clarification_reason = clarification_reason or "weather_location_missing"
            elif tool_name == "exchange_rate":
                if extract_exchange_request(message) is not None:
                    selected.append(tool_name)
                elif _looks_like_exchange_intent(normalized):
                    clarification_needed = True
                    clarification_reason = clarification_reason or "exchange_pair_missing"
            elif tool_name == "package_version_lookup":
                if extract_package_name(message):
                    selected.append(tool_name)
                elif _looks_like_package_intent(normalized):
                    clarification_needed = True
                    clarification_reason = clarification_reason or "package_name_missing"
            elif tool_name == "wikipedia_lookup":
                if _looks_like_wikipedia_intent(normalized):
                    selected.append(tool_name)
                elif _has_any(normalized, _WIKIPEDIA_INTENT_TERMS):
                    clarification_needed = True
                    clarification_reason = clarification_reason or "wikipedia_entity_missing"

        selected = _dedupe_preserve(selected)[:max_tool_calls]
        missing_reason = _missing_required_tool_reason(message, normalized, allowed_tools)
        if selected:
            return ToolPlanDecision(
                decision="tool_selected",
                tools_planned=selected,
                reason="explicit_tools",
                clarification_needed=bool(clarification_needed or missing_reason),
                clarification_reason=clarification_reason or missing_reason,
            )
        if clarification_needed or missing_reason:
            return ToolPlanDecision(
                decision="missing_required_parameters",
                tools_planned=[],
                reason=clarification_reason or missing_reason or "missing_required_parameters",
                clarification_needed=True,
                clarification_reason=clarification_reason or missing_reason,
            )
        return ToolPlanDecision(decision="no_tool_needed", tools_planned=[], reason="explicit_tools_no_match")

    aggressiveness = str(model_config.get("tool_aggressiveness", "auto")).strip().lower()
    planned: list[str] = []

    if aggressiveness == "low":
        if extract_calculator_expression(message):
            planned.append("calculator")
        if _looks_like_package_intent(normalized) and extract_package_name(message):
            planned.append("package_version_lookup")
        if _looks_like_weather_intent(normalized) and extract_weather_location(message, None):
            planned.append("weather_lookup")
        if _looks_like_exchange_intent(normalized) and extract_exchange_request(message) is not None:
            planned.append("exchange_rate")
    elif aggressiveness == "high_when_needed":
        planned = _detect_tools_high_when_needed(message)
    else:
        planned = _detect_tools_auto(message)

    planned = [name for name in planned if name in allowed_tools]
    planned = _dedupe_preserve(planned)[:max_tool_calls]
    missing_reason = _missing_required_tool_reason(message, normalized, allowed_tools)

    if planned:
        return ToolPlanDecision(
            decision="tool_selected",
            tools_planned=planned,
            reason="auto_planner",
            clarification_needed=bool(missing_reason),
            clarification_reason=missing_reason,
        )

    if missing_reason:
        return ToolPlanDecision(
            decision="missing_required_parameters",
            tools_planned=[],
            reason=missing_reason,
            clarification_needed=True,
            clarification_reason=missing_reason,
        )

    return ToolPlanDecision(decision="no_tool_needed", tools_planned=[], reason="no_deterministic_tool_intent")


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


def plan_tools_decision(
    message: str,
    model_config: dict,
    explicit_tools: str | list[str] | None = None,
) -> ToolPlanDecision:
    return _detect_tools_with_validation(message, model_config, explicit_tools=explicit_tools)
