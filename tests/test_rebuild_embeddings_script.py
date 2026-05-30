from __future__ import annotations

import argparse
import asyncio
import importlib

from app.storage.conversations import add_message, create_conversation, update_message_memory_controls
from app.storage.db import init_db


def test_rebuild_embeddings_script_import_has_no_side_effects() -> None:
    module = importlib.import_module("scripts.rebuild_embeddings")
    assert callable(module.main)


def test_rebuild_embeddings_script_dry_run(monkeypatch, tmp_path, capsys) -> None:
    module = importlib.import_module("scripts.rebuild_embeddings")
    db_path = str(tmp_path / "rebuild_embeddings.db")
    init_db(db_path)

    conversation = create_conversation(api_key_id="key_1", title="Test", db_path=db_path)
    add_message(
        conversation_id=conversation["id"],
        role="user",
        content="This is a message for embeddings.",
        db_path=db_path,
    )

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "nesty_db_path": db_path,
                "embeddings_enabled": True,
                "embeddings_provider": "openrouter",
                "embeddings_model": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
                "embeddings_backfill_batch_size": 50,
            },
        )(),
    )
    args = argparse.Namespace(
        db=db_path,
        owner_type="conversation_message",
        limit=10,
        skip_excluded=True,
        dry_run=True,
    )
    code = asyncio.run(module._run(args))
    output = capsys.readouterr().out
    assert code == 0
    assert "candidates_found: 1" in output
    assert "embedded_count: 0" in output
    assert "skipped_count: 1" in output
    assert "This is a message for embeddings." not in output


def test_rebuild_embeddings_script_skips_excluded_by_default(monkeypatch, tmp_path, capsys) -> None:
    module = importlib.import_module("scripts.rebuild_embeddings")
    db_path = str(tmp_path / "rebuild_embeddings_excluded.db")
    init_db(db_path)

    conversation = create_conversation(api_key_id="key_1", title="Test", db_path=db_path)
    msg = add_message(
        conversation_id=conversation["id"],
        role="user",
        content="Excluded message for embeddings.",
        db_path=db_path,
    )
    _ = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conversation["id"],
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "nesty_db_path": db_path,
                "embeddings_enabled": True,
                "embeddings_provider": "openrouter",
                "embeddings_model": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
                "embeddings_backfill_batch_size": 50,
            },
        )(),
    )
    args = argparse.Namespace(
        db=db_path,
        owner_type="conversation_message",
        limit=10,
        skip_excluded=True,
        dry_run=True,
    )
    code = asyncio.run(module._run(args))
    output = capsys.readouterr().out
    assert code == 0
    assert "candidates_found: 0" in output


def test_rebuild_embeddings_script_can_include_excluded(monkeypatch, tmp_path, capsys) -> None:
    module = importlib.import_module("scripts.rebuild_embeddings")
    db_path = str(tmp_path / "rebuild_embeddings_include_excluded.db")
    init_db(db_path)

    conversation = create_conversation(api_key_id="key_1", title="Test", db_path=db_path)
    msg = add_message(
        conversation_id=conversation["id"],
        role="user",
        content="Excluded message for embeddings.",
        db_path=db_path,
    )
    _ = update_message_memory_controls(
        message_id=msg["id"],
        conversation_id=conversation["id"],
        api_key_id="key_1",
        excluded=True,
        db_path=db_path,
    )

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "nesty_db_path": db_path,
                "embeddings_enabled": True,
                "embeddings_provider": "openrouter",
                "embeddings_model": "nvidia/llama-nemotron-embed-vl-1b-v2:free",
                "embeddings_backfill_batch_size": 50,
            },
        )(),
    )
    args = argparse.Namespace(
        db=db_path,
        owner_type="conversation_message",
        limit=10,
        skip_excluded=False,
        dry_run=True,
    )
    code = asyncio.run(module._run(args))
    output = capsys.readouterr().out
    assert code == 0
    assert "candidates_found: 1" in output
