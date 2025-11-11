"""End-to-end pipeline to extract invoices with Groq."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from loguru import logger

from services.pipeline.category.classifier import classify_item
from services.pipeline.config.settings import (
    DEFAULT_CURRENCY,
    PDF_OCR_MAX_PAGES,
    TEXT_MIN_LENGTH,
)
from services.pipeline.storage.db import get_document_by_hash, save_document
from services.pipeline.extract.text_extractor import (
    PageText,
    extract_image_text,
    extract_pdf_text,
    join_pages,
)
from services.pipeline.ingest.loader import detect_source
from services.pipeline.llm.groq_client import call_groq
from services.pipeline.llm.prompts import build_messages
from services.pipeline.llm.validator import InvalidGroqResponse, parse_response
from services.pipeline.schema.invoice_v1 import InvoiceV1, Item, Notes
from services.pipeline.utils.files import compute_file_hash


def run_pipeline(path: str) -> dict:
    logger.info("Processing document: %s", path)
    # Short-circuit if this file was already processed previously.
    file_hash = compute_file_hash(path)
    cached = get_document_by_hash(file_hash)
    if cached:
        logger.info("Cache hit by file hash")
        return cached

    # Decide which extraction strategy to use based on the input type.
    source = detect_source(path)
    logger.debug("Detected source type: %s", source)

    pages = _extract_pages(path, source)
    _ensure_pages(pages)

    # Build the textual payload passed to the LLM and persisted for audit.
    joined = join_pages(pages)
    raw_text = "\n".join(line for page in pages for line in page.lines)

    # Construct the Groq chat messages so we can request the structured invoice.
    messages = build_messages(joined)
    llm_messages = [
        {"role": "system", "content": messages["system"]},
        {"role": "user", "content": messages["user"]},
    ]

    logger.debug("Invoking Groq")
    response_text = call_groq(llm_messages, temperature=0.0, max_tokens=2048)

    # Parse the response, normalize fields, and convert to plain dict for storage.
    model = _parse_and_normalize(response_text, joined)
    payload = model.model_dump(mode="json")

    save_document(path, file_hash, raw_text, payload)
    return payload


def _extract_pages(path: str, source: str) -> List[PageText]:
    if source == "pdf":
        return extract_pdf_text(path, max_pages=PDF_OCR_MAX_PAGES)
    return extract_image_text(path)


def _ensure_pages(pages: List[PageText]) -> None:
    # Guard against empty OCR output so later steps can assume content.
    if not pages:
        raise ValueError("No text could be extracted from the document")
    total_chars = sum(len(line) for page in pages for line in page.lines)
    if total_chars == 0:
        raise ValueError("No text could be extracted from the document")
    if total_chars < TEXT_MIN_LENGTH:
        logger.warning(
            "Extracted text is very short (%s characters, recommended minimum %s)",
            total_chars,
            TEXT_MIN_LENGTH,
        )


def _parse_and_normalize(raw: str, document_text: str) -> InvoiceV1:
    try:
        model = parse_response(raw)
    except InvalidGroqResponse as exc:  # noqa: TRY003
        logger.error("Groq returned an invalid response: %s", exc)
        raise

    # Work on a copy so we preserve the original payload for eventual auditing.
    data = model.model_copy(deep=True)

    invoice = data.invoice
    invoice.currency_code = _resolve_currency(invoice.currency_code, document_text)
    invoice.invoice_number = invoice.invoice_number or None

    warnings: List[str] = []
    normalized_items: List[Item] = []

    # Fill missing defaults and categories per item to ensure downstream consistency.
    for position, item in enumerate(data.items, start=1):
        qty = item.qty if item.qty is not None else 1.0
        category = (
            item.category
            or classify_item(item.description, invoice.vendor_name)
            or "Other"
        )
        normalized_items.append(
            Item(
                idx=position,
                description=item.description,
                qty=qty,
                unit_price_cents=item.unit_price_cents,
                line_total_cents=item.line_total_cents,
                category=category,
            )
        )

    data.items = normalized_items

    diff = abs(sum(it.line_total_cents for it in data.items) - invoice.total_cents)
    tolerance = max(1, int(invoice.total_cents * 0.01))
    if diff > tolerance:
        # Surface mismatched totals as a warning without mutating the amounts.
        warnings.append("Line item sum does not match invoice total")

    notes: Optional[Notes] = data.notes
    if warnings:
        if notes:
            combined = (notes.warnings or []) + warnings
            data.notes = Notes(warnings=combined, confidence=notes.confidence)
        else:
            data.notes = Notes(warnings=warnings, confidence=None)

    _validate_required_fields(data)
    return data


def _resolve_currency(currency_code: str, text: str) -> str:
    # Prefer the LLM answer when it is definite; otherwise inspect raw text heuristics.
    if currency_code and currency_code.upper() != "UNK":
        return currency_code.upper()

    upper = text.upper()
    if "€" in text or " EUR" in upper:
        return "EUR"
    if "£" in text or " GBP" in upper:
        return "GBP"
    if "USD" in upper or "US$" in upper:
        return "USD"
    if "$" in text:
        if any(token in upper for token in ("VAT", "INVOICE", "TAX ID", "ARS", "AR$")):
            return "ARS"
        return "USD"
    if "MXN" in upper or "MEXICAN PESO" in upper:
        return "MXN"
    return DEFAULT_CURRENCY


def _validate_required_fields(model: InvoiceV1) -> None:
    # Basic contract enforcement so the persisted record is always complete.
    if not model.invoice.vendor_name:
        raise ValueError("vendor_name missing in Groq response")
    if not model.invoice.invoice_date:
        raise ValueError("invoice_date missing in Groq response")
    _validate_iso_date(model.invoice.invoice_date)
    if model.invoice.due_date:
        _validate_iso_date(model.invoice.due_date)
    if not model.items:
        raise ValueError("items missing in Groq response")


def _validate_iso_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:  # noqa: TRY003
        raise ValueError(f"Invalid date {value}") from exc
