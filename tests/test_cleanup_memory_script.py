from __future__ import annotations

import argparse
import importlib

from app.storage.conversations import add_message, create_conversation, update_message_memory_controls
from app.storage.db import init_db
from app.storage.embeddings import create_embedding_record, count_embedding_records


def test_cleanup_memory_script_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.cleanup_memory")
    assert callable(module.main)


def test_cleanup_memory_dry_run_does_not_delete(monkeypatch, tmp_path, capsys) -> None:
    module = importlib.import_module("scripts.cleanup_memory")
    db_path = str(tmp_path / "cleanup_memory_dry.db")
    init_db(db_path)
    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="hello", db_path=db_path)
    _ = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )
    _ = create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed",
        embedding=[1.0, 0.0],
        content_hash="h1",
        db_path=db_path,
    )
    monkeypatch.setattr(module, "get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    code = module._run(
        argparse.Namespace(
            db=db_path,
            apply=False,
            delete_embeddings_for_excluded=True,
            conversation_id=None,
            older_than_days=None,
        )
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "dry_run: True" in out
    assert count_embedding_records(db_path) == 1


def test_cleanup_memory_apply_deletes_excluded_embeddings(monkeypatch, tmp_path, capsys) -> None:
    module = importlib.import_module("scripts.cleanup_memory")
    db_path = str(tmp_path / "cleanup_memory_apply.db")
    init_db(db_path)
    conv = create_conversation(api_key_id="key_1", title="A", db_path=db_path)
    msg = add_message(conversation_id=conv["id"], role="user", content="hello", db_path=db_path)
    _ = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conv["id"],
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )
    _ = create_embedding_record(
        owner_type="conversation_message",
        owner_id=msg["id"],
        api_key_id="key_1",
        provider="openrouter",
        model="embed",
        embedding=[1.0, 0.0],
        content_hash="h1",
        db_path=db_path,
    )
    monkeypatch.setattr(module, "get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())
    code = module._run(
        argparse.Namespace(
            db=db_path,
            apply=True,
            delete_embeddings_for_excluded=True,
            conversation_id=None,
            older_than_days=None,
        )
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "deleted_embeddings_count: 1" in out
    assert count_embedding_records(db_path) == 0
