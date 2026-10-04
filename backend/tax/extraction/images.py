"""Turn an uploaded document into image bytes Textract can accept.

Textract's synchronous AnalyzeDocument accepts PNG/JPEG/TIFF bytes but NOT PDF
(PDF needs the async S3 path). Our scanned tax PDFs are a single image embedded
per page, so we pull that embedded image out with pypdf — no rasterizer needed.
PNG/JPEG uploads pass through unchanged.
"""
from __future__ import annotations

import io

from tax.models import DocKind


class NoPageImage(ValueError):
    """Raised when a PDF has no extractable embedded page image (e.g. a true
    digital/vector PDF with no scanned image). Such a doc should go the local
    text path, not Textract."""


def to_image_bytes(data: bytes, kind: DocKind) -> bytes:
    """Return image bytes suitable for synchronous Textract.

    PNG/JPEG pass through. For a PDF, extract the first embedded page image
    (our scans are a JPEG per page). Raises NoPageImage if the PDF carries no
    embedded raster image.
    """
    if kind in (DocKind.png, DocKind.jpeg):
        return data

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if not reader.pages:
        raise NoPageImage("PDF has no pages")
    page = reader.pages[0]
    resources = page.get("/Resources")
    xobject = resources.get("/XObject") if resources else None
    if not xobject:
        raise NoPageImage("PDF page has no image XObject (likely a digital/vector PDF)")
    xobject = xobject.get_object()
    for name in xobject:
        obj = xobject[name].get_object()
        if obj.get("/Subtype") == "/Image":
            try:
                return obj.data  # pypdf returns decoded bytes; DCTDecode -> JPEG
            except Exception as e:  # noqa: BLE001 - fall through to the raise below
                raise NoPageImage(f"could not decode embedded image: {e}") from e
    raise NoPageImage("no embedded image found on the first PDF page")
