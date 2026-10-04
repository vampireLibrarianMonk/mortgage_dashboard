"""Extraction providers — normalize document bytes to key/value pairs.

Each provider returns a list of ExtractedKV (key text, value text, confidence
0-1, page, and a normalized bounding box). Form readers consume this uniform
shape, so swapping providers never changes downstream code.
"""
from __future__ import annotations

import io
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from tax.extraction.images import NoPageImage, to_image_bytes
from tax.models import DocKind

# Extraction mode default. Local = offline/free (little on scans); aws = Textract.
EXTRACTION_MODE_ENV = "TAX_EXTRACTION_MODE"
AWS_REGION_ENV = "TAX_AWS_REGION"
_DEFAULT_REGION = "us-east-1"


@dataclass
class ExtractedKV:
    """One key/value pair from a provider, with provenance.

    bbox is (left, top, width, height), each 0-1 normalized to the page. A
    checkbox value is represented as the string "[X]" (checked) or "" (unchecked).
    """
    key: str
    value: str
    confidence: float  # 0-1
    page: int = 1
    bbox: tuple[float, float, float, float] | None = None
    is_selection: bool = False  # True when the value came from a checkbox


class ExtractionProvider(ABC):
    """Turns a document's bytes into normalized key/value pairs."""

    name: str = "base"

    @abstractmethod
    def extract(self, data: bytes, kind: DocKind) -> list[ExtractedKV]:
        """Return key/value pairs. Must not raise on an unreadable document —
        return [] and let the caller decide (so one bad doc never breaks a batch)."""
        raise NotImplementedError


class LocalDigitalProvider(ExtractionProvider):
    """Offline path: AcroForm fields, then native PDF text. Yields little on
    scanned/flattened PDFs (no text layer), which is the signal to escalate to
    AWS. Never calls out to the network."""

    name = "local"

    def extract(self, data: bytes, kind: DocKind) -> list[ExtractedKV]:
        if kind in (DocKind.png, DocKind.jpeg):
            return []  # images have no digital text/fields to read locally
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
        except Exception:
            return []

        out: list[ExtractedKV] = []

        # 1. AcroForm fields (exact values when a PDF is a real fillable form).
        try:
            fields = reader.get_fields() or {}
            for name, fld in fields.items():
                val = fld.get("/V") if hasattr(fld, "get") else None
                if val is not None:
                    out.append(ExtractedKV(key=str(name), value=str(val), confidence=1.0))
        except Exception:
            pass

        # 2. Native text (no KV association — low value for forms, but honest:
        # it proves whether a text layer exists at all). We expose it as a single
        # synthetic KV so the caller can tell "there was text" vs "nothing".
        try:
            text = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
            if text:
                out.append(ExtractedKV(key="__native_text__", value=text, confidence=1.0))
        except Exception:
            pass

        return out


class TextractProvider(ExtractionProvider):
    """AWS path: Textract AnalyzeDocument(FORMS) on the page image. Returns KV
    pairs with Textract's own per-field confidence and bounding boxes — the
    provenance the review UI and TaxFacts use. Opt-in / cloud."""

    name = "aws"

    def __init__(self, region: str | None = None):
        self.region = region or os.environ.get(AWS_REGION_ENV, _DEFAULT_REGION)

    def extract(self, data: bytes, kind: DocKind) -> list[ExtractedKV]:
        try:
            image = to_image_bytes(data, kind)
        except NoPageImage:
            return []  # no raster to send; local path should handle it

        import boto3

        client = boto3.client("textract", region_name=self.region)
        resp = client.analyze_document(Document={"Bytes": image}, FeatureTypes=["FORMS"])
        return _parse_textract(resp)


def _parse_textract(resp: dict) -> list[ExtractedKV]:
    """Flatten a Textract AnalyzeDocument response into ExtractedKV pairs."""
    blocks = {b["Id"]: b for b in resp.get("Blocks", [])}

    def child_text(block) -> tuple[str, bool]:
        """Concatenated text of a block's CHILD words; selected-checkbox flag."""
        words: list[str] = []
        selected = False
        for rel in block.get("Relationships", []):
            if rel["Type"] != "CHILD":
                continue
            for cid in rel["Ids"]:
                c = blocks.get(cid, {})
                if c.get("BlockType") == "WORD":
                    words.append(c.get("Text", ""))
                elif c.get("BlockType") == "SELECTION_ELEMENT":
                    if c.get("SelectionStatus") == "SELECTED":
                        selected = True
        return " ".join(words).strip(), selected

    def value_block_text(key_block) -> tuple[str, bool, float]:
        for rel in key_block.get("Relationships", []):
            if rel["Type"] == "VALUE":
                for vid in rel["Ids"]:
                    vb = blocks.get(vid, {})
                    text, sel = child_text(vb)
                    return text, sel, float(vb.get("Confidence", 0.0))
        return "", False, 0.0

    out: list[ExtractedKV] = []
    for b in resp.get("Blocks", []):
        if b.get("BlockType") != "KEY_VALUE_SET":
            continue
        if "KEY" not in b.get("EntityTypes", []):
            continue
        key_text, _ = child_text(b)
        val_text, selected, val_conf = value_block_text(b)
        key_conf = float(b.get("Confidence", 0.0))
        # Field confidence = the weaker of key/value detection, normalized to 0-1.
        conf = min(key_conf, val_conf) / 100.0 if val_text or selected else key_conf / 100.0
        geo = b.get("Geometry", {}).get("BoundingBox")
        bbox = (
            (geo["Left"], geo["Top"], geo["Width"], geo["Height"]) if geo else None
        )
        page = int(b.get("Page", 1))
        value = "[X]" if (selected and not val_text) else val_text
        out.append(
            ExtractedKV(
                key=key_text,
                value=value,
                confidence=round(conf, 4),
                page=page,
                bbox=bbox,
                is_selection=selected,
            )
        )
    return out


def get_provider(mode: str | None = None) -> ExtractionProvider:
    """Resolve a provider from an explicit mode or the TAX_EXTRACTION_MODE env
    flag (default 'local'). 'aws' -> Textract; anything else -> local digital."""
    resolved = (mode or os.environ.get(EXTRACTION_MODE_ENV, "local")).lower()
    if resolved == "aws":
        return TextractProvider()
    return LocalDigitalProvider()
