"""Tax Prep Phase 1 tests — document foundation (storage + routes).

No extraction/calc/AI is exercised (none exists yet). These cover: kind
detection by magic bytes, SHA-256 identity + dedupe, immutable originals,
list/get/read/delete, and the HTTP routes incl. rejecting unsupported types.

Isolation: the autouse `isolated_store` fixture (conftest) redirects
txn_store.DATA_DIR to a tmp dir, but tax.storage.TAX_ROOT was computed from
ts.DATA_DIR at import time, so we also repoint TAX_ROOT at the tmp dir here.
"""
import pytest
from starlette.testclient import TestClient

import main
from tax import storage
from tax.models import DocKind
from tax.storage import UnsupportedDocument

# Minimal valid file bodies (magic bytes are what detect_kind inspects).
PDF = b"%PDF-1.7\n% minimal\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
TXT = b"just some text, not a tax form"


@pytest.fixture(autouse=True)
def isolated_tax(isolated_store, monkeypatch):
    """Repoint TAX_ROOT at the isolated tmp data dir (isolated_store already
    redirected ts.DATA_DIR + the Fernet key)."""
    monkeypatch.setattr(storage, "TAX_ROOT", isolated_store.DATA_DIR / "tax")


@pytest.fixture
def client():
    return TestClient(main.app)


# --- kind detection ------------------------------------------------------------

def test_detect_kind_pdf_png_jpeg():
    assert storage.detect_kind(PDF) == DocKind.pdf
    assert storage.detect_kind(PNG) == DocKind.png
    assert storage.detect_kind(JPEG) == DocKind.jpeg


def test_detect_kind_rejects_unsupported():
    with pytest.raises(UnsupportedDocument):
        storage.detect_kind(TXT)


# --- storage layer -------------------------------------------------------------

def test_add_document_creates_and_indexes():
    doc, created = storage.add_document(2025, "W2_Patrick.pdf", PDF)
    assert created is True
    assert doc.id == storage.sha256(PDF)
    assert doc.kind == DocKind.pdf
    assert doc.tax_year == 2025
    assert doc.size_bytes == len(PDF)
    assert doc.stage.value == "ingested"
    assert doc.form_type.value == "unknown"


def test_add_document_dedupes_on_sha256():
    doc1, created1 = storage.add_document(2025, "W2_Patrick.pdf", PDF)
    # Same bytes, different filename -> same id, not created again.
    doc2, created2 = storage.add_document(2025, "renamed.pdf", PDF)
    assert created1 is True and created2 is False
    assert doc1.id == doc2.id
    assert len(storage.list_documents(2025)) == 1


def test_original_is_stored_immutably_on_disk():
    doc, _ = storage.add_document(2025, "scan.jpg", JPEG)
    path = storage._original_file(2025, doc.id, DocKind.jpeg)
    assert path.is_file()
    assert path.read_bytes() == JPEG  # byte-for-byte, untouched


def test_list_get_read_delete_roundtrip():
    d_pdf, _ = storage.add_document(2025, "a.pdf", PDF)
    d_png, _ = storage.add_document(2025, "b.png", PNG)

    docs = storage.list_documents(2025)
    assert {d.id for d in docs} == {d_pdf.id, d_png.id}

    got = storage.get_document(2025, d_pdf.id)
    assert got is not None and got.id == d_pdf.id
    assert storage.get_document(2025, "nope") is None

    raw = storage.read_original(2025, d_png.id)
    assert raw is not None
    data, kind = raw
    assert data == PNG and kind == DocKind.png

    assert storage.delete_document(2025, d_pdf.id) is True
    assert storage.get_document(2025, d_pdf.id) is None
    assert storage.delete_document(2025, d_pdf.id) is False  # already gone
    # The other doc + its original survive.
    assert storage.read_original(2025, d_png.id) is not None


def test_years_are_isolated():
    storage.add_document(2024, "old.pdf", PDF)
    storage.add_document(2025, "new.png", PNG)
    assert len(storage.list_documents(2024)) == 1
    assert len(storage.list_documents(2025)) == 1


# --- HTTP routes ---------------------------------------------------------------

def test_route_upload_list_raw_delete(client):
    # upload
    r = client.post("/tax/2025/documents",
                    files={"file": ("W2_Sara.pdf", PDF, "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["created"] is True
    doc_id = body["document"]["id"]

    # list
    r = client.get("/tax/2025/documents")
    assert r.status_code == 200
    assert any(d["id"] == doc_id for d in r.json()["documents"])

    # raw bytes + content-type for the viewer
    r = client.get(f"/tax/2025/documents/{doc_id}/raw")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == PDF

    # delete
    r = client.delete(f"/tax/2025/documents/{doc_id}")
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.get(f"/tax/2025/documents/{doc_id}/raw")
    assert r.status_code == 404


def test_route_preview_reports_duplicate(client):
    # first preview: new
    r = client.post("/tax/2025/documents/preview",
                    files={"file": ("x.png", PNG, "image/png")})
    assert r.json() == {
        "ok": True, "filename": "x.png", "kind": "png",
        "size_bytes": len(PNG), "id": storage.sha256(PNG), "duplicate": False,
    }
    # commit it, then preview again: duplicate
    client.post("/tax/2025/documents", files={"file": ("x.png", PNG, "image/png")})
    r = client.post("/tax/2025/documents/preview",
                    files={"file": ("x.png", PNG, "image/png")})
    assert r.json()["duplicate"] is True


def test_route_rejects_unsupported_type(client):
    r = client.post("/tax/2025/documents",
                    files={"file": ("notes.txt", TXT, "text/plain")})
    assert r.status_code == 200  # handled gracefully, not a 500
    body = r.json()
    assert body["ok"] is False and "unsupported" in body["error"].lower()
