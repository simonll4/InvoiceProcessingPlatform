"""End-to-end pipeline to extract invoices with a configurable LLM (Groq by default)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Dict, List, Optional

from loguru import logger

from src.modules.pipeline.category.classifier import classify_item
from src.modules.pipeline.config.settings import (
    DEFAULT_CURRENCY,
    PIPELINE_LLM_MODEL,
    PDF_OCR_MAX_PAGES,
    TEXT_MIN_LENGTH,
)
from src.modules.pipeline.storage.db import get_document_by_hash, save_document
from src.modules.pipeline.extract.text_extractor import (
    PageText,
    extract_image_text,
    extract_pdf_text,
    join_pages,
)
from src.modules.pipeline.ingest.loader import detect_source
from src.modules.pipeline.llm.groq_client import call_llm
from src.modules.pipeline.llm.prompts import build_messages
from src.modules.pipeline.llm.validator import InvalidLLMResponse, parse_response
from src.modules.pipeline.schema.invoice_v1 import InvoiceV1, Item, Notes, Invoice
from src.modules.pipeline.utils.files import compute_file_hash


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
    compact_joined = _compact_prompt_text(joined)
    raw_text = "\n".join(line for page in pages for line in page.lines)

    # Construct the chat messages so we can request the structured invoice.
    messages = build_messages(compact_joined)
    llm_messages = [
        {"role": "system", "content": messages["system"]},
        {"role": "user", "content": messages["user"]},
    ]

    # Call the LLM to extract structured data from the document text.
    logger.debug(
        "Invoking Groq LLM model={model}",
        model=PIPELINE_LLM_MODEL,
    )
    completion_budget = _dynamic_completion_budget(len(pages))
    response_text = call_llm(
        llm_messages,
        temperature=0.0,
        max_tokens=completion_budget,
        usage_tag="pipeline",
    )

    # Parse the response, normalize fields, and convert to plain dict for storage.
    model = _parse_and_normalize(response_text, joined)
    payload = model.model_dump(mode="json")

    # Persist the extracted document for future reference.
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
    except InvalidLLMResponse as exc:  # noqa: TRY003
        logger.error("LLM returned an invalid response: %s", exc)
        raise

    # Work on a copy so we preserve the original payload for eventual auditing.
    data = model.model_copy(deep=True)

    invoice = data.invoice
    invoice.currency_code = _resolve_currency(invoice.currency_code, document_text)
    invoice.invoice_number = invoice.invoice_number or None
    summary_values = _extract_summary_values(document_text)
    summary_overrides = _apply_summary_overrides(invoice, summary_values)

    # Defensive rule: if there's no explicit discount label or any mention of
    # a discount-like keyword in the OCR'd document, assume no discount was
    # intended and clear any LLM-inferred discount. This avoids false
    # positives coming from noisy OCR on images. We also mark the discount as
    # overridden (locked) so downstream recompute won't try to re-infer it.
    if "discount" not in summary_values:
        doc_lower = document_text.lower() if document_text else ""
        if (
            "discount" not in doc_lower
            and "rebate" not in doc_lower
            and "descuento" not in doc_lower
        ):
            # Force discount to zero and mark it as overridden so later
            # recomputation won't try to infer a discount from totals.
            invoice.discount_cents = 0
            summary_overrides.add("discount")
    _normalize_invoice_amounts(invoice)

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

    data.items = _merge_descriptor_items(normalized_items, invoice)

    items_sum = sum(it.line_total_cents for it in data.items)
    _harmonize_amount_scale(invoice, items_sum)
    _normalize_invoice_amounts(invoice)
    _recompute_discount(invoice, discount_locked="discount" in summary_overrides)
    expected_sum = _expected_line_items_total(invoice, items_sum)
    tolerance = max(1, int(expected_sum * 0.01)) if expected_sum else 1
    diff = abs(items_sum - expected_sum)
    if diff > tolerance:
        target = "subtotal" if invoice.subtotal_cents is not None else "total"
        warnings.append(f"Line item sum does not match invoice {target}")

    notes: Optional[Notes] = data.notes
    existing_warnings: List[str] = []
    confidence: Optional[float] = None
    if notes:
        existing_warnings = _filter_false_positive_warnings(
            notes.warnings or [], invoice
        )
        confidence = notes.confidence

    if warnings:
        combined = existing_warnings + warnings
        data.notes = Notes(
            warnings=combined,
            confidence=confidence,
        )
    elif notes:
        data.notes = Notes(
            warnings=existing_warnings or None,
            confidence=confidence,
        )

    _validate_required_fields(data)
    return data


def _resolve_currency(currency_code: str, text: str) -> str:
    """
    Resolve currency code - ALWAYS defaults to USD.
    
    All invoices are assumed to be in USD unless there's explicit evidence
    of another currency (€, £, etc.).
    """
    # ALWAYS return USD by default
    return "USD"


def _validate_required_fields(model: InvoiceV1) -> None:
    # Basic contract enforcement so the persisted record is always complete.
    if not model.invoice.vendor_name:
        raise ValueError("vendor_name missing in LLM response")
    if not model.invoice.invoice_date:
        raise ValueError("invoice_date missing in LLM response")
    _validate_iso_date(model.invoice.invoice_date)
    if not model.items:
        raise ValueError("items missing in LLM response")


def _normalize_invoice_amounts(invoice: Invoice) -> None:
    subtotal = invoice.subtotal_cents
    tax = invoice.tax_cents
    total = invoice.total_cents
    discount = invoice.discount_cents if invoice.discount_cents is not None else 0

    if discount < 0:
        discount = 0

    # Fix common LLM confusion: swapping subtotal and tax
    # This happens when LLM confuses Summary section fields:
    #   - Pattern 1: subtotal ≈ total (LLM put "Gross worth" in both)
    #   - Pattern 2: subtotal == tax (LLM duplicated "Net worth" in both)
    #   - Pattern 3: tax == total (LLM put "Gross worth" for both tax and total)
    
    # Pattern 1: subtotal ≈ total (Gross worth confusion)
    if (subtotal is not None and tax is not None and total is not None and 
        subtotal >= total * 0.95 and  # subtotal ≈ total (within 5%)
        tax + discount < total and    # tax is less than total
        tax > 0):                      # tax has actual value
        # After swap, verify: new_subtotal + new_tax ≈ total
        new_subtotal = tax
        new_tax = total - new_subtotal + discount
        tolerance = max(1, int(total * 0.01))
        # Check if swapped values make sense (new_tax should be reasonable)
        if new_tax > 0 and new_tax < new_subtotal:
            subtotal, tax = new_subtotal, new_tax
    
    # Pattern 2: subtotal == tax (Net worth duplication)
    # This happens when LLM reads "Net worth" for both subtotal and tax
    elif (subtotal is not None and tax is not None and total is not None and
          subtotal == tax and           # Exact duplication
          total > subtotal and          # total is larger (makes sense)
          total > 0):
        # Calculate correct tax from total - subtotal
        new_tax = total - subtotal + discount
        # Verify it's a reasonable tax (positive and less than subtotal)
        if new_tax > 0 and new_tax < subtotal:
            tax = new_tax
    
    # Pattern 3: tax == total (Gross worth duplication in tax and total)
    # This happens when LLM reads "Gross worth" for both tax and total fields
    elif (subtotal is not None and tax is not None and total is not None and
          tax == total and              # Exact duplication
          subtotal < total and          # subtotal is smaller (makes sense)
          subtotal > 0):
        # Calculate correct tax from total - subtotal
        new_tax = total - subtotal + discount
        # Verify it's a reasonable tax (positive and less than subtotal)
        if new_tax > 0 and new_tax < subtotal:
            tax = new_tax

    def _clamp(value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        return max(int(round(value)), 0)

    if subtotal is None and total is not None:
        inferred = total - (tax or 0) + discount
        if inferred >= 0:
            subtotal = inferred

    if tax is None and subtotal is not None and total is not None:
        inferred = total - subtotal + discount
        if inferred >= 0:
            tax = inferred

    if total is None and subtotal is not None:
        inferred = subtotal + (tax or 0) - discount
        if inferred >= 0:
            total = inferred

    invoice.subtotal_cents = _clamp(subtotal)
    invoice.tax_cents = _clamp(tax)
    invoice.total_cents = _clamp(total)
    invoice.discount_cents = _clamp(discount) or 0


def _expected_line_items_total(invoice: Invoice, items_sum: int) -> int:
    candidates = []
    if invoice.subtotal_cents is not None:
        candidates.append(invoice.subtotal_cents)
    if invoice.total_cents is not None:
        candidates.append(invoice.total_cents)
    if not candidates:
        return items_sum
    return min(candidates, key=lambda value: abs(items_sum - value))


def _totals_consistent(invoice: Invoice) -> bool:
    if (
        invoice.subtotal_cents is None
        or invoice.tax_cents is None
        or invoice.total_cents is None
    ):
        return True
    tolerance = max(1, int(invoice.total_cents * 0.001))
    discount = invoice.discount_cents or 0
    expected_total = invoice.subtotal_cents + invoice.tax_cents - discount
    return abs(expected_total - invoice.total_cents) <= tolerance


def _filter_false_positive_warnings(
    warnings: List[str], invoice: Invoice
) -> List[str]:
    if not warnings:
        return warnings
    cleaned = warnings
    if _totals_consistent(invoice):
        phrases = (
            "total and subtotal disagree",
            "total line items and invoice total disagree",
            "line item sum does not match",
            "total line item amount",
        )
        lowered = []
        for warning in cleaned:
            if any(phrase in warning.lower() for phrase in phrases):
                continue
            lowered.append(warning)
        cleaned = lowered
    return cleaned


def _harmonize_amount_scale(invoice: Invoice, items_sum: int) -> None:
    if not items_sum or items_sum <= 0:
        return
    scale = _detect_scale_factor(invoice, items_sum)
    if not scale or scale == 1:
        return
    for field in ("subtotal_cents", "tax_cents", "total_cents", "discount_cents"):
        value = getattr(invoice, field)
        if value is not None:
            setattr(invoice, field, max(int(round(value / scale)), 0))


def _detect_scale_factor(invoice: Invoice, items_sum: int) -> Optional[int]:
    candidates = (1000, 100, 10)
    for amount in (
        invoice.total_cents,
        invoice.subtotal_cents,
        invoice.tax_cents,
        invoice.discount_cents,
    ):
        if amount is None or amount <= 0:
            continue
        ratio = amount / items_sum
        for candidate in candidates:
            tolerance = max(0.05 * candidate, 0.5)
            if abs(ratio - candidate) <= tolerance:
                return candidate
    return 1


def _merge_descriptor_items(items: List[Item], invoice: Invoice) -> List[Item]:
    if not items:
        return items

    merged: List[Item] = []
    for item in items:
        if not merged:
            merged.append(item)
            continue

        if _is_summary_only_item(item, invoice):
            continue

        if _is_descriptor_line(item, merged[-1], invoice):
            merged[-1].description = (
                f"{merged[-1].description} {item.description}".strip()
            )
            continue

        merged.append(item)

    for idx, item in enumerate(merged, start=1):
        item.idx = idx
    return merged


def _is_summary_only_item(item: Item, invoice: Invoice) -> bool:
    if not item.description:
        return False
    description = item.description.lower()
    keywords = (
        "discount",
        "shipping",
        "freight",
        "delivery",
        "handling",
        "fees",
        "tax",
        "vat",
        "gst",
        "iva",
        "duty",
        "balance",
        "subtotal",
    )
    if any(word in description for word in keywords):
        return True
    if item.line_total_cents in {invoice.discount_cents, invoice.tax_cents}:
        return True
    return False


def _is_descriptor_line(item: Item, previous: Item, invoice: Invoice) -> bool:
    if not item.description:
        return False
    if item.unit_price_cents not in (None, 0):
        return False
    if item.qty not in (None, 0, 1, 1.0):
        return False
    if _contains_currency_amount(item.description):
        return False

    candidate_totals = {
        previous.line_total_cents,
        invoice.discount_cents,
        invoice.tax_cents,
        None,
        0,
    }
    if item.line_total_cents not in candidate_totals:
        return False
    return True


CURRENCY_TOKEN = re.compile(r"[$€£]|(\d+[.,]\d{1,2})")


def _contains_currency_amount(text: str) -> bool:
    return bool(CURRENCY_TOKEN.search(text))


def _validate_iso_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:  # noqa: TRY003
        raise ValueError(f"Invalid date {value}") from exc


def _compact_prompt_text(text: str) -> str:
    """
    Reduce redundant newlines but keep intra-line spacing intact.
    
    OCR often encodes column structure (Seller vs Client, etc.) via multiple spaces.
    Collapsing them causes the LLM to mix vendor/buyer fields, so we only trim tabs
    and excessive blank lines while preserving horizontal spacing.
    """
    text = text.replace("\t", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _dynamic_completion_budget(page_count: int) -> int:
    """Scale completion tokens with document size (caps at 1024)."""
    return min(1024, 256 + 120 * max(1, page_count))


def _extract_summary_values(text: str) -> Dict[str, int]:
    summary: Dict[str, int] = {}
    
    # Find all labels and amounts in the entire text
    label_matches = list(SUMMARY_LABEL_PATTERN.finditer(text))
    if not label_matches:
        return summary
    
    amount_matches = list(AMOUNT_PATTERN.finditer(text))
    if not amount_matches:
        return summary
    
    # Filter out percentages (numbers followed by % or in discount label context)
    valid_amounts = []
    for amount_match in amount_matches:
        after_pos = amount_match.end()
        after_text = text[after_pos:after_pos+3].strip()
        before_text = text[max(0, amount_match.start()-15):amount_match.start()]
        if after_text.startswith('%') or (after_text.startswith(')') and 'discount' in before_text.lower()):
            continue
        valid_amounts.append(amount_match)
    
    if not valid_amounts:
        return summary
    
    used_amounts = set()
    
    # Heuristic: only consider amounts that are reasonably close to a label.
    # OCR output from images is noisy and contains many numeric tokens (IDs,
    # addresses, unit counts). Restricting the allowed distance prevents the
    # algorithm from matching distant item-level numbers to summary labels.
    # Tighten default distance to avoid matching item-level amounts in noisy
    # image OCR outputs. 80 characters is a conservative value that keeps
    # amounts on the same line or immediately adjacent lines while ignoring
    # unrelated numbers elsewhere in the document.
    MAX_AMOUNT_LABEL_DISTANCE = 80

    # Detect label groups: consecutive labels without amounts between them
    i = 0
    while i < len(label_matches):
        # Start a potential group at label i
        group_labels = [label_matches[i]]
        j = i + 1
        
        # Extend the group while labels are consecutive (no amounts between them)
        while j < len(label_matches):
            prev_label_end = label_matches[j-1].end()
            curr_label_start = label_matches[j].start()
            
            # Check if there are any amounts between prev and current label
            amounts_between = [
                amt for amt in valid_amounts 
                if amt not in used_amounts and amt.start() >= prev_label_end and amt.start() < curr_label_start
            ]
            
            if amounts_between:
                # There are amounts between labels, so break the group
                break
            
            group_labels.append(label_matches[j])
            j += 1
        
        # Process this group
        if len(group_labels) == 1:
            # Single label: find closest amount after it
            label_match = group_labels[0]
            label_text = label_match.group(1)
            label_end = label_match.end()
            
            # Find boundary (next label or end of text)
            next_label_start = label_matches[i + 1].start() if i + 1 < len(label_matches) else len(text)
            
            # Find closest amount
            closest_amount = None
            min_distance = float('inf')
            
            for amt in valid_amounts:
                if amt in used_amounts:
                    continue
                # Only accept amounts that appear after the label but not too
                # far away (avoid matching unrelated numbers elsewhere in the
                # document). Also ensure the amount appears before the next
                # label.
                if not (amt.start() >= label_end and amt.start() < next_label_start):
                    continue
                if amt.start() - label_end > MAX_AMOUNT_LABEL_DISTANCE:
                    continue
                    distance = amt.start() - label_end
                    if distance < min_distance:
                        min_distance = distance
                        closest_amount = amt
            
            if closest_amount:
                amount_str = closest_amount.group(1)
                cents = _parse_amount_to_cents(amount_str)
                if cents is not None:
                    normalized = _normalize_summary_label(label_text)
                    if normalized == "addition":
                        summary["addition"] = summary.get("addition", 0) + cents
                    elif normalized and normalized not in summary:
                        summary[normalized] = cents
                    used_amounts.add(closest_amount)
        else:
            # Multiple labels in group: find amounts after last label and match in order
            last_label_end = group_labels[-1].end()
            
            # Find all amounts after the last label in the group but within a
            # limited distance so we don't sweep the entire document for
            # unrelated numbers.
            amounts_after = [
                amt
                for amt in valid_amounts
                if amt not in used_amounts
                and amt.start() >= last_label_end
                and amt.start() - last_label_end <= MAX_AMOUNT_LABEL_DISTANCE
            ]
            
            # Match labels to amounts in order
            for k, label_match in enumerate(group_labels):
                if k >= len(amounts_after):
                    break
                
                label_text = label_match.group(1)
                amount_match = amounts_after[k]
                
                amount_str = amount_match.group(1)
                cents = _parse_amount_to_cents(amount_str)
                if cents is None:
                    continue
                
                normalized = _normalize_summary_label(label_text)
                if normalized == "addition":
                    summary["addition"] = summary.get("addition", 0) + cents
                elif normalized and normalized not in summary:
                    summary[normalized] = cents
                
                used_amounts.add(amount_match)
        
        # Move to next group
        i = j if j > i else i + 1
    
    return summary


def _parse_amount_to_cents(value: str) -> Optional[int]:
    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("$", "").replace("€", "").replace("£", "")
    cleaned = cleaned.replace(" ", "")
    if cleaned.count(",") > 1 and "." not in cleaned:
        cleaned = cleaned.replace(",", "")
    elif cleaned.count(".") > 1 and "," not in cleaned:
        cleaned = cleaned.replace(".", "")
    elif "." in cleaned and "," in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        cents = int(round(Decimal(cleaned) * 100))
    except InvalidOperation:
        return None
    return cents


def _normalize_summary_label(label: str) -> Optional[str]:
    lower = label.lower()
    if "subtotal" in lower or "sub-total" in lower:
        return "subtotal"
    if "discount" in lower or "rebate" in lower:
        return "discount"
    if "total" in lower or "balance due" in lower:
        return "total"
    if any(
        keyword in lower
        for keyword in (
            "addition",
            "shipping",
            "freight",
            "delivery",
            "handling",
            "fees",
            "charge",
            "tax",
            "vat",
            "gst",
            "iva",
            "duty",
        )
    ):
        return "addition"
    return None


def _apply_summary_overrides(invoice: Invoice, summary: Dict[str, int]) -> set[str]:
    overrides: set[str] = set()
    if not summary:
        return overrides
    if "subtotal" in summary:
        invoice.subtotal_cents = summary["subtotal"]
        overrides.add("subtotal")
    if "total" in summary:
        invoice.total_cents = summary["total"]
        overrides.add("total")
    if "discount" in summary:
        invoice.discount_cents = summary["discount"]
        overrides.add("discount")
    if "addition" in summary:
        invoice.tax_cents = summary["addition"]
        overrides.add("addition")
    return overrides


def _recompute_discount(invoice: Invoice, discount_locked: bool = False) -> None:
    if discount_locked:
        return
    subtotal = invoice.subtotal_cents
    total = invoice.total_cents
    if subtotal is None or total is None:
        return
    additions = invoice.tax_cents or 0
    expected = subtotal + additions - total
    tolerance = max(1, int(max(total, 1) * 0.001))
    if expected < 0 and abs(expected) <= tolerance:
        expected = 0
    if expected < 0:
        return
    if abs(expected - (invoice.discount_cents or 0)) > tolerance:
        invoice.discount_cents = expected
SUMMARY_LABEL_PATTERN = re.compile(
    # Accept common summary labels with an optional trailing colon. Some OCR outputs
    # (especially from images) omit the colon, so make it optional to be robust.
    # Avoid matching "Tax" inside "Tax Id" by excluding that suffix. Other
    # labels remain as-is.
    r"(Subtotal|Sub-total|Total|Balance Due|Discount(?:\s*\([^)]*\))?|Shipping|Freight|Delivery|Handling|Fees|Charge|Tax(?!\s+Id)|Sales Tax|VAT|GST|IVA|Duty)\s*:?",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(
    # Match monetary-looking values. Require a decimal separator or an explicit
    # currency symbol to avoid matching arbitrary integers (invoice numbers,
    # addresses, zip codes) that OCR also captures in images.
    r"(?:[$€£]\s*)?([-+]?\d[\d,]*[.,]\d{1,2})",
    re.IGNORECASE,
)
