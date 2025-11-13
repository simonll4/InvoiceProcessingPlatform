"""Pipeline endpoints for OCR and invoice extraction."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from src.modules.pipeline.config.settings import UPLOAD_DIR
from src.modules.pipeline.service.pipeline import run_pipeline

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# Concurrency control
_semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "1")))


@router.post("/extract")
async def extract_document(file: UploadFile = File(...)) -> JSONResponse:
    """
    Process a PDF or image invoice and return structured data.

    Accepts: PDF, JPG, PNG, BMP
    Returns: Parsed invoice data (vendor, total, items, etc.)
    """
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
                f"Unsupported file type: {file.content_type}. "
                "Allowed: PDF, JPG, PNG, BMP"
            ),
        )

    # Save uploaded file
    file_id = str(uuid4())
    original_ext = Path(file.filename or "unknown").suffix.lower() or ".pdf"
    stored_path = UPLOAD_DIR / f"{file_id}{original_ext}"
    cleanup_file = True

    try:
        content = await file.read()
        stored_path.write_bytes(content)

        # Run pipeline with concurrency control
        async with _semaphore:
            result = await asyncio.to_thread(run_pipeline, str(stored_path))

        cleanup_file = False  # keep successfully processed uploads on disk

        return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Pipeline execution failed: {str(e)}"
        )
    finally:
        if cleanup_file and stored_path.exists():
            stored_path.unlink()
