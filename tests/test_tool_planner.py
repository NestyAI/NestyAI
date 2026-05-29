from __future__ import annotations

from app.tools.planner import plan_tools


def test_tool_planner_off_returns_empty() -> None:
    config = {"allowed_tools": ["calculator"], "max_tool_calls": 3}
    assert plan_tools("calculate 2+2", config, explicit_tools="off") == []


def test_tool_planner_explicit_list_filters_allowed() -> None:
    config = {"allowed_tools": ["calculator", "package_version_lookup"], "max_tool_calls": 3}
    planned = plan_tools(
        "anything",
        config,
        explicit_tools=["calculator", "wikipedia_lookup", "package_version_lookup"],
    )
    assert planned == ["calculator", "package_version_lookup"]


def test_tool_planner_respects_max_tool_calls() -> None:
    config = {
        "allowed_tools": [
            "calculator",
            "wikipedia_lookup",
            "package_version_lookup",
            "weather_lookup",
            "exchange_rate",
        ],
        "max_tool_calls": 1,
    }
    planned = plan_tools("What is the latest version and weather today?", config, explicit_tools="auto")
    assert len(planned) <= 1

