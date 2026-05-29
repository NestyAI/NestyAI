from __future__ import annotations

from app.utils.sse import format_sse_data, parse_sse_data_line


def test_format_sse_data_with_dict() -> None:
    event = format_sse_data({"object": "chat.completion.chunk", "ok": True})
    assert event.startswith("data: {")
    assert event.endswith("\n\n")


def test_format_sse_data_with_done_marker() -> None:
    event = format_sse_data("[DONE]")
    assert event == "data: [DONE]\n\n"


def test_parse_sse_data_line() -> None:
    assert parse_sse_data_line("data: [DONE]") == "[DONE]"
    assert parse_sse_data_line("event: message") is None
