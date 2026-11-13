"""Form readers: map normalized extraction output to TaxFacts per form type.

Phase 2 shipped the W-2 reader. Readers classify/map by content (not filename) and
preserve provenance (page, bbox, confidence, extraction method) on every fact.
"""
from __future__ import annotations

import re

from tax.models import ExtractionMethod, FactStatus, TaxFact

# Confidence below which a fact is flagged for human review (matches w2.py).
REVIEW_THRESHOLD = 0.90

_MONEY_CLEAN = re.compile(r"[^\d.\-]")


def normalize_money(value: str) -> str:
    """Strip $, commas, OCR mask artifacts (*) -> a plain numeric string."""
    cleaned = _MONEY_CLEAN.sub("", value.replace("*", ""))
    if cleaned in ("", "-", ".", "-."):
        return value
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return value


def is_money_value(value: str) -> bool:
    """True when normalize_money can turn the value into a number (guards
    readers against OCR junk like a bare '$')."""
    try:
        float(normalize_money(value))
        return True
    except ValueError:
        return False


def native_text(kvs) -> str:
    """A document's raw text: prefer the local provider's synthetic native-text
    KV; otherwise join whatever the KVs carry (keeps readers provider-agnostic)."""
    for kv in kvs:
        if getattr(kv, "key", None) == "__native_text__":
            return kv.value
    return "\n".join(f"{kv.key} {kv.value}" for kv in kvs)


def make_fact(
    document_id: str,
    tax_year: int,
    form_type,
    field_code: str,
    field_label: str,
    value,
    *,
    method: ExtractionMethod = ExtractionMethod.manual,
    confidence: float = 1.0,
    page: int = 1,
    bbox=None,
    money: bool = False,
    mask=None,
) -> TaxFact:
    """Build one provenance-carrying TaxFact.

    `money=True` normalizes a string dollar value; `mask` (a pii.py masker) is
    applied when the field carries PII. Facts below REVIEW_THRESHOLD are flagged
    needs_review; the extracted value is kept as the audit baseline."""
    stored = value
    if money and isinstance(value, str):
        stored = normalize_money(value)
    if mask is not None:
        stored = mask(str(stored))
    status = FactStatus.extracted if confidence >= REVIEW_THRESHOLD else FactStatus.needs_review
    return TaxFact(
        tax_year=tax_year,
        document_id=document_id,
        form_type=form_type,
        field_code=field_code,
        field_label=field_label,
        value=stored,
        page=page,
        bbox=bbox,
        extraction_method=method,
        confidence=round(confidence, 4),
        status=status,
        extracted_value=stored,  # audit baseline (already masked/normalized)
    )
