# Invoice Extraction Pipeline

This package implements the end-to-end workflow that ingests an uploaded document, extracts text, enriches it with language-model inference, and stores the normalized invoice payload. The modules below mirror each stage of that flow.

## High-level flow (`service/pipeline.py`)
- `run_pipeline(path: str)` orchestrates the full process: hashing the input file, checking the cache/database, routing extraction based on document type, prompting the LLM, normalizing the response, and persisting the result.
- Helper functions `_extract_pages`, `_ensure_pages`, `_parse_and_normalize`, `_resolve_currency`, and validation routines handle OCR fallback, defensive checks, currency resolution, and schema compliance before storage.

## Configuration (`config/settings.py`)
- Loads environment variables (with `.env` support) and resolves filesystem paths for uploads, processed files, cache, and database storage.
- Exposes Groq API configuration, OCR tuning knobs (`PDF_OCR_DPI`, `PDF_OCR_MAX_PAGES`), minimum text length thresholds, and default currency fallbacks.

## Ingestion (`ingest/loader.py`)
- `detect_source` inspects the file extension and MIME type to decide whether the document should be processed as a PDF or a single-page image.

## Extraction (`extract/text_extractor.py`)
- Provides a unified interface for PDF (pdfminer with OCR fallback) and image (Pillow + Tesseract) text extraction.
- `PageText` captures page-level content; `_binarize` pre-processes images for OCR; `join_pages` prepares concatenated text sent to the LLM.

## Categorization (`category/`)
- Light-weight keyword heuristics used during normalization when the LLM does not supply an item category.
- `rules.py` lists keyword vocabularies and vendor hints; `classifier.py` applies them.
- Category labels are returned in English (`Food`, `Technology`, `Transportation`, etc.) while the keyword lists include both English and Spanish triggers to match multilingual invoices.

## LLM integration (`llm/`)
- `prompts.py` builds the Groq system/user prompt pair (in English) that embeds the invoice schema and extraction instructions.
- `groq_client.py` calls the Groq API with retry/backoff logic and provides a stubbed fallback when the API key is absent.
- `validator.py` parses the JSON response and validates it against the Pydantic schema, surfacing contract violations.

## Schema (`schema/invoice_v1.py`)
- Defines the `InvoiceV1` Pydantic model (invoice header, items, notes) and exposes `validate_invoice_payload` for reuse in the validator and normalization steps.

## Persistence (`storage/db.py`)
- Configures the SQLite schema via SQLAlchemy, offers `get_document_by_hash` for cache hits, and `save_document` to persist the raw text, JSON payload, header fields, and line items.

## Utilities (`utils/files.py`)
- Utility helpers such as `compute_file_hash` used to deduplicate repeated uploads.

## Optional datasets (`datasets/donut_loader.py`)
- Convenience routine for downloading sample training data from the `katanaml-org/invoices-donut-data-v1` dataset, saving paired images/metadata. This module is not required for runtime extraction but is useful for experimentation and tests.
