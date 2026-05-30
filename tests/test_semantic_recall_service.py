from __future__ import annotations

import pytest

from app.core.semantic_recall import build_recall_query_text, retrieve_semantic_memories, should_use_semantic_recall
from app.schemas.embeddings import EmbeddingResult
from app.storage.conversations import add_message, create_conversation
from app.storage.db import init_db
from app.storage.embeddings import create_embedding_record


def _config(**overrides):
    base = {
        "semantic_recall_enabled": True,
        "semantic_recall_top_k": 5,
        "semantic_recall_min_score": 0.5,
        "semantic_recall_max_context_chars": 4000,
        "semantic_recall_scope": "conversation",
        "semantic_recall_include_roles": ["user", "assistant"],
        "semantic_recall_candidate_limit": 500,
        "embeddings_enabled": True,
        "embeddings_max_input_chars": 8000,
    }
    base.update(overrides)
    return type("Cfg", (), base)()


def test_build_recall_query_text_prefers_latest_user_message() -> None:
    messages = [
        {"role": "assistant", "content": "A"},
        {"role": "user", "content": "B"},
        {"role": "assistant", "content": "C"},
        {"role": "user", "content": "  D  "},
    ]
    assert build_recall_query_text(messages) == "D"


def test_should_use_semantic_recall_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr("app.core.semantic_recall.count_embedding_records", lambda: 0)
    req = type("R", (), {"semantic_recall": "auto", "store": True, "conversation_id": "conv_1"})()
    decision = should_use_semantic_recall(
        request=req,
        model_config={"behavior_profile": "balanced"},
        context_metadata={"latest_user_message": "remember that"},
        config=_config(semantic_recall_enabled=False),
    )
    assert decision["should_use"] is False
    assert decision["reason"] == "disabled_global"


def test_should_use_semantic_recall_auto_trigger_and_skip(monkeypatch) -> None:
    monkeypatch.setattr("app.core.semantic_recall.count_embedding_records", lambda: 3)
    req = type("R", (), {"semantic_recall": "auto", "store": True, "conversation_id": "conv_1"})()
    use = should_use_semantic_recall(
        request=req,
        model_config={"behavior_profile": "pro"},
        context_metadata={"latest_user_message": "Can you remember what I said earlier?"},
        config=_config(),
    )
    skip = should_use_semantic_recall(
        request=req,
        model_config={"behavior_profile": "flash"},
        context_metadata={"latest_user_message": "hello there"},
        config=_config(),
    )
    assert use["should_use"] is True
    assert skip["should_use"] is False


def test_should_use_semantic_recall_on_mode_forces_use_when_available(monkeypatch) -> None:
    monkeypatch.setattr("app.core.semantic_recall.count_embedding_records", lambda: 2)
    req = type("R", (), {"semantic_recall": "on", "store": True, "conversation_id": "conv_1"})()
    decision = should_use_semantic_recall(
        request=req,
        model_config={"behavior_profile": "balanced"},
        context_metadata={"latest_user_message": "hello"},
        config=_config(),
    )
    assert decision["should_use"] is True
    assert decision["reason"] == "semantic_recall_enabled"


@pytest.mark.asyncio
async def test_retrieve_semantic_memories_returns_matches(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "semantic_recall_service.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg = add_message(
        conversation_id=conv["id"],
        role="user",
        content="We tuned provider chains in phase seven.",
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed",
        embedding=[1.0, 0.0, 0.0],
        content_hash="h1",
        metadata={"role": "user"},
        db_path=db_path,
    )

    async def _mock_generate_embedding(text: str, provider=None, model=None):
        return EmbeddingResult(
            provider="openrouter",
            model="embed",
            embedding=[1.0, 0.0, 0.0],
            dimensions=3,
            usage=None,
            latency_ms=1,
        )

    monkeypatch.setattr("app.core.semantic_recall.generate_embedding", _mock_generate_embedding)

    result = await retrieve_semantic_memories(
        latest_user_message="What did I say earlier about provider chains?",
        api_key_id="key_1",
        conversation_id=conv["id"],
        config=_config(semantic_recall_scope="conversation", semantic_recall_min_score=0.1),
        request_semantic_recall="on",
        exclude_message_ids=[],
    )
    assert result["used"] is True
    assert result["matches"]
    assert result["reason"] == "semantic_recall_enabled"
    assert "[Memory 1 | score=" in result["context_text"]


@pytest.mark.asyncio
async def test_retrieve_semantic_memories_provider_failure_is_safe(monkeypatch) -> None:
    async def _raise_generate(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.core.semantic_recall.generate_embedding", _raise_generate)
    result = await retrieve_semantic_memories(
        latest_user_message="remember this",
        api_key_id=None,
        conversation_id="conv_1",
        config=_config(),
        request_semantic_recall="on",
        exclude_message_ids=[],
    )
    assert result["used"] is False
    assert result["reason"] == "provider_failed"
