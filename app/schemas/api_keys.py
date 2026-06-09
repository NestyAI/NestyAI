from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from app.core.model_config_loader import load_default_model_configs


class InternalApiKeyCreateRequest(BaseModel):
    name: str
    environment: str = "prod"
    daily_limit: int | None = None
    monthly_limit: int | None = None
    models: list[str] | None = None
    key_prefix: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Name cannot be empty or only whitespace.")
        return v.strip()

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if v_clean not in ("dev", "live", "prod"):
            raise ValueError("Environment must be either 'dev', 'live', or 'prod'.")
        return v_clean

    @field_validator("daily_limit")
    @classmethod
    def validate_daily_limit(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("daily_limit must be >= 0.")
        return v

    @field_validator("monthly_limit")
    @classmethod
    def validate_monthly_limit(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("monthly_limit must be >= 0.")
        return v

    @field_validator("models")
    @classmethod
    def validate_models(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            valid_models = set(load_default_model_configs().keys())
            for model in v:
                if model not in valid_models:
                    raise ValueError(f"Invalid model alias: {model}")
        return v

    @field_validator("key_prefix")
    @classmethod
    def validate_key_prefix(cls, v: str | None) -> str | None:
        if v is not None:
            v_clean = v.strip()
            if not v_clean:
                raise ValueError("key_prefix cannot be empty.")
            if len(v_clean) > 20:
                raise ValueError("key_prefix cannot be longer than 20 characters.")
            if not all(c.isalnum() or c in ("_", "-") for c in v_clean):
                raise ValueError("key_prefix must contain only alphanumeric characters, underscores, or hyphens.")
            return v_clean
        return v


class InternalApiKeyUpdateRequest(BaseModel):
    name: str | None = None
    environment: str | None = None
    daily_limit: int | None = None
    monthly_limit: int | None = None
    models: list[str] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            if not v.strip():
                raise ValueError("Name cannot be empty or only whitespace.")
            return v.strip()
        return v

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str | None) -> str | None:
        if v is not None:
            v_clean = v.strip().lower()
            if v_clean not in ("dev", "live", "prod"):
                raise ValueError("Environment must be either 'dev', 'live', or 'prod'.")
            return v_clean
        return v

    @field_validator("daily_limit")
    @classmethod
    def validate_daily_limit(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("daily_limit must be >= 0.")
        return v

    @field_validator("monthly_limit")
    @classmethod
    def validate_monthly_limit(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("monthly_limit must be >= 0.")
        return v

    @field_validator("models")
    @classmethod
    def validate_models(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            valid_models = set(load_default_model_configs().keys())
            for model in v:
                if model not in valid_models:
                    raise ValueError(f"Invalid model alias: {model}")
        return v


class InternalApiKeyRevokeRequest(BaseModel):
    reason: str | None = None


class InternalApiKeyPublicInfo(BaseModel):
    id: str
    name: str
    environment: str
    key_prefix: str
    models: list[str] | None = None
    daily_limit: int | None = None
    monthly_limit: int | None = None
    is_revoked: bool
    revoked_at: str | None = None
    created_at: str
    updated_at: str | None = None
    last_used_at: str | None = None
    usage_today: int | None = None
    usage_month: int | None = None


class InternalApiKeyCreateResponse(BaseModel):
    api_key: InternalApiKeyPublicInfo
    raw_key: str


class InternalApiKeyListResponse(BaseModel):
    items: list[InternalApiKeyPublicInfo]
    limit: int
    offset: int
    has_more: bool


class InternalApiKeyRevokeResponse(BaseModel):
    id: str
    is_revoked: bool
    revoked_at: str | None
    reason: str | None = None
