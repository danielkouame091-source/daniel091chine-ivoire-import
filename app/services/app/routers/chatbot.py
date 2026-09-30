"""Endpoints Chatbot — REST + SSE streaming."""
from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.dependencies.auth import CurrentUser
from app.dependencies.subscription import RequireActiveSubscription
from app.dependencies.tenant import CurrentTenant
from app.dependencies.tenant_db import TenantDBSession
from app.schemas.chatbot import (
    ChatFeedbackIn,
    ChatRequest,
    ChatResponse,
    ConversationDetailOut,
    ConversationOut,
    MessageOut,
)
from app.services.chatbot_service import ChatbotService

router = APIRouter()


def _svc(current_tenant, current_user, db) -> ChatbotService:
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    return ChatbotService(db, current_tenant.id, current_user.id, role=role)


# ═════════════════════════════════════════════════════════════════════════════
# CHAT (NON-STREAMING)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> ChatResponse:
    svc = _svc(current_tenant, current_user, db)
    return await svc.chat(
        message=data.message,
        conversation_id=data.conversation_id,
        page_contexte=data.page_contexte,
        use_tools=data.use_tools,
        use_rag=data.use_rag,
        langue=data.langue,
    )


# ═════════════════════════════════════════════════════════════════════════════
# CHAT STREAMING (SSE)
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/chat/stream")
async def chat_stream(
    data: ChatRequest,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    _: RequireActiveSubscription,
    db: TenantDBSession,
) -> StreamingResponse:
    svc = _svc(current_tenant, current_user, db)

    async def event_generator():
        try:
            async for chunk in svc.chat_stream(
                message=data.message,
                conversation_id=data.conversation_id,
                page_contexte=data.page_contexte,
                use_tools=data.use_tools,
                use_rag=data.use_rag,
                langue=data.langue,
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ═════════════════════════════════════════════════════════════════════════════
# CONVERSATIONS
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
    limit: int = 50,
) -> list[ConversationOut]:
    svc = _svc(current_tenant, current_user, db)
    rows = await svc.lister_conversations(limit)
    return [ConversationOut.model_validate(c) for c in rows]


@router.get("/conversations/{conv_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conv_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> ConversationDetailOut:
    svc = _svc(current_tenant, current_user, db)
    data = await svc.get_conversation_detail(conv_id)
    return ConversationDetailOut(
        **{k: v for k, v in data.items() if k != "messages"},
        messages=[MessageOut.model_validate(m) for m in data["messages"]],
    )


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: UUID,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> None:
    svc = _svc(current_tenant, current_user, db)
    await svc.supprimer_conversation(conv_id)


# ═════════════════════════════════════════════════════════════════════════════
# FEEDBACK
# ═════════════════════════════════════════════════════════════════════════════
@router.post("/feedback", response_model=MessageOut)
async def feedback(
    data: ChatFeedbackIn,
    current_tenant: CurrentTenant,
    current_user: CurrentUser,
    db: TenantDBSession,
) -> MessageOut:
    svc = _svc(current_tenant, current_user, db)
    msg = await svc.donner_feedback(data.message_id, data.feedback, data.commentaire)
    return MessageOut.model_validate(msg)


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/health")
async def chatbot_health() -> dict:
    from app.integrations.ollama_client import ollama_client
    from app.core.llm_config import llm_settings

    ok = await ollama_client.health()
    return {
        "status": "ok" if ok else "degraded",
        "provider": llm_settings.LLM_PROVIDER,
        "model": llm_settings.OLLAMA_MODEL,
        "ollama_reachable": ok,
    }
