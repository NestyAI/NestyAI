from __future__ import annotations

import pytest

from app.core.semantic_recall import retrieve_semantic_memories
from app.schemas.embeddings import EmbeddingResult
from app.storage.conversations import add_message, create_conversation, update_message_memory_controls
from app.storage.db import init_db
from app.storage.embeddings import create_embedding_record


def _config(**overrides):
    base = {
        "semantic_recall_enabled": True,
        "semantic_recall_top_k": 5,
        "semantic_recall_min_score": 0.7,
        "semantic_recall_max_context_chars": 4000,
        "semantic_recall_scope": "conversation",
        "semantic_recall_include_roles": ["user", "assistant"],
        "semantic_recall_candidate_limit": 500,
        "semantic_recall_pinned_boost": 0.08,
        "semantic_recall_dedup_similarity": 0.96,
        "semantic_recall_max_per_conversation": 3,
        "semantic_recall_exclude_memory_excluded": True,
        "embeddings_enabled": True,
        "embeddings_max_input_chars": 8000,
    }
    base.update(overrides)
    return type("Cfg", (), base)()


@pytest.mark.asyncio
async def test_semantic_recall_excludes_memory_excluded_messages(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "semantic_recall_excluded.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg_keep = add_message(conversation_id=conv["id"], role="user", content="keep me", db_path=db_path)
    msg_excluded = add_message(conversation_id=conv["id"], role="assistant", content="exclude me", db_path=db_path)
    _ = update_message_memory_controls(
        message_id=msg_excluded["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg_keep["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed",
        embedding=[1.0, 0.0],
        content_hash="h1",
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg_excluded["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed",
        embedding=[1.0, 0.0],
        content_hash="h2",
        db_path=db_path,
    )

    async def _mock_generate_embedding(*args, **kwargs):
        return EmbeddingResult(
            provider="openrouter",
            model="embed",
            embedding=[1.0, 0.0],
            dimensions=2,
            usage=None,
            latency_ms=1,
        )

    monkeypatch.setattr("app.core.semantic_recall.generate_embedding", _mock_generate_embedding)
    result = await retrieve_semantic_memories(
        latest_user_message="remember this",
        api_key_id="key_1",
        conversation_id=conv["id"],
        config=_config(),
        request_semantic_recall="on",
        exclude_message_ids=[],
    )
    ids = {item["message_id"] for item in result["matches"]}
    assert msg_excluded["id"] not in ids
    assert result["excluded_matches_count"] >= 0


@pytest.mark.asyncio
async def test_semantic_recall_pinned_boost_applies_and_caps_at_one(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "semantic_recall_pinned.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="pinned memory", db_path=db_path)
    _ = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        pinned=True,
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed",
        embedding=[0.93, 0.3675595],
        content_hash="h1",
        db_path=db_path,
    )

    async def _mock_generate_embedding(*args, **kwargs):
        return EmbeddingResult(
            provider="openrouter",
            model="embed",
            embedding=[1.0, 0.0],
            dimensions=2,
            usage=None,
            latency_ms=1,
        )

    monkeypatch.setattr("app.core.semantic_recall.generate_embedding", _mock_generate_embedding)
    result = await retrieve_semantic_memories(
        latest_user_message="remember this",
        api_key_id="key_1",
        conversation_id=conv["id"],
        config=_config(semantic_recall_min_score=0.95),
        request_semantic_recall="on",
        exclude_message_ids=[],
    )
    assert result["used"] is True
    assert result["matches"][0]["pinned"] is True
    assert result["matches"][0]["score"] == 1.0
    assert result["matches"][0]["raw_score"] < result["matches"][0]["score"]


@pytest.mark.asyncio
async def test_semantic_recall_max_per_conversation_enforced(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "semantic_recall_per_conv.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    for idx in range(5):
        msg = add_message(conversation_id=conv["id"], role="user", content=f"msg {idx}", db_path=db_path)
        create_embedding_record(
            owner_type="conversation_message",
            owner_id=msg["id"],
            api_key_id="key_1",
            provider="openrouter",
            model="embed",
            embedding=[1.0, 0.0],
            content_hash=f"h{idx}",
            db_path=db_path,
        )

    async def _mock_generate_embedding(*args, **kwargs):
        return EmbeddingResult(
            provider="openrouter",
            model="embed",
            embedding=[1.0, 0.0],
            dimensions=2,
            usage=None,
            latency_ms=1,
        )

    monkeypatch.setattr("app.core.semantic_recall.generate_embedding", _mock_generate_embedding)
    result = await retrieve_semantic_memories(
        latest_user_message="remember all",
        api_key_id="key_1",
        conversation_id=conv["id"],
        config=_config(semantic_recall_top_k=5, semantic_recall_max_per_conversation=3, semantic_recall_min_score=0.1),
        request_semantic_recall="on",
        exclude_message_ids=[],
    )
    assert len(result["matches"]) <= 3
