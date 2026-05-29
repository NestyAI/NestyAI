from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tools.planner import plan_tools
from app.tools.registry import ToolRegistry, ToolSpec, tool_registry
from app.tools.weather import extract_weather_location
from app.tools.exchange_rate import extract_exchange_request
from app.schemas.tools import ToolResult


async def main() -> int:
    print("Registered tools:")
    for spec in tool_registry.list_tools(enabled_only=True):
        print(f"- {spec.name}: {spec.description}")

    model_cfg = {
        "allowed_tools": ["calculator", "package_version_lookup"],
        "max_tool_calls": 2,
    }
    message = "calculate 15% of 2350000"
    planned = plan_tools(message, model_cfg, explicit_tools="auto")
    print("\nPlanned tools:", planned)

    if "calculator" in planned:
        result = await tool_registry.execute_tool("calculator", message, context={})
        print("\nCalculator result:")
        print(" success:", result.success)
        print(" content:", result.content)

    print("\nExchange parser demo:")
    ex = extract_exchange_request("đổi 100 USD sang VND")
    print(" parsed:", ex)

    print("\nWeather location parser demo:")
    wx = extract_weather_location("thời tiết ở TP.HCM hôm nay", default_location=None)
    print(" location:", wx)

    print("\nCache demo:")
    demo_registry = ToolRegistry()

    async def cached_echo(message: str, context: dict):
        return ToolResult(name="cached_echo", success=True, content=f"echo:{message}", confidence="high")

    demo_registry.register_tool(
        ToolSpec(
            name="cached_echo",
            description="Local cache demo tool",
            enabled=True,
            timeout_seconds=2,
            max_result_chars=200,
            execute=cached_echo,
            cache_enabled=True,
            cache_ttl_seconds=30,
        )
    )
    first = await demo_registry.execute_tool("cached_echo", "hello-cache", context={})
    second = await demo_registry.execute_tool("cached_echo", "hello-cache", context={})
    print(" cached_echo cache enabled:", demo_registry.get_tool("cached_echo").cache_enabled)
    print(" first cache_hit:", first.cache_hit)
    print(" second cache_hit:", second.cache_hit)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
