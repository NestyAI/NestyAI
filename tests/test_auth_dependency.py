from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.errors import APIError, build_error_response
from app.security.api_key import generate_api_key
from app.security.auth import AuthContext, require_api_key
from app.storage.api_keys import create_api_key_record, revoke_api_key
from app.storage.db import init_db


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.get("/protected")
    async def protected(auth: AuthContext = Depends(require_api_key)) -> dict[str, str]:
        return {"api_key_id": auth.api_key_id, "name": auth.name}

    return app


def test_missing_key_rejected(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "auth.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)

    client = TestClient(_build_test_app())
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


def test_invalid_key_rejected(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "auth.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)

    client = TestClient(_build_test_app())
    response = client.get("/protected", headers={"Authorization": "Bearer nsk_dev_invalid"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_active_key_accepted_with_bearer(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "auth.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)

    raw_key = generate_api_key("dev")
    record = create_api_key_record(
        db_path=db_path,
        name="dev-key",
        raw_key=raw_key,
        hash_secret="secret123",
    )
    client = TestClient(_build_test_app())
    response = client.get("/protected", headers={"Authorization": f"Bearer {raw_key}"})
    assert response.status_code == 200
    assert response.json()["api_key_id"] == record["id"]


def test_revoked_key_rejected(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "auth.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)

    raw_key = generate_api_key("dev")
    record = create_api_key_record(
        db_path=db_path,
        name="dev-key",
        raw_key=raw_key,
        hash_secret="secret123",
    )
    revoke_api_key(db_path, record["id"])

    client = TestClient(_build_test_app())
    response = client.get("/protected", headers={"Authorization": f"Bearer {raw_key}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


def test_x_nesty_header_accepted(monkeypatch, tmp_path) -> None:
    db_path = str(tmp_path / "auth.db")
    init_db(db_path)
    settings = Settings(nesty_db_path=db_path, nesty_api_key_hash_secret="secret123")
    monkeypatch.setattr("app.security.auth.get_settings", lambda: settings)

    raw_key = generate_api_key("dev")
    create_api_key_record(
        db_path=db_path,
        name="dev-key",
        raw_key=raw_key,
        hash_secret="secret123",
    )

    client = TestClient(_build_test_app())
    response = client.get("/protected", headers={"X-Nesty-API-Key": raw_key})
    assert response.status_code == 200
