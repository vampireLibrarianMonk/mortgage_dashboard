"""Tax dump reconciliation: manifest, triage, classification, routing.

Phase 0 (manifest): walk Scans/Dump/Taxes and Scans/Organized/Tax_Documents,
    write SHA-256 manifests + extension triage + archive/other overlap report.
Phase 1 (classify): classify every dump candidate by content — pypdf native
    text first (the same LocalDigitalProvider the app uses), then AWS Textract
    DetectDocumentText OCR as the cheap triage fallback (FORMS analysis is left
    to real ingest), cached by SHA-256 so re-runs are free. Produces form type,
    tax year, person, payer and copy tag per file, plus the 2025 1099-DIV
    hunt verdict for the backlog dividend item.
Phase 2 (dry-run / apply): match dump candidates against the Organized tree
    (exact SHA-256 first, then basename + text-similarity variants) and propose
    copy-only routing under Organized/Tax_Documents/<year>/<Category>/ using
    the corpus naming conventions. `apply` executes the approved plan.

Safety: the dump tree is NEVER modified; apply only ever copies (never moves)
into the Organized tree. Artifacts live under backend/txn_data/tax_reconcile/
(gitignored along with the rest of txn_data). Classification runs are
resumable: files already classified in classification.json are skipped.

Usage (from the repo root):
    backend/venv/Scripts/python.exe backend/scripts/tax_dump_reconcile.py manifest
    backend/venv/Scripts/python.exe backend/scripts/tax_dump_reconcile.py classify [--no-ocr] [--limit N]
    backend/venv/Scripts/python.exe backend/scripts/tax_dump_reconcile.py dry-run [--threshold 0.85]
    backend/venv/Scripts/python.exe backend/scripts/tax_dump_reconcile.py apply --yes
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import re
import shutil
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DUMP_ROOT = Path(r"C:\Users\mothe\Documents\Scans\Dump\Taxes")
ORG_ROOT = Path(r"C:\Users\mothe\Documents\Scans\Organized\Tax_Documents")
ART_DIR = BACKEND / "txn_data" / "tax_reconcile"
OCR_CACHE_DIR = ART_DIR / "ocr_cache"

NOW = datetime.now()
CURRENT_YEAR = NOW.year
YEAR_MIN, YEAR_MAX = 2004, CURRENT_YEAR + 1

# Triage buckets (plan Phase 0 step 2). Extension-less files are candidates
# only when their magic bytes say PDF/PNG/JPEG (the store's accepted kinds).
DOC_EXTS = {"pdf", "jpg", "jpeg", "png", "tif", "tiff"}
SKIP_EXTS = {
    "gif", "js", "htm", "html", "css", "mht", "mhtml", "aspx", "axd", "swf",
    "exe", "ba8", "ta8", "bk7", "efr", "one", "log", "db",
}
HOLD_EXTS = {"xps", "xls", "xlsx", "csv", "docx"}

_MAGICS = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)

_HOUSEHOLD_NAMES = ("Patrick", "Sara")  # mirrors tax.routes._HOUSEHOLD_NAMES


def _magic_kind(head: bytes) -> str | None:
    for magic, kind in _MAGICS:
        if head.startswith(magic):
            return kind
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FileRec:
    relpath: str        # posix relpath under the tree root
    folder: str         # top-level entry under the root ("2024", "archive", ...)
    size: int
    mtime: str
    sha256: str
    ext: str
    kind: str           # content kind: pdf/png/jpeg/tiff/other
    status: str         # dump triage: candidate/hold/junk; organized: present


def _walk_tree(root: Path, triage: bool) -> list[FileRec]:
    """Read-only walk. Hashes every file (streaming); never writes."""
    recs: list[FileRec] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        folder = rel.split("/", 1)[0]
        ext = path.suffix.lower().lstrip(".")
        st = path.stat()
        with path.open("rb") as fh:
            head = fh.read(8)
        kind = _magic_kind(head) or "other"
        if triage:
            if ext in DOC_EXTS or (ext == "" and kind in ("pdf", "png", "jpeg")):
                status = "candidate"
            elif ext in HOLD_EXTS:
                status = "hold"
            else:
                status = "junk"
        else:
            status = "present"
        recs.append(
            FileRec(
                relpath=rel,
                folder=folder,
                size=st.st_size,
                mtime=datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                sha256=_sha256_file(path),
                ext=ext,
                kind=kind,
                status=status,
            )
        )
    return recs


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


def _read_json(path: Path, default=None):
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _md_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- Phase 0: manifests, triage, duplicate-tree check ------------------------

def cmd_manifest(args: argparse.Namespace) -> None:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    dump = _walk_tree(DUMP_ROOT, triage=True)
    org = _walk_tree(ORG_ROOT, triage=False)
    _write_json(ART_DIR / "manifest_dump.json", [asdict(r) for r in dump])
    _write_json(ART_DIR / "manifest_organized.json", [asdict(r) for r in org])

    cands = [r for r in dump if r.status == "candidate"]
    holds = [r for r in dump if r.status == "hold"]
    junk = [r for r in dump if r.status == "junk"]

    per_folder: dict[str, dict[str, int]] = {}
    for r in dump:
        slot = per_folder.setdefault(r.folder, {"files": 0, "candidate": 0, "hold": 0, "junk": 0})
        slot["files"] += 1
        slot[r.status] += 1

    # archive vs other — suspected duplicate trees; compare by hash.
    arch = {r.sha256 for r in dump if r.folder == "archive"}
    othr = {r.sha256 for r in dump if r.folder == "other"}
    shared = arch & othr
    overlap = {
        "archive_files": len(arch),
        "other_files": len(othr),
        "shared_hashes": len(shared),
        "archive_only": len(arch - othr),
        "other_only": len(othr - arch),
    }

    dump_shas = {r.sha256 for r in dump}
    org_shas = {r.sha256 for r in org}
    already_organized = dump_shas & org_shas

    summary = {
        "generated_at": _ts(),
        "dump_root": str(DUMP_ROOT),
        "organized_root": str(ORG_ROOT),
        "dump_files": len(dump),
        "dump_candidates": len(cands),
        "dump_hold": len(holds),
        "dump_junk": len(junk),
        "organized_files": len(org),
        "per_folder": per_folder,
        "archive_vs_other": overlap,
        "dump_hashes_already_in_organized": len(already_organized),
    }
    _write_json(ART_DIR / "manifest_summary.json", summary)
    _write_json(
        ART_DIR / "overlap.json",
        {
            "archive_vs_other": overlap,
            "shared_sha_examples": sorted(shared)[:20],
            "dump_shas_already_in_organized": sorted(already_organized),
        },
    )

    print(f"Dump   : {len(dump)} files | candidates={len(cands)} hold={len(holds)} junk={len(junk)}")
    print(f"Organiz: {len(org)} files")
    print(f"archive vs other: shared={overlap['shared_hashes']} "
          f"archive_only={overlap['archive_only']} other_only={overlap['other_only']}")
    print(f"dump hashes already present under Organized: {len(already_organized)}")
    print("per-folder (files / candidates / hold / junk):")
    for folder, slot in per_folder.items():
        print(f"  {folder:<12} {slot['files']:>4} {slot['candidate']:>4} "
              f"{slot['hold']:>4} {slot['junk']:>4}")
    ok = len(dump) == 861 and len(cands) == 308
    print(f"context check (861 files / 308 candidates): {'MATCH' if ok else 'MISMATCH — re-verify'}")
    print(f"artifacts -> {ART_DIR}")


# --- Phase 1: text acquisition (native first, cached Textract OCR fallback) --

from tax.classify import classify_form  # noqa: E402  (needs backend on sys.path)
from tax.extraction.images import NoPageImage, iter_page_images  # noqa: E402
from tax.extraction.providers import ExtractedKV, LocalDigitalProvider  # noqa: E402
from tax.models import DocKind, FormType  # noqa: E402


@dataclass
class TextResult:
    kvs: list = field(default_factory=list)
    text: str = ""
    source: str = "none"   # native | ocr | needs_ocr | none | failed
    pages: int = 0
    error: str = ""


def _tiff_pages(data: bytes) -> list[bytes]:
    """Decode every TIFF frame and re-encode as PNG (CCITT-fax safe via Pillow)."""
    from PIL import Image

    pages: list[bytes] = []
    with Image.open(io.BytesIO(data)) as im:
        frame_count = getattr(im, "n_frames", 1)
        for i in range(frame_count):
            im.seek(i)
            frame = im.convert("L") if im.mode not in ("L", "RGB", "RGBA") else im.copy()
            out = io.BytesIO()
            frame.save(out, format="PNG")
            pages.append(out.getvalue())
    return pages or [data]


def _page_images(data: bytes, kind: str) -> list[bytes]:
    if kind == "pdf":
        return list(iter_page_images(data, DocKind.pdf))
    if kind == "tiff":
        return _tiff_pages(data)
    return [data]  # jpeg / png pass through unchanged


def _ocr_page_lines(client, image: bytes) -> str:
    """DetectDocumentText on one page image -> text lines in reading order."""
    resp = client.detect_document_text(Document={"Bytes": image})

    def _key(block: dict) -> tuple[float, float]:
        geo = block.get("Geometry", {}).get("BoundingBox", {})
        return (round(float(geo.get("Top", 0.0)), 2), float(geo.get("Left", 0.0)))

    lines = [b for b in resp.get("Blocks", []) if b.get("BlockType") == "LINE"]
    lines.sort(key=_key)
    return "\n".join(b.get("Text", "") for b in lines)


def _cache_path(sha: str) -> Path:
    return OCR_CACHE_DIR / f"{sha}.json"


def decrypted_pdf_bytes(data: bytes, password: str) -> bytes | None:
    """Decrypted PDF bytes when `password` opens it; None otherwise (or when
    the PDF is not encrypted). Used so password-protected originals can be
    copied into Organized as readable documents the app can ingest."""
    try:
        from pypdf import PdfReader, PdfWriter

        if not data.startswith(b"%PDF"):
            return None
        reader = PdfReader(io.BytesIO(data))
        if not reader.is_encrypted:
            return None
        if not reader.decrypt(password):
            return None
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def acquire_text(data: bytes, kind: str, sha: str, client, password: str | None = None) -> TextResult:
    """Native text layer first; OCR (cached by SHA-256) for scans.

    Takes raw inputs so both dump files and Organized-tree files can use it."""
    native_err = ""
    if kind == "pdf" and password:
        dec = decrypted_pdf_bytes(data, password)
        if dec is not None:
            data = dec  # read the decrypted form for both text and OCR paths
    if kind == "pdf":
        try:
            kvs = LocalDigitalProvider().extract(data, DocKind.pdf)
        except Exception as e:  # noqa: BLE001
            kvs = []
            native_err = f"{type(e).__name__}: {e}"
        text = "\n".join(f"{kv.key} {kv.value}" for kv in kvs)
        if len(text.strip()) >= 40:
            return TextResult(kvs=kvs, text=text, source="native")

    cache = _read_json(_cache_path(sha))
    if cache and cache.get("text"):
        return TextResult(text=cache["text"], source="ocr", pages=int(cache.get("pages", 0)))

    if client is None:
        return TextResult(source="needs_ocr", error="OCR disabled (--no-ocr)")

    try:
        images = _page_images(data, kind)
    except NoPageImage as e:
        err = native_err if kind == "pdf" and native_err else str(e)
        return TextResult(source="failed", error=f"no page image: {err}")
    except Exception as e:  # noqa: BLE001
        return TextResult(source="failed", error=f"{type(e).__name__}: {e}")

    page_texts: list[str] = []
    last_err = ""
    for image in images:
        try:
            page_texts.append(_ocr_page_lines(client, image))
        except Exception as e:  # noqa: BLE001 - one bad page must not kill the doc
            last_err = f"{type(e).__name__}: {e}"
    text = "\n".join(t for t in page_texts if t).strip()
    if not text:
        return TextResult(source="failed", error=last_err or "OCR produced no text")
    _write_json(_cache_path(sha), {"pages": len(images), "text": text})
    return TextResult(text=text, source="ocr", pages=len(images))


def make_textract_client(profile: str, region: str):
    import boto3

    session = boto3.Session(profile_name=profile or None, region_name=region)
    return session.client("textract")


# --- Phase 1: classification heuristics --------------------------------------

_YEAR_TOKEN = re.compile(r"(?<![\d])(20\d{2})(?![\d,.])")

_EXPLICIT_YEAR_RES = [
    re.compile(r"(?i)(?:tax\s+year|year\s+ended|for\s+(?:the\s+)?year|for\s+(?:the\s+)?tax\s+year)\D{0,15}(20\d{2})(?![\d,.])"),
    re.compile(r"(?i)(?:taxable|calendar)\s+year\D{0,15}(20\d{2})(?![\d,.])"),   # state returns (VA etc.)
    re.compile(r"(?i)\b12[/\-.]31[/\-. ]*(20\d{2})(?![\d,.])"),   # paystub YTD end date
    re.compile(r"(?i)\bdec(?:ember)?[/\-. ]\s*31[\s,]*(20\d{2})(?![\d,.])"),
]
_FORM_ADJ_RES = [
    re.compile(r"(?i)\b(20\d{2})(?![\d,.])\s*[-]?\s*(?:W[- ]?2\b|1099\b|1095\b|3922\b|1040\b|wage and tax)"),
    re.compile(r"(?i)(?:W[- ]?2|1099|1095|3922|1040)[ :#.\-]{0,6}(20\d{2})(?![\d,.])"),
    re.compile(r"(?i)(?:W[- ]?2|1099|1095|3922|1040)\s*\(\s*(20\d{2})\s*\)"),   # "Form 1040 (2010)"
    re.compile(r"(?i)wage(?:s)?\s+and\s+tax\s+statement\D{0,12}(20\d{2})(?![\d,.])"),
    re.compile(r"(?i)(?:1099|1095)[-\s]?(?:int|div|b|nec|misc|r|c)\b\D{0,14}(20\d{2})(?![\d,.])"),
    re.compile(r"(?i)individual\s+income\s+tax\s+return\D{0,14}(20\d{2})(?![\d,.])"),
]
_DATE_PREFIX = re.compile(r"^(\d{4})(\d{2})(\d{2})\b")


def detect_year(text: str, filename: str, folder: str) -> tuple[int | None, str, list[str]]:
    """(year, method, evidence). Priority: text-explicit > text-form
    > text-frequency > folder name > filename (per plan Phase 1)."""
    hits: list[str] = []
    for rx in _EXPLICIT_YEAR_RES:
        m = rx.search(text)
        if m and YEAR_MIN <= int(m.group(1)) <= YEAR_MAX:
            hits.append(m.group(0)[:60])
            return int(m.group(1)), "text-explicit", hits
    for rx in _FORM_ADJ_RES:
        m = rx.search(text)
        if m and YEAR_MIN <= int(m.group(1)) <= YEAR_MAX:
            hits.append(m.group(0)[:60])
            return int(m.group(1)), "text-form", hits
    counts = Counter(y for y in _YEAR_TOKEN.findall(text) if YEAR_MIN <= int(y) <= YEAR_MAX)
    if counts:
        year = int(counts.most_common(1)[0][0])
        top = dict(sorted(counts.items(), key=lambda kv: -kv[1])[:3])
        hits.append(f"freq={top}")
        return year, "text-freq", hits
    m = re.match(r"^(20\d{2})", folder or "")
    if m:
        hits.append(f"folder={folder}")
        return int(m.group(1)), "folder", hits
    stem = Path(filename).stem
    dm = _DATE_PREFIX.match(stem)
    if dm:
        y, mo = int(dm.group(1)), int(dm.group(2))
        # Jan-Apr statements (issued early the next year) belong to the prior
        # tax year; Jun-Dec belong to that same year.
        year = y - 1 if mo <= 4 else y
        if YEAR_MIN <= year <= YEAR_MAX:
            hits.append(f"filename-date={stem[:12]} (month {mo:02d})")
            return year, "filename", hits
    for tok in _YEAR_TOKEN.findall(stem):
        year = int(tok)
        if YEAR_MIN <= year <= YEAR_MAX:
            hits.append(f"filename={stem}")
            return year, "filename", hits
    return None, "none", hits


def detect_person(text: str, filename: str) -> str | None:
    low = f"{text}\n{filename.replace('_', ' ').replace('-', ' ')}".lower()
    found = [name for name in _HOUSEHOLD_NAMES if name.lower() in low]
    if len(found) == 2 or re.search(r"(?i)\b(joint|wros|tod)\b", low):
        return "Joint"
    return found[0] if found else None


def detect_copy_tag(text: str, filename: str) -> str | None:
    m = (re.search(r"(?i)\bcopy\s*([abcd1-4])\b", filename)
         or re.search(r"(?i)\bcopy\s*([abcd1-4])\b", text))
    return m.group(1).upper() if m else None


_BRANDS = [
    "Fidelity", "Charles Schwab", "Schwab", "Vanguard", "Navy Federal",
    "Bank of America", "Wells Fargo", "Chase", "JPMorgan", "USAA", "Discover",
    "Capital One", "Booz Allen", "Inova", "Northrop Grumman", "Lockheed Martin",
    "Raytheon", "General Dynamics", "Morgan Stanley", "E*Trade", "DFAS",
]
_BROKERAGE = {"fidelity", "charles schwab", "schwab", "vanguard", "morgan stanley", "e*trade"}


def guess_payer(form_value: str, text: str, filename: str) -> str | None:
    """Best-effort employer/payer for the destination filename; None is fine
    (the fallback keeps the cleaned original stem). Filename brands win over
    text brands — the user's own naming beats content scanning."""
    low_text = text.lower()
    low_name = filename.lower().replace("_", " ").replace("-", " ")
    for brand in _BRANDS:
        if brand.lower() in low_name:
            return brand
    for brand in _BRANDS:
        if brand.lower() in low_text:
            return brand
    m = re.search(r"(?im)^\s*(?:employer'?s|payer'?s)\s+name\b[,:;. ]*(\S.{2,60})$", text)
    if m:
        val = re.split(r"(?i)\b(address|zip|city|state)\b", m.group(1))[0]
        val = re.sub(r"\s+", " ", val).strip(" ,.-")
        if len(val) >= 3 and not re.match(r"(?i)^(none|n/?a|same)$", val):
            return val.title()[:40]
    return None


