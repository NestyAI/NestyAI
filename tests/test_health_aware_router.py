from __future__ import annotations

from collections.abc import Callable

import pytest

from app.config import ModelProfile, ModelsConfig, ProviderTarget, load_models_config
from app.core.errors import APIError, ProviderError
from app.core.router import ProviderRouter
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult
from app.storage.db import init_db
from app.storage.model_configs import upsert_model_override
from app.utils.logging import get_logger


class _DummyProvider(BaseProvider):
    def __init__(self, provider_name: str, behavior: Callable[[], ProviderChatResult]) -> None:
        self.provider_name = provider_name
        self._behavior = behavior
        self.calls = 0

    async def generate_chat_completion(self, messages, model, temperature, max_tokens):
        self.calls += 1
        return self._behavior()


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
async def test_router_skips_unhealthy_and_uses_next_provider(monkeypatch) -> None:
    def _skip_decision(provider: str, model: str, model_alias: str | None, role: str | None, config):
        if provider == "groq":
            return {"healthy": False, "skip": True, "reason": "recent_failures"}
        return {"healthy": True, "skip": False, "reason": "healthy_recent"}

    monkeypatch.setattr("app.core.router.should_skip_provider_target", _skip_decision)
    groq = _DummyProvider("groq", lambda: ProviderChatResult(provider="groq", content="bad"))
    openrouter = _DummyProvider("openrouter", lambda: ProviderChatResult(provider="openrouter", content="ok"))
    router = ProviderRouter(
        models_config=_models_config(),
        providers={"groq": groq, "openrouter": openrouter},
        logger=get_logger("test.health.router"),
        settings=_settings(aware=True, strict=False),
    )
    result = await router.route_chat(
        request_id="req_health_1",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.0,
        max_tokens=32,
    )
    assert result.provider_used == "openrouter"
    assert groq.calls == 0
    assert openrouter.calls == 1
    assert result.provider_health is not None
    assert result.provider_health["aware_routing"] is True
    assert result.provider_health["skipped_targets"][0]["provider"] == "groq"


@pytest.mark.asyncio
async def test_router_fallbacks_when_all_skipped_and_strict_false(monkeypatch) -> None:
    def _skip_all(provider: str, model: str, model_alias: str | None, role: str | None, config):
        return {"healthy": False, "skip": True, "reason": "recent_failures"}

    monkeypatch.setattr("app.core.router.should_skip_provider_target", _skip_all)

    def _fail():
        raise ProviderError(provider="groq", message="temporary", retryable=True)

    groq = _DummyProvider("groq", _fail)
    openrouter = _DummyProvider("openrouter", lambda: ProviderChatResult(provider="openrouter", content="ok"))
    router = ProviderRouter(
        models_config=_models_config(),
        providers={"groq": groq, "openrouter": openrouter},
        logger=get_logger("test.health.router"),
        settings=_settings(aware=True, strict=False),
    )
    result = await router.route_chat(
        request_id="req_health_2",
        model_alias="nesty-test",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.0,
        max_tokens=32,
    )
    assert result.provider_used == "openrouter"
    assert groq.calls == 1
    assert openrouter.calls == 1
    assert result.provider_health is not None
    assert result.provider_health["fallback_to_unhealthy_allowed"] is True


@pytest.mark.asyncio
async def test_router_strict_mode_blocks_when_all_skipped(monkeypatch) -> None:
    def _skip_all(provider: str, model: str, model_alias: str | None, role: str | None, config):
        return {"healthy": False, "skip": True, "reason": "recent_failures"}

    monkeypatch.setattr("app.core.router.should_skip_provider_target", _skip_all)
    router = ProviderRouter(
        models_config=_models_config(),
        providers={"groq": _DummyProvider("groq", lambda: ProviderChatResult(provider="groq", content="x"))},
        logger=get_logger("test.health.router"),
        settings=_settings(aware=True, strict=True),
    )
    with pytest.raises(APIError) as exc_info:
        await router.route_chat(
            request_id="req_health_3",
            model_alias="nesty-test",
            messages=[ChatMessage(role="user", content="hello")],
            temperature=0.0,
            max_tokens=32,
        )
    assert exc_info.value.code == "provider_health_strict_blocked"


@pytest.mark.asyncio
async def test_runtime_override_chain_respected_with_health_skip(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "health_router_runtime_override.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    upsert_model_override(
        model_id="nesty-flash-1.0",
        config={
            "provider_chain": [
                {"provider": "groq", "model": "override-m1"},
                {"provider": "openrouter", "model": "override-m2"},
            ]
        },
        db_path=db_path,
    )

    def _skip_first(provider: str, model: str, model_alias: str | None, role: str | None, config):
        if provider == "groq" and model == "override-m1":
            return {"healthy": False, "skip": True, "reason": "recent_failures"}
        return {"healthy": True, "skip": False, "reason": "healthy_recent"}

    monkeypatch.setattr("app.core.router.should_skip_provider_target", _skip_first)
    groq = _DummyProvider("groq", lambda: ProviderChatResult(provider="groq", content="x"))
    openrouter = _DummyProvider("openrouter", lambda: ProviderChatResult(provider="openrouter", content="ok"))
    nvidia = _DummyProvider("nvidia", lambda: ProviderChatResult(provider="nvidia", content="x"))
    router = ProviderRouter(
        models_config=load_models_config(),
        providers={"groq": groq, "openrouter": openrouter, "nvidia": nvidia},
        logger=get_logger("test.health.router.runtime"),
        settings=_settings(aware=True, strict=False),
    )
    result = await router.route_chat(
        request_id="req_health_runtime",
        model_alias="nesty-flash-1.0",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.0,
        max_tokens=32,
    )
    assert result.provider_used == "openrouter"
    assert groq.calls == 0
    assert openrouter.calls == 1
