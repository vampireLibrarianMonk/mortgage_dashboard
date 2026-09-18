"""Modular statement-import framework.

This package turns raw statement files (PDF, CSV, ...) into the app's normalized
transaction schema so they can be previewed and merged into the encrypted txn
store. It is deliberately pluggable: each source (PayPal, a bank CSV, an OCR'd
image PDF, ...) is a small `StatementReader` registered in a central registry,
and callers (the console `import` command and the GUI upload endpoint) dispatch
through that registry without knowing which reader handles a given file.

Design goals
------------
* **Appendable** - adding a new format means writing one `StatementReader`
  subclass and calling `register_reader(...)`. Nothing else changes.
* **Local-first** - the PayPal statements are text-based, so parsing is pure
  Python (`pypdf`); financial data never leaves the machine. A future OCR /
  AWS Textract reader for scanned/image PDFs *could* be registered here, but is
  intentionally not required today.
* **Preview before write** - readers only ever *produce* normalized rows. The
  actual merge into the store is a separate, explicit step, so both the CLI and
  GUI can show the user what will be imported first.

The normalized row shape matches what `console_routes._cmd_sync` collects and
what `txn_store.upsert_transactions` expects, plus a `source` field marking the
importer of origin (e.g. ``"paypal_statement"``).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Iterable

# --------------------------------------------------------------------------- #
# Shared constants
# --------------------------------------------------------------------------- #

# Hard data-start boundary. Statement history before this date is partial (the
# user began tracking mid-June 2026), so importing those rows unfiltered would
# skew monthly budgets/actuals. Rows dated before this are dropped by default
# (or annotated as pre-start) rather than merged. Single source of truth -
# everything that filters imported history references this constant.
DATA_START = dt.date(2026, 6, 18)


# --------------------------------------------------------------------------- #
# Normalized transaction
# --------------------------------------------------------------------------- #


@dataclass
class ImportedTxn:
    """A single normalized transaction produced by a reader.

    Field names mirror the store schema (see console_routes._cmd_sync and
    txn_store.upsert_transactions) so `to_store_dict()` output can be handed
    straight to `upsert_transactions`. `source` and `offset` are import-only
    metadata used for reconciliation/preview and are persisted too so we can
    later tell where a row came from.
    """

    transaction_id: str
    date: str  # posted date, ISO "YYYY-MM-DD"
    name: str
    amount: float  # negative = money out, positive = money in (Plaid convention)
    authorized_date: str | None = None
    merchant: str = ""
    bank: str = ""
    account_id: str | None = None
    account_mask: str | None = None
    source: str = ""
    # True when this row offsets another (e.g. a PayPal "General Credit Card
    # Deposit" that funds a purchase). Offsetting rows are still imported for a
    # complete ledger but flagged so they can be auto-categorized as a transfer
    # and excluded from budget spend, mirroring the existing card-payment logic.
    offset: bool = False
    # transaction_id of the row this one offsets, when known (Ref ID pairing).
    offsets_id: str | None = None

    @property
    def posted_date(self) -> dt.date:
        return dt.date.fromisoformat(self.date)

    @property
    def effective_date(self) -> dt.date:
        """Date used for month bucketing - swipe date when present, else posted."""
        if self.authorized_date:
            return dt.date.fromisoformat(self.authorized_date)
        return self.posted_date

    def to_store_dict(self) -> dict:
        """Render into the dict shape `upsert_transactions` consumes."""
        eff = self.effective_date
        return {
            "transaction_id": self.transaction_id,
            "date": self.date,
            "authorized_date": self.authorized_date,
            "year": eff.year,
            "month": eff.month,
            "name": self.name,
            "merchant": self.merchant,
            "amount": float(self.amount),
            "bank": self.bank,
            "account_id": self.account_id,
            "account_mask": self.account_mask,
            "source": self.source,
            "offset": self.offset,
            "offsets_id": self.offsets_id,
        }


# --------------------------------------------------------------------------- #
# Reader interface
# --------------------------------------------------------------------------- #


class StatementReader:
    """Base class for a statement reader.

    A reader knows how to recognize files it can handle (`matches`) and turn a
    single file's bytes into normalized transactions (`parse`). Readers are pure
    - they must not touch the store or any global state - so callers can preview
    results before importing. Subclasses set `name` and `format` and implement
    `matches` and `parse`.
    """

    #: Short stable identifier, also written to each row's `source` field.
    name: str = "base"
    #: Human-friendly format label for previews/UX.
    format: str = "unknown"

    def matches(self, filename: str, data: bytes) -> bool:
        """Return True if this reader can parse the given file.

        Implementations should be cheap and side-effect free: sniff the
        extension and, if useful, a few header bytes. `data` may be inspected
        but should not be fully parsed here.
        """
        raise NotImplementedError

    def parse(self, filename: str, data: bytes) -> list[ImportedTxn]:
        """Parse one file's bytes into normalized transactions."""
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_READERS: list[StatementReader] = []


def register_reader(reader: StatementReader) -> StatementReader:
    """Register a reader instance. Returns it so it can be used as a decorator-ish
    one-liner. Later registrations take precedence in `reader_for` (last wins),
    which lets a more specific reader override a general one if needed."""
    _READERS.append(reader)
    return reader


def registered_readers() -> list[StatementReader]:
    """All registered readers, most-recently-registered first."""
    return list(reversed(_READERS))


def reader_for(filename: str, data: bytes) -> StatementReader | None:
    """Return the first registered reader that claims this file, or None."""
    for reader in registered_readers():
        try:
            if reader.matches(filename, data):
                return reader
        except Exception:
            # A misbehaving reader's sniff must not break dispatch.
            continue
    return None


@dataclass
class ParsedFile:
    """Outcome of parsing one file inside an archive/batch."""

    filename: str
    reader: str | None
    txns: list[ImportedTxn] = field(default_factory=list)
    error: str | None = None


def parse_files(files: Iterable[tuple[str, bytes]]) -> list[ParsedFile]:
    """Parse many (filename, bytes) pairs, dispatching each to its reader.

    Never raises for a single bad file - failures are captured per-file in the
    returned `ParsedFile.error` so a preview can show partial success.
    """
    results: list[ParsedFile] = []
    for filename, data in files:
        reader = reader_for(filename, data)
        if reader is None:
            results.append(ParsedFile(filename=filename, reader=None,
                                      error="no reader recognized this file"))
            continue
        try:
            txns = reader.parse(filename, data)
            results.append(ParsedFile(filename=filename, reader=reader.name, txns=txns))
        except Exception as e:  # noqa: BLE001 - surface any parse error to the preview
            results.append(ParsedFile(filename=filename, reader=reader.name,
                                      error=f"{type(e).__name__}: {e}"))
    return results


# Register built-in readers. Imported at the bottom to avoid circular imports:
# reader modules import ImportedTxn/StatementReader from this package.
from . import paypal as _paypal  # noqa: E402,F401  (registers PayPalPdfReader)
