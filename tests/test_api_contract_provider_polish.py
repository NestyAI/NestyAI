from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.api.models import router as models_router
from app.config import Settings
from app.core.errors import APIError, build_error_response, validation_error_param
from app.core.orchestrator import StreamHandle, StreamOutcome
from app.main import create_app
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessage, GuardInfo, Usage
from app.schemas.tools import ToolMetadata
from app.security.api_key import generate_api_key
from app.storage.api_keys import create_api_key_record
from app.storage.db import init_db
from app.storage.usage import insert_usage_log


class _SuccessOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        return ChatCompletionResponse(
            id="chatcmpl_provider_polish",
            created=1700000000,
            model=request.model,
            provider="openrouter",
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Hello from NestyAI."),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            guard=GuardInfo(),
            tools=ToolMetadata(),
            sources=[],
            model_alias=request.model,
        )


class _StreamOrchestrator:
    async def create_chat_completion_stream(self, request_id: str, request) -> StreamHandle:
        async def events():
            yield (
                'data: {"id":"chatcmpl_stream","object":"chat.completion.chunk","created":1700000000,'
                '"model":"nesty-combined-1.0","provider":"groq","choices":[{"index":0,'
                '"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
            )
            yield (
                'data: {"id":"chatcmpl_stream","object":"chat.completion.metadata","created":1700000000,'
                '"model":"nesty-combined-1.0","provider":"groq","usage":{"prompt_tokens":1,'
                '"completion_tokens":1,"total_tokens":2},"model_alias":"nesty-combined-1.0"}\n\n'
            )
            yield "data: [DONE]\n\n"

        return StreamHandle(
            events=events(),
            outcome=StreamOutcome(provider="groq", status="success", assistant_content="Hi"),
        )


class _ProviderFailureOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        raise APIError(
            code="provider_unavailable",
            message="Provider unavailable for this request.",
            status_code=502,
            details={"attempted_providers": ["groq"], "provider_errors": [], "fallback_used": False},
        )


def _build_chat_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(models_router)
    app.include_router(chat_router)

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        payload = build_error_response(
            exc.code,
            exc.message,
            exc.details,
            status_code=exc.status_code,
        )
        return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        sanitized_errors = [dict(err) for err in exc.errors()]
        payload = build_error_response(
            code="invalid_request",
            message="Invalid request payload.",
            details={"errors": sanitized_errors},
            param=validation_error_param(sanitized_errors),
            status_code=400,
        )
        return JSONResponse(status_code=400, content=payload)

    return app


def _patch_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.models.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)


def _create_key(
    db_path: str,
    *,
    allowed_models: list[str] | None = None,
    daily_limit: int | None = None,
) -> str:
    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="provider-polish-key",
        raw_key=raw_key,
        hash_secret="secret123",
        allowed_models=allowed_models,
        daily_limit=daily_limit,
    )
    return raw_key


def test_models_list_openai_shape(monkeypatch) -> None:
    settings = Settings(app_env="development", require_api_key=False)
    _patch_settings(monkeypatch, settings)
    client = TestClient(create_app(settings))

    response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0

    for card in body["data"]:
        assert card["object"] == "model"
        assert "id" in card
        assert "created" in card
        assert isinstance(card["created"], int)
        assert card["owned_by"] == "nestyai"


def test_models_allowlist_filters_when_authenticated(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "models_allowlist.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=False,
        public_models=True,
    )
    _patch_settings(monkeypatch, settings)
    raw_key = _create_key(db_path, allowed_models=["nesty-flash-1.0"])

    client = TestClient(_build_chat_app(settings))
    response = client.get("/v1/models", headers={"Authorization": f"Bearer {raw_key}"})
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert ids == {"nesty-flash-1.0"}


def test_models_unrestricted_key_lists_all_public(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "models_unrestricted.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=False,
        public_models=True,
    )
    _patch_settings(monkeypatch, settings)
    raw_key = _create_key(db_path, allowed_models=None)

    client = TestClient(_build_chat_app(settings))
    response = client.get("/v1/models", headers={"Authorization": f"Bearer {raw_key}"})
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert "nesty-flash-1.0" in ids
    assert "nesty-combined-1.0" in ids
    assert "nesty-pro-1.0" in ids


