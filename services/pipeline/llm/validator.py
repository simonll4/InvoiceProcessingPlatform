"""Utilities to validate Groq responses against invoice_v1 schema."""

from __future__ import annotations

import json
from typing import Any, Dict

from loguru import logger

from services.pipeline.schema.invoice_v1 import InvoiceV1, validate_invoice_payload


class InvalidGroqResponse(Exception):
    pass


def parse_response(raw: str) -> InvoiceV1:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        payload: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidGroqResponse("Groq devolvió JSON inválido") from exc

    try:
        validated = validate_invoice_payload(payload)
        logger.debug("Groq response validated successfully")
        return validated
    except Exception as exc:  # noqa: BLE001
        raise InvalidGroqResponse("Groq respondió datos fuera de contrato") from exc
