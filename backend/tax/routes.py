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

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from tax import storage
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
