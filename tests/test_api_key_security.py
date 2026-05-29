from __future__ import annotations

from app.security.api_key import generate_api_key, hash_api_key, verify_api_key
from app.storage.api_keys import create_api_key_record, get_api_key_by_hash
from app.storage.db import init_db


def test_generate_api_key_prefixes() -> None:
    dev_key = generate_api_key("dev")
    live_key = generate_api_key("live")
    assert dev_key.startswith("nsk_dev_")
    assert live_key.startswith("nsk_live_")


def test_hash_and_verify_with_secret() -> None:
    raw_key = generate_api_key("dev")
    key_hash = hash_api_key(raw_key, hash_secret="secret123")
    assert verify_api_key(raw_key, key_hash, hash_secret="secret123") is True
    assert verify_api_key(raw_key + "_bad", key_hash, hash_secret="secret123") is False


def test_raw_key_is_not_stored(tmp_path) -> None:
    db_path = str(tmp_path / "test_auth.db")
    init_db(db_path)
    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="local-dev",
        raw_key=raw_key,
        environment="dev",
        hash_secret="secret123",
    )
    stored = get_api_key_by_hash(db_path, hash_api_key(raw_key, hash_secret="secret123"))
    assert stored is not None
    assert stored["key_hash"] != raw_key
