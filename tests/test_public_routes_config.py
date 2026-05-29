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
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
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
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        payload = build_error_response(
            code="invalid_request",
            message="Invalid request payload.",
            details={"errors": exc.errors()},
        )
        return JSONResponse(status_code=400, content=payload)

    return app


def _patch_settings(monkeypatch, settings: Settings) -> None:
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.health.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.models.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())


def test_health_public_when_required_and_public_true(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "config_health_public.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=True, public_health=True, public_models=True)
    _patch_settings(monkeypatch, settings)
    client = TestClient(_build_test_app())
    response = client.get("/health")
    assert response.status_code == 200


def test_health_private_when_required_and_public_false(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "config_health_private.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=True, public_health=False, public_models=True)
    _patch_settings(monkeypatch, settings)
    client = TestClient(_build_test_app())
    response = client.get("/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


def test_models_public_when_required_and_public_true(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "config_models_public.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=True, public_health=True, public_models=True)
    _patch_settings(monkeypatch, settings)
    client = TestClient(_build_test_app())
    response = client.get("/v1/models")
    assert response.status_code == 200


def test_models_private_when_required_and_public_false(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "config_models_private.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=True, public_health=True, public_models=False)
    _patch_settings(monkeypatch, settings)
    client = TestClient(_build_test_app())
    response = client.get("/v1/models")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


def test_chat_public_when_require_api_key_false(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "config_chat_public.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=False, public_health=True, public_models=True)
    _patch_settings(monkeypatch, settings)
    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "search": "off",
        },
    )
    assert response.status_code == 200


def test_chat_private_when_require_api_key_true(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "config_chat_private.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, require_api_key=True, public_health=True, public_models=True)
    _patch_settings(monkeypatch, settings)
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