def route_category(form_value: str, text: str, filename: str, org_dirs: set[str],
                   note: str = "") -> tuple[str, str]:
    """(category, note) for a NEW file. Mirrors the plan's category map."""
    low = f"{text}\n{filename.replace('_', ' ').replace('-', ' ')}".lower()
    # Reference material — the classifier's own decision wins when present;
    # otherwise scope the match to filename/title area (real forms carry the
    # word "instructions" in their reverse-side boilerplate).
    fname_low = filename.replace("_", " ").replace("-", " ").lower()
    title_low = text[:300].lower()
    if "instructions-like text" in note:
        # form evidence won in the classifier — only hard reference signals
        # (an instructions/publication filename or an IRS publication title)
        # may still route to the reference shelf.
        if (re.search(r"(?i)(?:^|[\d\s_\-])instr|instructions", fname_low)
                or re.search(r"(?i)\bpublication\b", title_low)):
            return "_Reference_and_NonTax", "reference material"
    elif "reference material" in note:
        return "_Reference_and_NonTax", "reference material"
    elif (re.search(r"(?i)(?:^|[\d\s_\-])instr|instructions", fname_low)
            or re.search(r"(?i)\bpublication\b|instructions\s+(?:for|form)|\binstructions\s*\(", title_low)):
        # note: no bare irs.gov trigger — every form prints "www.irs.gov".
        return "_Reference_and_NonTax", "reference material"
    if form_value in ("W-2", "1099-NEC", "Paystub"):
        return "Income", ""
    if form_value in ("1099-DIV", "1099-B", "3922"):
        return "Investments", ""
    if form_value == "1099-INT":
        broker = any(b in low for b in _BROKERAGE) or "consolidated" in low
        return ("Investments", "brokerage 1099-INT") if broker else ("Income", "")
    if form_value == "1099-R" or re.search(r"(?i)\b1099-?r\b", low):
        return "Income", "1099-R (retirement)"
    if re.search(r"(?i)\b1098-?t\b", low):
        return "Other", "1098-T (tuition statement)"
    if form_value in ("1040", "IL-1040") or re.search(r"(?i)income\s+tax\s+return", low):
        return "Returns", ""
    if form_value == "1095-C" or re.search(r"(?i)1095-?b|5498-?sa|1099-?sa|health\s+savings", low):
        # 2023/2024 already use "Health_Coverage"; plan canonical is Health_and_HSA.
        return ("Health_Coverage" if "Health_Coverage" in org_dirs else "Health_and_HSA"), ""
    if re.search(r"(?i)(personal\s+property|real\s+estate)\s+tax", low):
        return "Property", ""
    if re.search(r"(?i)\bdrill\b|military|national\s+guard|gi\s+bill|ebenefits|reserv(e|ist)\b", low):
        return "Military_Income", ""
    if re.search(r"(?i)1040-?es\b|760-?es\b|estimated\s+tax", low):
        return "Estimated_Payments", ""
    if re.search(r"(?i)schedule\s+c\b|profit\s+or\s+loss\s+from\s+business", low):
        return "Business_Expenses", ""
    if "1099-b" in low or "proceeds from broker" in low:
        return "Investments", "1099-B by keyword"
    return "Other", ""


