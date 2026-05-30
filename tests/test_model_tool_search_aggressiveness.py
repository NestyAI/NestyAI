from __future__ import annotations

from app.tools.planner import plan_tools
from app.tools.search_intent import should_use_search


def test_flash_search_auto_is_more_conservative_than_pro() -> None:
    message = "Compare FastAPI and Flask for backend architecture"
    flash_cfg = {"search_mode": "auto", "search_aggressiveness": "low"}
    pro_cfg = {"search_mode": "auto", "search_aggressiveness": "high_when_needed"}
    assert should_use_search(message, flash_cfg, explicit_search_mode="auto") is False
    assert should_use_search(message, pro_cfg, explicit_search_mode="auto") is True


def test_flash_tool_auto_is_more_conservative_than_pro() -> None:
    message = "What is asyncio and compare it with threading"
    flash_cfg = {
        "allowed_tools": ["calculator", "wikipedia_lookup", "package_version_lookup", "weather_lookup", "exchange_rate"],
        "max_tool_calls": 4,
        "tool_aggressiveness": "low",
    }
    pro_cfg = {
        "allowed_tools": ["calculator", "wikipedia_lookup", "package_version_lookup", "weather_lookup", "exchange_rate"],
        "max_tool_calls": 4,
        "tool_aggressiveness": "high_when_needed",
    }
    planned_flash = plan_tools(message, flash_cfg, explicit_tools="auto")
    planned_pro = plan_tools(message, pro_cfg, explicit_tools="auto")

    assert "wikipedia_lookup" not in planned_flash
    assert "wikipedia_lookup" in planned_pro
