from __future__ import annotations

from app.tools.registry import list_tool_trigger_keywords, tool_registry


def test_tool_registry_contains_expected_tools() -> None:
    names = set(tool_registry.list_tool_names())
    assert "calculator" in names
    assert "wikipedia_lookup" in names
    assert "package_version_lookup" in names
    assert "weather_lookup" in names
    assert "exchange_rate" in names


def test_tool_registry_tool_specs_have_required_fields() -> None:
    spec = tool_registry.get_tool("calculator")
    assert spec is not None
    assert spec.name == "calculator"
    assert spec.description
    assert spec.timeout_seconds > 0
    assert spec.max_result_chars > 0
    assert callable(spec.execute)


def test_tool_registry_exposes_trigger_keywords_for_planner() -> None:
    keywords = list_tool_trigger_keywords()
    assert "calculator" in keywords
    assert "weather_lookup" in keywords
    assert any("weather" in item.lower() for item in keywords["weather_lookup"])


def test_tool_errors_do_not_include_stack_traces() -> None:
    import asyncio

    spec = tool_registry.get_tool("calculator")
    assert spec is not None
    result = asyncio.run(spec.execute("hello without math", {}))
    assert result.success is False
    assert result.error == "invalid_expression"
    assert "Traceback" not in (result.content or "")

