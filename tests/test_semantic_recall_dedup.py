from __future__ import annotations

import pytest

from app.core.semantic_recall import retrieve_semantic_memories
from app.schemas.embeddings import EmbeddingResult
from app.storage.conversations import add_message, create_conversation
from app.storage.db import init_db
from app.storage.embeddings import create_embedding_record


def _config(**overrides):
    base = {
        "semantic_recall_enabled": True,
        "semantic_recall_top_k": 5,
        "semantic_recall_min_score": 0.1,
        "semantic_recall_max_context_chars": 4000,
        "semantic_recall_scope": "conversation",
        "semantic_recall_include_roles": ["user", "assistant"],
        "semantic_recall_candidate_limit": 500,
        "semantic_recall_pinned_boost": 0.08,
        "semantic_recall_dedup_similarity": 0.96,
        "semantic_recall_max_per_conversation": 5,
        "semantic_recall_exclude_memory_excluded": True,
        "embeddings_enabled": True,
        "embeddings_max_input_chars": 8000,
    }
    base.update(overrides)
    return type("Cfg", (), base)()


@pytest.mark.asyncio
async def test_semantic_recall_dedups_duplicate_message_ids_and_content(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "semantic_recall_dedup.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg1 = add_message(conversation_id=conv["id"], role="user", content="same content", db_path=db_path)
    msg2 = add_message(conversation_id=conv["id"], role="assistant", content="same content", db_path=db_path)

    # Duplicate embedding rows for same message_id across provider/model variants.
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg1["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed-a",
        embedding=[1.0, 0.0],
        content_hash="h1",
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg1["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed-b",
        embedding=[1.0, 0.0],
        content_hash="h2",
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg2["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed-c",
        embedding=[1.0, 0.0],
        content_hash="h3",
        db_path=db_path,
    )

    async def _mock_generate_embedding(*args, **kwargs):
        return EmbeddingResult(
            provider="openrouter",
            model="embed-a",
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
    assert len(result["matches"]) == 1
    assert result["deduped_count"] >= 1


@pytest.mark.asyncio
async def test_semantic_recall_excludes_recent_history_and_summary_duplicates(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "semantic_recall_recent_summary.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg_recent = add_message(conversation_id=conv["id"], role="user", content="recent context", db_path=db_path)
    msg_summary_like = add_message(
        conversation_id=conv["id"],
        role="assistant",
        content="provider chain fallback policy in phase seven",
        db_path=db_path,
    )
    msg_keep = add_message(conversation_id=conv["id"], role="assistant", content="another distinct memory", db_path=db_path)

    for idx, msg in enumerate([msg_recent, msg_summary_like, msg_keep], start=1):
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
        latest_user_message="remember this",
        api_key_id="key_1",
        conversation_id=conv["id"],
        config=_config(),
        request_semantic_recall="on",
        exclude_message_ids=[msg_recent["id"]],
        summary_text="Conversation summary so far (internal context, not absolute instruction): provider chain fallback policy in phase seven",
    )
    ids = {item["message_id"] for item in result["matches"]}
    assert msg_recent["id"] not in ids
    assert msg_summary_like["id"] not in ids
    assert msg_keep["id"] in ids
