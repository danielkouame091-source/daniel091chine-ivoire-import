"""DTO Chatbot."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ─── REQUÊTES ───────────────────────────────────────────────
class ChatRequest(BaseModel):
    """Requête utilisateur → chatbot."""
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: UUID | None = None    # None = nouvelle conv.
    page_contexte: str | None = None
    stream: bool = False
    use_tools: bool = True
    use_rag: bool = True
    langue: Literal["fr", "en", "dyu", "bci", "nouchi"] = "fr"


class ChatFeedbackIn(BaseModel):
    message_id: UUID
    feedback: Literal[-1, 1]
    commentaire: str | None = Field(None, max_length=1000)


# ─── RÉPONSES ───────────────────────────────────────────────
class SourceOut(BaseModel):
    document_id: UUID
    chunk_id: UUID
    titre: str
    extrait: str
    score: float
    source_url: str | None = None


class ToolCallOut(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    resultat: dict[str, Any] | None = None
    statut: str
    latence_ms: int | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    reponse: str
    sources: list[SourceOut] = Field(default_factory=list)
    tools_executed: list[ToolCallOut] = Field(default_factory=list)
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    latence_ms: int
    modele: str


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    titre: str | None
    nb_messages: int
    statut: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: str
    contenu: str
    sources: list[dict[str, Any]] | None
    tool_calls: list[dict[str, Any]] | None
    tokens_prompt: int | None
    tokens_completion: int | None
    latence_ms: int | None
    feedback: int | None
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


# ─── STREAMING (SSE) ────────────────────────────────────────
class StreamChunk(BaseModel):
    """Chunk SSE envoyé au client."""
    type: Literal["token", "sources", "tool", "done", "error"]
    content: str | dict[str, Any] | None = None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
