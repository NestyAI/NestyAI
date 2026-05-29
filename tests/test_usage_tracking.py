from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.errors import APIError
from app.core.errors import build_error_response
from app.api.chat import router as chat_router
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessage, GuardInfo, Usage
from app.schemas.tools import ToolMetadata
from app.storage.db import get_connection, init_db


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
            usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            guard=GuardInfo(),
            tools=ToolMetadata(),
            sources=[],
        )


class _ErrorOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        raise APIError(
            code="provider_unavailable",
            message="Provider unavailable for this request.",
            status_code=502,
        )


def _build_test_app() -> FastAPI:
    app = FastAPI()
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


def test_success_request_logs_usage(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "usage.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello usage"}],
            "search": "off",
        },
    )
    assert response.status_code == 200

    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM usage_logs ORDER BY created_at DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["status"] == "success"
    assert row["model"] == "nesty-combined-1.0"
    assert row["provider"] == "openrouter"
    assert row["error_code"] is None
    assert "prompt" not in row.keys()


def test_error_request_logs_usage_when_possible(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "usage_error.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _ErrorOrchestrator())

    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello usage"}],
            "search": "off",
        },
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unavailable"

    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM usage_logs ORDER BY created_at DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["status"] == "error"
    assert row["error_code"] == "provider_unavailable"