def test_chat_openai_minimal_request(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "chat_minimal.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [
                {"role": "system", "content": "You are an AI assistant inside an external app."},
                {"role": "user", "content": "Hello"},
            ],
            "stream": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert isinstance(body["id"], str)
    assert isinstance(body["created"], int)
    assert body["model"] == "nesty-combined-1.0"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert "usage" in body
    assert "guard" in body


def test_chat_ignores_harmless_openai_sdk_fields(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "chat_sdk_fields.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
            "user": "external-user-123",
            "top_p": 0.9,
            "stop": ["END"],
            "presence_penalty": 0.1,
            "frequency_penalty": 0.2,
            "metadata": {"project": "example"},
            "tool_choice": "none",
            "response_format": {"type": "text"},
        },
    )
    assert response.status_code == 200


def test_streaming_openai_compatible_chunks(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "stream_polish.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _StreamOrchestrator())

    client = TestClient(_build_chat_app(settings))
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        data_lines = [line.strip() for line in response.iter_lines() if line.strip()]
        assert data_lines[-1] == "data: [DONE]"

        chunk = json.loads(data_lines[0][6:])
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["choices"][0]["delta"]["content"] == "Hi"

        metadata = json.loads(data_lines[1][6:])
        assert metadata["object"] == "chat.completion.metadata"


def test_error_missing_api_key_openai_like(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "err_missing.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401
    err = response.json()["error"]
    assert err["code"] == "missing_api_key"
    assert err["type"] == "authentication_error"
    assert "param" in err
    assert "details" in err


def test_error_invalid_api_key_openai_like(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "err_invalid.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer nsk_dev_invalid"},
    )
    assert response.status_code == 401
    err = response.json()["error"]
    assert err["code"] == "invalid_api_key"
    assert err["type"] == "authentication_error"


def test_error_invalid_model_stays_400(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "err_model.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=False, rate_limit_enabled=False)
    _patch_settings(monkeypatch, settings)

    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "does-not-exist-v999", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 400
    err = response.json()["error"]
    assert err["code"] == "invalid_model"
    assert err["type"] == "invalid_request_error"


def test_error_model_not_allowed_openai_like(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "err_allowed.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())
    raw_key = _create_key(db_path, allowed_models=["nesty-flash-1.0"])

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-pro-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403
    err = response.json()["error"]
    assert err["code"] == "model_not_allowed"
    assert err["type"] == "permission_error"


def test_error_quota_exceeded_openai_like(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "err_quota.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    raw_key = generate_api_key("dev")
    key_record = create_api_key_record(
        db_path=db_path,
        name="quota-key",
        raw_key=raw_key,
        daily_limit=1,
        hash_secret="secret123",
    )
    insert_usage_log(
        db_path=db_path,
        api_key_id=key_record["id"],
        request_id="req_quota_existing",
        model="nesty-flash-1.0",
        provider="openrouter",
        status="success",
    )

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-flash-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 429
    err = response.json()["error"]
    assert err["code"] == "daily_quota_exceeded"
    assert err["type"] == "rate_limit_error"
    assert err["details"]["quota_type"] == "daily"
    assert err["details"]["limit"] == 1
    assert err["details"]["openai_code_alias"] == "quota_exceeded"


def test_error_provider_failure_openai_like(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "err_provider.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=False, rate_limit_enabled=False)
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _ProviderFailureOrchestrator())

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 502
    err = response.json()["error"]
    assert err["code"] == "provider_unavailable"
    assert err["type"] == "provider_error"
    body_text = response.text.lower()
    assert "traceback" not in body_text
    assert "groq_api_key" not in body_text


def test_error_body_never_leaks_secrets(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "err_sanitize.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _ProviderFailureOrchestrator())

    client = TestClient(_build_chat_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer nsk_dev_invalid"},
    )
    body_text = response.text
    assert not re.search(r"nsk_(dev|live)_[A-Za-z0-9]+", body_text)
    assert "traceback" not in body_text.lower()
    assert "internal admin" not in body_text.lower()
