from __future__ import annotations

import re

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.api.models import router as models_router
from app.config import Settings
from app.core.errors import APIError, build_error_response, validation_error_param
from app.main import create_app
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessage, GuardInfo, Usage
from app.schemas.tools import ToolMetadata
from app.security.api_key import generate_api_key
from app.security.rate_limit import get_rate_limiter
from app.storage.api_keys import create_api_key_record, revoke_api_key
from app.storage.db import init_db
from app.storage.usage import insert_usage_log


class _SuccessOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        return ChatCompletionResponse(
            id="chatcmpl_usage_polish",
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


def test_revoked_api_key_returns_403(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "revoked_key.db")
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
    record = create_api_key_record(
        db_path=db_path,
        name="revoked",
        raw_key=raw_key,
        hash_secret="secret123",
    )
    revoke_api_key(db_path, record["id"])

    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403
    err = response.json()["error"]
    assert err["code"] == "api_key_revoked"
    assert err["type"] == "permission_error"


def test_invalid_api_key_stays_401(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "invalid_key.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer nsk_dev_does_not_exist"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_request_id_header_on_success_and_error(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "request_id.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(create_app(settings))
    ok = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Request-ID": "client-req-001"},
    )
    assert ok.status_code == 200
    assert ok.headers.get("x-request-id") == "client-req-001"

    bad = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0"},
    )
    assert bad.status_code == 400
    assert bad.headers.get("x-request-id")
    assert re.fullmatch(r"req_[0-9a-f]{12}", bad.headers.get("x-request-id", ""))


def test_request_id_rejects_unsafe_incoming_value(monkeypatch) -> None:
    settings = Settings(require_api_key=False, rate_limit_enabled=False)
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())

    client = TestClient(create_app(settings))
    response = client.get("/v1/models", headers={"X-Request-ID": "Bearer secret-token"})
    assert response.status_code == 200
    request_id = response.headers.get("x-request-id", "")
    assert request_id.startswith("req_")
    assert "Bearer" not in request_id


def test_rate_limit_headers_on_success_and_429(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "rate_limit_headers.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=1,
    )
    _patch_settings(monkeypatch, settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _SuccessOrchestrator())
    get_rate_limiter().reset()

    client = TestClient(create_app(settings))
    first = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "one"}]},
    )
    assert first.status_code == 200
    assert first.headers.get("x-ratelimit-limit") == "1"
    assert first.headers.get("x-ratelimit-remaining") == "0"
    assert first.headers.get("x-ratelimit-reset")

    second = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "two"}]},
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
    assert second.headers.get("retry-after")
    assert second.headers.get("x-ratelimit-limit") == "1"
    assert second.headers.get("x-ratelimit-remaining") == "0"


def test_daily_quota_details(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "quota_details.db")
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
        name="quota",
        raw_key=raw_key,
        daily_limit=1,
        hash_secret="secret123",
    )
    insert_usage_log(
        db_path=db_path,
        api_key_id=key_record["id"],
        request_id="req_existing",
        model="nesty-combined-1.0",
        provider="openrouter",
        status="success",
    )

    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 429
    err = response.json()["error"]
    assert err["code"] == "daily_quota_exceeded"
    assert err["type"] == "rate_limit_error"
    assert err["details"]["quota_type"] == "daily"
    assert err["details"]["limit"] == 1
    assert err["details"]["openai_code_alias"] == "quota_exceeded"


def test_monthly_quota_details(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "monthly_quota.db")
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
        name="monthly",
        raw_key=raw_key,
        monthly_limit=1,
        hash_secret="secret123",
    )
    insert_usage_log(
        db_path=db_path,
        api_key_id=key_record["id"],
        request_id="req_monthly",
        model="nesty-combined-1.0",
        provider="openrouter",
        status="success",
    )

    client = TestClient(create_app(settings))
    response = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-combined-1.0", "messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 429
    err = response.json()["error"]
    assert err["code"] == "monthly_quota_exceeded"
    assert err["details"]["quota_type"] == "monthly"
    assert err["details"]["openai_code_alias"] == "quota_exceeded"
