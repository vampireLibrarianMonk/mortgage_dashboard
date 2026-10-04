"""Tax document storage: SHA-256 identity, immutable originals, encrypted index.

Layout (under the existing encrypted-store data dir, gitignored):

    txn_data/tax/<year>/originals/<sha256>.<ext>   immutable original bytes
    txn_data/tax/<year>/index.json.enc             Fernet-encrypted metadata index

Originals are stored byte-for-byte and never modified (the spec's "preserve
originals"). They are large binaries living only on this local, gitignored disk,
so they are not Fernet-wrapped; the *metadata index* is encrypted, reusing
txn_store's Fernet helpers (same key in Windows Credential Manager). Derived,
sensitive artifacts (extracted facts, searchable OCR copies) come in later phases
and will be encrypted.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import txn_store as ts  # reuse DATA_DIR + Fernet _read_enc/_write_enc
from tax.models import DocKind, DocStage, TaxDocument, TaxFact

TAX_ROOT = ts.DATA_DIR / "tax"

# Accepted upload kinds: scanned images + digital/flattened PDFs (user's corpus).
_MAGIC = [
    (b"%PDF", DocKind.pdf),
    (b"\x89PNG\r\n\x1a\n", DocKind.png),
    (b"\xff\xd8\xff", DocKind.jpeg),
]
_EXT = {DocKind.pdf: "pdf", DocKind.png: "png", DocKind.jpeg: "jpeg"}


class UnsupportedDocument(ValueError):
    """Raised when the uploaded bytes are not a PDF/PNG/JPEG."""


def detect_kind(data: bytes) -> DocKind:
    """Identify the file kind from magic bytes (content, not filename). Raises
    UnsupportedDocument for anything that is not PDF/PNG/JPEG."""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    raise UnsupportedDocument(
        "unsupported file type: expected a PDF, PNG, or JPEG tax document"
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _year_dir(tax_year: int) -> Path:
    return TAX_ROOT / str(int(tax_year))


def _originals_dir(tax_year: int) -> Path:
    return _year_dir(tax_year) / "originals"


def _index_path(tax_year: int) -> Path:
    return _year_dir(tax_year) / "index.json.enc"


def _load_index(tax_year: int) -> dict:
    """Map of doc_id -> TaxDocument dict for one year. {} when none."""
    return ts._read_enc(_index_path(tax_year), {})


def _save_index(tax_year: int, index: dict) -> None:
    _index_path(tax_year).parent.mkdir(parents=True, exist_ok=True)
    ts._write_enc(_index_path(tax_year), index)


def _original_file(tax_year: int, doc_id: str, kind: DocKind) -> Path:
    return _originals_dir(tax_year) / f"{doc_id}.{_EXT[kind]}"


def _page_count(data: bytes, kind: DocKind) -> int | None:
    """Best-effort page count (null when not cheaply knowable). Images = 1 page;
    PDFs via pypdf if available. Never raises — page count is informational."""
    if kind in (DocKind.png, DocKind.jpeg):
        return 1
    try:
        import io

        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return None


def add_document(tax_year: int, filename: str, data: bytes) -> tuple[TaxDocument, bool]:
    """Store an uploaded document immutably and index it.

    Returns (document, created). `created` is False when the identical bytes were
    already stored for this year (SHA-256 match) — a dedup, not an error. The
    original file is written once and never modified.
    """
    kind = detect_kind(data)  # raises UnsupportedDocument
    doc_id = sha256(data)
    index = _load_index(tax_year)

    if doc_id in index:
        return TaxDocument(**index[doc_id]), False

    orig = _original_file(tax_year, doc_id, kind)
    orig.parent.mkdir(parents=True, exist_ok=True)
    if not orig.exists():  # immutable: write once, never overwrite
        orig.write_bytes(data)

    doc = TaxDocument(
        id=doc_id,
        tax_year=int(tax_year),
        original_filename=filename or f"{doc_id}.{_EXT[kind]}",
        kind=kind,
        size_bytes=len(data),
        uploaded_at=dt.datetime.now().isoformat(timespec="seconds"),
        stage=DocStage.ingested,
        page_count=_page_count(data, kind),
    )
    index[doc_id] = doc.model_dump()
    _save_index(tax_year, index)
    return doc, True


def list_documents(tax_year: int) -> list[TaxDocument]:
    index = _load_index(tax_year)
    docs = [TaxDocument(**v) for v in index.values()]
    docs.sort(key=lambda d: d.uploaded_at, reverse=True)
    return docs


def get_document(tax_year: int, doc_id: str) -> TaxDocument | None:
    index = _load_index(tax_year)
    rec = index.get(doc_id)
    return TaxDocument(**rec) if rec else None


def read_original(tax_year: int, doc_id: str) -> tuple[bytes, DocKind] | None:
    """Raw original bytes + kind for the viewer, or None if unknown."""
    doc = get_document(tax_year, doc_id)
    if doc is None:
        return None
    path = _original_file(tax_year, doc_id, doc.kind)
    if not path.is_file():
        return None
    return path.read_bytes(), doc.kind


def delete_document(tax_year: int, doc_id: str) -> bool:
    """Remove a document's index entry, its original file, and its facts. True if
    it existed."""
    index = _load_index(tax_year)
    rec = index.pop(doc_id, None)
    if rec is None:
        return False
    doc = TaxDocument(**rec)
    path = _original_file(tax_year, doc_id, doc.kind)
    path.unlink(missing_ok=True)
    _save_index(tax_year, index)
    # Drop any extracted facts for this document too.
    facts = _load_facts_index(tax_year)
    if facts.pop(doc_id, None) is not None:
        _save_facts_index(tax_year, facts)
    return True


def update_document(tax_year: int, doc_id: str, **patch) -> TaxDocument | None:
    """Patch fields on a stored TaxDocument (e.g. stage, form_type, taxpayer)."""
    index = _load_index(tax_year)
    rec = index.get(doc_id)
    if rec is None:
        return None
    rec.update(patch)
    doc = TaxDocument(**rec)  # validate
    index[doc_id] = doc.model_dump()
    _save_index(tax_year, index)
    return doc


# --- Extracted facts (per year, keyed by document id) -------------------------

def _facts_path(tax_year: int) -> Path:
    return _year_dir(tax_year) / "facts.json.enc"


def _load_facts_index(tax_year: int) -> dict:
    """Map of doc_id -> list[TaxFact dict] for one year. {} when none."""
    return ts._read_enc(_facts_path(tax_year), {})


def _save_facts_index(tax_year: int, facts: dict) -> None:
    _facts_path(tax_year).parent.mkdir(parents=True, exist_ok=True)
    ts._write_enc(_facts_path(tax_year), facts)


def save_facts(tax_year: int, doc_id: str, facts: list[TaxFact]) -> None:
    """Replace the stored facts for one document (facts are already PII-masked)."""
    index = _load_facts_index(tax_year)
    index[doc_id] = [f.model_dump() for f in facts]
    _save_facts_index(tax_year, index)


def load_facts(tax_year: int, doc_id: str) -> list[TaxFact]:
    return [TaxFact(**f) for f in _load_facts_index(tax_year).get(doc_id, [])]


def load_all_facts(tax_year: int) -> dict[str, list[TaxFact]]:
    index = _load_facts_index(tax_year)
    return {doc_id: [TaxFact(**f) for f in facts] for doc_id, facts in index.items()}


def update_fact(tax_year: int, doc_id: str, field_code: str, patch: dict) -> TaxFact | None:
    """Patch one fact (by field_code) within a document's fact list. Returns the
    updated fact, or None if not found."""
    index = _load_facts_index(tax_year)
    rows = index.get(doc_id)
    if not rows:
        return None
    updated: TaxFact | None = None
    for i, row in enumerate(rows):
        if row.get("field_code") == field_code:
            row.update(patch)
            updated = TaxFact(**row)  # validate
            rows[i] = updated.model_dump()
            break
    if updated is None:
        return None
    index[doc_id] = rows
    _save_facts_index(tax_year, index)
    return updated
