from __future__ import annotations

import pytest

from app.tools.calculator import execute_calculator


@pytest.mark.asyncio
async def test_calculator_basic_arithmetic() -> None:
    result = await execute_calculator("calculate (2 + 3) * 4", {})
    assert result.success is True
    assert "20" in result.content
    assert result.data is not None
    assert result.data["result"] == 20


@pytest.mark.asyncio
async def test_calculator_percentage_expression() -> None:
    result = await execute_calculator("15% of 2350000", {})
    assert result.success is True
    assert result.data is not None
    assert result.data["result"] == 352500


@pytest.mark.asyncio
async def test_calculator_rejects_unsafe_expression() -> None:
    result = await execute_calculator("__import__('os').system('dir')", {})
    assert result.success is False
    assert result.error in {"invalid_expression"}

