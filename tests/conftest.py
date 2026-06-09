from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = Settings.from_env()
    settings.require_api_key = False
    settings.public_models = True
    settings.public_health = True
    trusted_hosts = [host.strip() for host in str(getattr(settings, "trusted_hosts", "") or "").split(",") if host.strip()]
    if "testserver" not in trusted_hosts:
        trusted_hosts.append("testserver")
    settings.trusted_hosts = ",".join(trusted_hosts)
    monkeypatch.setattr("app.deps.get_settings", lambda: settings)
    app = create_app(settings=settings)
    return TestClient(app)

