from __future__ import annotations

from app.guards.output_guard import OutputGuard


def test_output_guard_removes_internal_tool_markup() -> None:
    guard = OutputGuard()
    raw = (
        "<longcat_tool_call>search\n"
        "<longcat_arg_key>query</longcat_arg_key>\n"
        "<longcat_arg_value>weather</longcat_arg_value>\n"
        "</longcat_tool_call>\n"
        "Xin chao ban."
    )
    safe_text, meta, output_safety = guard.scan_text(raw)
    assert "<longcat_tool_call" not in safe_text
    assert "longcat_arg_key" not in safe_text
    assert "Xin chao ban." in safe_text
    assert meta.output_redacted is True
    assert "internal_tool_markup" in meta.categories
