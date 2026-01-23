from __future__ import annotations

from fastapi import APIRouter, Depends

from internal.controllers.schemas import ChatOk, ChatRequest
from internal.dependencies import get_chat_usecase, get_user_key
from internal.usecases.chat_usecase import ChatUseCase


router = APIRouter()

@router.post("/api/chat", response_model=ChatOk)
async def chat(
    req: ChatRequest,
    user_key: str = Depends(get_user_key),
    usecase: ChatUseCase = Depends(get_chat_usecase),
) -> ChatOk:
    response_text, sid = await usecase.chat(user_key, req.message, req.session_id)
    return ChatOk(response=response_text, session_id=sid)

