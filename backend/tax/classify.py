"""Content-based form classification.

Identifies a tax form from its extracted key/value text, NOT its filename — a
file named "Document123.pdf" is still recognized as a W-2 if its content says so.
Phase 2 only classifies W-2; other form types fall through to `unknown` and are
added in later phases.
"""
from __future__ import annotations

from tax.extraction.providers import ExtractedKV
from tax.models import FormType


def _corpus(kvs: list[ExtractedKV]) -> str:
    """All key + value text, lowercased, for keyword/structure checks."""
    parts: list[str] = []
    for kv in kvs:
        parts.append(kv.key)
        parts.append(kv.value)
    return " ".join(parts).lower()


def classify_form(kvs: list[ExtractedKV]) -> FormType:
    """Best-effort form type from extracted content. `unknown` when unsure."""
    text = _corpus(kvs)
    if not text.strip():
        return FormType.unknown

    # Strong signals: the form's own title / designation.
    if "wage and tax statement" in text or "w-2" in text or "w2" in text:
        return FormType.w2

    # Structural fallback: the signature pair of W-2 boxes.
    has_wages = "wages, tips" in text or "wages tips" in text
    has_fed_wh = "federal income tax withheld" in text
    if has_wages and has_fed_wh:
        return FormType.w2

    return FormType.unknown
