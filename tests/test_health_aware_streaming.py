from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, Settings
from app.core.errors import APIError, ProviderError
from app.core.orchestrator import ChatOrchestrator
from app.core.router import ProviderRouter
from app.guards.context_guard import ContextGuard
from app.guards.input_guard import InputGuard
from app.guards.output_guard import OutputGuard
from app.providers.base import BaseProvider
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.schemas.provider import ProviderChatResult, ProviderStreamChunk, ProviderUsage
from app.tools.registry import ToolRegistry
from app.utils.logging import get_logger


class _DummyStreamProvider(BaseProvider):
    def __init__(self, provider_name: str, stream_behavior: Callable[[], AsyncIterator[ProviderStreamChunk]]) -> None:
        self.provider_name = provider_name
        self._stream_behavior = stream_behavior
        self.stream_calls = 0

    async def generate_chat_completion(self, messages, model, temperature, max_tokens):
        return ProviderChatResult(provider=self.provider_name, content="unused")

    async def stream_chat_completion(self, messages, model, temperature, max_tokens):
        self.stream_calls += 1
        async for chunk in self._stream_behavior():
            yield chunk


def _models_config() -> ModelsConfig:
    return ModelsConfig(
        models={
            "nesty-test": ModelProfile(
                display_name="Nesty Test",
                description="Test profile",
                strategy="balanced",
                search_mode="off",
                max_tool_calls=0,
                max_search_results=0,
                max_context_chars=1000,
                provider_chain=[
                    ProviderTarget(provider="groq", model="m1"),
                    ProviderTarget(provider="openrouter", model="m2"),
                ],
            )
        }
    )


def _settings(*, aware: bool, strict: bool):
    return type(
        "S",
        (),
        {
            "provider_health_aware_routing": aware,
            "provider_health_strict_mode": strict,
            "provider_health_ttl_seconds": 900,
            "provider_health_failure_threshold": 2,
            "provider_health_skip_statuses": "failed,unavailable,timeout",
            "provider_health_allow_stale_after_seconds": 3600,
        },
    )()


@pytest.mark.asyncio
async def test_streaming_router_skips_unhealthy_before_stream(monkeypatch) -> None:
    def _skip_decision(provider: str, model: str, model_alias: str | None, role: str | None, config):
        if provider == "groq":
            return {"healthy": False, "skip": True, "reason": "recent_failures"}
        return {"healthy": True, "skip": False, "reason": "healthy_recent"}

    monkeypatch.setattr("app.core.router.should_skip_provider_target", _skip_decision)

    async def _groq_stream():
        yield ProviderStreamChunk(delta="bad")

    async def _openrouter_stream():
        yield ProviderStreamChunk(delta="ok")
        yield ProviderStreamChunk(finish_reason="stop")

    groq = _DummyStreamProvider("groq", _groq_stream)
    openrouter = _DummyStreamProvider("openrouter", _openrouter_stream)
    router = ProviderRouter(
        models_config=_models_config(),
        providers={"groq": groq, "openrouter": openrouter},
        logger=get_logger("test.health.stream.router"),
        settings=_settings(aware=True, strict=False),
    )
    result = await router.route_chat_stream(
        request_id="req_health_stream_1",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.0,
        max_tokens=32,
    )
    collected: list[str] = []
    async for chunk in result.stream:
        if chunk.delta:
            collected.append(chunk.delta)
    assert "".join(collected) == "ok"
    assert groq.stream_calls == 0
    assert openrouter.stream_calls == 1
    assert result.provider_health is not None
    assert result.provider_health["aware_routing"] is True


@pytest.mark.asyncio
async def test_streaming_router_strict_blocks_when_all_skipped(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.router.should_skip_provider_target",
        lambda provider, model, model_alias, role, config: {"healthy": False, "skip": True, "reason": "recent_failures"},
    )

    async def _stream():
        yield ProviderStreamChunk(delta="x")

    router = ProviderRouter(
        models_config=_models_config(),
        providers={"groq": _DummyStreamProvider("groq", _stream)},
        logger=get_logger("test.health.stream.router"),
        settings=_settings(aware=True, strict=True),
    )
    with pytest.raises(APIError) as exc_info:
        await router.route_chat_stream(
            request_id="req_health_stream_2",
            model_alias="nesty-test",
            messages=[ChatMessage(role="user", content="hello")],
            temperature=0.0,
            max_tokens=32,
        )
    assert exc_info.value.code == "provider_health_strict_blocked"


