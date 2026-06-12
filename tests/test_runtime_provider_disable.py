from __future__ import annotations

from app.core.runtime_gateway_state import (
    get_runtime_gateway_state,
    is_provider_runtime_disabled,
    set_provider_runtime_disabled,
)
from app.storage.db import init_db


def test_runtime_provider_disable_is_reversible(tmp_path) -> None:
    db_path = str(tmp_path / "runtime_state.db")
    init_db(db_path)

    assert is_provider_runtime_disabled("groq", db_path=db_path) is False
    state = set_provider_runtime_disabled("groq", disabled=True, db_path=db_path)
    assert "groq" in state["disabled_providers"]
    assert is_provider_runtime_disabled("groq", db_path=db_path) is True

    state = set_provider_runtime_disabled("groq", disabled=False, db_path=db_path)
    assert "groq" not in state["disabled_providers"]
    assert is_provider_runtime_disabled("groq", db_path=db_path) is False

    loaded = get_runtime_gateway_state(db_path=db_path)
    assert loaded["disabled_providers"] == []
