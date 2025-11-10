def system_prompt() -> str:
    """System prompt for strict JSON extraction"""
    return (
        "You are a strict information extractor for receipts and invoices.\n"
        "You MUST return ONLY valid JSON that matches the provided JSON Schema.\n"
        "If a field is absent, use null. Dates must be ISO-8601 (YYYY-MM-DD).\n"
        "Numbers must be numeric (not strings). Arrays must contain objects.\n"
        "Do not fabricate values. Be precise and accurate.\n"
        "Return pure JSON without markdown code blocks or explanations."
    )


def user_prompt(source: str, ocr_text: str, candidates: list, json_schema: dict, currency_hint: str) -> str:
    """User prompt with OCR text and schema"""
    # Limit text to avoid token limits
    text_limit = 8000
    if len(ocr_text) > text_limit:
        ocr_text = ocr_text[:text_limit] + "\n[...truncated...]"
    
    # Format candidates
    candidate_lines = "\n- ".join(candidates[:20]) if candidates else "(none)"
    
    return f"""SOURCE: {source}
CURRENCY_HINT: {currency_hint}

OCR/TEXT CONTENT:
<<<
{ocr_text}
>>>

CANDIDATE LINES (key information):

JSON SCHEMA (must match exactly):
<<<
{json_schema}
>>>

Return ONLY the JSON object (no markdown, no explanation, no code blocks)."""


def repair_prompt(validation_error: str) -> str:
    """Prompt to repair invalid JSON"""
    return (
        f"The previous JSON did not validate.\n"
        f"Validation error:\n{validation_error}\n\n"
        f"Return ONLY a corrected JSON object (no text around it)."
    )
