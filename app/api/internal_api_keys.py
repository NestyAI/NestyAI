from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Query

import app.deps as deps
from app.core.errors import APIError
from app.security.api_key import generate_api_key
from app.security.internal_auth import require_internal_admin
from app.storage.api_keys import (
    create_api_key_record,
    get_api_key_by_id,
    list_api_keys_filtered,
    revoke_api_key,
    update_api_key_record,
)
from app.storage.usage import count_daily_requests, count_monthly_requests
from app.schemas.api_keys import (
    InternalApiKeyCreateRequest,
    InternalApiKeyUpdateRequest,
    InternalApiKeyRevokeRequest,
    InternalApiKeyPublicInfo,
    InternalApiKeyCreateResponse,
    InternalApiKeyListResponse,
    InternalApiKeyRevokeResponse,
)

router = APIRouter(
    prefix="/internal/api-keys",
    tags=["internal-api-keys"],
    dependencies=[Depends(require_internal_admin)],
)


def get_settings():
    return deps.get_settings()


def map_db_record_to_public_info(record: dict[str, Any], settings: Any) -> dict[str, Any]:
    api_key_id = record["id"]
    is_revoked = not record.get("is_active", True)

    try:
        usage_today = count_daily_requests(settings.nesty_db_path, api_key_id)
        usage_month = count_monthly_requests(settings.nesty_db_path, api_key_id)
    except Exception:
        usage_today = None
        usage_month = None

    return {
        "id": api_key_id,
        "name": record["name"],
        "environment": record["environment"],
        "key_prefix": record["key_prefix"],
        "models": record.get("allowed_models"),
        "daily_limit": record.get("daily_limit"),
        "monthly_limit": record.get("monthly_limit"),
        "is_revoked": is_revoked,
        "revoked_at": record.get("revoked_at"),
        "created_at": record["created_at"],
        "updated_at": record["created_at"],  # Fallback to created_at
        "last_used_at": record.get("last_used_at"),
        "usage_today": usage_today,
        "usage_month": usage_month,
    }


@router.get("", response_model=InternalApiKeyListResponse)
async def list_api_keys_endpoint(
    environment: str | None = None,
    revoked: bool | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    settings = get_settings()

    # Query limit + 1 to detect has_more
    records = list_api_keys_filtered(
        db_path=settings.nesty_db_path,
        environment=environment,
        revoked=revoked,
        q=q,
        limit=limit + 1,
        offset=offset,
    )

    has_more = len(records) > limit
    if has_more:
        records = records[:limit]

    items = [map_db_record_to_public_info(r, settings) for r in records]

    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }


@router.post("", response_model=InternalApiKeyCreateResponse, status_code=201)
async def create_api_key_endpoint(body: InternalApiKeyCreateRequest) -> dict[str, Any]:
    settings = get_settings()

    if body.key_prefix:
        token = secrets.token_urlsafe(32)
        raw_key = f"{body.key_prefix}_{token}"
    else:
        # Generate with live/dev environment mapping to match existing nsk_live_ or nsk_dev_ prefix logic
        generate_env = "live" if body.environment.strip().lower() in ("live", "prod") else "dev"
        raw_key = generate_api_key(generate_env)

    record = create_api_key_record(
        db_path=settings.nesty_db_path,
        name=body.name,
        raw_key=raw_key,
        environment=body.environment,
        daily_limit=body.daily_limit,
        monthly_limit=body.monthly_limit,
        allowed_models=body.models,
        hash_secret=settings.nesty_api_key_hash_secret,
    )

    full_record = get_api_key_by_id(settings.nesty_db_path, record["id"])
    if full_record is None:
        raise APIError(
            code="api_key_create_failed",
            message="Failed to retrieve created API key.",
            status_code=500,
        )

    public_info = map_db_record_to_public_info(full_record, settings)

    return {
        "api_key": public_info,
        "raw_key": raw_key,
    }


@router.get("/{api_key_id}", response_model=InternalApiKeyPublicInfo)
async def get_api_key_endpoint(api_key_id: str) -> dict[str, Any]:
    settings = get_settings()
    record = get_api_key_by_id(settings.nesty_db_path, api_key_id)
    if record is None:
        raise APIError(
            code="api_key_not_found",
            message="API key not found.",
            status_code=404,
        )
    return map_db_record_to_public_info(record, settings)


@router.post("/{api_key_id}/revoke", response_model=InternalApiKeyRevokeResponse)
async def revoke_api_key_endpoint(
    api_key_id: str,
    body: InternalApiKeyRevokeRequest,
) -> dict[str, Any]:
    settings = get_settings()
    record = get_api_key_by_id(settings.nesty_db_path, api_key_id)
    if record is None:
        raise APIError(
            code="api_key_not_found",
            message="API key not found.",
            status_code=404,
        )

    if record.get("is_active"):
        revoke_api_key(settings.nesty_db_path, api_key_id)
        record = get_api_key_by_id(settings.nesty_db_path, api_key_id)

    response: dict[str, Any] = {
        "id": api_key_id,
        "is_revoked": True,
        "revoked_at": record.get("revoked_at") if record else None,
    }
    if body.reason is not None:
        response["reason"] = body.reason

    return response


@router.patch("/{api_key_id}", response_model=InternalApiKeyPublicInfo)
async def patch_api_key_endpoint(
    api_key_id: str,
    body: InternalApiKeyUpdateRequest,
) -> dict[str, Any]:
    settings = get_settings()

    record = get_api_key_by_id(settings.nesty_db_path, api_key_id)
    if record is None:
        raise APIError(
            code="api_key_not_found",
            message="API key not found.",
            status_code=404,
        )

    updates = body.model_dump(exclude_unset=True)
    if "models" in updates:
        updates["allowed_models"] = updates.pop("models")

    updated_record = update_api_key_record(
        db_path=settings.nesty_db_path,
        key_id=api_key_id,
        updates=updates,
    )

    if updated_record is None:
        raise APIError(
            code="api_key_not_found",
            message="API key not found.",
            status_code=404,
        )

    return map_db_record_to_public_info(updated_record, settings)
