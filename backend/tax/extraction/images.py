"""Turn an uploaded document into image bytes Textract can accept.

Textract's synchronous AnalyzeDocument accepts PNG/JPEG/TIFF bytes but NOT PDF
(PDF needs the async S3 path). Our scanned tax PDFs are a single image embedded
per page, so we pull that embedded image out with pypdf — no rasterizer needed.
PNG/JPEG uploads pass through unchanged.
"""
from __future__ import annotations

import io

from tax.models import DocKind

# PDF image filters whose encoded stream IS already a complete image file
# (JPEG / JPEG2000). For these we hand Textract the raw stream bytes untouched
# when possible; anything Textract can't take (TIFF from CCITT fax, JP2) is
# re-encoded to PNG via Pillow when Pillow is available.
_PASSTHROUGH_FILTERS = {"/DCTDecode", "/JPXDecode"}

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _acceptable_for_textract(image: bytes) -> bytes:
    """Image bytes Textract's synchronous API will accept (PNG/JPEG).

    JPEG and PNG pass through. Anything else (the TIFF that pypdf wraps around
    CCITT-fax scans, JP2, raw pixel blobs) is re-encoded to PNG via Pillow when
    Pillow is installed; without Pillow the bytes pass through unchanged and
    Textract's error surfaces to the caller (the pre-Pillow behavior)."""
    if image[:3] == _JPEG_MAGIC or image[:8] == _PNG_MAGIC:
        return image
    try:
        from PIL import Image
    except ImportError:
        return image  # optional dependency; keep the pre-Pillow behavior
    try:
        with Image.open(io.BytesIO(image)) as im:
            if im.mode not in ("L", "RGB", "RGBA"):
                im = im.convert("L")
            out = io.BytesIO()
            im.save(out, format="PNG")
            return out.getvalue()
    except Exception:  # noqa: BLE001 - fall back to the raw bytes on any failure
        return image


class NoPageImage(ValueError):
    """Raised when a PDF has no extractable embedded page image (e.g. a true
    digital/vector PDF with no scanned image). Such a doc should go the local
    text path, not Textract."""


def _filter_names(obj) -> list[str]:
    flt = obj.get("/Filter")
    if flt is None:
        return []
    if isinstance(flt, list):
        return [str(f) for f in flt]
    return [str(flt)]


def _image_bytes_from_xobject(obj) -> bytes:
    """Encoded bytes of one image XObject. For DCTDecode/JPXDecode the stream is
    already a JPEG/JP2 file, so return it raw; otherwise fall back to pypdf's
    decoded data (a TIFF for CCITT-fax scans). Either way the result is
    normalized to something Textract accepts (PNG/JPEG) before returning."""
    filters = _filter_names(obj)
    if any(f in _PASSTHROUGH_FILTERS for f in filters):
        # Raw encoded stream = the image file itself. Prefer the private _data
        # (encoded) over get_data(), which would attempt to inflate the stream.
        raw = getattr(obj, "_data", None)
        if raw:
            return _acceptable_for_textract(raw)
    return _acceptable_for_textract(obj.get_data())


def _first_page_image(page) -> bytes | None:
    """First embedded image on one pypdf page, or None if the page has none."""
    resources = page.get("/Resources")
    xobject = resources.get("/XObject") if resources else None
    if not xobject:
        return None
    xobject = xobject.get_object()
    for name in xobject:
        obj = xobject[name].get_object()
        if obj.get("/Subtype") == "/Image":
            try:
                image = _image_bytes_from_xobject(obj)
            except Exception:  # a non-decodable image means "no image here"
                continue
            if image:
                return image
    return None


def iter_page_images(data: bytes, kind: DocKind):
    """Yield one embedded image (bytes) per PDF page that has one.

    Real-world W-2 PDFs are multi-page: a scanned "Notice to Employee"
    instructions page can precede the actual form, so a caller must be able to
    try every page, not just the first. PNG/JPEG uploads yield their single
    image. Raises NoPageImage only when a PDF contains no page image at all.
    """
    if kind in (DocKind.png, DocKind.jpeg):
        yield data
        return

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if not reader.pages:
        raise NoPageImage("PDF has no pages")

    found = False
    for page in reader.pages:
        image = _first_page_image(page)
        if image:
            found = True
            yield image
    if not found:
        raise NoPageImage("PDF has no embedded page image (likely a digital/vector PDF)")


def to_image_bytes(data: bytes, kind: DocKind) -> bytes:
    """Return the first page's image bytes (back-compat single-image helper).

    PNG/JPEG pass through. For a PDF, return the first embedded page image.
    Prefer iter_page_images when a document may have multiple pages.
    """
    for image in iter_page_images(data, kind):
        return image
    raise NoPageImage("no embedded image found")