def classify_candidate(rec: FileRec, client, password: str | None = None) -> dict:
    """One candidate -> classification row (status CLASSIFIED/UNCLASSIFIED/
    UNREADABLE/NEEDS_OCR + form/year/person/payer/copy-tag)."""
    out = {
        "relpath": rec.relpath,
        "folder": rec.folder,
        "sha256": rec.sha256,
        "size": rec.size,
        "kind": rec.kind,
        "status": "UNREADABLE",
        "text_source": "none",
        "chars": 0,
        "form_type": None,
        "form_effective": None,
        "year": None,
        "year_method": "none",
        "year_evidence": [],
        "person": None,
        "payer": None,
        "copy_tag": None,
        "note": "",
        "error": "",
    }
    path = DUMP_ROOT / rec.relpath
    try:
        data = path.read_bytes()
    except OSError as e:
        out["error"] = f"read failed: {type(e).__name__}: {e}"
        return out

    res = acquire_text(data, rec.kind, rec.sha256, client, password)
    out["text_source"] = res.source
    out["chars"] = len(res.text)
    if res.source == "needs_ocr":
        out["status"] = "NEEDS_OCR"
        return out
    if res.source == "failed" or len(res.text.strip()) < 20:
        out["status"] = "UNREADABLE"
        out["error"] = res.error or f"text too short ({len(res.text.strip())} chars)"
        return out

    kvs = res.kvs or [ExtractedKV(key="__native_text__", value=res.text,
                                  confidence=0.6 if res.source == "ocr" else 1.0)]
    form = classify_form(kvs)
    low = res.text.lower()

    # Strong specific-form evidence: title adjacency or dense mentions. A
    # consolidated container wins first (Fidelity statements cite every
    # sub-form they contain); the rest follow classify_form's own ladder.
    strong = None  # (FormType, label)
    if "consolidated" in low:
        strong = (FormType.f1099_div, "consolidated statement")
    else:
        for marker, ft in (
            ("1099-int", FormType.f1099_int),
            ("1099-div", FormType.f1099_div),
            ("1099-r", FormType.f1099_r),
            ("1099-nec", FormType.f1099_nec),
            ("1095-c", FormType.f1095_c),
            ("3922", FormType.f3922),
        ):
            if f"form {marker}" in low or low.count(marker) >= 3:
                strong = (ft, marker)
                break
    w2_strong = ("wage and tax statement" in low
                 or ("wages, tips" in low and "federal income tax withheld" in low)
                 or low.count("w-2") + low.count("w2") >= 4
                 or "employer identification number" in low)
    state_return_marker = ("department of taxation" in low
                           or ("virginia" in low and "income tax" in low))

    # Weak-1040 guard: classify_form's 1040 branch also fires on the loose
    # ("1040" + "department of the treasury") combination, which full-text
    # input (vs the app's KV corpora) trips constantly — bank 1099-INTs cite
    # Form 1040 and even echo "adjusted gross income" on their reverse-side
    # instructions. Keep 1040 only with real return evidence; otherwise prefer
    # strong/weak specific-form markers.
    #
    # A REAL RETURN beats every specific-form marker: e-file packages embed
    # the very 1099s/3922s they report (so the baseline may even come back as
    # 3922 or 1099-DIV). The 1040's own OMB number (1545-0074) is printed on
    # every genuine 1040 page and on no other form.
    real_return = ("1545-0074" in low
                   or ("adjusted gross income" in low
                       and "u.s. individual income tax return" in low))
    if real_return and form not in (FormType.f1040, FormType.f1040_il):
        il_package = "illinois" in low and "income tax" in low
        out["note"] = f"return package (OMB 1545-0074) overrode '{form.value}'"
        form = FormType.f1040_il if il_package else FormType.f1040
    if form is FormType.f1040 and not real_return:
        if strong is not None:
            out["note"] = f"1040 lookalike overridden by '{strong[1]}'"
            form = strong[0]
        else:
            weak = None
            for marker, ft in (
                ("1095-c", FormType.f1095_c),
                ("3922", FormType.f3922),
                ("1099-nec", FormType.f1099_nec),
                ("nonemployee compensation", FormType.f1099_nec),
                ("1099-div", FormType.f1099_div),
                ("1099-int", FormType.f1099_int),
                ("1098-t", FormType.other),
                ("wage and tax statement", FormType.w2),
            ):
                if marker in low:
                    weak = (ft, marker)
                    break
            if weak is not None:
                out["note"] = f"1040 lookalike overridden by '{weak[1]}'"
                form = weak[0]
            else:
                out["note"] = "weak 1040 evidence (no AGI/title; likely a cross-reference or pub)"
    if form is FormType.f1040_il and strong is not None and not real_return:
        # The back of a 1099 mentions Illinois income tax and trips the IL
        # branch; a strong specific-form marker means it is that form's page.
        out["note"] = f"IL-1040 lookalike overridden by '{strong[1]}'"
        form = strong[0]

    # Weak-W-2 guard: a stray "w-2" mention inside a state return (or its
    # instructions) must not become a W-2. A real W-2 carries its own title or
    # the structural box pair; a state-form document says "Department of
    # Taxation" (a federal W-2 never does).
    if form is FormType.w2:
        if state_return_marker and not w2_strong:
            out["note"] = "W-2 lookalike: weak w-2 mention inside a state return"
            form = FormType.unknown
        elif state_return_marker and w2_strong and "760" in low:
            # VA 760 instructions discuss W-2 boxes at length — still not a W-2.
            out["note"] = "W-2 lookalike: Virginia form instructions"
            form = FormType.unknown

    # Reference material (IRS pubs / instruction booklets). Scoped to the
    # filename and title area, and suppressed when the document carries its
    # own specific-form evidence — a W-2's "Notice to Employee" page or a
    # 1099's instruction-heavy back side is part of that form, not a pub.
    fname_low = Path(rec.relpath).name.lower().replace("_", " ").replace("-", " ")
    title_area = res.text[:300].lower()
    reference_hit = (re.search(r"(?i)(?:^|[\d\s_\-])instr|instructions", fname_low)
                     or re.search(r"(?i)\bpublication\b|instructions\s+(?:for|form)|\binstructions\s*\(", title_area))
    # Any specific-form token (even a single mention) means the document is
    # form page(s) — its instruction-heavy sides belong to the form, not to
    # the reference shelf.
    form_token = re.search(r"(?i)\b1099\b|\b1098\b|\bw-2\b|\bw2\b|\b1095\b|\b3922\b|wage and tax statement", low)
    if reference_hit and (strong or form_token or w2_strong):
        out["note"] = (out["note"] + "; " if out["note"] else "") + "instructions-like text (form evidence wins)"
    elif reference_hit:
        out["note"] = (out["note"] + "; " if out["note"] else "") + "reference material"

    # Container override: consolidated brokerage statements mention 3922
    # (ESPP) and would classify as a bare 3922 before the consolidated branch
    # is reached. Route them as the DIV container they actually are.
    if form is FormType.f3922 and ("consolidated" in low or ("1099-div" in low and "1099-b" in low)):
        out["note"] = (out["note"] + "; " if out["note"] else "")
        out["note"] += "3922 mention inside a consolidated statement; routed as 1099-DIV container"
        form = FormType.f1099_div

    year, method, evidence = detect_year(res.text, rec.relpath, rec.folder)
    folder_year = None
    m = re.match(r"^(20\d{2})", rec.folder)
    if m:
        folder_year = int(m.group(1))
    if folder_year and year and year != folder_year:
        out["note"] = (out["note"] + "; " if out["note"] else "")
        out["note"] += f"year disagreement: text={year} vs folder={folder_year}"

    out.update(
        status="CLASSIFIED" if form is not FormType.unknown else "UNCLASSIFIED",
        form_type=form.value if form is not FormType.unknown else None,
        form_effective=form.value,
        year=year,
        year_method=method,
        year_evidence=evidence,
        person=detect_person(res.text, Path(rec.relpath).name),
        payer=guess_payer(form.value, res.text, Path(rec.relpath).name),
        copy_tag=detect_copy_tag(res.text, Path(rec.relpath).name),
        # routing keyword source (keep artifacts bounded)
        text_excerpt=res.text[:3000],
    )
    return out


