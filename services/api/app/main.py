#!/usr/bin/env python3
"""FastAPI server exposing the OCR-LLM pipeline and static UI."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.pipeline.config.settings import UPLOAD_DIR
from services.pipeline.service.pipeline import run_pipeline

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
INDEX_FILE = STATIC_DIR / "index.html"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="OCR-LLM Pipeline",
    description="Extracción de datos de facturas y recibos",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ajusta en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class HealthResponse(BaseModel):
    status: str
    message: str


api_router = APIRouter(prefix="/api")

# Concurrency control for CPU-bound pipeline
_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "1")))


@app.get("/", response_class=FileResponse)
async def serve_index() -> FileResponse:
    """Serve the single-page application."""
    if not INDEX_FILE.exists():  # pragma: no cover - defensive
        raise HTTPException(status_code=404, detail="UI no disponible")
    return FileResponse(INDEX_FILE)


@api_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint for monitoring."""
    return HealthResponse(status="ok", message="Service is healthy")


@api_router.get("/warmup", response_model=HealthResponse)
async def warmup() -> HealthResponse:
    """No-op endpoint so the UI can wake the service."""
    return HealthResponse(status="ok", message="Ready")


@api_router.post("/extract")
async def extract_document(file: UploadFile = File(...)) -> JSONResponse:
    """Process a PDF or image invoice and return structured data."""
    allowed_types = {
        "application/pdf",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/bmp",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tipo de archivo no soportado: {file.content_type}. "
                "Formatos permitidos: PDF, JPG, PNG, BMP"
            ),
        )

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx 10MB)")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid4().hex}_{Path(file.filename).name}"
    stored_path = UPLOAD_DIR / safe_name
    stored_path.write_bytes(content)

    try:
        loop = asyncio.get_running_loop()
        async with _semaphore:
            result = await loop.run_in_executor(None, run_pipeline, str(stored_path))

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "filename": file.filename,
                "stored_path": str(stored_path),
                "data": result,
            },
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Error procesando documento: {exc}") from exc


app.include_router(api_router)


def run() -> None:
    """Entrypoint for `python -m services.api.app.main`."""
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("services.api.app.main:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    run()
