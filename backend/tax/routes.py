"""Tax Prep API (Phase 1: document foundation).

Mirrors the app's preview -> commit upload idiom and the 25 MB cap used by the
statement importer. Endpoints under /tax:

    POST   /tax/{year}/documents/preview   validate an upload (writes nothing)
    POST   /tax/{year}/documents           store an upload (immutable + indexed)
    GET    /tax/{year}/documents           list documents for a year
    GET    /tax/{year}/documents/{id}      one document's metadata
    GET    /tax/{year}/documents/{id}/raw  original bytes (for the viewer)
    DELETE /tax/{year}/documents/{id}      remove a document

Phase 1 does NO extraction/OCR/calc/AI — it stores originals and tracks them.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Body, File, UploadFile
from fastapi.responses import Response

from tax import storage
from tax.classify import classify_form
from tax.extraction.providers import get_provider
from tax.forms.w2 import extract_w2_facts
from tax.models import DocStage, ExtractionMethod, FactStatus, FormType
from tax.storage import UnsupportedDocument

router = APIRouter(prefix="/tax", tags=["tax"])

# Match the statement importer's cap; a scanned multi-page return is well under.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_MIME = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg"}


async def _read_upload(upload: UploadFile) -> tuple[str, bytes]:
    data = await upload.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValueError(f"upload too large ({len(data)} bytes; max {_MAX_UPLOAD_BYTES})")
    return upload.filename or "upload", data


@router.post("/{year}/documents/preview")
async def preview_document(year: int, file: UploadFile = File(...)):
    """Validate an upload and report whether it would be new or a duplicate.
    Writes nothing."""
    try:
        name, data = await _read_upload(file)
        kind = storage.detect_kind(data)  # raises UnsupportedDocument
    except UnsupportedDocument as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 - surface any read/size error to the UI
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    doc_id = storage.sha256(data)
    existing = storage.get_document(year, doc_id)
    return {
        "ok": True,
        "filename": name,
        "kind": kind.value,
        "size_bytes": len(data),
        "id": doc_id,
        "duplicate": existing is not None,
    }


@router.post("/{year}/documents")
async def upload_document(year: int, file: UploadFile = File(...)):
    """Store an uploaded tax document immutably and index it."""
    try:
        name, data = await _read_upload(file)
        doc, created = storage.add_document(year, name, data)
    except UnsupportedDocument as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True, "created": created, "document": doc.model_dump()}


@router.get("/{year}/documents")
def list_documents(year: int):
    return {"documents": [d.model_dump() for d in storage.list_documents(year)]}


@router.get("/{year}/documents/{doc_id}")
def get_document(year: int, doc_id: str):
    doc = storage.get_document(year, doc_id)
    if doc is None:
        return {"ok": False, "error": "document not found"}
    return {"ok": True, "document": doc.model_dump()}


@router.get("/{year}/documents/{doc_id}/raw")
def get_document_raw(year: int, doc_id: str):
    """Original bytes for the in-app viewer. inline so the browser can render it."""
    result = storage.read_original(year, doc_id)
    if result is None:
        return Response(status_code=404, content=b"not found")
    data, kind = result
    return Response(
        content=data,
        media_type=_MIME.get(kind.value, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{doc_id}.{kind.value}"'},
    )


@router.delete("/{year}/documents/{doc_id}")
def delete_document(year: int, doc_id: str):
    ok = storage.delete_document(year, doc_id)
    return {"ok": ok}


# --- Extraction + verification ------------------------------------------------

# Maps the chosen provider to the ExtractionMethod recorded on each fact.
_METHOD_FOR_PROVIDER = {
    "aws": ExtractionMethod.textract,
    "local": ExtractionMethod.native_pdf,
}


@router.post("/{year}/documents/{doc_id}/extract")
def extract_document(
    year: int,
    doc_id: str,
    provider: str = Body("local", embed=True),
):
    """Run extraction on a stored document and persist any facts.

    `provider` is 'local' (offline, free; little on scans) or 'aws' (Textract,
    opt-in). The document is classified from its content, then — if it's a W-2 —
    its boxes are mapped into facts. On a scanned doc with the local provider
    this honestly returns zero facts and a note telling the user to enable AWS.
    """
    doc = storage.get_document(year, doc_id)
    if doc is None:
        return {"ok": False, "error": "document not found"}

    result = storage.read_original(year, doc_id)
    if result is None:
        return {"ok": False, "error": "original bytes not found"}
    data, kind = result

    choice = (provider or "local").lower()
    if choice not in ("local", "aws"):
        return {"ok": False, "error": f"unknown provider '{provider}'"}

    try:
        kvs = get_provider(choice).extract(data, kind)
    except Exception as e:  # noqa: BLE001 - surface extraction failure to the UI
        storage.update_document(year, doc_id, stage=DocStage.error, note=str(e))
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    form_type = classify_form(kvs)
    note = ""

    facts: list = []
    if form_type is FormType.w2:
        facts = extract_w2_facts(
            doc_id, year, kvs, method=_METHOD_FOR_PROVIDER.get(choice, ExtractionMethod.manual)
        )

    if facts:
        storage.save_facts(year, doc_id, facts)
        stage = DocStage.extracted
    elif form_type is not FormType.unknown:
        stage = DocStage.classified
    else:
        stage = DocStage.classified if kvs else doc.stage

    if not kvs and choice == "local":
        note = (
            "Local extraction found no form fields or text layer — this looks "
            "like a scanned document. Enable AWS Textract to read its boxes."
        )
    elif form_type is FormType.unknown and kvs:
        note = "Content did not match a supported form type (only W-2 so far)."
    elif form_type is FormType.w2 and not facts:
        note = "Classified as W-2 but no boxes could be mapped from the content."

    storage.update_document(year, doc_id, stage=stage, form_type=form_type, note=note)

    return {
        "ok": True,
        "provider": choice,
        "form_type": form_type.value,
        "stage": stage.value,
        "fact_count": len(facts),
        "facts": [f.model_dump() for f in facts],
        "note": note,
    }


@router.get("/{year}/documents/{doc_id}/facts")
def get_document_facts(year: int, doc_id: str):
    """Facts extracted for one document (already PII-masked at creation)."""
    if storage.get_document(year, doc_id) is None:
        return {"ok": False, "error": "document not found"}
    facts = storage.load_facts(year, doc_id)
    return {"ok": True, "facts": [f.model_dump() for f in facts]}


@router.post("/{year}/documents/{doc_id}/facts/{field_code}/verify")
def verify_fact(
    year: int,
    doc_id: str,
    field_code: str,
    value: object = Body(None, embed=True),
    corrected_by: str | None = Body(None, embed=True),
):
    """Human review of one fact.

    If `value` is omitted (or equals the extracted value) the fact is accepted as
    verified; otherwise it's recorded as corrected. The original extracted_value
    is never overwritten — corrections keep a full audit trail. When every fact
    on the document is reviewed, the document advances to 'verified'.
    """
    existing = storage.load_facts(year, doc_id)
    target = next((f for f in existing if f.field_code == field_code), None)
    if target is None:
        return {"ok": False, "error": "fact not found"}

    # No explicit value -> accept the extracted value as-is.
    new_value = target.extracted_value if value is None else value
    corrected = new_value != target.extracted_value

    patch = {
        "verified_value": new_value,
        "value": new_value,
        "status": (FactStatus.corrected if corrected else FactStatus.verified).value,
        "corrected_at": dt.datetime.now().isoformat(timespec="seconds"),
        "corrected_by": corrected_by,
    }
    updated = storage.update_fact(year, doc_id, field_code, patch)
    if updated is None:
        return {"ok": False, "error": "fact not found"}

    # Advance the document to 'verified' once no fact still needs review.
    remaining = storage.load_facts(year, doc_id)
    reviewed = {FactStatus.verified, FactStatus.corrected, FactStatus.rejected}
    if remaining and all(f.status in reviewed for f in remaining):
        storage.update_document(year, doc_id, stage=DocStage.verified)

    return {"ok": True, "fact": updated.model_dump()}