def _candidate_order(folder: str) -> tuple[int, str]:
    """Year folders first (so within-dump dupes keep the year-folder copy),
    then archive, then other."""
    if re.match(r"^(20\d{2})", folder):
        return (0, folder)
    return (1 if folder == "archive" else 2, folder)


def cmd_classify(args: argparse.Namespace) -> None:
    manifest = _read_json(ART_DIR / "manifest_dump.json")
    if manifest is None:
        sys.exit("run `manifest` first")
    recs = [FileRec(**r) for r in manifest if r["status"] == "candidate"]
    recs.sort(key=lambda r: (_candidate_order(r.folder), r.relpath))
    if args.limit:
        recs = recs[: args.limit]

    rows: list[dict] = _read_json(ART_DIR / "classification.json", default=[])
    if args.recheck_unreadable:
        rows = [r for r in rows if r["status"] not in ("UNREADABLE", "NEEDS_OCR")]
        _write_json(ART_DIR / "classification.json", rows)
    if args.recheck_suspect:
        # Re-decide rows the earlier heuristics flagged ambiguously: reference
        # material hits, IL-1040 lookalikes, W-2s (the guard changed), and
        # weak-1040 evidence. Their OCR/native text is cached, so this is fast.
        def _suspect(r: dict) -> bool:
            note = r.get("note") or ""
            return ("reference material" in note
                    or "instructions-like text" in note
                    or "weak 1040 evidence" in note
                    or "3922 mention inside" in note
                    or r.get("form_effective") in ("IL-1040", "W-2"))
        before = len(rows)
        rows = [r for r in rows if not _suspect(r)]
        _write_json(ART_DIR / "classification.json", rows)
        print(f"recheck-suspect: dropped {before - len(rows)} rows for re-decision")
    done = {r["sha256"]: r for r in rows}
    todo = [r for r in recs if r.sha256 not in done]
    print(f"candidates: {len(recs)} | already classified: {len(recs) - len(todo)} | todo: {len(todo)}")

    client = None
    if not args.no_ocr and todo:
        try:
            client = make_textract_client(args.aws_profile, args.region)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"could not create Textract client ({type(e).__name__}: {e}); "
                     "re-run with --no-ocr to classify text-layer files only")

    started = datetime.now()
    ocr_calls = 0
    for i, rec in enumerate(todo, 1):
        row = classify_candidate(rec, client, args.pdf_password or None)
        if row["text_source"] == "ocr" and rec.sha256 not in done:
            ocr_calls += 1
        rows.append(row)
        if i % 25 == 0 or i == len(todo):
            rate = (datetime.now() - started).total_seconds() / max(i, 1)
            print(f"  {i}/{len(todo)} classified ({rate:.1f}s/file, ~{ocr_calls} OCR docs)")
            _write_json(ART_DIR / "classification.json", rows)  # checkpoint (resumable)
    _write_json(ART_DIR / "classification.json", rows)

    by_status = Counter(r["status"] for r in rows)
    by_form = Counter(r["form_effective"] for r in rows if r["status"] == "CLASSIFIED")
    print(f"status: {dict(by_status)}")
    print(f"forms : {dict(by_form)}")
    elapsed = (datetime.now() - started).total_seconds()
    print(f"done in {elapsed:.0f}s | artifacts -> {ART_DIR / 'classification.json'}")

    # The backlog dividend hunt: any 2025 1099-DIV/1099-B candidate, loudly.
    hunt = [r for r in rows if r["status"] == "CLASSIFIED"
            and r["form_effective"] in ("1099-DIV", "1099-B")
            and (r["year"] == 2025 or (r["year"] is None and r["folder"] in ("archive", "other", "2026")))]
    print("\n=== 2025 1099-DIV hunt (backlog item 2) ===")
    if hunt:
        for r in hunt:
            print(f"  HIT: {r['relpath']} -> {r['form_effective']} year={r['year']} "
                  f"person={r['person']} payer={r['payer']} note={r['note']}")
    else:
        print("  MISS: no 2025-dividend candidate found in this pass. "
              "The ~$3,863 ordinary / ~$278 qualified gap remains unexplained by the dump; "
              "the statement must come from the source (Fidelity -> 2025 tax forms, all "
              "accounts, or Sara's brokerage).")

    _write_classification_md(rows)
    print(f"human report -> {ART_DIR / 'classification_report.md'}")


