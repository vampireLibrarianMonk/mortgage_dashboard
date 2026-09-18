"""Import service: parse -> filter (data-start) -> reconcile -> preview / commit.

This is the layer both entry points (the console ``import`` command and the GUI
upload endpoint) call. It sits on top of the reader registry and the txn store,
and it enforces the two policy decisions that keep budgets honest:

1. **Hard data start (2026-06-18).** History before this date is partial, so
   importing it would skew monthly budgets. Rows whose effective date is before
   ``DATA_START`` are dropped from the import (reported separately so the user
   sees they were recognized but intentionally excluded).

2. **Reconciliation with opaque bank rows.** The PayPal account funds from USAA
   checking x-0000, so each itemized PayPal purchase also shows up as an opaque
   ``PAYPAL PURCHASE`` line synced from USAA via Plaid (with the sign flipped:
   Plaid debits are positive). Counting both would double the spend. We keep the
   itemized PayPal row as the real (categorizable) spend and mark the matching
   opaque bank row ``Ignore`` so it drops out of budget actuals.

The two public entry points are:

* ``preview_files(files)`` -> an :class:`ImportPreview` describing exactly what a
  commit would do, without writing anything.
* ``commit(preview)`` -> applies the preview to the store (snapshot first, so it
  is undoable) and returns a short summary.

Nothing here writes to disk except ``commit``.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from dataclasses import dataclass, field

import txn_store as ts

from . import DATA_START, ImportedTxn, ParsedFile, parse_files

# Category assigned to the offsetting "General Credit Card Deposit" rows and to
# the reconciled opaque bank rows: excluded from budget actuals (see actuals.py).
_OFFSET_CATEGORY = "Ignore"

# How close (in days) an opaque bank row's date must be to a PayPal purchase to
# be considered the same charge. Plaid posts 0-3 days after PayPal's date.
_RECONCILE_DAY_WINDOW = 4


@dataclass
class ReconcileMatch:
    """An itemized PayPal row matched to an opaque bank row it supersedes."""

    paypal_id: str
    paypal_name: str
    bank_txn_id: str
    amount: float
    paypal_date: str
    bank_date: str


@dataclass
class ImportPreview:
    """Everything a commit would do, computed without writing anything."""

    # Rows that will be upserted (post-filter, post-reconcile), as store dicts.
    to_import: list[dict] = field(default_factory=list)
    # Recognized but dropped because they predate DATA_START.
    pre_start: list[ImportedTxn] = field(default_factory=list)
    # Offsetting CC-deposit rows among to_import (already categorized Ignore).
    offsets: list[dict] = field(default_factory=list)
    # Opaque bank rows that will be re-categorized Ignore to avoid double count.
    reconciled: list[ReconcileMatch] = field(default_factory=list)
    # Per-file parse outcomes (for showing what was read / any errors).
    files: list[ParsedFile] = field(default_factory=list)
    # Files that no reader recognized, or that errored.
    problems: list[str] = field(default_factory=list)

    @property
    def import_count(self) -> int:
        return len(self.to_import)


def iter_zip(data: bytes) -> list[tuple[str, bytes]]:
    """Return (filename, bytes) for each non-directory member of a zip archive."""
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Skip macOS resource-fork noise.
            base = info.filename.rsplit("/", 1)[-1]
            if base.startswith("._") or "__MACOSX" in info.filename:
                continue
            out.append((base, zf.read(info)))
    return out


def collect_files(name: str, data: bytes) -> list[tuple[str, bytes]]:
    """Expand an upload into individual (filename, bytes) pairs.

    A .zip is unpacked into its members; anything else is treated as a single
    file. This is what lets the user drop the raw ``statement-2026.zip`` PayPal
    exports straight in.
    """
    if name.lower().endswith(".zip"):
        return iter_zip(data)
    return [(name, data)]


def preview_files(files: list[tuple[str, bytes]]) -> ImportPreview:
    """Parse, filter by data-start, and reconcile - without writing anything."""
    parsed = parse_files(files)
    preview = ImportPreview(files=parsed)

    imported: list[ImportedTxn] = []
    for pf in parsed:
        if pf.error:
            preview.problems.append(f"{pf.filename}: {pf.error}")
            continue
        if not pf.txns:
            preview.problems.append(f"{pf.filename}: recognized but no transactions found")
            continue
        imported.extend(pf.txns)

    # 1) Data-start filter: drop rows before DATA_START (report them separately).
    kept: list[ImportedTxn] = []
    for t in imported:
        if t.effective_date < DATA_START:
            preview.pre_start.append(t)
        else:
            kept.append(t)

    # 2) Categorize offsetting CC deposits as Ignore up front.
    store_rows: list[dict] = []
    for t in kept:
        row = t.to_store_dict()
        if t.offset:
            row["category"] = _OFFSET_CATEGORY
            preview.offsets.append(row)
        store_rows.append(row)

    preview.to_import = store_rows

    # 3) Reconcile against opaque bank rows already in the store.
    preview.reconciled = _plan_reconciliation(kept)
    return preview


def _plan_reconciliation(paypal_txns: list[ImportedTxn]) -> list[ReconcileMatch]:
    """Match itemized PayPal purchases to opaque ``PAYPAL PURCHASE`` bank rows.

    The bank (Plaid) side records the USAA debit with the opposite sign and a
    posting date a few days later. For each PayPal *purchase* (negative amount,
    not an offset deposit) we look for an as-yet-unclaimed opaque bank row with a
    matching magnitude within the date window. Matches are what ``commit`` will
    flip to ``Ignore`` so the spend is only counted once (on the itemized row).
    """
    existing = ts.load_transactions()
    # Candidate opaque rows: name mentions PAYPAL PURCHASE, not already Ignored,
    # not themselves from a statement import.
    candidates = [
        t for t in existing
        if "paypal purchase" in (t.get("name", "").lower())
        and t.get("source") != "paypal_statement"
        and t.get("category") != _OFFSET_CATEGORY
    ]
    claimed: set[str] = set()
    matches: list[ReconcileMatch] = []

    for p in paypal_txns:
        if p.offset or p.amount >= 0:
            continue  # only real purchases (money out) reconcile
        mag = round(abs(p.amount), 2)
        p_date = p.posted_date
        best = None
        best_gap = _RECONCILE_DAY_WINDOW + 1
        for c in candidates:
            cid = c["transaction_id"]
            if cid in claimed:
                continue
            if round(abs(float(c.get("amount", 0.0))), 2) != mag:
                continue
            try:
                c_date = dt.date.fromisoformat(c["date"])
            except (ValueError, KeyError):
                continue
            gap = abs((c_date - p_date).days)
            if gap < best_gap:
                best, best_gap = c, gap
        if best is not None:
            claimed.add(best["transaction_id"])
            matches.append(ReconcileMatch(
                paypal_id=p.transaction_id,
                paypal_name=p.name,
                bank_txn_id=best["transaction_id"],
                amount=p.amount,
                paypal_date=p.date,
                bank_date=best["date"],
            ))
    return matches


def commit(preview: ImportPreview) -> list[str]:
    """Apply a preview to the store. Snapshots first so it is undoable.

    Order: snapshot -> re-categorize reconciled bank rows to Ignore -> upsert the
    imported PayPal rows. Returns human-readable summary lines.
    """
    ts.snapshot()
    out: list[str] = []

    # Flip matched opaque bank rows to Ignore so they drop out of actuals.
    if preview.reconciled:
        rows = ts.load_transactions()
        by_id = {t["transaction_id"]: t for t in rows}
        n = 0
        for m in preview.reconciled:
            row = by_id.get(m.bank_txn_id)
            if row is not None and row.get("category") != _OFFSET_CATEGORY:
                row["category"] = _OFFSET_CATEGORY
                n += 1
        if n:
            ts.save_transactions(list(by_id.values()))
        out.append(f"reconciled {n} opaque bank row(s) -> Ignore (superseded by itemized PayPal detail)")

    added, skipped = ts.upsert_transactions(preview.to_import)
    out.append(f"imported {added} new PayPal transaction(s), {skipped} already known")
    if preview.offsets:
        out.append(f"{len(preview.offsets)} funding deposit(s) categorized Ignore (offset purchases)")
    if preview.pre_start:
        out.append(f"skipped {len(preview.pre_start)} transaction(s) before data start {DATA_START}")
    return out
