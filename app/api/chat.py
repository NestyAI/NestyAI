from __future__ import annotations

from fastapi import APIRouter

from app.deps import get_orchestrator
from app.schemas.chat import ChatCompletionRequest, ChatCompletionResponse
from app.utils.ids import generate_request_id


router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
    orchestrator = get_orchestrator()
    request_id = generate_request_id()
    return await orchestrator.create_chat_completion(request_id=request_id, request=request)

