"""tests/test_backward_compatibility_freeze.py

Contract snapshot tests for the NestyAI v1 API.

Rules:
- All tests are hermetic (no real providers).
- We verify that guaranteed fields exist and have the right types/values.
- We never assert that a field is *absent* (additive changes are allowed).
- We check error envelope shape across multiple error codes.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.chat import (
    ChatChoice,
    ChatCompletionResponse,
    ChatMessage,
    GuardInfo,
    Usage,
)
from app.schemas.tools import ToolMetadata
from app.storage.db import init_db
from app.version import VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(content: str = "Compat check.") -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-freeze-test",
        object="chat.completion",
        created=int(time.time()),
        model="nesty-flash-1.0",
        model_alias="nesty-flash-1.0",
        provider="openrouter",
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=5, completion_tokens=10, total_tokens=15),
        guard=GuardInfo(),
        tools=ToolMetadata(),
    )


class _FakeOrchestrator:
    def __init__(self, response: ChatCompletionResponse) -> None:
        self._response = response

    async def create_chat_completion(self, request_id: str, request):
        return self._response


# ---------------------------------------------------------------------------
# App fixture (hermetic)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    # Pre-initialize DB before app sees it.
    init_db(db_path)

    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        public_health=True,
        security_headers_enabled=False,
        embeddings_enabled=False,
        semantic_recall_enabled=False,
    )
    # Patch everywhere get_settings is called so all modules use the tmp DB.
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.conversations.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.health.get_settings", lambda: settings)

    test_app = create_app(settings)
    with TestClient(test_app, raise_server_exceptions=False) as c:
        yield c



# ---------------------------------------------------------------------------
# /health — guaranteed fields
# ---------------------------------------------------------------------------

def test_health_guaranteed_fields(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "nesty-ai"
    assert isinstance(body["version"], str)
    assert body["api_version"] == "v1"


# ---------------------------------------------------------------------------
# /ready — guaranteed fields
# ---------------------------------------------------------------------------

def test_ready_guaranteed_fields(client) -> None:
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["service"] == "nesty-ai"
    assert body["database"] == "ok"
    assert isinstance(body["version"], str)
    assert body["api_version"] == "v1"


# ---------------------------------------------------------------------------
# / root — guaranteed fields
# ---------------------------------------------------------------------------

def test_root_guaranteed_fields(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert "name" in body
    assert "version" in body
    assert "description" in body
    assert "api_version" in body


# ---------------------------------------------------------------------------
# /v1/models — guaranteed shape
# ---------------------------------------------------------------------------

def test_models_list_guaranteed_shape(client) -> None:
    r = client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0
    for item in body["data"]:
        assert "id" in item
        assert "object" in item
        assert item["object"] == "model"
        assert "created" in item
        assert isinstance(item["created"], int)
        # owned_by is a guaranteed field (defaults to "nestyai")
        assert "owned_by" in item


# ---------------------------------------------------------------------------
# /v1/chat/completions — non-streaming guaranteed shape
# ---------------------------------------------------------------------------

def test_chat_completion_non_streaming_guaranteed_shape(client, monkeypatch) -> None:
    fake = _FakeOrchestrator(_fake_response("Compat freeze check."))
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: fake)

    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-flash-1.0",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )

    assert r.status_code == 200
    body = r.json()

    # Top-level required fields
    assert "id" in body
    assert isinstance(body["id"], str)
    assert body["object"] == "chat.completion"
    assert isinstance(body["created"], int)
    assert "model" in body
    assert isinstance(body["model"], str)

    # choices
    assert isinstance(body["choices"], list)
    assert len(body["choices"]) > 0
    choice = body["choices"][0]
    assert isinstance(choice["index"], int)
    assert "message" in choice
    assert choice["message"]["role"] == "assistant"
    assert isinstance(choice["message"]["content"], str)
    assert "finish_reason" in choice

    # usage
    assert "usage" in body
    usage = body["usage"]
    assert "prompt_tokens" in usage
    assert "completion_tokens" in usage
    assert "total_tokens" in usage


# ---------------------------------------------------------------------------
# ChatCompletionResponse.model field — must not change meaning
# ---------------------------------------------------------------------------

def test_chat_model_field_is_string_and_present(client, monkeypatch) -> None:
    fake = _FakeOrchestrator(_fake_response())
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: fake)

    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-flash-1.0",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert r.status_code == 200
    body = r.json()
    # model must be a non-empty string — its meaning must never change.
    assert isinstance(body["model"], str)
    assert body["model"]


# ---------------------------------------------------------------------------
# Error envelope — guaranteed shape across error scenarios
# ---------------------------------------------------------------------------

def test_error_envelope_invalid_request(client) -> None:
    # Missing "messages" triggers a validation error.
    r = client.post(
        "/v1/chat/completions",
        json={"model": "nesty-flash-1.0"},
    )
    assert r.status_code == 400
    _assert_error_envelope(r.json())


def test_error_envelope_model_not_found(client) -> None:
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "does-not-exist-v999",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    # invalid_model returns 400
    assert r.status_code in (400, 404, 422)
    _assert_error_envelope(r.json())


def _assert_error_envelope(body: dict) -> None:
    """Asserts the standard NestyAI error envelope shape."""
    assert "error" in body, f"'error' key missing from response: {body}"
    err = body["error"]
    assert "code" in err, f"'code' missing from error: {err}"
    assert "message" in err, f"'message' missing from error: {err}"
    assert isinstance(err["code"], str)
    assert isinstance(err["message"], str)


# ---------------------------------------------------------------------------
# Response header — X-Nesty-API-Version stability
# ---------------------------------------------------------------------------

def test_version_header_on_health(client) -> None:
    r = client.get("/health")
    header = r.headers.get("x-nesty-api-version")
    assert header is not None, "X-Nesty-API-Version header must be present"
    assert header == VERSION


def test_version_header_on_models(client) -> None:
    r = client.get("/v1/models")
    assert r.headers.get("x-nesty-api-version") == VERSION


# ---------------------------------------------------------------------------
# Conversations — guaranteed list shape
# ---------------------------------------------------------------------------

def test_conversations_list_guaranteed_shape(client) -> None:
    r = client.get("/v1/conversations")
    assert r.status_code == 200
    body = r.json()
    # The conversations list returns {object: "list", data: [...]}
    assert "object" in body
    assert body["object"] == "list"
    assert isinstance(body["data"], list)
