from __future__ import annotations

import pytest
from fastapi import Request

from app.core.errors import APIError
from app.security.console_client_auth import require_console_client


def _request(headers: dict[str, str] | None = None) -> Request:
    encoded = []
    for key, value in (headers or {}).items():
        encoded.append((key.lower().encode("utf-8"), value.encode("utf-8")))
    return Request({"type": "http", "headers": encoded})


def test_console_client_auth_disabled_allows_missing_headers(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.console_client_auth.get_settings",
        lambda: type(
            "S",
            (),
            {
                "nesty_console_client_auth_required": False,
                "nesty_console_client_id": "default-console",
                "nesty_console_client_secret": None,
            },
        )(),
    )
    require_console_client(_request())


def test_console_client_auth_required_rejects_missing_headers(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.console_client_auth.get_settings",
        lambda: type(
            "S",
            (),
            {
                "nesty_console_client_auth_required": True,
                "nesty_console_client_id": "default-console",
                "nesty_console_client_secret": "ncc_secret_value_1234567890",
            },
        )(),
    )
    with pytest.raises(APIError) as exc:
        require_console_client(_request())
    assert exc.value.code == "console_client_unauthorized"


def test_console_client_auth_required_accepts_valid_headers(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.security.console_client_auth.get_settings",
        lambda: type(
            "S",
            (),
            {
                "nesty_console_client_auth_required": True,
                "nesty_console_client_id": "default-console",
                "nesty_console_client_secret": "ncc_secret_value_1234567890",
            },
        )(),
    )
    require_console_client(
        _request(
            {
                "X-Nesty-Console-ID": "default-console",
                "X-Nesty-Console-Secret": "ncc_secret_value_1234567890",
            }
        )
    )
