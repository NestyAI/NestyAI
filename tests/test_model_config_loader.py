from __future__ import annotations

from app.core.model_config_loader import (
    get_default_model_config,
    get_effective_model_config,
    list_effective_model_configs,
    load_default_model_configs,
    merge_model_config,
)
from app.storage.db import init_db
from app.storage.model_configs import upsert_model_override


def test_default_model_configs_load() -> None:
    defaults = load_default_model_configs()
    assert "nesty-flash-1.0" in defaults
    assert "nesty-combined-1.0" in defaults
    assert "nesty-pro-1.0" in defaults


def test_effective_config_equals_default_without_override(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "effective_no_override.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    default_cfg = get_default_model_config("nesty-flash-1.0")
    effective_cfg = get_effective_model_config("nesty-flash-1.0")
    assert default_cfg is not None
    assert effective_cfg is not None
    assert effective_cfg["display_name"] == default_cfg["display_name"]


def test_effective_config_uses_override_and_provider_chain_replaces(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "effective_with_override.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    override = {
        "display_name": "Flash Runtime",
        "provider_chain": [{"provider": "openrouter", "model": "qwen/qwen3-14b:free"}],
    }
    upsert_model_override("nesty-flash-1.0", override, changed_by_label="test", db_path=db_path)
    effective = get_effective_model_config("nesty-flash-1.0")
    assert effective is not None
    assert effective["display_name"] == "Flash Runtime"
    assert effective["provider_chain"] == [{"provider": "openrouter", "model": "qwen/qwen3-14b:free"}]


def test_merge_model_config_deep_merge_dicts() -> None:
    default = {"a": {"b": 1, "c": 2}, "list": [1, 2], "x": "y"}
    override = {"a": {"c": 9}, "list": [3], "x": "z"}
    merged = merge_model_config(default, override)
    assert merged["a"]["b"] == 1
    assert merged["a"]["c"] == 9
    assert merged["list"] == [3]
    assert merged["x"] == "z"


def test_list_effective_model_configs_contains_source(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "effective_list.db")
    init_db(db_path)
    monkeypatch.setattr("app.storage.model_configs.get_settings", lambda: type("S", (), {"nesty_db_path": db_path})())

    upsert_model_override("nesty-combined-1.0", {"display_name": "Combined Runtime"}, db_path=db_path)
    rows = list_effective_model_configs()
    combined = next(item for item in rows if item["model_id"] == "nesty-combined-1.0")
    assert combined["config_source"] == "override"
    assert combined["effective_config"]["display_name"] == "Combined Runtime"
