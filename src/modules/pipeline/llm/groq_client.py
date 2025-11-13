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

from src.modules.pipeline.config.settings import (
    PIPELINE_LLM_ALLOW_STUB,
    PIPELINE_LLM_API_BASE,
    PIPELINE_LLM_API_KEY,
    PIPELINE_LLM_MODEL,
)  # noqa: E402
from src.modules.pipeline.llm.rate_limiter import get_rate_limiter  # noqa: E402


def call_llm(
    messages: List[Dict],
    temperature: float = 0.0,
    max_tokens: int = 4096,
    usage_tag: str = "pipeline",
) -> str:
    """Call the Groq chat completion endpoint used by the pipeline."""
    if not PIPELINE_LLM_API_KEY:
        if PIPELINE_LLM_ALLOW_STUB:
            logger.warning(
                "PIPELINE_LLM_API_KEY missing; returning stub response"
            )
            return _generate_stub_response(messages)
        raise ValueError("PIPELINE_LLM_API_KEY not set in environment")

    rate_limiter = get_rate_limiter()
    prompt_text = json.dumps(messages, ensure_ascii=False)
    estimated_tokens = max_tokens + max(1, len(prompt_text) // 4)

    base_url = (PIPELINE_LLM_API_BASE or "https://api.groq.com/openai/v1").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PIPELINE_LLM_API_KEY}",
    }

    body = {
        "model": PIPELINE_LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    response: Optional[requests.Response] = None
    for attempt in range(4):
        entry_id = None
        try:
            if rate_limiter:
                rate_info = rate_limiter.check_and_wait(estimated_tokens, tag=usage_tag)
                entry_id = rate_info.get("entry_id")
                if rate_info.get("wait_time", 0) > 0:
                    logger.info(
                        "Rate limiter waited {wait:.1f}s before request",
                        wait=rate_info["wait_time"],
                    )

            logger.debug(
                "Calling Groq chat API (attempt {attempt})",
                attempt=attempt + 1,
            )
            response = requests.post(url, headers=headers, json=body, timeout=60)

            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                logger.debug(
                    "Groq response received: {chars} chars",
                    chars=len(content),
                )
                usage = data.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens", 0)
                if prompt_tokens is None:
                    prompt_tokens = max(0, estimated_tokens - max_tokens)
                if rate_limiter and entry_id is not None:
                    rate_limiter.record_actual_tokens(
                        entry_id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                return content

            if response.status_code == 429:
                retry_after = response.headers.get("retry-after", "60")
                remaining_requests = response.headers.get(
                    "x-ratelimit-remaining-requests", "unknown"
                )
                remaining_tokens = response.headers.get(
                    "x-ratelimit-remaining-tokens", "unknown"
                )
                logger.warning(
                    "Groq rate limit (429): remaining_requests={req}, remaining_tokens={tok}, retry_after={retry}s",
                    req=remaining_requests,
                    tok=remaining_tokens,
                    retry=retry_after,
                )

                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)

                if attempt >= 3:
                    break

                wait_time = min(int(retry_after), 60) if retry_after.isdigit() else 2**attempt
                logger.info("Waiting {wait}s before retry…", wait=wait_time)
                time.sleep(wait_time)
                continue

            if response.status_code in (500, 502, 503):
                wait_time = 2**attempt
                logger.warning(
                    "Groq API error {code}, retrying in {wait}s (attempt {idx}/4)",
                    code=response.status_code,
                    wait=wait_time,
                    idx=attempt + 1,
                )
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)
                time.sleep(wait_time)
                continue

            logger.error(
                "Groq API error: {code} - {body}",
                code=response.status_code,
                body=response.text,
            )
            response.raise_for_status()

        except requests.exceptions.Timeout:
            logger.warning(
                "Groq API timeout (attempt {idx}/4)",
                idx=attempt + 1,
            )
            if attempt < 3:
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)
                time.sleep(2**attempt)
                continue
            raise

        except Exception as exc:
            logger.error(
                "Groq API exception: {error}",
                error=exc,
            )
            if attempt < 3:
                if rate_limiter and entry_id is not None:
                    rate_limiter.cancel_request(entry_id)
                time.sleep(2**attempt)
                continue
            raise

        if rate_limiter and entry_id is not None:
            rate_limiter.cancel_request(entry_id)

    if response and response.status_code == 429:
        retry_after = response.headers.get("retry-after", "unknown")
        remaining_tokens = response.headers.get("x-ratelimit-remaining-tokens", "0")
        reset_tokens = response.headers.get("x-ratelimit-reset-tokens", "unknown")
        if remaining_tokens == "0":
            raise RuntimeError(
                f"⚠️ Groq daily token limit reached. Tokens reset in: {reset_tokens}."
            )
        raise RuntimeError(
            f"⚠️ Groq rate limit reached. Retry after: {retry_after}s."
        )

    raise RuntimeError("Groq API call failed after all retries")


def _generate_stub_response(messages: List[Dict]) -> str:
    # Offline fallback that infers a minimal invoice payload from the prompt text itself.
    user_payload = _extract_user_content(messages)
    vendor = _infer_vendor(user_payload)
    invoice_number = _extract_invoice_number(user_payload)
    invoice_date = _extract_date(user_payload)
    subtotal = _find_amount(
        user_payload, ["subtotal", "sub total", "net amount", "net subtotal"]
    )
    tax = _find_amount(user_payload, ["tax", "vat", "sales tax"])
    total = _find_amount(
        user_payload,
        [
            "amount due",
            "balance due",
            "total",
            "total due",
            "amount payable",
        ],
    )

    if total is None:
        total = subtotal

    if subtotal is None:
        subtotal = total

    if total is None:
        total = Decimal("0")

    if subtotal is None:
        subtotal = Decimal("0")

    discount = Decimal("0")

    if tax is None and subtotal is not None and total is not None:
        tax = max(total - subtotal + discount, Decimal("0"))

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
            "discount_cents": _to_cents(discount),
        },
        "items": [
            {
                "idx": 1,
                "description": "Total invoice amount",
                "qty": 1.0,
                "unit_price_cents": _to_cents(total),
                "line_total_cents": _to_cents(total),
                "category": "Other",
            }
        ],
        "notes": {
            "warnings": [
                "LLM stub enabled: configure PIPELINE_LLM_API_BASE and PIPELINE_LLM_API_KEY to enable the real extractor.",
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
        if len(line) > 2 and not any(
            keyword in line.lower() for keyword in ("invoice", ":")
        ):
            return line[:80]
    return "Demo Vendor"


def _extract_invoice_number(text: str) -> Optional[str]:
    patterns = [
        r"invoice\s*no\.?\s*([\w-]+)",
        r"invoice\s*#\s*([\w-]+)",
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
    # Normalise locale-dependent separators before converting to Decimal.
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
    # Keep monetary values as integer cents to align with the Pydantic schema.
    if value is None:
        return 0
    return int((value * 100).quantize(Decimal("1")))


def _iter_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# Backward compatibility aliases for older code paths
call_groq = call_llm
call_grok = call_llm
