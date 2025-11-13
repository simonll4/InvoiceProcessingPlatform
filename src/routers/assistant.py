"""Assistant endpoints for conversational Q&A about invoices."""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ..modules.assistant import LLMOrchestrator, SessionManager, SQLiteMCPServer
from ..modules.assistant.config import DB_PATH
from ..modules.assistant.models import (
    ChatRequest,
    ChatResponse,
    SessionChatRequest,
    SessionCreateResponse,
    SessionInfoResponse,
)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

# Global instances (initialized at startup)
mcp_server: SQLiteMCPServer | None = None
orchestrator: LLMOrchestrator | None = None
session_manager: SessionManager | None = None


def get_mcp_server() -> SQLiteMCPServer:
    """Dependency to get MCP server instance."""
    if mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    return mcp_server


def get_orchestrator() -> LLMOrchestrator:
    """Dependency to get orchestrator instance."""
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return orchestrator


def get_session_manager() -> SessionManager:
    """Dependency to get session manager instance."""
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")
    return session_manager


def cleanup_sessions():
    """Background task for session cleanup."""
    if session_manager:
        session_manager.cleanup_expired_sessions()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
) -> ChatResponse:
    """
    Stateless chat endpoint - no session required.

    Use this for one-off questions without conversation history.
    """
    orch = get_orchestrator()

    try:
        result = orch.process_question(request.question)

        # Schedule cleanup
        background_tasks.add_task(cleanup_sessions)

        # orchestrator returns a dict with success, answer, tool_calls, etc.
        if isinstance(result, dict):
            return ChatResponse(
                success=result.get("success", True),
                answer=result.get("answer", ""),
                session_id=None,
            )
        else:
            # Fallback if it's a plain string
            return ChatResponse(
                success=True,
                answer=str(result),
                session_id=None,
            )
    except Exception as e:
        return ChatResponse(
            success=False,
            answer=f"Error processing question: {str(e)}",
            session_id=None,
        )


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(user_id: str = "anonymous") -> SessionCreateResponse:
    """Create a new conversation session."""
    mgr = get_session_manager()
    session = mgr.create_session(user_id)

    return SessionCreateResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at.isoformat(),
    )


@router.post("/sessions/{session_id}/chat", response_model=ChatResponse)
async def chat_with_session(
    session_id: str,
    request: SessionChatRequest,
    background_tasks: BackgroundTasks,
) -> ChatResponse:
    """
    Chat with conversation history.

    Maintains context across multiple questions.
    """
    mgr = get_session_manager()
    orch = get_orchestrator()

    # Get session
    session = mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Process with history
        result = orch.process_question(request.question, history=session.history)

        # Extract answer from result dict
        if isinstance(result, dict):
            answer = result.get("answer", "")
            success = result.get("success", True)
        else:
            answer = str(result)
            success = True

        # Update session
        mgr.add_message(session_id, "user", request.question)
        mgr.add_message(session_id, "assistant", answer)

        # Schedule cleanup
        background_tasks.add_task(cleanup_sessions)

        return ChatResponse(
            success=success,
            answer=answer,
            session_id=session_id,
        )
    except Exception as e:
        return ChatResponse(
            success=False,
            answer=f"Error: {str(e)}",
            session_id=session_id,
        )


@router.get("/sessions/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str) -> SessionInfoResponse:
    """Get session information and history."""
    mgr = get_session_manager()
    session = mgr.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionInfoResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at.isoformat(),
        last_activity=session.last_activity.isoformat(),
        message_count=len(session.history),
        history=session.history,
    )


@router.get("/sessions")
async def list_sessions() -> dict:
    """List all active sessions."""
    mgr = get_session_manager()
    sessions = mgr.list_active_sessions()

    return {
        "count": len(sessions),
        "sessions": [
            {
                "session_id": s.session_id,
                "user_id": s.user_id,
                "message_count": len(s.history),
                "last_activity": s.last_activity.isoformat(),
            }
            for s in sessions
        ],
    }


@router.get("/stats")
async def get_stats() -> dict:
    """Get assistant statistics."""
    mcp = get_mcp_server()
    schema = mcp.get_schema()

    # Get invoice count
    result = mcp.execute_query("SELECT COUNT(*) as count FROM invoices")
    invoice_count = result["rows"][0]["count"] if result["rows"] else 0

    return {
        "database": str(DB_PATH),
        "tables": len(schema.get("tables", {})),
        "invoices": invoice_count,
        "mcp_tools": len(mcp.get_tools_description()),
    }
