"""
Pydantic schemas for Invoice Agent API.

Request and response models for the /ask endpoint.
All user-facing responses are in Spanish.
Error codes and technical messages are in English.
"""

from typing import Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Request model for the /ask endpoint."""

    session_id: str = Field(
        ...,
        description="Unique identifier for the conversation session",
        min_length=1,
    )
    question: str = Field(
        ...,
        description="Natural language question from the user (can be in Spanish)",
        min_length=1,
    )


class AskResponse(BaseModel):
    """Response model for the /ask endpoint."""

    answer: Optional[str] = Field(
        None,
        description="Final answer to the user in Spanish",
    )
    error_code: Optional[str] = Field(
        None,
        description="Error code in English (e.g., 'validation_error', 'mcp_error', 'agent_error')",
    )
    error_message: Optional[str] = Field(
        None,
        description="Technical error message in English for debugging",
    )


class HealthResponse(BaseModel):
    """Response model for the /health endpoint."""

    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")
