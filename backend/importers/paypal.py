"""PayPal PDF statement reader.

Parses the monthly ``statement-<Mon>-2026.pdf`` account-activity PDFs PayPal
exports. These are text-based PDFs, so extraction is pure Python via ``pypdf``
(no OCR / cloud). See the package docstring for why we parse locally.

Statement layout (per transaction), as observed across all 8 months::

    07/05/2026 PreApproved Payment Bill User Payment:
    Apple Services
      USAA FEDERAL SAVINGS BANK -
      Checking x-0000                                         2.99
    USD
    ID: 52U00157F85268330
    USD -2.99 0.00 -2.99

Notes handled here:

* The leading ``MM/DD/YYYY`` date is sometimes wrapped across two lines
  (``07/08/202`` / ``6``); we stitch it back together before parsing.
* Description spans one or more lines between the date and the ``ID:`` line and
  may include a funding-source line (``USAA FEDERAL SAVINGS BANK - ...``) which
  we drop from the display name.
* The ``ID:`` value is a stable per-transaction key -> ``transaction_id``.
* A purchase funded from a linked card is followed by a ``General Credit Card
  Deposit`` whose ``Ref ID:`` points back at the purchase's ``ID:``. That
  deposit offsets the purchase (PayPal pulled the money from the card), so it is
  flagged ``offset=True`` / ``offsets_id=<purchase id>`` and later categorized as
  a transfer rather than counted as income.
* Boilerplate (money-waiting banner, error-resolution paragraphs, page footers,
  repeated headers) contains no ``ID:`` line and is naturally skipped.
"""

from __future__ import annotations

import io
import re

from pypdf import PdfReader

from . import ImportedTxn, StatementReader, register_reader

# Funding source is the linked USAA checking account already tracked in the app.
_ACCOUNT_MASK = "0000"
_BANK = "paypal"
_SOURCE = "paypal_statement"

# MM/DD/YYYY at the start of a transaction block.
_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\b(.*)$")
# A date whose year got wrapped, e.g. "07/08/202" with the trailing "6" on the
# next line.
_DATE_WRAP_RE = re.compile(r"^(\d{2}/\d{2}/\d{3})$")
_ID_RE = re.compile(r"^ID:\s*([A-Za-z0-9]+)\s*$")
_REF_RE = re.compile(r"^Ref ID:\s*([A-Za-z0-9]+)\s*$")
# Value line: "USD -2.99 0.00 -2.99" -> amount fees total.
_VALUE_RE = re.compile(
    r"^USD\s+(-?\d[\d,]*\.\d{2})\s+(-?\d[\d,]*\.\d{2})\s+(-?\d[\d,]*\.\d{2})\s*$"
)
_FUNDING_RE = re.compile(r"FEDERAL SAVINGS BANK|Checking x-|^\s*USD\s*$", re.IGNORECASE)
# Page-footer boilerplate that can bleed into the last transaction's description
# block on a page ("ACCOUNT STATEMENTS doe, john Page 1"). Anything from
# this marker onward in a description is dropped.
_FOOTER_RE = re.compile(r"ACCOUNT STATEMENTS", re.IGNORECASE)


