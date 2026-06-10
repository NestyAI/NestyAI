from __future__ import annotations

from pydantic import BaseModel, Field


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "nestyai"
    description: str
    config_source: str | None = None


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelCard] = Field(default_factory=list)
