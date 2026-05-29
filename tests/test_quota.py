from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.config import Settings
from app.core.errors import APIError, build_error_response
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessage, GuardInfo, Usage
from app.schemas.tools import ToolMetadata
from app.security.api_key import generate_api_key
from app.storage.api_keys import create_api_key_record
from app.storage.db import init_db
from app.storage.usage import insert_usage_log


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


def test_daily_quota_exceeded_blocks(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "quota_daily.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    raw_key = generate_api_key("dev")
    key_record = create_api_key_record(
        db_path=db_path,
        name="daily-key",
        raw_key=raw_key,
        daily_limit=1,
        hash_secret="secret123",
    )
    insert_usage_log(
        db_path=db_path,
        api_key_id=key_record["id"],
        request_id="req_existing_1",
        model="nesty-combined-1.0",
        provider="openrouter",
        status="success",
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
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "daily_quota_exceeded"


def test_monthly_quota_exceeded_blocks(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "quota_monthly.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    raw_key = generate_api_key("dev")
    key_record = create_api_key_record(
        db_path=db_path,
        name="monthly-key",
        raw_key=raw_key,
        monthly_limit=1,
        hash_secret="secret123",
    )
    insert_usage_log(
        db_path=db_path,
        api_key_id=key_record["id"],
        request_id="req_existing_2",
        model="nesty-combined-1.0",
        provider="openrouter",
        status="success",
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
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "monthly_quota_exceeded"


def test_no_quota_means_unlimited(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "quota_unlimited.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="unlimited-key",
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
