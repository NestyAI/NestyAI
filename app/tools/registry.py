from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.schemas.tools import ToolResult
from app.tools.calculator import execute_calculator
from app.tools.datetime_tool import get_current_datetime
from app.tools.exchange_rate import execute_exchange_rate
from app.tools.fetch_url import fetch_url_text
from app.tools.package_version import execute_package_version_lookup
from app.tools.weather import execute_weather_lookup
from app.tools.web_search import web_search_multi_with_meta, web_search_with_meta
from app.tools.wikipedia import execute_wikipedia_lookup
from app.utils.cache_keys import make_tool_cache_key
from app.utils.ttl_cache import TTLCache

ExecuteToolFunc = Callable[[str, dict[str, Any]], Awaitable[ToolResult] | ToolResult]


@dataclass
class ToolSpec:
    name: str
    description: str
    enabled: bool
    timeout_seconds: float
    max_result_chars: int
    execute: ExecuteToolFunc
    cache_enabled: bool = False
    cache_ttl_seconds: int = 0
    trigger_keywords: list[str] = field(default_factory=list)


class ToolRegistry:
    def __init__(self, cache: TTLCache[ToolResult] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._helpers: dict[str, Callable[..., Any]] = {}
        self._cache = cache or TTLCache[ToolResult](max_size=512)

    def register_tool(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def register_helper(self, name: str, fn: Callable[..., Any]) -> None:
        self._helpers[name] = fn

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self, enabled_only: bool = False) -> list[ToolSpec]:
        items = sorted(self._tools.values(), key=lambda item: item.name)
        if not enabled_only:
            return items
        return [item for item in items if item.enabled]

    def list_tool_names(self, enabled_only: bool = False) -> list[str]:
        return [spec.name for spec in self.list_tools(enabled_only=enabled_only)]

    def get_helper(self, name: str) -> Callable[..., Any] | None:
        return self._helpers.get(name)

    async def execute_tool(
        self,
        name: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        spec = self.get_tool(name)
        context_data = context or {}
        started = time.perf_counter()
        if spec is None:
            return ToolResult(
                name=name,
                success=False,
                content=f"Tool '{name}' is not registered.",
                error="unknown_tool",
                latency_ms=0,
            )
        if not spec.enabled:
            return ToolResult(
                name=name,
                success=False,
                content=f"Tool '{name}' is disabled.",
                error="tool_not_configured",
                latency_ms=0,
            )

        cache_key = ""
        if spec.cache_enabled and spec.cache_ttl_seconds > 0:
            cache_key = make_tool_cache_key(
                tool_name=spec.name,
                params={"message": message, "context": context_data},
            )
            cached = await self._cache.get(cache_key)
            if cached is not None:
                result = cached.model_copy(deep=True)
                result.cache_hit = True
                return result

        try:
            outcome = spec.execute(message, context_data)
            if asyncio.iscoroutine(outcome):
                result = await asyncio.wait_for(outcome, timeout=spec.timeout_seconds)
            else:
                result = outcome
        except asyncio.TimeoutError:
            return ToolResult(
                name=name,
                success=False,
                content=f"Tool '{name}' timed out.",
                error="tool_timeout",
                cache_hit=False,
                confidence="low",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception:
            return ToolResult(
                name=name,
                success=False,
                content=f"Tool '{name}' execution failed.",
                error="tool_execution_failed",
                cache_hit=False,
                confidence="low",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        result.cache_hit = False
        if len(result.content) > spec.max_result_chars:
            result.content = result.content[: spec.max_result_chars].rstrip()
            result.raw_truncated = True
        if result.latency_ms is None:
            result.latency_ms = int((time.perf_counter() - started) * 1000)
        if spec.cache_enabled and spec.cache_ttl_seconds > 0 and result.success and cache_key:
            await self._cache.set(cache_key, result.model_copy(deep=True), spec.cache_ttl_seconds)
        return result

    async def clear_cache(self) -> None:
        await self._cache.clear()

    def apply_cache_config(self, config: dict[str, Any]) -> None:
        for tool_name, settings in config.items():
            spec = self.get_tool(tool_name)
            if not spec or not isinstance(settings, dict):
                continue
            spec.cache_enabled = bool(settings.get("cache_enabled", spec.cache_enabled))
            ttl = int(settings.get("cache_ttl_seconds", spec.cache_ttl_seconds or 0))
            spec.cache_ttl_seconds = max(0, ttl)


def list_tool_trigger_keywords(registry: ToolRegistry | None = None) -> dict[str, list[str]]:
    source = registry or tool_registry
    keywords: dict[str, list[str]] = {}
    for spec in source.list_tools(enabled_only=True):
        if spec.trigger_keywords:
            keywords[spec.name] = list(spec.trigger_keywords)
    return keywords


tool_registry = ToolRegistry()

tool_registry.register_tool(
    ToolSpec(
        name="calculator",
        description="Compute safe arithmetic expressions.",
        enabled=True,
        timeout_seconds=2,
        max_result_chars=1000,
        execute=execute_calculator,
        cache_enabled=False,
        cache_ttl_seconds=0,
        trigger_keywords=["calculate", "compute", "tính", "%", "+", "-", "*", "/"],
    )
)
tool_registry.register_tool(
    ToolSpec(
        name="wikipedia_lookup",
        description="Lookup Wikipedia summary for general knowledge terms.",
        enabled=True,
        timeout_seconds=8,
        max_result_chars=3000,
        execute=execute_wikipedia_lookup,
        cache_enabled=True,
        cache_ttl_seconds=86400,
        trigger_keywords=["what is", "who is", "là gì", "định nghĩa", "khái niệm"],
    )
)
tool_registry.register_tool(
    ToolSpec(
        name="package_version_lookup",
        description="Lookup latest package version from PyPI/npm registries.",
        enabled=True,
        timeout_seconds=8,
        max_result_chars=3000,
        execute=execute_package_version_lookup,
        cache_enabled=True,
        cache_ttl_seconds=1800,
        trigger_keywords=["version", "release", "changelog", "npm", "pypi", "pip"],
    )
)
tool_registry.register_tool(
    ToolSpec(
        name="weather_lookup",
        description="Weather lookup via Open-Meteo geocoding + forecast APIs.",
        enabled=True,
        timeout_seconds=5,
        max_result_chars=1000,
        execute=execute_weather_lookup,
        cache_enabled=True,
        cache_ttl_seconds=600,
        trigger_keywords=["weather", "thời tiết", "forecast", "nhiệt độ"],
    )
)
tool_registry.register_tool(
    ToolSpec(
        name="exchange_rate",
        description="Exchange rate lookup via Frankfurter API.",
        enabled=True,
        timeout_seconds=5,
        max_result_chars=1000,
        execute=execute_exchange_rate,
        cache_enabled=True,
        cache_ttl_seconds=1800,
        trigger_keywords=["exchange rate", "tỷ giá", "currency", "USD", "VND"],
    )
)

# Internal helpers used by orchestrator search/fetch utilities.
tool_registry.register_helper("datetime.now", get_current_datetime)
tool_registry.register_helper("web.search", web_search_with_meta)
tool_registry.register_helper("web.search.multi", web_search_multi_with_meta)
tool_registry.register_helper("web.fetch_url_text", fetch_url_text)
