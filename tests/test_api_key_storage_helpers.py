from __future__ import annotations

import json
from typing import Any

import pytest

from app.security.api_key import generate_api_key, hash_api_key
from app.storage.api_keys import (
    create_api_key_record,
    get_api_key_by_id,
    list_api_keys_filtered,
    revoke_api_key,
    update_api_key_record,
    _parse_allowed_models,
)
from app.storage.db import init_db


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "test_api_keys.db")
    init_db(path)
    return path


def test_get_api_key_by_id(db_path: str) -> None:
    # Test getting a non-existent key
    assert get_api_key_by_id(db_path, "key_nonexistent") is None

    # Create a key
    raw_key = generate_api_key("dev")
    record = create_api_key_record(
        db_path=db_path,
        name="test-key",
        raw_key=raw_key,
        environment="dev",
        daily_limit=100,
        monthly_limit=2000,
        allowed_models=["model-a", "model-b"],
        hash_secret="secret123",
    )

    key_id = record["id"]
    fetched = get_api_key_by_id(db_path, key_id)
    assert fetched is not None
    assert fetched["id"] == key_id
    assert fetched["name"] == "test-key"
    assert fetched["environment"] == "dev"
    assert fetched["is_active"] is True
    assert fetched["daily_limit"] == 100
    assert fetched["monthly_limit"] == 2000
    assert fetched["allowed_models"] == ["model-a", "model-b"]
    assert "key_hash" in fetched
    assert fetched["key_prefix"] == raw_key[:12]  # Checks prefix logic


def test_list_api_keys_filtered(db_path: str) -> None:
    # Create multiple keys in different environments and states
    # Key 1: active dev key
    k1 = create_api_key_record(
        db_path=db_path,
        name="alpha-dev-key",
        raw_key=generate_api_key("dev"),
        environment="dev",
    )
    # Key 2: active prod key
    k2 = create_api_key_record(
        db_path=db_path,
        name="beta-prod-key",
        raw_key=generate_api_key("prod"),
        environment="prod",
    )
    # Key 3: revoked dev key
    k3 = create_api_key_record(
        db_path=db_path,
        name="gamma-dev-key",
        raw_key=generate_api_key("dev"),
        environment="dev",
    )
    revoke_api_key(db_path, k3["id"])

    # 1. No filters (limit defaults to 50)
    all_keys = list_api_keys_filtered(db_path)
    assert len(all_keys) == 3
    # Ordered by created_at DESC (k3, then k2, then k1)
    assert all_keys[0]["id"] == k3["id"]
    assert all_keys[1]["id"] == k2["id"]
    assert all_keys[2]["id"] == k1["id"]

    # 2. Filter by environment
    dev_keys = list_api_keys_filtered(db_path, environment="dev")
    assert len(dev_keys) == 2
    assert {k["id"] for k in dev_keys} == {k1["id"], k3["id"]}

    prod_keys = list_api_keys_filtered(db_path, environment="prod")
    assert len(prod_keys) == 1
    assert prod_keys[0]["id"] == k2["id"]

    # 3. Filter by revoked
    revoked_keys = list_api_keys_filtered(db_path, revoked=True)
    assert len(revoked_keys) == 1
    assert revoked_keys[0]["id"] == k3["id"]

    active_keys = list_api_keys_filtered(db_path, revoked=False)
    assert len(active_keys) == 2
    assert {k["id"] for k in active_keys} == {k1["id"], k2["id"]}

    # 4. Filter by q (name or prefix)
    q_keys = list_api_keys_filtered(db_path, q="prod")
    assert len(q_keys) == 1
    assert q_keys[0]["id"] == k2["id"]

    # Test prefix matching
    prefix = k1["key_prefix"]
    q_prefix_keys = list_api_keys_filtered(db_path, q=prefix)
    assert len(q_prefix_keys) == 1
    assert q_prefix_keys[0]["id"] == k1["id"]

    # 5. Limit and offset
    limited = list_api_keys_filtered(db_path, limit=2)
    assert len(limited) == 2
    assert limited[0]["id"] == k3["id"]
    assert limited[1]["id"] == k2["id"]

    offset_keys = list_api_keys_filtered(db_path, limit=2, offset=1)
    assert len(offset_keys) == 2
    assert offset_keys[0]["id"] == k2["id"]
    assert offset_keys[1]["id"] == k1["id"]

    # 6. Safety check for out of bounds limits
    safe_keys_neg = list_api_keys_filtered(db_path, limit=-10)
    assert len(safe_keys_neg) == 3  # defaults back to 50
    safe_keys_huge = list_api_keys_filtered(db_path, limit=9999)
    assert len(safe_keys_huge) == 3  # defaults back to 50 (or max)


def test_update_api_key_record(db_path: str) -> None:
    # Update a non-existent key
    assert update_api_key_record(db_path, "key_nonexistent", {"name": "test"}) is None

    # Create a key
    k = create_api_key_record(
        db_path=db_path,
        name="initial-name",
        raw_key=generate_api_key("dev"),
        environment="dev",
        daily_limit=10,
        monthly_limit=100,
        allowed_models=["model-x"],
    )
    key_id = k["id"]

    # Update subset of fields
    updated = update_api_key_record(
        db_path,
        key_id,
        {
            "name": "updated-name",
            "daily_limit": 50,
            "allowed_models": ["model-y", "model-z"],
        },
    )

    assert updated is not None
    assert updated["id"] == key_id
    assert updated["name"] == "updated-name"
    assert updated["environment"] == "dev"  # unchanged
    assert updated["daily_limit"] == 50
    assert updated["monthly_limit"] == 100  # unchanged
    assert updated["allowed_models"] == ["model-y", "model-z"]

    # Update with empty dict (should just return record)
    assert update_api_key_record(db_path, key_id, {})["name"] == "updated-name"

    # Update allowed_models to None/null
    updated_null_models = update_api_key_record(
        db_path,
        key_id,
        {"allowed_models": None},
    )
    assert updated_null_models["allowed_models"] is None

    # Update allowed_models to empty list (should be stored as None/null)
    updated_empty_models = update_api_key_record(
        db_path,
        key_id,
        {"allowed_models": []},
    )
    assert updated_empty_models["allowed_models"] is None


def test_parse_allowed_models_non_string() -> None:
    assert _parse_allowed_models(None) is None
    assert _parse_allowed_models(123) == ["123"]
    assert _parse_allowed_models(True) == ["True"]
    assert _parse_allowed_models("") is None
