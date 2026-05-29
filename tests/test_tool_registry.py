from __future__ import annotations

from app.tools.registry import tool_registry


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