def _unwrap_dates(lines: list[str]) -> list[str]:
    """Rejoin dates split across two lines (``07/08/202`` + ``6`` -> one line).

    The wrapped remainder is a lone digit (the last year digit). We merge it back
    onto the preceding partial date so the block-splitter sees a clean
    ``MM/DD/YYYY`` prefix.
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        m = _DATE_WRAP_RE.match(line.strip())
        if m and i + 1 < len(lines) and re.fullmatch(r"\d", lines[i + 1].strip()):
            out.append(m.group(1) + lines[i + 1].strip())
            i += 2
            continue
        out.append(line)
        i += 1
    return out


def _clean_name(desc_lines: list[str]) -> str:
    """Collapse a transaction's description lines into a single display name.

    Drops the funding-source line and the bare trailing amount PayPal prints
    beside it, then joins the remainder into one whitespace-normalized string.
    """
    parts: list[str] = []
    for ln in desc_lines:
        s = ln.strip()
        if not s:
            continue
        # Drop the page footer and anything after it (it bleeds into the last
        # transaction on a page).
        fm = _FOOTER_RE.search(s)
        if fm:
            s = s[: fm.start()].strip()
            if not s:
                break
        if _FUNDING_RE.search(s):
            continue
        # A funding line often carries a trailing bare amount ("...  2.99");
        # skip a token that is purely a number so it doesn't pollute the name.
        if re.fullmatch(r"-?\d[\d,]*\.\d{2}", s):
            continue
        parts.append(s)
    name = " ".join(parts)
    name = re.sub(r"\s+", " ", name).strip()
    # Trailing colon from "...User Payment:" reads oddly on its own.
    return name.rstrip(":").strip()


def _iter_blocks(lines: list[str]):
    """Yield (date_str, body_lines) blocks, each starting at a MM/DD/YYYY line."""
    block: list[str] | None = None
    date_str: str | None = None
    for line in lines:
        m = _DATE_RE.match(line.strip())
        if m:
            if block is not None and date_str is not None:
                yield date_str, block
            mm, dd, yyyy, rest = m.groups()
            date_str = f"{yyyy}-{mm}-{dd}"
            block = [rest.strip()] if rest.strip() else []
        elif block is not None:
            block.append(line)
    if block is not None and date_str is not None:
        yield date_str, block


class PayPalPdfReader(StatementReader):
    name = _SOURCE
    format = "PayPal PDF statement"

    def matches(self, filename: str, data: bytes) -> bool:
        low = filename.lower()
        if not low.endswith(".pdf"):
            return False
        # "statement-<mon>-YYYY.pdf" is PayPal's export name; also accept any PDF
        # whose text carries the PayPal account-activity header, so a renamed
        # file still routes here.
        if low.startswith("statement-") or "paypal" in low:
            return True
        try:
            text = _extract_text(data)[:2000]
        except Exception:
            return False
        return "PayPal Account ID" in text or "PAYPAL ACCOUNT" in text

    def parse(self, filename: str, data: bytes) -> list[ImportedTxn]:
        return parse_text(_extract_text(data))


def parse_text(text: str) -> list[ImportedTxn]:
    """Parse already-extracted statement text into normalized transactions.

    Split out from PDF extraction so the parsing logic (date unwrapping, block
    splitting, offset pairing) can be unit-tested without a real PDF.
    """
    lines = _unwrap_dates(text.splitlines())
    txns: list[ImportedTxn] = []
    for date_str, body in _iter_blocks(lines):
        txn = _parse_block(date_str, body)
        if txn is not None:
            txns.append(txn)
    _mark_offsets(txns)
    return txns


def _extract_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _parse_block(date_str: str, body: list[str]) -> ImportedTxn | None:
    """Turn one date-anchored block into an ImportedTxn, or None if it has no
    ID/value line (i.e. it was boilerplate that happened to start with digits)."""
    txn_id: str | None = None
    ref_id: str | None = None
    amount: float | None = None
    desc_lines: list[str] = []

    for ln in body:
        s = ln.strip()
        mid = _ID_RE.match(s)
        if mid:
            txn_id = mid.group(1)
            continue
        mref = _REF_RE.match(s)
        if mref:
            ref_id = mref.group(1)
            continue
        mval = _VALUE_RE.match(s)
        if mval:
            amount = float(mval.group(1).replace(",", ""))
            continue
        desc_lines.append(ln)

    if txn_id is None or amount is None:
        return None

    name = _clean_name(desc_lines) or "PayPal transaction"
    return ImportedTxn(
        transaction_id=f"paypal_{txn_id}",
        date=date_str,
        name=name,
        amount=amount,
        merchant=name,
        bank=_BANK,
        account_mask=_ACCOUNT_MASK,
        source=_SOURCE,
        offsets_id=f"paypal_{ref_id}" if ref_id else None,
    )


def _mark_offsets(txns: list[ImportedTxn]) -> None:
    """Flag 'General Credit Card Deposit' rows that fund a purchase as offsets.

    Such a deposit references the purchase via Ref ID (stored in `offsets_id`).
    It is a funding movement, not real income, so we mark it `offset=True` so the
    importer can categorize it as a transfer and keep it out of budget spend.
    """
    ids = {t.transaction_id for t in txns}
    for t in txns:
        if t.offsets_id and t.offsets_id in ids and t.amount > 0:
            t.offset = True


# Register the built-in PayPal reader with the framework.
register_reader(PayPalPdfReader())
