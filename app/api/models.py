from __future__ import annotations

from fastapi import APIRouter, Request

import app.deps as deps
from app.core.model_config_loader import list_effective_model_configs
from app.deps import get_models_config
from app.security.auth import require_api_key
from app.schemas.models import ModelCard, ModelListResponse


router = APIRouter(prefix="/v1", tags=["models"])


def get_settings():
    return deps.get_settings()


@router.get("/models", response_model=ModelListResponse)
async def list_models(request: Request) -> ModelListResponse:
    settings = get_settings()
    if settings.require_api_key and not settings.public_models:
        require_api_key(request)

    cards: list[ModelCard] = []
    try:
        effective_rows = list_effective_model_configs()
        cards = [
            ModelCard(
                id=str(row["model_id"]),
                description=str((row.get("effective_config") or {}).get("description") or ""),
                config_source=str(row.get("config_source") or "default"),
            )
            for row in effective_rows
        ]
    except Exception:
        config = get_models_config()
        cards = [
            ModelCard(
                id=model_id,
                description=model_profile.description,
            )
            for model_id, model_profile in config.models.items()
        ]
    return ModelListResponse(data=cards)

