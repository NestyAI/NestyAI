from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.config import load_models_config
from app.core.errors import ProviderError
from app.core.router import ProviderRouter
from app.deps import get_settings
from app.providers.base import BaseProvider
from app.schemas.chat import ChatMessage
from app.schemas.provider import ProviderChatResult
from app.storage.db import init_db
from app.storage.model_configs import upsert_model_override
from app.utils.logging import get_logger


class _DummyProvider(BaseProvider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self.calls = 0
        self.models: list[str] = []

    async def generate_chat_completion(self, messages, model, temperature, max_tokens):
        self.calls += 1
        self.models.append(model)
        return ProviderChatResult(provider=self.provider_name, content=f"{self.provider_name}:{model}")


class _FailingProvider(BaseProvider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self.calls = 0

    async def generate_chat_completion(self, messages, model, temperature, max_tokens):
        self.calls += 1
        raise ProviderError(provider=self.provider_name, message="model missing", retryable=False, status_code=404)


@pytest.mark.asyncio
async def test_runtime_override_provider_chain_used_by_router(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "runtime_effective_config.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    upsert_model_override(
        model_id="nesty-flash-1.0",
        config={"provider_chain": [{"provider": "openrouter", "model": "runtime-test-model"}]},
        db_path=db_path,
    )

    groq = _DummyProvider("groq")
    openrouter = _DummyProvider("openrouter")
    nvidia = _DummyProvider("nvidia")
    router = ProviderRouter(
        models_config=load_models_config(),
        providers={"groq": groq, "openrouter": openrouter, "nvidia": nvidia},
        logger=get_logger("test.runtime.effective"),
    )

    result = await router.route_chat(
        request_id="req_runtime",
        model_alias="nesty-flash-1.0",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_tokens=64,
    )
    assert result.provider_used == "openrouter"
    assert openrouter.calls == 1
    assert openrouter.models[-1] == "runtime-test-model"
    assert groq.calls == 0


def test_models_endpoint_backward_compatible_shape(client, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        "app.api.models.get_settings",
        lambda: type("S", (), {"require_api_key": False, "public_models": True})(),
    )
    headers = {}
    trusted_hosts = str(getattr(settings, "trusted_hosts", "") or "").strip()
    if trusted_hosts:
        first_host = trusted_hosts.split(",")[0].strip()
        if first_host:
            headers["host"] = first_host
    response = client.get("/v1/models", headers=headers or None)
    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    assert isinstance(payload["data"], list)
    assert all("id" in item for item in payload["data"])
    assert all("description" in item for item in payload["data"])


@pytest.mark.asyncio
async def test_runtime_override_provider_chain_falls_back_to_next_entry(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "runtime_override_fallback.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    upsert_model_override(
        model_id="nesty-flash-1.0",
        config={
            "provider_chain": [
                {"provider": "groq", "model": "missing-model"},
                {"provider": "ollama_cloud", "model": "gemma3:12b"},
            ]
        },
        db_path=db_path,
    )

    groq = _FailingProvider("groq")
    ollama = _DummyProvider("ollama_cloud")
    router = ProviderRouter(
        models_config=load_models_config(),
        providers={"groq": groq, "ollama_cloud": ollama},
        logger=get_logger("test.runtime.override.fallback"),
    )

    result = await router.route_chat(
        request_id="req_runtime_fallback",
        model_alias="nesty-flash-1.0",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_tokens=64,
    )
    assert result.provider_used == "ollama_cloud"
    assert groq.calls == 1
    assert ollama.calls == 1
