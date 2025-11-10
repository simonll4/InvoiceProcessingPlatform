import json
import os
import re
import sys
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

import requests
from loguru import logger

# Ensure src package is importable when the module is executed directly
default_root = os.path.join(os.path.dirname(__file__), "..", "..")
if default_root not in sys.path:
    sys.path.insert(0, default_root)

from services.pipeline.config.settings import GROQ_ALLOW_STUB, GROQ_API_BASE, GROQ_API_KEY, GROQ_MODEL  # noqa: E402


def call_groq(messages: List[Dict], temperature: float = 0.0, max_tokens: int = 4096) -> str:
    """Call the Groq Chat Completions API with simple exponential backoff."""
    if not GROQ_API_KEY:
        if GROQ_ALLOW_STUB:
            logger.warning("GROQ_API_KEY missing, using stubbed Groq response")
            return _generate_stub_response(messages)
        raise ValueError("GROQ_API_KEY not set in environment")

    url = f"{GROQ_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(4):
        try:
            logger.debug(f"Calling Groq API (attempt {attempt + 1})...")
            response = requests.post(url, headers=headers, json=body, timeout=60)

            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                logger.debug(f"Groq response received: {len(content)} chars")
                return content

            if response.status_code in (429, 500, 502, 503):
                wait_time = 2 ** attempt
                logger.warning(
                    "Groq API error {code}, retrying in {wait}s (attempt {idx}/4)",
                    code=response.status_code,
                    wait=wait_time,
                    idx=attempt + 1,
                )
                time.sleep(wait_time)
                continue

            logger.error(
                "Groq API error: {code} - {body}",
                code=response.status_code,
                body=response.text,
            )
            response.raise_for_status()

        except requests.exceptions.Timeout:
            logger.warning("Groq API timeout (attempt {idx}/4)", idx=attempt + 1)
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise

        except Exception as exc:
            logger.error("Groq API exception: {error}", error=exc)
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise

    raise RuntimeError("Groq API call failed after all retries")
    raise RuntimeError("Groq API call failed after all retries")


def _generate_stub_response(messages: List[Dict]) -> str:
    user_payload = _extract_user_content(messages)
    vendor = _infer_vendor(user_payload)
    invoice_number = _extract_invoice_number(user_payload)
    invoice_date = _extract_date(user_payload)
    subtotal = _find_amount(user_payload, ["subtotal", "sub total", "importe neto", "net amount"])
    tax = _find_amount(user_payload, ["tax", "iva", "vat"])
    total = _find_amount(
        user_payload,
        ["amount due", "balance due", "total", "importe total", "total due", "total a pagar"],
    )

    if total is None:
        total = subtotal

    if subtotal is None:
        subtotal = total

    if total is None:
        total = Decimal("0")

    if subtotal is None:
        subtotal = Decimal("0")

    if tax is None and subtotal is not None and total is not None:
        tax = max(total - subtotal, Decimal("0"))

    payload = {
        "schema_version": "invoice_v1",
        "invoice": {
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "vendor_name": vendor,
            "vendor_tax_id": None,
            "buyer_name": None,
            "currency_code": "UNK",
            "subtotal_cents": _to_cents(subtotal),
            "tax_cents": _to_cents(tax),
            "total_cents": _to_cents(total),
            "due_date": None,
        },
        "items": [
            {
                "idx": 1,
                "description": "Total invoice amount",
                "qty": 1.0,
                "unit_price_cents": _to_cents(total),
                "line_total_cents": _to_cents(total),
                "category": "Otros",
            }
        ],
        "notes": {
            "warnings": [
                "Groq stub activo: define GROQ_API_KEY para habilitar el extractor real.",
            ],
            "confidence": 0.0,
        },
    }

    return json.dumps(payload)


def _extract_user_content(messages: List[Dict]) -> str:
    for entry in reversed(messages):
        if entry.get("role") == "user":
            return entry.get("content", "")
    return ""


def _infer_vendor(text: str) -> str:
    for line in _iter_lines(text):
        if len(line) > 2 and not any(keyword in line.lower() for keyword in ("invoice", "factura", ":")):
            return line[:80]
    return "Demo Vendor"


def _extract_invoice_number(text: str) -> Optional[str]:
    patterns = [
        r"invoice\s*no\.?\s*([\w-]+)",
        r"invoice\s*#\s*([\w-]+)",
        r"factura\s*n[oº]\.?\s*([\w-]+)",
        r"n[oº]\.?\s*de\s*factura\s*([\w-]+)",
    ]
    lower = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _extract_date(text: str) -> str:
    iso = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if iso:
        return iso.group(1)

    euro = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", text)
    if euro:
        day, month, year = euro.groups()
        return f"{year}-{month}-{day}"

    us = re.search(r"(\d{4})/(\d{2})/(\d{2})", text)
    if us:
        year, month, day = us.groups()
        return f"{year}-{month}-{day}"

    return date.today().isoformat()


def _find_amount(text: str, keywords: List[str]) -> Optional[Decimal]:
    for line in _iter_lines(text):
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            amount = _extract_number(line)
            if amount is not None:
                return amount
    return None


def _extract_number(text: str) -> Optional[Decimal]:
    match = re.search(r"[-+]?\d[\d., ]*", text)
    if not match:
        return None

    raw = match.group(0)
    normalized = re.sub(r"[^0-9.,]", "", raw)

    if normalized.count(".") > 1 and normalized.count(",") == 0:
        normalized = normalized.replace(".", "")
    if normalized.count(",") > 1 and normalized.count(".") == 0:
        normalized = normalized.replace(",", "")
    if "." in normalized and "," in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized and "." not in normalized:
        normalized = normalized.replace(",", ".")

    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def _to_cents(value: Optional[Decimal]) -> int:
    if value is None:
        return 0
    return int((value * 100).quantize(Decimal("1")))


def _iter_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# Backward compatibility alias for older code paths
call_grok = call_groq
