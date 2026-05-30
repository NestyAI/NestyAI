from __future__ import annotations


def test_internal_recall_endpoint_hidden_when_admin_disabled(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": False, "nesty_internal_admin_token": "abc"})(),
    )
    response = client.post("/internal/embeddings/recall-test", json={"text": "remember this"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "internal_admin_disabled"


def test_internal_recall_endpoint_requires_token(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_embeddings.get_settings",
        lambda: type("S", (), {"semantic_recall_enabled": True, "semantic_recall_scope": "conversation"})(),
    )
    response = client.post("/internal/embeddings/recall-test", json={"text": "remember this"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_admin_unauthorized"


def test_internal_recall_endpoint_returns_preview_without_vectors(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.internal_auth.get_settings",
        lambda: type("S", (), {"internal_admin_enabled": True, "nesty_internal_admin_token": "abc"})(),
    )
    monkeypatch.setattr(
        "app.api.internal_embeddings.get_settings",
        lambda: type(
            "S",
            (),
            {
                "semantic_recall_enabled": True,
                "semantic_recall_scope": "conversation",
                "semantic_recall_top_k": 5,
                "semantic_recall_min_score": 0.72,
            },
        )(),
    )

    async def _mock_retrieve(**kwargs):
        return {
            "query_embedded": True,
            "reason": "semantic_recall_enabled",
            "scope": "conversation",
            "pinned_matches_count": 1,
            "excluded_matches_count": 0,
            "deduped_count": 2,
            "candidate_count": 4,
            "max_score": 0.91,
            "min_returned_score": 0.88,
            "matches": [
                {
                    "message_id": "msg_1",
                    "conversation_id": "conv_1",
                    "role": "user",
                    "score": 0.88,
                    "raw_score": 0.80,
                    "pinned": True,
                    "excluded": False,
                    "tags": ["important"],
                    "content": "A" * 260,
                }
            ],
        }

    monkeypatch.setattr("app.api.internal_embeddings.retrieve_semantic_memories", _mock_retrieve)
    response = client.post(
        "/internal/embeddings/recall-test",
        headers={"Authorization": "Bearer abc"},
        json={"text": "What did I say?", "conversation_id": "conv_1", "include_pinned_boost": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["query_embedded"] is True
    assert payload["matches"][0]["message_id"] == "msg_1"
    assert "embedding" not in payload["matches"][0]
    assert payload["matches"][0]["excluded"] is False
    assert payload["matches"][0]["pinned"] is True
    assert len(payload["matches"][0]["content_preview"]) <= 203