@pytest.mark.asyncio
async def test_streaming_router_fallback_when_all_skipped_non_strict(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.router.should_skip_provider_target",
        lambda provider, model, model_alias, role, config: {"healthy": False, "skip": True, "reason": "recent_failures"},
    )

    async def _fail_first():
        raise ProviderError(provider="groq", message="temporary", retryable=True)
        yield ProviderStreamChunk(delta="x")

    async def _success_second():
        yield ProviderStreamChunk(delta="ok")
        yield ProviderStreamChunk(finish_reason="stop")

    groq = _DummyStreamProvider("groq", _fail_first)
    openrouter = _DummyStreamProvider("openrouter", _success_second)
    router = ProviderRouter(
        models_config=_models_config(),
        providers={"groq": groq, "openrouter": openrouter},
        logger=get_logger("test.health.stream.router"),
        settings=_settings(aware=True, strict=False),
    )
    result = await router.route_chat_stream(
        request_id="req_health_stream_3",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.0,
        max_tokens=32,
    )
    collected: list[str] = []
    async for chunk in result.stream:
        if chunk.delta:
            collected.append(chunk.delta)
    assert "".join(collected) == "ok"
    assert groq.stream_calls == 1
    assert openrouter.stream_calls == 1
    assert result.provider_health is not None
    assert result.provider_health["fallback_to_unhealthy_allowed"] is True


@dataclass
class _StreamRouteResult:
    provider_used: str
    stream: object
    provider_health: dict


class _StreamRouter:
    async def route_chat(self, request_id, model_alias, messages, temperature, max_tokens):
        raise AssertionError("non-stream path should not be used")

    async def route_chat_stream(self, request_id, model_alias, messages, temperature, max_tokens):
        async def _events():
            yield ProviderStreamChunk(delta="Hello")
            yield ProviderStreamChunk(
                finish_reason="stop",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        return _StreamRouteResult(
            provider_used="openrouter",
            stream=_events(),
            provider_health={
                "aware_routing": True,
                "strict_mode": False,
                "skipped_targets": [{"provider": "groq", "model": "m1", "reason": "recent_failures"}],
                "fallback_to_unhealthy_allowed": False,
                "all_targets_skipped": False,
            },
        )


def _orchestrator(db_path: str) -> ChatOrchestrator:
    models = ModelsConfig(
        models={
            "nesty-test": ModelProfile(
                display_name="test",
                description="test",
                strategy="balanced",
                search_mode="off",
                behavior_profile="balanced",
                max_tool_calls=0,
                max_search_results=0,
                max_context_chars=4000,
                provider_chain=[ProviderTarget(provider="dummy", model="dummy-model")],
            )
        }
    )
    settings = Settings(
        nesty_db_path=db_path,
        rate_limit_enabled=False,
        semantic_recall_enabled=False,
    )
    return ChatOrchestrator(
        router=_StreamRouter(),
        input_guard=InputGuard(),
        output_guard=OutputGuard(),
        context_guard=ContextGuard(),
        models_config=models,
        tool_registry=ToolRegistry(),
        guard_rules={"tools": {"search_timeout_seconds": 3}, "tool_context": {"max_chars": 4000}},
        settings=settings,
        enable_input_guard=True,
        enable_output_guard=True,
        logger=get_logger("test.health.stream.orch"),
    )


@pytest.mark.asyncio
async def test_stream_metadata_includes_provider_health(tmp_path) -> None:
    orchestrator = _orchestrator(str(tmp_path / "health_stream_metadata.db"))
    request = ChatCompletionRequest(
        model="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
        search="off",
        tools="off",
    )
    handle = await orchestrator.create_chat_completion_stream("req_stream_meta", request)
    payload = ""
    async for event in handle.events:
        payload += event

    metadata_lines = [
        line
        for line in payload.splitlines()
        if '"object":"chat.completion.metadata"' in line or '"object": "chat.completion.metadata"' in line
    ]
    assert metadata_lines
    raw = metadata_lines[0].split("data:", 1)[1].strip()
    data = json.loads(raw)
    assert data["provider_health"]["aware_routing"] is True
    assert data["provider_health"]["skipped_targets"][0]["provider"] == "groq"