def _write_classification_md(rows: list[dict]) -> None:
    lines = [
        "# Dump classification report (Phase 1)",
        "",
        f"Generated {_ts()}. {len(rows)} candidates classified.",
        "",
        "| # | file | form | year | person | payer | copy | src | note |",
        "|---|------|------|------|--------|-------|------|-----|------|",
    ]
    for i, r in enumerate(rows, 1):
        name = r["relpath"].split("/")[-1]
        folder = r["folder"]
        note = r.get("note") or r.get("error") or ""
        lines.append(
            f"| {i} | {folder}/{name} | {r['form_effective'] or '-'} | {r['year'] or '-'} "
            f"| {r['person'] or '-'} | {(r['payer'] or '-').replace('|', '/')} "
            f"| {r['copy_tag'] or '-'} | {r['text_source']} | {note.replace('|', '/')} |"
        )
    lines += ["", "## 2025 1099-DIV hunt (backlog item 2)", ""]
    hunt = [r for r in rows if r["status"] == "CLASSIFIED"
            and r["form_effective"] in ("1099-DIV", "1099-B")
            and (r["year"] == 2025 or (r["year"] is None and r["folder"] in ("archive", "other", "2026")))]
    if hunt:
        for r in hunt:
            lines.append(f"- **HIT** `{r['relpath']}` -> {r['form_effective']}, year={r['year']}, "
                         f"person={r['person']}, payer={r['payer']}")
    else:
        lines.append("- **MISS** — no 2025 dividend candidate in the dump; the ~$3,863 / ~$278 "
                     "gap must come from the source (Fidelity 2025 tax forms, all accounts, or "
                     "Sara's brokerage).")
    _md_write(ART_DIR / "classification_report.md", "\n".join(lines) + "\n")


