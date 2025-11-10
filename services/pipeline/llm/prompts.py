"""Prompt templates for Groq extraction."""

from __future__ import annotations

import json
from typing import Dict

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
            "category": "Alimentos|Tecnologia|Oficina|Transporte|Servicios|Impuestos|Salud|Hogar|Otros",
        }
    ],
    "notes": {
        "warnings": ["string"],
        "confidence": 0.0,
    },
}

CATEGORIES = "Alimentos, Tecnologia, Oficina, Transporte, Servicios, Impuestos, Salud, Hogar, Otros"


def build_system_prompt() -> str:
    return (
        "Eres un extractor experto de facturas. Devuelves EXCLUSIVAMENTE un JSON válido que siga "
        "exactamente el esquema 'invoice_v1'. No agregues texto fuera del JSON. No inventes datos: "
        "si un campo no aparece claramente, usa null (o valores por defecto donde se indique). Convierte "
        "todos los importes a centavos (INTEGER). Detecta la moneda por símbolos o texto; si dudas, usa 'UNK'. "
        "Categoriza cada ítem usando una sola categoría de la lista dada; si no encaja, usa 'Otros'. Verifica que "
        "sum(items.line_total_cents) ≈ invoice.total_cents (tolerancia 1%). Si no, registra un warning sin alterar los montos."
    )


def build_user_prompt(page_text: str) -> str:
    schema_text = json.dumps(SCHEMA_SNIPPET, ensure_ascii=False, indent=2)
    return (
        "Texto de documento (por páginas si aplica):\n"
        f"{page_text}\n\n"
        f"Categorías válidas:\n{CATEGORIES}.\n\n"
        "Esquema requerido (invoice_v1):\n"
        f"{schema_text}\n\n"
        "Instrucciones:\n"
        "Retorna SOLO el JSON válido del esquema 'invoice_v1'.\n"
        "Normaliza montos a centavos (INTEGER).\n"
        "Si falta qty → usar 1.0; si falta unit_price → null; line_total_cents es obligatorio.\n"
        "Detecta moneda por símbolo/texto; si dudas → 'UNK'.\n"
        "Fecha en YYYY-MM-DD resolviendo DD/MM vs MM/DD por mes ≤ 12.\n"
        "Categoriza cada ítem según las categorías válidas; si no encaja, 'Otros'.\n"
        "Incluye warnings si hay ambigüedad o si la suma de ítems difiere del total."
    )


def build_messages(page_text: str) -> Dict[str, str]:
    system = build_system_prompt()
    user = build_user_prompt(page_text)
    return {"system": system, "user": user}
