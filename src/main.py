"""
Invoice Processing Platform - Unified API

Combines OCR/LLM pipeline and conversational assistant in a single service.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .modules.assistant import LLMOrchestrator, SessionManager, SQLiteMCPServer
from .modules.assistant.config import DB_PATH
from .routers import assistant, monitoring, pipeline

# Static files location
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    logger.info("=== Starting Invoice Processing Platform ===")

    # Initialize assistant components
    logger.info("Initializing Assistant module...")
    assistant.mcp_server = SQLiteMCPServer(DB_PATH)
    assistant.mcp_server.mount_http_transport(app)
    assistant.orchestrator = LLMOrchestrator(assistant.mcp_server)
    assistant.session_manager = SessionManager()

    # Validate database
    if not DB_PATH.exists():
        logger.warning(f"Database not found at {DB_PATH}")
    else:
        logger.info(f"Database connected: {DB_PATH}")

    # Load schema
    schema = assistant.mcp_server.get_schema()
    logger.info(f"Schema loaded: {len(schema.get('tables', {}))} tables")

    logger.info("=== All services ready ===")

    yield

    # Shutdown
    logger.info("=== Shutting down ===")


# Create FastAPI application
app = FastAPI(
    title="Invoice Processing Platform",
    description="Unified API for invoice OCR, data extraction, and conversational Q&A",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include routers
app.include_router(monitoring.router)
app.include_router(pipeline.router)
app.include_router(assistant.router)


@app.get("/")
async def root():
    """Serve the main UI."""
    if INDEX_FILE.exists():
        return FileResponse(INDEX_FILE)
    return {
        "message": "Invoice Processing Platform API",
        "docs": "/docs",
        "modules": {
            "pipeline": "/api/pipeline",
            "assistant": "/api/assistant",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
