from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import get_models_config
from app.deps import get_settings
from app.security.auth import require_api_key
from app.schemas.models import ModelCard, ModelListResponse


router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", response_model=ModelListResponse)
async def list_models(request: Request) -> ModelListResponse:
    settings = get_settings()
    if settings.require_api_key and not settings.public_models:
        require_api_key(request)

    config = get_models_config()
    cards = [
        ModelCard(
            id=model_id,
            description=model_profile.description,
        )
        for model_id, model_profile in config.models.items()
    ]
    return ModelListResponse(data=cards)

