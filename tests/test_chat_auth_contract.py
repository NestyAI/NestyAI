from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.models import router as models_router
from app.config import Settings
from app.core.errors import APIError, build_error_response
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessage, GuardInfo, Usage
from app.schemas.tools import ToolMetadata
from app.security.api_key import generate_api_key
from app.security.rate_limit import get_rate_limiter
from app.storage.api_keys import create_api_key_record
from app.storage.db import init_db


class _SuccessOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        return ChatCompletionResponse(
            id="chatcmpl_test",
            created=1700000000,
            model=request.model,
            provider="openrouter",
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=2, completion_tokens=2, total_tokens=4),
            guard=GuardInfo(),
            tools=ToolMetadata(),
            sources=[],
        )


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(models_router)
    app.include_router(chat_router)

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        payload = build_error_response(exc.code, exc.message, exc.details)
        return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        payload = build_error_response(
            code="invalid_request",
            message="Invalid request payload.",
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=400, content=payload)

    return app


def _patch_phase4_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.health.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.models.get_settings", lambda: settings)


def test_chat_requires_key_when_enabled(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "chat_auth.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        public_health=True,
        public_models=True,
        rate_limit_enabled=False,
    )
    _patch_phase4_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())
    get_rate_limiter().reset()

    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "search": "off",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


def test_chat_works_with_valid_key(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "chat_valid.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_phase4_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="valid-key",
        raw_key=raw_key,
        hash_secret="secret123",
    )
    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "search": "off",
        },
    )
    assert response.status_code == 200


def test_model_not_allowed_for_restricted_key(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "chat_model_restrict.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_phase4_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="restricted-key",
        raw_key=raw_key,
        allowed_models=["nesty-flash-1.0"],
        hash_secret="secret123",
    )
    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "search": "off",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"


def test_health_and_models_public_when_configured(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "chat_public.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        public_health=True,
        public_models=True,
        rate_limit_enabled=False,
    )
    _patch_phase4_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(_build_test_app())
    health = client.get("/health")
    models = client.get("/v1/models")
    assert health.status_code == 200
    assert models.status_code == 200