# --- Phase 2: routing plan (dry-run) and apply -------------------------------

_FORM_SLUG = {
    "W-2": "W2", "1099-INT": "1099-INT", "1099-DIV": "1099-DIV",
    "1099-B": "1099-B", "1099-NEC": "1099-NEC", "1095-C": "1095-C",
    "3922": "Form_3922", "1040": "1040", "IL-1040": "IL-1040",
    "Paystub": "Paystub", "1099-MISC": "1099-MISC", "1099-R": "1099-R",
}

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _slug(value: str, cap: int = 48) -> str:
    value = _ILLEGAL.sub(" ", value)
    value = re.sub(r"[\s]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_-")
    return value[:cap].strip("_-")


def dest_ext(kind: str) -> str:
    if kind == "pdf":
        return ".pdf"
    if kind in ("png", "tiff"):
        return ".png"   # TIFF converts to PNG at copy time
    if kind == "jpeg":
        return ".jpg"
    return ".pdf"


def build_filename(row: dict) -> str:
    """Corpus naming conventions: W2_<person>_<employer>_<year>[_Copy_X],
    <form>_<payer>_<person>_<year>, else cleaned original stem."""
    stem = _slug(Path(row["relpath"]).stem)
    ext = dest_ext(row["kind"])
    year_s = str(row["year"]) if row["year"] else None
    person = row.get("person")
    payer = row.get("payer")
    form = row.get("form_effective")
    slug = _FORM_SLUG.get(form) if form else None

    def _stem_informative() -> bool:
        """A stem worth carrying into the new name: not numeric mush, and it
        must not already contain the year segment."""
        if not stem or len(stem) < 4:
            return False
        if stem.lower() in ("document", "scan", "p3", "untitled", "download"):
            return False
        if stem.replace("_", "").replace("-", "").isdigit():
            return False
        if year_s and year_s in stem:
            return False
        return True

    if slug == "W2":
        segs = ["W2"]
        if person:
            segs.append(person)
        if payer:
            segs.append(_slug(payer, 40))
        elif _stem_informative():
            segs.append(stem[:40])
        if year_s and year_s not in segs:
            segs.append(year_s)
        if row.get("copy_tag"):
            segs.append(f"Copy_{row['copy_tag']}")
    elif slug:
        # Returns never carry a payer segment (a 1040 cites banks; that is
        # not the filer's "payer" in the naming sense).
        use_payer = payer if slug not in ("1040", "IL-1040") else None
        segs = [slug]
        if use_payer:
            segs.append(_slug(use_payer, 40))
        elif _stem_informative():
            segs.append(stem[:40])
        if person and (not segs[-1] or person.lower() != segs[-1].lower()):
            segs.append(person)
        if year_s and year_s not in segs:
            segs.append(year_s)
    else:
        segs = [stem or "document"]
        if person and person.lower() not in segs[0].lower():
            segs.append(person)
        if year_s and year_s not in segs[0]:
            segs.append(year_s)
    # case-insensitive segment dedupe, preserving order
    seen: set[str] = set()
    deduped = []
    for seg in segs:
        key = seg.lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(seg)
    return "_".join(deduped) + ext


def _norm_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio()


def _organized_text(rec: dict, client) -> str:
    """Text of an Organized-tree file (native first, cached OCR fallback)."""
    path = ORG_ROOT / rec["relpath"]
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    res = acquire_text(data, rec["kind"], rec["sha256"], client)
    return res.text


def _org_maps(org: list[FileRec]) -> tuple[dict[str, list[str]], dict[str, list[dict]], set[str]]:
    by_sha: dict[str, list[str]] = {}
    by_base: dict[str, list[dict]] = {}
    prefixes: set[str] = set()
    for r in org:
        by_sha.setdefault(r.sha256, []).append(r.relpath)
        base = Path(r.relpath).name.lower()
        by_base.setdefault(base, []).append({"relpath": r.relpath, "kind": r.kind, "sha256": r.sha256})
        parts = r.relpath.split("/")
        if len(parts) >= 2:
            prefixes.add("/".join(parts[:2]))
    return by_sha, by_base, prefixes


