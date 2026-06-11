from __future__ import annotations

from app.core.internal_tool_markup import sanitize_internal_tool_markup, strip_internal_tool_markup
from app.providers.content_extract import (
    extract_choice_message_content,
    extract_delta_content,
    extract_text_content,
)


def test_extract_text_content_from_string() -> None:
    assert extract_text_content("Hello world") == "Hello world"


def test_extract_text_content_from_text_parts_list() -> None:
    payload = [
        {"type": "text", "text": "Hello "},
        {"type": "text", "text": "world"},
    ]
    assert extract_text_content(payload) == "Hello world"


def test_extract_text_content_from_output_text_parts() -> None:
    payload = [{"type": "output_text", "text": "Answer from parts."}]
    assert extract_text_content(payload) == "Answer from parts."


def test_extract_text_content_ignores_non_text_parts() -> None:
    payload = [
        {"type": "reasoning", "text": "hidden chain"},
        {"type": "text", "text": "Visible answer."},
    ]
    assert extract_text_content(payload) == "Visible answer."


def test_extract_text_content_empty_list_returns_empty_string() -> None:
    assert extract_text_content([]) == ""


def test_extract_choice_message_content_openai_shape() -> None:
    choice = {"message": {"role": "assistant", "content": "Direct string."}}
    assert extract_choice_message_content(choice) == "Direct string."


def test_extract_choice_message_content_list_shape() -> None:
    choice = {
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "From list parts."}],
        }
    }
    assert extract_choice_message_content(choice) == "From list parts."


def test_extract_choice_message_content_fallback_text_field() -> None:
    choice = {"message": {"role": "assistant", "content": "", "text": "Legacy text field."}}
    assert extract_choice_message_content(choice) == "Legacy text field."


def test_extract_delta_content_string_and_list() -> None:
    assert extract_delta_content({"content": "delta"}) == "delta"
    assert extract_delta_content({"content": [{"type": "text", "text": "part"}]}) == "part"


def test_strip_internal_tool_markup_preserves_surrounding_prose() -> None:
    raw = (
        "Here is the intro.\n"
        "<longcat_tool_call>search\n"
        "<longcat_arg_key>query</longcat_arg_key>\n"
        "<longcat_arg_value>weather</longcat_arg_value>\n"
        "</longcat_tool_call>\n"
        "And here is the conclusion."
    )
    cleaned = strip_internal_tool_markup(raw)
    assert "Here is the intro." in cleaned
    assert "And here is the conclusion." in cleaned
    assert "<longcat_tool_call" not in cleaned


def test_sanitize_internal_tool_markup_preserves_surrounding_prose() -> None:
    raw = (
        "<longcat_tool_call>search</longcat_tool_call>\n"
        "User-facing answer remains."
    )
    cleaned, meta = sanitize_internal_tool_markup(raw)
    assert "User-facing answer remains." in cleaned
    assert meta["internal_tool_markup_detected"] is True
    assert meta["internal_tool_markup_removed"] is True
