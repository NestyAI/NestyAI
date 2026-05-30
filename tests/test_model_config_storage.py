from __future__ import annotations

from app.storage.db import init_db
from app.storage.model_configs import (
    get_model_config_audit_logs,
    get_model_override,
    list_model_overrides,
    reset_model_override,
    upsert_model_override,
)


def test_model_config_storage_upsert_list_reset_and_audit(tmp_path) -> None:
    db_path = str(tmp_path / "model_config_storage.db")
    init_db(db_path)

    override = {"display_name": "Flash Fast", "default_temperature": 0.5}
    created = upsert_model_override(
        model_id="nesty-flash-1.0",
        config=override,
        changed_by_label="test-suite",
        db_path=db_path,
    )
    assert created["model_id"] == "nesty-flash-1.0"
    assert created["config"]["display_name"] == "Flash Fast"

    listed = list_model_overrides(db_path=db_path)
    assert len(listed) == 1
    assert listed[0]["model_id"] == "nesty-flash-1.0"

    fetched = get_model_override(model_id="nesty-flash-1.0", db_path=db_path)
    assert fetched is not None
    assert fetched["config"]["default_temperature"] == 0.5

    updated = upsert_model_override(
        model_id="nesty-flash-1.0",
        config={"display_name": "Flash Updated"},
        changed_by_label="test-suite",
        db_path=db_path,
    )
    assert updated["config"]["display_name"] == "Flash Updated"

    assert reset_model_override("nesty-flash-1.0", changed_by_label="test-suite", db_path=db_path) is True
    assert get_model_override("nesty-flash-1.0", db_path=db_path) is None

    logs = get_model_config_audit_logs(model_id="nesty-flash-1.0", limit=20, db_path=db_path)
    actions = [item["action"] for item in logs]
    assert "create_override" in actions
    assert "update_override" in actions
    assert "reset_override" in actions
