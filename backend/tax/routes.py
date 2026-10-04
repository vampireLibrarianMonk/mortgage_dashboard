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
from tax.forms.paystub import extract_paystub_facts, parse_paystub, rebuild_year
from tax.forms.w2 import extract_w2_facts
from tax.models import DocStage, ExtractionMethod, FactStatus, FormType
from tax.reconcile import reconcile_household
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
    method = _METHOD_FOR_PROVIDER.get(choice, ExtractionMethod.manual)

    facts: list = []
    taxpayer: str | None = None
    if form_type is FormType.w2:
        facts = extract_w2_facts(doc_id, year, kvs, method=method)
        taxpayer = _person_from_name(_fact_name(facts)) or _person_from_filename(
            doc.original_filename
        )
    elif form_type is FormType.paystub:
        facts = extract_paystub_facts(doc_id, year, kvs, method=method)
        reading = parse_paystub(kvs)
        taxpayer = _person_from_name(reading.employee_name) or _person_from_filename(
            doc.original_filename
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
        note = "Content did not match a supported form type (W-2 / paystub so far)."
    elif form_type is FormType.w2 and not facts:
        note = "Classified as W-2 but no boxes could be mapped from the content."

    patch = {"stage": stage, "form_type": form_type, "note": note}
    if taxpayer:
        patch["taxpayer"] = taxpayer
    storage.update_document(year, doc_id, **patch)

    return {
        "ok": True,
        "provider": choice,
        "form_type": form_type.value,
        "stage": stage.value,
        "taxpayer": taxpayer,
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


# --- Person attribution + household reconciliation ----------------------------

def _fact_name(facts: list) -> str | None:
    """The employee/taxpayer name carried on a document's facts, if any."""
    for f in facts:
        name = getattr(f, "taxpayer_name", None)
        if name:
            return name
        # W-2 facts stash the name as the employee_name field's value.
        if getattr(f, "field_code", "") == "employee_name" and f.value:
            return str(f.value)
    return None


def _person_from_name(name: str | None) -> str | None:
    """Normalize a full name to a stable household key (the first name).

    Keeps attribution robust across documents where the name is formatted
    differently (e.g. "SARA FLANIGAN 4005 ANCIENT OAK CT ..." from a W-2 vs
    "Patrick Flanigan" from a paystub)."""
    if not name:
        return None
    first = name.strip().split()[0] if name.strip() else ""
    return first.title() or None


# Known household members, matched case-insensitively against a filename as a
# fallback when a document's own text didn't yield a clean name (W-2 scans often
# format the employee name unpredictably, and the name is PII we avoid parsing
# aggressively). Filenames in the corpus are explicit, e.g.
# "W2_Patrick_Booz_Allen_2025_Copy_B.pdf".
_HOUSEHOLD_NAMES = ("Patrick", "Sara")


def _person_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    low = filename.lower()
    for name in _HOUSEHOLD_NAMES:
        if name.lower() in low:
            return name
    return None


def _paystub_readings_for(year: int, person: str):
    """Parse every stored paystub attributable to `person`, pulling in the next
    year's documents too so a December period paid in January still routes to
    the right W-2 year (the rebuild filters by pay date)."""
    readings = []
    for y in (year, year + 1):
        for doc in storage.list_documents(y):
            if doc.form_type is not FormType.paystub:
                continue
            doc_person = _person_from_name(doc.taxpayer) or _person_from_filename(
                doc.original_filename
            )
            if doc_person not in (person, None):
                continue
            res = storage.read_original(y, doc.id)
            if res is None:
                continue
            data, kind = res
            try:
                kvs = get_provider("local").extract(data, kind)
            except Exception:  # one unreadable stub must not fail reconciliation
                continue
            reading = parse_paystub(kvs)
            # Guard attribution when the doc wasn't tagged: match on the name.
            if doc.taxpayer is None and _person_from_name(reading.employee_name) != person:
                continue
            readings.append(reading)
    return readings


@router.get("/{year}/reconcile")
def household_reconcile(year: int):
    """W-2 ↔ paystub reconciliation for the whole household in one year.

    Gathers every person who has a W-2 and/or paystubs (from already-extracted
    documents), rebuilds each person's full-year paystub totals on a pay-date
    basis, reconciles against their W-2, and rolls the W-2 figures into a
    household total. Nothing is computed that isn't backed by a document.
    """
    # Collect people from W-2 and paystub documents' attribution.
    people: set[str] = set()
    w2_facts_by_person: dict[str, list] = {}

    for doc in storage.list_documents(year):
        person = _person_from_name(doc.taxpayer) or _person_from_filename(doc.original_filename)
        if doc.form_type is FormType.w2:
            facts = storage.load_facts(year, doc.id)
            if person is None:
                person = _person_from_name(_fact_name(facts))
            if person:
                people.add(person)
                # Keep the richest W-2 if a person has multiple copies.
                prior = w2_facts_by_person.get(person, [])
                if len(facts) > len(prior):
                    w2_facts_by_person[person] = facts
        elif doc.form_type is FormType.paystub and person:
            people.add(person)

    if not people:
        return {
            "ok": True,
            "reconciliation": None,
            "note": (
                "No extracted W-2 or paystub documents yet. Upload and extract "
                "them first, then run reconciliation."
            ),
        }

    per_person: dict[str, tuple] = {}
    for person in people:
        readings = _paystub_readings_for(year, person)
        rebuild = rebuild_year(readings, year) if readings else None
        per_person[person] = (w2_facts_by_person.get(person), rebuild)

    household = reconcile_household(year, per_person)
    return {"ok": True, "reconciliation": household.model_dump()}
