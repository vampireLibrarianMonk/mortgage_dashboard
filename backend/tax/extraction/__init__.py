"""Document extraction providers for Tax Prep (Phase 2).

A provider turns a document's bytes into normalized key/value pairs with a
bounding box and confidence (the raw material for form readers). Everything
downstream (classification, form readers, TaxFacts) is identical regardless of
which provider ran, so providers are swappable behind one interface:

    local   LocalDigitalProvider   AcroForm fields + native PDF text (digital PDFs)
    aws     TextractProvider       AWS Textract AnalyzeDocument FORMS (scanned docs)

Default is local (offline, free). AWS is opt-in (per request and/or the
TAX_EXTRACTION_MODE env flag) because the real corpus is scanned and local
extraction yields little on scans — see new_spec/tax_prep_tab_design.md.
"""
from tax.extraction.providers import (
    ExtractedKV,
    ExtractionProvider,
    LocalDigitalProvider,
    TextractProvider,
    get_provider,
)

__all__ = [
    "ExtractedKV",
    "ExtractionProvider",
    "LocalDigitalProvider",
    "TextractProvider",
    "get_provider",
]
