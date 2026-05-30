from __future__ import annotations

from app.config import Settings
from app.security.api_key import generate_api_key
from app.storage.api_keys import create_api_key_record
from app.storage.conversations import add_message, archive_conversation, create_conversation
from app.storage.db import init_db


def _auth_setup(client, monkeypatch, tmp_path):
    db_path = str(tmp_path / "memory_controls_endpoints.db")
    init_db(db_path)
    settings = Settings(
        nesty_db_path=db_path,
        nesty_api_key_hash_secret="secret123",
        require_api_key=True,
        rate_limit_enabled=False,
    )
    monkeypatch.setattr("app.api.conversations.get_settings", lambda: settings)
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)
    return db_path


def test_patch_message_memory_controls_success_and_list(client, monkeypatch, tmp_path) -> None:
    db_path = _auth_setup(client, monkeypatch, tmp_path)
    raw_key = generate_api_key("dev")
    key = create_api_key_record(db_path=db_path, name="owner", raw_key=raw_key, hash_secret="secret123")
    conv = create_conversation(api_key_id=key["id"], title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="a" * 260, db_path=db_path)
    headers = {"Authorization": f"Bearer {raw_key}"}

    patch_resp = client.patch(
        f"/v1/conversations/{conv['id']}/messages/{msg['id']}/memory",
        headers=headers,
        json={"pinned": True, "excluded": False, "tags": ["project", "important"]},
    )
    assert patch_resp.status_code == 200
    payload = patch_resp.json()
    assert payload["ok"] is True
    assert payload["message"]["memory_pinned"] is True
    assert payload["message"]["memory_excluded"] is False
    assert payload["message"]["memory_tags"] == ["project", "important"]

    list_resp = client.get("/v1/conversations/memory-controls?pinned=true", headers=headers)
    assert list_resp.status_code == 200
    data = list_resp.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == msg["id"]
    assert len(data[0]["content_preview"]) <= 203


def test_patch_message_memory_controls_rejects_conflicting_state(client, monkeypatch, tmp_path) -> None:
    db_path = _auth_setup(client, monkeypatch, tmp_path)
    raw_key = generate_api_key("dev")
    key = create_api_key_record(db_path=db_path, name="owner", raw_key=raw_key, hash_secret="secret123")
    conv = create_conversation(api_key_id=key["id"], title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="hello", db_path=db_path)
    headers = {"Authorization": f"Bearer {raw_key}"}

    response = client.patch(
        f"/v1/conversations/{conv['id']}/messages/{msg['id']}/memory",
        headers=headers,
        json={"pinned": True, "excluded": True},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_memory_control_request"


def test_patch_message_memory_controls_requires_ownership(client, monkeypatch, tmp_path) -> None:
    db_path = _auth_setup(client, monkeypatch, tmp_path)
    owner_key = generate_api_key("dev")
    owner = create_api_key_record(db_path=db_path, name="owner", raw_key=owner_key, hash_secret="secret123")
    other_key = generate_api_key("dev")
    _ = create_api_key_record(db_path=db_path, name="other", raw_key=other_key, hash_secret="secret123")
    conv = create_conversation(api_key_id=owner["id"], title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="hello", db_path=db_path)

    response = client.patch(
        f"/v1/conversations/{conv['id']}/messages/{msg['id']}/memory",
        headers={"Authorization": f"Bearer {other_key}"},
        json={"excluded": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"


def test_patch_message_memory_controls_archived_conversation_not_found(client, monkeypatch, tmp_path) -> None:
    db_path = _auth_setup(client, monkeypatch, tmp_path)
    raw_key = generate_api_key("dev")
    key = create_api_key_record(db_path=db_path, name="owner", raw_key=raw_key, hash_secret="secret123")
    conv = create_conversation(api_key_id=key["id"], title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="hello", db_path=db_path)
    _ = archive_conversation(conversation_id=conv["id"], api_key_id=key["id"], db_path=db_path)

    response = client.patch(
        f"/v1/conversations/{conv['id']}/messages/{msg['id']}/memory",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={"pinned": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"
