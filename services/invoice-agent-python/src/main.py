"""
FastAPI application for Invoice Agent service.

Provides endpoints:
- POST /ask: Ask a question about invoices
- GET /health: Health check

The agent uses LangGraph to orchestrate question answering with:
- Conversation memory per session
- SQL generation and validation
- MCP-based database access
- Spanish responses for users
"""

from fastapi import FastAPI
from loguru import logger

from .agent.graph import save_to_memory
from .api.schemas import AskRequest, AskResponse, HealthResponse
from .config import settings
from .di import get_graph, get_memory_store

app = FastAPI(
    title="Invoice Agent Service",
    description="AI agent for Q&A sobre facturas usando LangGraph y Groq",
    version="1.0.0",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns:
        Service status and name
    """
    return HealthResponse(status="ok", service="invoice-agent")


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """
    Ask a question about invoices.
    
    The agent will:
    1. Load conversation history for the session
    2. Understand the question using context
    3. Generate and execute SQL query
    4. Return answer in Spanish
    
    Args:
        request: Question and session ID
        
    Returns:
        Answer in Spanish, or error information
    """
    session_id = request.session_id
    question = request.question
    
    logger.info(f"[Ask] Received question from session {session_id}: {question}")
    
    try:
        # Get dependencies
        graph = get_graph()
        memory_store = get_memory_store()
        
        # Create initial state
        initial_state = {
            "session_id": session_id,
            "question": question,
        }
        
        logger.info(f"[Ask] Invoking graph for session {session_id}")
        
        # Execute the graph
        final_state = graph.invoke(initial_state)
        
        logger.info(f"[Ask] Graph execution completed for session {session_id}")
        logger.debug(f"[Ask] Final state: error_code={final_state.get('error_code')}, has_answer={bool(final_state.get('answer'))}")
        
        # Save to memory if successful (has answer and no critical error)
        if final_state.get("answer"):
            save_to_memory(final_state, memory_store)
        
        # Build response
        response = AskResponse(
            answer=final_state.get("answer"),
            error_code=final_state.get("error_code"),
            error_message=final_state.get("error_message"),
        )
        
        logger.info(f"[Ask] Returning response for session {session_id}")
        
        return response
    
    except Exception as exc:
        logger.error(f"[Ask] Unexpected error processing question: {exc}")
        
        # Return a generic error response in Spanish
        return AskResponse(
            answer="Lo siento, ocurrió un error inesperado al procesar tu pregunta.",
            error_code="internal_error",
            error_message=f"Unexpected error: {str(exc)}",
        )


def run_dev() -> None:
    """Helper para levantar el servicio en desarrollo."""
    import uvicorn

    logger.info(f"Starting Invoice Agent service on {settings.api_host}:{settings.api_port}")
    
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )


