from __future__ import annotations

import pytest

from app.schemas.tools import ToolResult
from app.tools.registry import ToolRegistry, ToolSpec


@pytest.mark.asyncio
async def test_tool_cache_success_result_cached() -> None:
    counter = {"count": 0}

    async def exec_tool(message: str, context: dict):
        counter["count"] += 1
        return ToolResult(name="t", success=True, content=f"ok-{counter['count']}", confidence="high")

    registry = ToolRegistry()
    registry.register_tool(
        ToolSpec(
            name="demo_tool",
            description="demo",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=exec_tool,
            cache_enabled=True,
            cache_ttl_seconds=60,
        )
    )

    first = await registry.execute_tool("demo_tool", "hello", {})
    second = await registry.execute_tool("demo_tool", "hello", {})
    assert first.success and second.success
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.content == first.content
    assert counter["count"] == 1


@pytest.mark.asyncio
async def test_tool_cache_failed_result_not_cached() -> None:
    counter = {"count": 0}

    async def exec_tool(message: str, context: dict):
        counter["count"] += 1
        return ToolResult(name="t", success=False, content="fail", error="tool_execution_failed")

    registry = ToolRegistry()
    registry.register_tool(
        ToolSpec(
            name="demo_tool",
            description="demo",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=1000,
            execute=exec_tool,
            cache_enabled=True,
            cache_ttl_seconds=60,
        )
    )

    first = await registry.execute_tool("demo_tool", "hello", {})
    second = await registry.execute_tool("demo_tool", "hello", {})
    assert first.success is False and second.success is False
    assert first.cache_hit is False and second.cache_hit is False
    assert counter["count"] == 2

