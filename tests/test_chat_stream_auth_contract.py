from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.config import Settings
from app.core.errors import APIError, build_error_response
from app.core.orchestrator import StreamHandle, StreamOutcome
from app.schemas.chat import Usage
from app.schemas.tools import ToolMetadata
from app.security.api_key import generate_api_key
from app.storage.api_keys import create_api_key_record
from app.storage.db import init_db


class _StreamCapableOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        raise AssertionError("non-stream path is not used here")

    async def create_chat_completion_stream(self, request_id: str, request):
        if request.model == "not-a-real-model":
            raise APIError(code="invalid_model", message="Model 'not-a-real-model' is not supported.", status_code=400)

        async def events():
            yield (
                'data: {"id":"chatcmpl_auth","object":"chat.completion.chunk","created":1700000000,'
                '"model":"nesty-combined-1.0","provider":"openrouter","choices":[{"index":0,'
                '"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            )
            yield "data: [DONE]\n\n"

        return StreamHandle(
            events=events(),
            outcome=StreamOutcome(
                provider="openrouter",
                usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                tools=ToolMetadata(),
                status="success",
            ),
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


def test_stream_chat_requires_key_when_enabled(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "stream_auth_required.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _StreamCapableOrchestrator())

    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


def test_stream_chat_with_valid_key_returns_sse(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "stream_auth_ok.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _StreamCapableOrchestrator())

    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="stream-key",
        raw_key=raw_key,
        hash_secret="secret123",
    )

    client = TestClient(_build_test_app())
    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    ) as response:
        payload = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in payload


def test_stream_chat_invalid_model_rejected_before_stream(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "stream_invalid_model.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _StreamCapableOrchestrator())

    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="stream-key",
        raw_key=raw_key,
        hash_secret="secret123",
    )

    client = TestClient(_build_test_app())
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "model": "not-a-real-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_model"
