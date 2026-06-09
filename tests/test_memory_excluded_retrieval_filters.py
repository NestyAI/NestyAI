from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.config import Settings
from app.core.errors import APIError, build_error_response
from app.schemas.chat import ChatChoice, ChatCompletionResponse, ChatMessage, GuardInfo, Usage
from app.schemas.tools import ToolMetadata
from app.storage.conversations import (
    add_message,
    create_conversation,
    search_messages,
    update_conversation_summary,
    update_message_memory_controls,
)
from app.storage.db import init_db


class _CaptureOrchestrator:
    def __init__(self, response: ChatCompletionResponse) -> None:
        self.response = response
        self.messages: list[ChatMessage] = []

    async def create_chat_completion(self, request_id: str, request) -> ChatCompletionResponse:
        self.messages = list(request.messages)
        return self.response

    async def create_chat_completion_stream(self, request_id: str, request):
        raise AssertionError("stream path should not be used")


def _build_response() -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl_test",
        created=1700000000,
        model="nesty-combined-1.0",
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
    )


def _build_client(settings: Settings, orchestrator: _CaptureOrchestrator, monkeypatch) -> TestClient:
    monkeypatch.setattr("app.api.chat.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: orchestrator)

    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

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

    return TestClient(app)


def test_chat_preparation_filters_memory_excluded_recent_history(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "memory_filter_recent.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
    )
    orchestrator = _CaptureOrchestrator(_build_response())
    client = _build_client(settings, orchestrator, monkeypatch)

    conv = create_conversation(api_key_id=None, title="recent filter", db_path=db_path)
    conv_id = conv["id"]
    add_message(conversation_id=conv_id, role="user", content="keep this one", db_path=db_path)
    excluded = add_message(conversation_id=conv_id, role="assistant", content="hide this one", db_path=db_path)
    update_message_memory_controls(
        message_id=excluded["id"],
        conversation_id=conv_id,
        api_key_id=None,
        excluded=True,
        db_path=db_path,
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "store": True,
            "conversation_id": conv_id,
            "search": "off",
            "tools": "off",
            "semantic_recall": "off",
        },
    )
    assert response.status_code == 200
    prepared_text = " ".join(message.content for message in orchestrator.messages)
    assert "keep this one" in prepared_text
    assert "hide this one" not in prepared_text


def test_chat_preparation_filters_memory_excluded_after_summary(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "memory_filter_summary.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        require_api_key=False,
        rate_limit_enabled=False,
        conversation_summary_enabled=True,
    )
    orchestrator = _CaptureOrchestrator(_build_response())
    client = _build_client(settings, orchestrator, monkeypatch)

    conv = create_conversation(api_key_id=None, title="summary filter", db_path=db_path)
    conv_id = conv["id"]
    add_message(conversation_id=conv_id, role="user", content="summary anchor", db_path=db_path)
    add_message(conversation_id=conv_id, role="assistant", content="summary bridge", db_path=db_path)
    update_conversation_summary(conv_id, "compressed summary", 2, db_path=db_path)
    add_message(conversation_id=conv_id, role="user", content="visible after summary", db_path=db_path)
    excluded = add_message(conversation_id=conv_id, role="assistant", content="hidden after summary", db_path=db_path)
    update_message_memory_controls(
        message_id=excluded["id"],
        conversation_id=conv_id,
        api_key_id=None,
        excluded=True,
        db_path=db_path,
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "what happened?"}],
            "store": True,
            "conversation_id": conv_id,
            "search": "off",
            "tools": "off",
            "semantic_recall": "off",
        },
    )
    assert response.status_code == 200
    prepared_text = " ".join(message.content for message in orchestrator.messages)
    assert "compressed summary" in prepared_text
    assert "visible after summary" in prepared_text
    assert "hidden after summary" not in prepared_text


def test_search_messages_excludes_memory_excluded_rows(tmp_path) -> None:
    db_path = str(tmp_path / "memory_filter_search.db")
    init_db(db_path)
    conv = create_conversation(api_key_id=None, title="search filter", db_path=db_path)
    conv_id = conv["id"]
    add_message(conversation_id=conv_id, role="user", content="keep this one", db_path=db_path)
    excluded = add_message(conversation_id=conv_id, role="assistant", content="searchable secret", db_path=db_path)
    update_message_memory_controls(
        message_id=excluded["id"],
        conversation_id=conv_id,
        api_key_id=None,
        excluded=True,
        db_path=db_path,
    )

    hidden = search_messages(
        api_key_id=None,
        query="searchable",
        limit=20,
        offset=0,
        backend="like",
        conversation_id=conv_id,
        exclude_memory_excluded=True,
        db_path=db_path,
    )
    assert hidden["data"] == []

    visible = search_messages(
        api_key_id=None,
        query="searchable",
        limit=20,
        offset=0,
        backend="like",
        conversation_id=conv_id,
        exclude_memory_excluded=False,
        db_path=db_path,
    )
    assert len(visible["data"]) >= 1