def cmd_dry_run(args: argparse.Namespace) -> None:
    dump = _read_json(ART_DIR / "manifest_dump.json")
    if dump is None:
        sys.exit("run `manifest` first")
    # Organized is re-walked FRESH every time — it changes between runs
    # (apply copies into it), and a stale manifest double-proposes files.
    org = _walk_tree(ORG_ROOT, triage=False)
    _write_json(ART_DIR / "manifest_organized.json", [asdict(r) for r in org])
    rows = _read_json(ART_DIR / "classification.json", default=[])
    if not rows:
        sys.exit("run `classify` first")

    applied = _read_json(ART_DIR / "applied.json", default=[])
    applied_shas = {a["sha256"] for a in applied}

    org_recs = org  # _walk_tree already returns FileRec objects
    org_by_sha, org_by_base, org_prefixes = _org_maps(org_recs)

    client = None
    if not args.no_ocr:
        try:
            client = make_textract_client(args.aws_profile, args.region)
        except Exception as e:  # noqa: BLE001
            print(f"warning: no Textract client ({type(e).__name__}: {e}); "
                  "name-collision variants may go unverified")

    seen: set[str] = set()          # dump shas handled so far (in-tree dupes)
    first_rel: dict[str, str] = {}  # sha -> first-seen relpath (the "kept" copy)
    used_dest: set[str] = set()     # destination relpaths claimed by this plan
    actions: list[dict] = []
    duplicates: list[dict] = []
    dup_in_dump: list[dict] = []
    variants: list[dict] = []
    variant_maybe: list[dict] = []
    unaccounted: list[dict] = []
    web_assets: list[dict] = []
    already_applied: list[dict] = []

    ordered = sorted(rows, key=lambda r: (_candidate_order(r["folder"]), r["relpath"]))
    for row in ordered:
        rel, sha = row["relpath"], row["sha256"]
        if sha in seen:
            dup_in_dump.append({"relpath": rel, "kept": first_rel.get(sha, "")})
            continue
        seen.add(sha)
        first_rel[sha] = rel

        # Anything already copied by a previous `apply` is never re-proposed
        # (sha alone cannot catch decrypted copies, hence the ledger).
        if sha in applied_shas:
            already_applied.append({"relpath": rel})
            continue

        # Saved-web-page asset folders ("*_files/") are browser junk that
        # happens to carry .jpg/.png extensions — never tax documents.
        if "_files/" in rel:
            web_assets.append({"relpath": rel})
            continue

        if sha in org_by_sha:
            duplicates.append({"relpath": rel, "matches": org_by_sha[sha]})
            continue

        if row["status"] in ("UNREADABLE", "NEEDS_OCR") or (
            row["status"] == "UNCLASSIFIED" and not row["year"]
        ):
            unaccounted.append({"relpath": rel, "status": row["status"],
                                "reason": row.get("error") or row.get("note") or "no tax year detected"})
            continue

        # Basename collision -> verify by text similarity before calling it new.
        base = Path(rel).name.lower()
        collisions = org_by_base.get(base, [])
        if collisions:
            my_res = None
            try:
                my_res = acquire_text((DUMP_ROOT / rel).read_bytes(), row["kind"], sha, client)
            except OSError:
                pass
            my_text = my_res.text if my_res else ""
            best: dict | None = None
            best_ratio = 0.0
            best_text_missing = False
            for c in collisions:
                other_text = _organized_text(c, client)
                if not other_text:
                    best_text_missing = True
                    continue
                ratio = _similarity(my_text, other_text)
                if ratio > best_ratio:
                    best, best_ratio = c, ratio
            if best and best_ratio >= args.threshold:
                variants.append({"relpath": rel, "matches": best["relpath"],
                                 "ratio": round(best_ratio, 3)})
                continue
            if best and best_ratio >= args.threshold - 0.10:
                variant_maybe.append({"relpath": rel, "matches": best["relpath"],
                                      "ratio": round(best_ratio, 3),
                                      "threshold": args.threshold})
                continue
            if best_text_missing and best is None:
                variant_maybe.append({"relpath": rel, "matches": collisions[0]["relpath"],
                                      "ratio": None, "threshold": args.threshold,
                                      "note": "organized side has no readable text; needs manual review"})
                continue
            # else: genuinely new — fall through to routing.

        # NEW -> propose destination.
        category, cat_note = route_category(
            row["form_effective"] or "", row.get("text_excerpt") or "", Path(rel).name, org_prefixes,
            row.get("note") or "",
        )
        if row["status"] == "UNCLASSIFIED":
            cat_note = "; ".join(x for x in ("unclassified form; routed by content keywords", cat_note) if x)
        filename = build_filename(row)
        year_dir = str(row["year"]) if row["year"] else "undated"
        if category == "_Reference_and_NonTax":
            dest_dir = "_Reference_and_NonTax"
        else:
            dest_dir = f"{year_dir}/{category}"
        candidate = f"{dest_dir}/{filename}"
        final = candidate
        n = 2
        stem, ext = Path(candidate).stem, Path(candidate).suffix
        while final in used_dest or (ORG_ROOT / final).is_file():
            final = f"{dest_dir}/{stem}_{n}{ext}"
            n += 1
        used_dest.add(final)
        actions.append({
            "relpath": rel,
            "sha256": sha,
            "form": row["form_effective"],
            "year": row["year"],
            "person": row["person"],
            "payer": row["payer"],
            "copy_tag": row["copy_tag"],
            "dest_rel": final,
            "convert_tif": row["kind"] == "tiff",
            "note": "; ".join(x for x in (row.get("note") or "", cat_note) if x),
        })

    counts = {
        "actions_new": len(actions),
        "already_applied": len(already_applied),
        "duplicates_exact": len(duplicates),
        "duplicates_within_dump": len(dup_in_dump),
        "variants_confirmed": len(variants),
        "variants_need_review": len(variant_maybe),
        "unaccounted": len(unaccounted),
        "web_assets": len(web_assets),
    }
    holds = [{"relpath": r["relpath"], "ext": r["ext"], "size": r["size"]}
             for r in dump if r["status"] == "hold"]
    plan = {
        "generated_at": _ts(),
        "threshold": args.threshold,
        "dump_root": str(DUMP_ROOT),
        "organized_root": str(ORG_ROOT),
        "counts": counts,
        "actions": actions,
        "duplicates": duplicates,
        "dup_in_dump": dup_in_dump,
        "variants": variants,
        "variant_maybe": variant_maybe,
        "unaccounted": unaccounted,
        "web_assets": web_assets,
        "already_applied": already_applied,
        "holds": holds,
        "div_hunt": [
            {k: r.get(k) for k in ("relpath", "form_effective", "year", "person", "payer", "note")}
            for r in rows
            if r["status"] == "CLASSIFIED" and r["form_effective"] in ("1099-DIV", "1099-B")
            and (r["year"] == 2025 or (r["year"] is None and r["folder"] in ("archive", "other", "2026")))
        ],
    }
    _write_json(ART_DIR / "dry_run.json", plan)
    print(f"plan: {counts}")
    print(f"-> {ART_DIR / 'dry_run.json'} (review it, then run `apply --yes`)")
    _write_dry_run_md(plan)


