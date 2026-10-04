"""Pydantic models for the Tax Prep module.

Phase 1 populates only TaxDocument (the stored, immutable upload + its pipeline
status). TaxFact and its enums are defined now so later phases (extraction,
verification, provenance) have a stable shape to target, but Phase 1 never
produces facts.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocKind(str, Enum):
    """Physical file kind. Scanned images and flattened PDFs behave like images
    (no text layer); digital PDFs may carry text/form fields."""
    pdf = "pdf"
    png = "png"
    jpeg = "jpeg"


class FormType(str, Enum):
    """Tax form a document is classified as. 'unknown' until a later phase's
    content classifier runs — Phase 1 leaves everything unknown."""
    unknown = "unknown"
    w2 = "W-2"
    f1099_int = "1099-INT"
    f1099_div = "1099-DIV"
    f1099_b = "1099-B"
    f1099_nec = "1099-NEC"
    f1099_misc = "1099-MISC"
    f1099_r = "1099-R"
    f1098 = "1098"
    f1095_c = "1095-C"
    f3922 = "3922"
    ssa_1099 = "SSA-1099"
    k1 = "K-1"
    paystub = "Paystub"
    other = "other"


class DocStage(str, Enum):
    """Where a document sits in the pipeline (drives the per-doc status pills in
    the UI). Phase 1 only ever reaches 'ingested'."""
    ingested = "ingested"      # stored, SHA-256 identity assigned
    classified = "classified"  # form type detected (later phase)
    extracted = "extracted"    # facts pulled (later phase)
    verified = "verified"      # human-reviewed (later phase)
    error = "error"


class ExtractionMethod(str, Enum):
    """How a fact's value was obtained (provenance). Later phases only."""
    acroform = "acroform"
    native_pdf = "native_pdf"
    local_ocr = "local_ocr"
    textract = "textract"
    manual = "manual"


class FactStatus(str, Enum):
    extracted = "extracted"
    verified = "verified"
    corrected = "corrected"
    rejected = "rejected"
    needs_review = "needs_review"
    conflict = "conflict"


class TaxDocument(BaseModel):
    """An immutable uploaded tax document + its pipeline status. The original
    bytes are stored untouched on disk under the SHA-256 id; this record is the
    metadata index entry."""
    id: str                      # SHA-256 of the original bytes (identity + dedupe)
    tax_year: int
    original_filename: str
    kind: DocKind
    size_bytes: int
    uploaded_at: str             # iso8601
    stage: DocStage = DocStage.ingested
    form_type: FormType = FormType.unknown
    # Who the document is attributed to (e.g. "Patrick", "Sara", "Joint").
    # Phase 1 leaves this null; a later phase assigns it from extracted facts.
    taxpayer: str | None = None
    page_count: int | None = None  # best-effort; null when not cheaply known
    note: str = ""


class TaxFact(BaseModel):
    """A single extracted value with full provenance. DEFINED for later phases;
    Phase 1 does not create these. Corrections never destroy the original value
    (keep extracted_value alongside verified_value)."""
    tax_year: int
    document_id: str
    form_type: FormType = FormType.unknown

    payer_name: str | None = None
    payer_tin_masked: str | None = None
    taxpayer_name: str | None = None

    field_code: str
    field_label: str = ""
    # bool must precede int in the union: bool is an int subclass, and Pydantic
    # would otherwise coerce True -> 1.0. The Box 13 retirement-plan checkbox
    # relies on staying a real bool.
    value: bool | str | float | int | None = None

    page: int = 1
    bbox: tuple[float, float, float, float] | None = None

    extraction_method: ExtractionMethod = ExtractionMethod.manual
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: FactStatus = FactStatus.extracted

    # Audit trail — never overwrite the original extracted value on correction.
    extracted_value: bool | str | float | int | None = None
    verified_value: bool | str | float | int | None = None
    corrected_by: str | None = None
    corrected_at: str | None = None
    parser_version: str | None = None
