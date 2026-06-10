from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

import app.deps as deps
from app.core.errors import APIError
from app.security.api_key import hash_api_key
from app.storage.api_keys import get_api_key_by_hash, mark_api_key_used


@dataclass
class AuthContext:
    api_key_id: str
    name: str
    environment: str
    allowed_models: list[str] | None
    daily_limit: int | None
    monthly_limit: int | None


def get_settings():
    return deps.get_settings()


def _extract_api_key(request: Request) -> str | None:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header:
        parts = auth_header.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            bearer_key = parts[1].strip()
            if bearer_key:
                return bearer_key

    custom_header = (request.headers.get("X-Nesty-API-Key") or "").strip()
    if custom_header:
        return custom_header
    return None


def _validate_raw_api_key(raw_key: str) -> AuthContext:
    settings = get_settings()
    key_hash = hash_api_key(raw_key, hash_secret=settings.nesty_api_key_hash_secret)
    record = get_api_key_by_hash(settings.nesty_db_path, key_hash)
    if not record:
        raise APIError(
            code="invalid_api_key",
            message="Invalid or inactive NestyAI API key.",
            status_code=401,
        )
    if not record.get("is_active", False):
        if record.get("revoked_at"):
            raise APIError(
                code="api_key_revoked",
                message="This API key has been revoked.",
                status_code=403,
            )
        raise APIError(
            code="invalid_api_key",
            message="Invalid or inactive NestyAI API key.",
            status_code=401,
        )

    api_key_id = str(record["id"])
    mark_api_key_used(settings.nesty_db_path, api_key_id)

    return AuthContext(
        api_key_id=api_key_id,
        name=str(record["name"]),
        environment=str(record["environment"]),
        allowed_models=record.get("allowed_models"),
        daily_limit=record.get("daily_limit"),
        monthly_limit=record.get("monthly_limit"),
    )


def require_api_key(request: Request) -> AuthContext:
    raw_key = _extract_api_key(request)
    if not raw_key:
        raise APIError(
            code="missing_api_key",
            message="Missing NestyAI API key.",
            status_code=401,
        )
    return _validate_raw_api_key(raw_key)


def optional_api_key(request: Request) -> AuthContext | None:
    raw_key = _extract_api_key(request)
    if not raw_key:
        return None
    return _validate_raw_api_key(raw_key)