def _write_dry_run_md(plan: dict) -> None:
    c = plan["counts"]
    lines = [
        "# Dry-run routing plan (Phase 2) — copy only, nothing applied yet",
        "",
        f"Generated {plan['generated_at']} | similarity threshold {plan['threshold']}",
        "",
        f"- NEW (to copy): **{c['actions_new']}**",
        f"- exact duplicates of Organized files (report only): {c['duplicates_exact']}",
        f"- duplicates within the dump (report only): {c['duplicates_within_dump']}",
        f"- confirmed name/byte variants of Organized files (report only): {c['variants_confirmed']}",
        f"- variant candidates needing review (not routed): {c['variants_need_review']}",
        f"- unaccounted (UNREADABLE/NEEDS_OCR/UNCLASSIFIED): {c['unaccounted']}",
        f"- HOLD extension files (xps/xls/csv/docx — decision pending): {len(plan['holds'])}",
        "",
        "## Proposed copies (dump -> Organized)",
        "",
        "| dump file | -> destination | form | yr | person | note |",
        "|-----------|----------------|------|----|--------|------|",
    ]
    for a in plan["actions"]:
        lines.append(
            f"| {a['relpath']} | {a['dest_rel']} | {a['form'] or '-'} "
            f"| {a['year'] or '-'} | {a['person'] or '-'} | {(a['note'] or '').replace('|', '/')} |"
        )
    lines += ["", "## Exact duplicates (already in Organized — no action)", ""]
    for d in plan["duplicates"]:
        lines.append(f"- `{d['relpath']}` == {', '.join(f'`{m}`' for m in d['matches'])}")
    lines += ["", "## In-dump duplicates (report only)", ""]
    for d in plan["dup_in_dump"]:
        lines.append(f"- `{d['relpath']}` == `{d['kept']}`")
    lines += ["", "## Confirmed variants (report only)", ""]
    for v in plan["variants"]:
        lines.append(f"- `{v['relpath']}` ~ `{v['matches']}` (text similarity {v['ratio']})")
    lines += ["", "## Variant candidates needing manual review (NOT routed)", ""]
    for v in plan["variant_maybe"]:
        ratio = v.get("ratio")
        lines.append(f"- `{v['relpath']}` ~ `{v['matches']}` "
                     f"(similarity {ratio if ratio is not None else 'n/a - no readable text'}; "
                     f"threshold {v['threshold']})")
    lines += ["", "## Already applied by a previous apply (no action)", ""]
    for a in plan.get("already_applied", []):
        lines.append(f"- `{a['relpath']}`")
    lines += ["", "## Unaccounted candidates", ""]
    for u in plan["unaccounted"]:
        lines.append(f"- `{u['relpath']}` — {u['status']}: {u['reason']}")
    lines += ["", "## Saved-web-page assets (browser junk, no action)", ""]
    for w in plan.get("web_assets", []):
        lines.append(f"- `{w['relpath']}`")
    lines += ["", "## HOLD files (extension triage — decision pending)", ""]
    for h in plan["holds"]:
        lines.append(f"- `{h['relpath']}` ({h['ext']}, {h['size']} bytes)")
    lines += ["", "## 2025 1099-DIV hunt (backlog item 2)", ""]
    if plan["div_hunt"]:
        for r in plan["div_hunt"]:
            lines.append(f"- **HIT** `{r['relpath']}` -> {r['form_effective']}, year={r['year']}, "
                         f"person={r['person']}, payer={r['payer']}")
    else:
        lines.append("- **MISS** — no 2025 dividend candidate found in the dump. The ~$3,863 "
                     "ordinary / ~$278 qualified gap is not explained by anything on disk; pull "
                     "the statement from the source (Fidelity -> 2025 tax forms, all accounts, "
                     "or Sara's brokerage).")
    _md_write(ART_DIR / "dry_run_report.md", "\n".join(lines) + "\n")


def cmd_apply(args: argparse.Namespace) -> None:
    plan = _read_json(ART_DIR / "dry_run.json")
    if plan is None:
        sys.exit("run `dry-run` first (and review its report)")
    actions = plan["actions"]
    if not actions:
        print("nothing to apply — plan has no NEW actions")
        return
    if not args.yes:
        print(f"this would COPY {len(actions)} file(s) into {ORG_ROOT}; "
              "re-run with --yes to execute")
        return

    password = args.pdf_password or None
    results = {"started_at": _ts(), "copied": [], "converted": [], "decrypted": [], "failed": []}
    for a in actions:
        src = DUMP_ROOT / a["relpath"]
        dst = ORG_ROOT / a["dest_rel"]
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if a.get("convert_tif"):
                from PIL import Image

                with Image.open(src) as im:
                    frame = im.convert("L") if im.mode not in ("L", "RGB", "RGBA") else im.copy()
                    frame.save(dst, format="PNG")
                results["converted"].append(a["dest_rel"])
                results["copied"].append(a["dest_rel"])
            elif password:
                data = src.read_bytes()
                dec = decrypted_pdf_bytes(data, password)
                if dec is not None:
                    dst.write_bytes(dec)
                    results["decrypted"].append(a["dest_rel"])
                    results["copied"].append(a["dest_rel"])
                else:
                    shutil.copy2(src, dst)
                    results["copied"].append(a["dest_rel"])
            else:
                shutil.copy2(src, dst)
                results["copied"].append(a["dest_rel"])
        except Exception as e:  # noqa: BLE001
            results["failed"].append({"relpath": a["relpath"], "dest": a["dest_rel"],
                                      "error": f"{type(e).__name__}: {e}"})
    results["finished_at"] = _ts()
    results["summary"] = {"copied": len(results["copied"]),
                          "converted_tif": len(results["converted"]),
                          "decrypted": len(results["decrypted"]),
                          "failed": len(results["failed"])}
    _write_json(ART_DIR / "apply_report.json", results)
    # Ledger of applied sources so future dry-runs never re-propose them
    # (a decrypted copy's sha differs from the dump original's).
    ledger = _read_json(ART_DIR / "applied.json", default=[])
    known = {a["sha256"] for a in ledger}
    failed_rels = {f["relpath"] for f in results["failed"]}
    for a in actions:
        if a["relpath"] in failed_rels:
            continue
        if a["sha256"] not in known:
            ledger.append({"relpath": a["relpath"], "sha256": a["sha256"],
                           "dest_rel": a["dest_rel"], "applied_at": _ts()})
    _write_json(ART_DIR / "applied.json", ledger)
    print(f"copied {len(results['copied'])} (incl. {len(results['converted'])} TIFF->PNG, "
          f"{len(results['decrypted'])} decrypted), failed {len(results['failed'])}")
    print(f"-> {ART_DIR / 'apply_report.json'}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Tax dump reconciliation tooling")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("manifest", help="Phase 0: manifests + triage + overlap")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("classify", help="Phase 1: classify candidates (resumable)")
    p.add_argument("--no-ocr", action="store_true", help="text-layer files only; skip Textract")
    p.add_argument("--limit", type=int, default=0, help="only the first N candidates (smoke test)")
    p.add_argument("--recheck-unreadable", action="store_true",
                   help="drop UNREADABLE/NEEDS_OCR rows first so they are re-processed")
    p.add_argument("--recheck-suspect", action="store_true",
                   help="re-decide reference/IL-1040/W-2/weak-1040 rows with current logic")
    p.add_argument("--pdf-password", default="",
                   help="password for password-protected PDFs (tried before the empty password)")
    p.add_argument("--aws-profile", default="",
                   help="boto3 profile; empty = default credentials chain (the "
                        "asus-tester IAM user lives under [default] here)")
    p.add_argument("--region", default="us-east-1")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("dry-run", help="Phase 2: match + propose copy routing")
    p.add_argument("--threshold", type=float, default=0.85,
                   help="text similarity that confirms a variant duplicate")
    p.add_argument("--no-ocr", action="store_true")
    p.add_argument("--aws-profile", default="",
                   help="boto3 profile; empty = default credentials chain")
    p.add_argument("--region", default="us-east-1")
    p.set_defaults(func=cmd_dry_run)

    p = sub.add_parser("apply", help="Phase 2: execute the approved plan (copies only)")
    p.add_argument("--yes", action="store_true", help="required to actually copy")
    p.add_argument("--pdf-password", default="",
                   help="password for password-protected PDFs (writes decrypted copies)")
    p.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
