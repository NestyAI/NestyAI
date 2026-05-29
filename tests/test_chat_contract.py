from __future__ import annotations

from app.schemas.chat import (
    ChatChoice,
    ChatCompletionResponse,
    ChatMessage,
    GuardInfo,
    Usage,
)
from app.schemas.tools import SearchToolMetadata, SourceItem, ToolMetadata


class FakeOrchestrator:
    def __init__(self, response: ChatCompletionResponse) -> None:
        self.response = response

    async def create_chat_completion(self, request_id: str, request):
        return self.response


def _mock_response(search_enabled: bool = False, with_sources: bool = False) -> ChatCompletionResponse:
    tools = ToolMetadata(
        used=["current_datetime", "web_search"] if search_enabled else [],
        search=SearchToolMetadata(
            enabled=search_enabled,
            query="What is latest?",
            results_count=1 if search_enabled else 0,
            failed=False,
        ),
    )
    sources = (
        [SourceItem(title="A", url="https://example.com", snippet="Snippet")]
        if with_sources
        else []
    )
    return ChatCompletionResponse(
        id="chatcmpl_test",
        created=1700000000,
        model="nesty-combined-1.0",
        provider="openrouter",
        choices=[
            ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content="Hello from NestyAI"),
                finish_reason="stop",
            )
        ],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        guard=GuardInfo(),
        tools=tools,
        sources=sources,
    )


def test_chat_contract_success_shape(client, monkeypatch) -> None:
    fake = FakeOrchestrator(_mock_response(search_enabled=False, with_sources=False))
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: fake)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "Hello"}],
            "search": "off",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "id" in payload
    assert payload["object"] == "chat.completion"
    assert "created" in payload
    assert payload["model"] == "nesty-combined-1.0"
    assert isinstance(payload["choices"], list)
    assert payload["choices"][0]["message"]["role"] == "assistant"
    assert "content" in payload["choices"][0]["message"]
    assert "usage" in payload
    assert "guard" in payload
    assert "tools" in payload
    assert "sources" in payload


def test_chat_invalid_model_returns_invalid_model(client) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "not-a-real-model",
            "messages": [{"role": "user", "content": "hello"}],
            "search": "off",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_model"


def test_chat_stream_not_implemented(client) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "streaming_not_implemented"


def test_chat_invalid_search_mode(client) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "hello"}],
            "search": "invalid",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_search_mode"


def test_chat_search_off_has_tools_disabled(client, monkeypatch) -> None:
    fake = FakeOrchestrator(_mock_response(search_enabled=False, with_sources=False))
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: fake)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "Write intro"}],
            "search": "off",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tools"]["search"]["enabled"] is False
    assert payload["sources"] == []


def test_chat_response_contains_tools_and_sources_when_present(client, monkeypatch) -> None:
    fake = FakeOrchestrator(_mock_response(search_enabled=True, with_sources=True))
    monkeypatch.setattr("app.api.chat.get_orchestrator", lambda: fake)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "nesty-combined-1.0",
            "messages": [{"role": "user", "content": "latest news"}],
            "search": "auto",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "tools" in payload
    assert payload["tools"]["search"]["enabled"] is True
    assert len(payload["sources"]) >= 1

