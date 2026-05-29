from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.config import Settings
from app.core.errors import APIError, build_error_response
from app.core.orchestrator import StreamHandle, StreamOutcome
from app.schemas.chat import GuardInfo, Usage
from app.schemas.tools import SearchToolMetadata, ToolMetadata
from app.storage.db import get_connection, init_db


class _FakeStreamingOrchestrator:
    async def create_chat_completion(self, request_id: str, request):
        raise AssertionError("non-stream path should not be used in this test")

    async def create_chat_completion_stream(self, request_id: str, request):
        async def events():
            yield (
                'data: {"id":"chatcmpl_stream","object":"chat.completion.chunk","created":1700000000,'
                '"model":"nesty-combined-1.0","provider":"openrouter","choices":[{"index":0,'
                '"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            )
            yield (
                'data: {"id":"chatcmpl_stream","object":"chat.completion.chunk","created":1700000000,'
                '"model":"nesty-combined-1.0","provider":"openrouter","choices":[{"index":0,'
                '"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
            )
            yield (
                'data: {"id":"chatcmpl_stream","object":"chat.completion.chunk","created":1700000000,'
                '"model":"nesty-combined-1.0","provider":"openrouter","choices":[{"index":0,'
                '"delta":{},"finish_reason":"stop"}]}\n\n'
            )
            yield (
                'data: {"id":"chatcmpl_stream","object":"chat.completion.metadata","created":1700000000,'
                '"model":"nesty-combined-1.0","provider":"openrouter","guard":{"input_redacted":false,'
                '"output_redacted":false,"redaction_count":0,"categories":[]},"tools":{"used":[],"search":'
                '{"enabled":false,"query":null,"results_count":0,"failed":false},"executions":[]},'
                '"sources":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}\n\n'
            )
            yield "data: [DONE]\n\n"

        return StreamHandle(
            events=events(),
            outcome=StreamOutcome(
                provider="openrouter",
                usage=Usage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
                guard=GuardInfo(),
                tools=ToolMetadata(used=[], search=SearchToolMetadata(enabled=False)),
                sources=[],
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


def _extract_data_objects(sse_payload: str) -> list[dict]:
    objects: list[dict] = []
    for line in sse_payload.splitlines():
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if raw == "[DONE]":
            continue
        objects.append(json.loads(raw))
    return objects


def test_streaming_contract_sse_shape(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "stream_contract.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: _FakeStreamingOrchestrator())

    client = TestClient(_build_test_app())
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "search": "off",
            "tools": "off",
        },
    ) as response:
        payload = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"
    assert "keep-alive" in (response.headers.get("connection", "").lower())
    assert payload.strip().endswith("data: [DONE]")

    events = _extract_data_objects(payload)
    assert events[0]["object"] == "chat.completion.chunk"
    assert events[0]["choices"][0]["delta"]["role"] == "assistant"
    assert any(event.get("object") == "chat.completion.metadata" for event in events)

    with get_connection(db_path) as conn:
        row = conn.execute("SELECT status FROM usage_logs ORDER BY created_at DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["status"] == "success"
