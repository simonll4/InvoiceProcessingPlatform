"""Modelos Pydantic para request/response de la API."""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request para una pregunta puntual sin sesión."""

    question: str = Field(..., min_length=1, description="Pregunta del usuario")
    include_debug: bool = Field(
        default=False, description="Incluir información de debug (tool calls, etc.)"
    )


class SessionChatRequest(BaseModel):
    """Request para una pregunta dentro de una sesión con historial."""

    question: str = Field(..., min_length=1, description="Pregunta del usuario")
    include_debug: bool = Field(default=False, description="Incluir debug info")


class ChatResponse(BaseModel):
    """Standard response for queries."""

    success: bool
    answer: str
    session_id: str | None = None
    debug: dict[str, Any] | None = None


class SessionCreateResponse(BaseModel):
    """Response al crear una nueva sesión."""

    session_id: str
    created_at: float


class SessionInfoResponse(BaseModel):
    """Información sobre una sesión."""

    session_id: str
    created_at: float
    last_activity: float
    message_count: int
    is_expired: bool


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    database_accessible: bool
    llm_configured: bool


class StatsResponse(BaseModel):
    """Estadísticas del servicio."""

    sessions: dict[str, Any]
    database: dict[str, Any]
