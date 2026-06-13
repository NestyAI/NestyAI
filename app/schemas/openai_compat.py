from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_TEXT_PART_TYPE = "text"
_UNSUPPORTED_PLACEHOLDER = "[unsupported content part: {type}]"
_MAX_WARNINGS = 8
_MAX_TOOL_NAMES = 32
_MAX_TOOL_NAME_LEN = 64
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_VALID_ROLES = frozenset({"system", "user", "assistant", "tool"})


class OpenAIContentPart(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    text: str | None = None


class ClientToolsCompatInfo(BaseModel):
    client_tools_count: int = 0
    client_tool_names: list[str] = Field(default_factory=list)
    client_tool_choice_mode: str | None = None
    client_tools_ignored: bool = True


def _content_part_dict(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        dumped = item.model_dump()
        if isinstance(dumped, dict):
            return dumped
    return None


def normalize_message_content(content: Any) -> tuple[str, list[str]]:
    """Coerce OpenAI message content to a single string for the internal pipeline."""
    warnings: list[str] = []

    def _add_warning(message: str) -> None:
        if len(warnings) < _MAX_WARNINGS:
            warnings.append(message)

    if content is None:
        _add_warning("message content was null; treated as empty string")
        return "", warnings
    if isinstance(content, str):
        return content, warnings
    if isinstance(content, list):
        parts: list[str] = []
        for index, item in enumerate(content):
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            part = _content_part_dict(item)
            if part is None:
                _add_warning(f"content part {index} ignored: unsupported shape")
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type == _TEXT_PART_TYPE:
                text_value = part.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
                else:
                    _add_warning(f"content part {index} text field missing or invalid")
                continue
            if part_type:
                parts.append(_UNSUPPORTED_PLACEHOLDER.format(type=part_type))
                _add_warning(f"unsupported content part type: {part_type}")
            else:
                _add_warning(f"content part {index} missing type")
        return "".join(parts), warnings
    _add_warning("message content had unsupported type; treated as empty string")
    return "", warnings


def normalize_messages(raw_messages: list[Any]) -> tuple[list[tuple[str, str]], list[str]]:
    """Normalize incoming chat messages to (role, string content) pairs."""
    normalized: list[tuple[str, str]] = []
    all_warnings: list[str] = []

    for index, item in enumerate(raw_messages):
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
        elif hasattr(item, "role") and hasattr(item, "content"):
            role = item.role
            content = item.content
        elif hasattr(item, "model_dump"):
            dumped = item.model_dump()
            role = dumped.get("role")
            content = dumped.get("content")
        else:
            all_warnings.append(f"message {index} ignored: unsupported shape")
            continue

        role_str = str(role or "").strip()
        if role_str not in _VALID_ROLES:
            all_warnings.append(f"message {index} has invalid role")
            continue

        text, warnings = normalize_message_content(content)
        for warning in warnings:
            if len(all_warnings) < _MAX_WARNINGS:
                all_warnings.append(f"messages[{index}]: {warning}")
        normalized.append((role_str, text))

    return normalized, all_warnings


def is_openai_function_tools(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    if not value:
        return True
    for item in value:
        if not isinstance(item, dict):
            return False
        if str(item.get("type") or "").strip().lower() != "function":
            return False
        function_block = item.get("function")
        if not isinstance(function_block, dict):
            return False
    return True


def _sanitize_tool_name(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    candidate = name.strip()[:_MAX_TOOL_NAME_LEN]
    if not candidate or not _TOOL_NAME_PATTERN.match(candidate):
        return None
    return candidate


def _tool_choice_mode(tool_choice: Any) -> str | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        mode = tool_choice.strip().lower()
        return mode[:32] if mode else None
    if isinstance(tool_choice, dict):
        choice_type = str(tool_choice.get("type") or "").strip().lower()
        if choice_type:
            return choice_type[:32]
        function_block = tool_choice.get("function")
        if isinstance(function_block, dict):
            name = _sanitize_tool_name(function_block.get("name"))
            if name:
                return f"function:{name}"[:32]
    return "object"


def extract_client_tools_metadata(
    tools: list[dict[str, Any]],
    tool_choice: Any,
) -> ClientToolsCompatInfo:
    names: list[str] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        function_block = item.get("function")
        if not isinstance(function_block, dict):
            continue
        name = _sanitize_tool_name(function_block.get("name"))
        if name and name not in names:
            names.append(name)
        if len(names) >= _MAX_TOOL_NAMES:
            break
    return ClientToolsCompatInfo(
        client_tools_count=len(tools) if isinstance(tools, list) else 0,
        client_tool_names=names,
        client_tool_choice_mode=_tool_choice_mode(tool_choice),
        client_tools_ignored=True,
    )


def resolve_tools_mode(
    tools: str | list[str] | list[dict[str, Any]],
    tool_choice: Any,
) -> tuple[str | list[str], ClientToolsCompatInfo | None]:
    if is_openai_function_tools(tools):
        metadata = extract_client_tools_metadata(tools if isinstance(tools, list) else [], tool_choice)
        return "auto", metadata
    if isinstance(tools, str):
        return tools, None
    if isinstance(tools, list) and all(isinstance(item, str) for item in tools):
        return tools, None
    return "auto", None


IncomingMessageRole = Literal["system", "user", "assistant", "tool"]


class IncomingChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: IncomingMessageRole
    content: str | list[OpenAIContentPart | dict[str, Any]] | None = None
