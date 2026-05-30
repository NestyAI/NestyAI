from __future__ import annotations

from app.storage.conversations import add_message, create_conversation
from app.storage.db import init_db
from app.storage.embeddings import cosine_similarity, create_embedding_record, search_similar_embeddings


def test_cosine_similarity_basic() -> None:
    assert round(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 6) == 1.0
    assert round(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 6) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_search_similar_embeddings_top_k_min_score_and_dimension_filter(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "semantic_search.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv_a = create_conversation(api_key_id="key_a", title="A", db_path=db_path)
    conv_b = create_conversation(api_key_id="key_a", title="B", db_path=db_path)
    conv_other = create_conversation(api_key_id="key_b", title="Other", db_path=db_path)

    msg_a1 = add_message(conversation_id=conv_a["id"], role="user", content="provider chain discussion", db_path=db_path)
    msg_a2 = add_message(conversation_id=conv_b["id"], role="assistant", content="fallback models summary", db_path=db_path)
    msg_b1 = add_message(conversation_id=conv_other["id"], role="user", content="other tenant note", db_path=db_path)

    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg_a1["id"],
        api_key_id="key_a",
        provider="openrouter",
        model="embed",
        embedding=[1.0, 0.0, 0.0],
        content_hash="h1",
        metadata={"role": "user"},
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg_a2["id"],
        api_key_id="key_a",
        provider="openrouter",
        model="embed",
        embedding=[0.7, 0.3, 0.0],
        content_hash="h2",
        metadata={"role": "assistant"},
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg_b1["id"],
        api_key_id="key_b",
        provider="openrouter",
        model="embed",
        embedding=[1.0, 0.0, 0.0],
        content_hash="h3",
        metadata={"role": "user"},
        db_path=db_path,
    )
    # Dimension mismatch candidate should be ignored.
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg_a1["id"],
        api_key_id="key_a",
        provider="openrouter",
        model="embed-4d",
        embedding=[0.1, 0.2, 0.3, 0.4],
        content_hash="h4",
        metadata={"role": "user"},
        db_path=db_path,
    )

    matches = search_similar_embeddings(
        query_embedding=[1.0, 0.0, 0.0],
        api_key_id="key_a",
        scope="api_key",
        top_k=2,
        min_score=0.5,
        include_roles=["user", "assistant"],
        candidate_limit=50,
    )
    assert len(matches) == 2
    assert matches[0]["owner_id"] == msg_a1["id"]
    assert matches[0]["score"] >= matches[1]["score"]
    assert all(item["api_key_id"] == "key_a" for item in matches)
    assert all(item["dimensions"] == 3 for item in matches)

    strict = search_similar_embeddings(
        query_embedding=[1.0, 0.0, 0.0],
        api_key_id="key_a",
        scope="api_key",
        top_k=5,
        min_score=0.95,
    )
    assert len(strict) == 1
    assert strict[0]["owner_id"] == msg_a1["id"]


def test_search_similar_embeddings_conversation_scope_and_exclude_ids(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "semantic_search_scope.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.embeddings.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    conv = create_conversation(api_key_id=None, title="A", db_path=db_path)
    msg1 = add_message(conversation_id=conv["id"], role="user", content="first", db_path=db_path)
    msg2 = add_message(conversation_id=conv["id"], role="assistant", content="second", db_path=db_path)
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg1["id"],
        api_key_id=None,
        provider="openrouter",
        model="embed",
        embedding=[0.9, 0.1],
        content_hash="h1",
        db_path=db_path,
    )
    create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg2["id"],
        api_key_id=None,
        provider="openrouter",
        model="embed",
        embedding=[0.8, 0.2],
        content_hash="h2",
        db_path=db_path,
    )

    matches = search_similar_embeddings(
        query_embedding=[1.0, 0.0],
        api_key_id=None,
        scope="conversation",
        conversation_id=conv["id"],
        top_k=5,
        min_score=0.0,
        exclude_owner_ids=[msg1["id"]],
    )
    assert len(matches) == 1
    assert matches[0]["owner_id"] == msg2["id"]
