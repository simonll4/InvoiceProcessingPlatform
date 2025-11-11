"""Prompt templates for Groq extraction."""

from __future__ import annotations

import json
from typing import Dict

# Inline schema example keeps the model grounded on the target contract without external files.
SCHEMA_SNIPPET = {
    "schema_version": "invoice_v1",
    "invoice": {
        "invoice_number": "string|null",
        "invoice_date": "YYYY-MM-DD",
        "vendor_name": "string",
        "vendor_tax_id": "string|null",
        "buyer_name": "string|null",
        "currency_code": "ISO4217|UNK",
        "subtotal_cents": 12345,
        "tax_cents": 2345,
        "total_cents": 14690,
        "due_date": "YYYY-MM-DD|null",
    },
    "items": [
        {
            "idx": 1,
            "description": "string",
            "qty": 1.0,
            "unit_price_cents": 1234,
            "line_total_cents": 1234,
            "category": "Food|Technology|Office|Transportation|Services|Taxes|Health|Home|Other",
        }
    ],
    "notes": {
        "warnings": ["string"],
        "confidence": 0.0,
    },
}

# Mirror the classifier categories so both LLM and rule-based fallbacks stay aligned.
CATEGORIES = (
    "Food, Technology, Office, Transportation, Services, Taxes, Health, Home, Other"
)


def build_system_prompt() -> str:
    return (
        "You are an expert invoice extractor. Return ONLY valid JSON that exactly matches the "
        "'invoice_v1' schema. Do not add any text outside the JSON. Do not hallucinate values: "
        "if a field is missing, use null (or documented defaults). Convert all monetary amounts "
        "to cents (INTEGER). Detect the currency from symbols or text; when unsure, use 'UNK'. "
        "Categorize each line item using exactly one category from the provided list; if nothing fits, use 'Other'. "
        "Ensure sum(items.line_total_cents) is within 1% of invoice.total_cents; if it is not, append a warning without adjusting amounts."
    )


def build_user_prompt(page_text: str) -> str:
    schema_text = json.dumps(SCHEMA_SNIPPET, ensure_ascii=False, indent=2)
    return (
        "Document text (separated by pages when applicable):\n"
        f"{page_text}\n\n"
        f"Valid categories:\n{CATEGORIES}.\n\n"
        "Required schema (invoice_v1):\n"
        f"{schema_text}\n\n"
        "Instructions:\n"
        "Return ONLY the JSON object that matches 'invoice_v1'.\n"
        "Normalize monetary values to cents (INTEGER).\n"
        "If qty is missing → use 1.0; if unit_price is missing → null; line_total_cents is mandatory.\n"
        "Detect the currency from symbols/text; if unsure → 'UNK'.\n"
        "Provide dates in YYYY-MM-DD, resolving DD/MM vs MM/DD by month ≤ 12.\n"
        "Assign each item to one of the valid categories; if nothing fits, use 'Other'.\n"
        "Include warnings when values are ambiguous or item totals disagree with the invoice total."
    )


def build_messages(page_text: str) -> Dict[str, str]:
    # Return a dict compatible with the OpenAI-style chat API used by Groq.
    system = build_system_prompt()
    user = build_user_prompt(page_text)
    return {"system": system, "user": user}
