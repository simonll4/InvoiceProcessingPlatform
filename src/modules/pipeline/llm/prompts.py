"""Prompt templates for invoice extraction via LLM."""

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
        "discount_cents": 0,
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
        "Ensure sum(items.line_total_cents) matches invoice.subtotal_cents when available "
        "(or invoice.total_cents if subtotal is missing). Only warn when the relevant target differs "
        "by more than ~1%, and never warn solely because total_cents includes tax on top of subtotal. "
        "Capture discounts explicitly in invoice.discount_cents (0 when no discount) so that "
        "total_cents = subtotal_cents + tax_cents - discount_cents. "
        "Absolutely never emit arithmetic expressions (e.g., '322639 * 0.15'); every numeric field MUST be a literal integer."
    )


def build_user_prompt(page_text: str) -> str:
    schema_text = json.dumps(SCHEMA_SNIPPET, ensure_ascii=False, separators=(",", ":"))
    return (
        "Extract the structured invoice from the following document text.\n"
        "Do not output anything except the JSON payload.\n\n"
        "### Document text\n"
        f"{page_text}\n\n"
        "### Valid categories\n"
        f"{CATEGORIES}.\n\n"
        "### Schema (compact JSON)\n"
        f"{schema_text}\n\n"
        "### Guidelines\n"
        "- Return one JSON object matching 'invoice_v1'.\n"
        "- Amounts in cents (integers).\n"
        "- **CRITICAL - Number format handling**: Some invoices use European format where COMMA is decimal separator (e.g., '49,99' means $49.99, NOT $4999). "
        "When you see prices like '49,99' or '177,08', treat the comma as a decimal point. Convert '49,99' → 4999 cents, '177,08' → 17708 cents.\n"
        "- **CRITICAL - Use correct totals**: For line items, ALWAYS use 'Gross worth' (total INCLUDING tax/VAT), NOT 'Net worth'. "
        "If you see both 'Net worth' and 'Gross worth' columns, use 'Gross worth' for line_total_cents.\n"
        "- **CRITICAL - Summary section mapping (VERY IMPORTANT)**:\n"
        "  * 'Net worth' in summary = invoice.subtotal_cents (amount BEFORE tax)\n"
        "  * 'VAT' in summary = invoice.tax_cents (tax amount)\n"
        "  * 'Gross worth' in summary = invoice.total_cents (amount AFTER tax, includes tax)\n"
        "  * Formula: Gross worth = Net worth + VAT → total_cents = subtotal_cents + tax_cents\n"
        "  * Example: If summary shows 'Net worth: $958.27, VAT: $95.83, Gross worth: $1,054.10' then:\n"
        "    subtotal_cents = 95827, tax_cents = 9583, total_cents = 105410\n"
        "- Missing qty → 1.0, missing unit_price → null, line_total_cents is required.\n"
        "- Detect currency from symbols/text, otherwise 'UNK'.\n"
        "- Dates in YYYY-MM-DD. Resolve ambiguous dates via month ≤ 12.\n"
        "- Use exactly one allowed category per item (fallback 'Other').\n"
        "- Only compare sum(items.line_total_cents) against invoice.subtotal_cents (or invoice.total_cents if subtotal is null). "
        "Do NOT warn when invoice.total_cents = subtotal_cents + tax_cents - discount_cents.\n"
        "- Always include invoice.discount_cents (0 if there is no discount).\n"
        "- ALL amounts in cents must be literal integers (no formulas, multiplications, or strings with symbols).\n"
        "- Some invoices list a descriptive line right below the item (category, SKU, etc.). "
        "If that line does NOT have quantity/price/amounts, concatenate it to the previous item instead of creating a new item."
    )


def build_messages(page_text: str) -> Dict[str, str]:
    # Return a dict compatible with the OpenAI-style chat API used by Groq and other providers.
    system = build_system_prompt()
    user = build_user_prompt(page_text)
    return {"system": system, "user": user}
