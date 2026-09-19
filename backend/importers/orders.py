"""Order-detail framework: turn an itemized order document into a split plan.

Distinct from the statement readers in this package. A *statement* reader
produces new transactions to import; an *order* reader produces an
:class:`OrderDetail` - the itemized breakdown of ONE existing payment (line
items + subtotal/savings/shipping/tax/total) - which is then matched to a
transaction already in the store and used to *split* it into per-item
categories.

This is the "authenticated order page saved to PDF" path: bank/PayPal feeds and
retailer *emails* only give a payment total, but the order-details invoice the
user saves from the retailer's site has the real per-item prices. Parsing is
local (pypdf), same privacy posture as the rest of the importers.

**Pluggable per vendor.** Each retailer's invoice format differs, so each gets
its own reader module (``orders_walmart``, ``orders_amazon``, ...) that
registers an :class:`OrderReader` here. ``read_order()`` sniffs a file and routes
it to the right vendor reader, so the caller drops mixed PDFs into one place and
the framework separates them by content. Adding a vendor = one new module.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from . import DATA_START

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


# --------------------------------------------------------------------------- #
# Normalized models
# --------------------------------------------------------------------------- #


@dataclass
class OrderItem:
    name: str
    qty: int
    price: float  # extended line price (unit x qty)


@dataclass
class OrderDetail:
    """The itemized breakdown of one order, ready to match + split a transaction."""

    vendor: str
    order_no: str | None
    date: dt.date | None
    # When the item shipped/was delivered (retailers bill at ship time, so the
    # bank charge lands near here, not near the order date). Used to match orders
    # whose charge posts long after the order (Subscribe & Save, slow ship).
    delivered_date: dt.date | None = None
    items: list[OrderItem] = field(default_factory=list)
    subtotal: float | None = None
    savings: float = 0.0  # order-level discount (positive number, subtracted)
    shipping: float = 0.0
    tax: float = 0.0
    tip: float = 0.0  # driver/delivery tip - an added charge (e.g. Amazon grocery)
    total: float | None = None
    seller: str = ""  # marketplace seller when present (e.g. "Ballucci")
    source_file: str = ""
    # Grocery orders (Whole Foods / Amazon Fresh) charge under a different
    # merchant name and the final amount drifts from the estimate (weight-priced
    # produce, substitutions). Flagged so the matcher can allow a small amount
    # tolerance, guarded by an exact date match, and scale the split to the real
    # charge. `match_names` are extra merchant-name aliases the charge may use.
    grocery: bool = False
    match_names: tuple[str, ...] = ()

    @property
    def item_count(self) -> int:
        return len(self.items)

    def sanity(self) -> list[str]:
        """Warnings if the parsed numbers don't reconcile.

        Reconciliation: item prices sum to the subtotal; the total is
        subtotal - savings + shipping + tax.
        """
        warns: list[str] = []
        if self.subtotal is not None and self.items:
            s = round(sum(i.price for i in self.items), 2)
            if abs(s - self.subtotal) > 0.01:
                warns.append(f"item prices sum to {s:.2f} but subtotal is {self.subtotal:.2f}")
        if self.total is not None and self.subtotal is not None:
            expected = round(self.subtotal - self.savings + self.shipping
                             + self.tax + self.tip, 2)
            if abs(expected - self.total) > 0.01:
                warns.append(
                    f"subtotal-savings+shipping+tax+tip = {expected:.2f} "
                    f"but total is {self.total:.2f}")
        return warns


# --------------------------------------------------------------------------- #
# Shared parsing helpers (used by vendor readers)
# --------------------------------------------------------------------------- #


def extract_text(data: bytes) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def money(s: str) -> float:
    return float(s.replace(",", "").replace("$", ""))


def parse_month_day_year(text: str) -> dt.date | None:
    """Parse the first 'Mon[th] DD, YYYY' (abbreviated or full month) in text."""
    m = re.search(r"([A-Z][a-z]{2,8})\s+(\d{1,2}),\s+(\d{4})", text)
    if not m:
        return None
    mon = m.group(1)[:3].title()
    if mon not in _MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), _MONTHS[mon], int(m.group(2)))
    except ValueError:
        return None


def order_slug(order: OrderDetail) -> str | None:
    """Canonical id for an order folder/file: date-vendor-<units>items-total.

    'units' is the sum of line-item quantities (what a receipt calls the item
    count). Returns None if the order lacks a date or total to name it by.
    """
    if order.date is None or order.total is None:
        return None
    units = sum(i.qty for i in order.items) or order.item_count
    return f"{order.date.isoformat()}-{order.vendor}-{units}items-{order.total:.2f}"


# --------------------------------------------------------------------------- #
# Vendor reader interface + registry
# --------------------------------------------------------------------------- #


class OrderReader:
    """Base class for a vendor order-details reader.

    Subclasses set ``vendor`` and implement ``matches`` (cheap sniff) and
    ``parse_text`` (text -> OrderDetail). ``parse`` extracts PDF text and
    delegates to ``parse_text`` so the parsing is unit-testable without a PDF.
    """

    vendor: str = "base"

    def matches(self, filename: str, data: bytes) -> bool:
        raise NotImplementedError

    def parse_text(self, text: str, source_file: str = "") -> OrderDetail:
        raise NotImplementedError

    def parse(self, filename: str, data: bytes) -> OrderDetail:
        return self.parse_text(extract_text(data), source_file=filename)


_ORDER_READERS: list[OrderReader] = []


def register_order_reader(reader):
    """Register a vendor reader. Usable as a class decorator: the decorated class
    is instantiated and its instance stored (so ``matches``/``parse`` are bound).
    Returns the original class/instance unchanged for the decorator to rebind."""
    instance = reader() if isinstance(reader, type) else reader
    _ORDER_READERS.append(instance)
    return reader


def order_reader_for(filename: str, data: bytes) -> OrderReader | None:
    """Return the first registered vendor reader that claims this file."""
    for reader in reversed(_ORDER_READERS):
        try:
            if reader.matches(filename, data):
                return reader
        except Exception:
            continue
    return None


def read_order(filename: str, data: bytes) -> OrderDetail | None:
    """Sniff + parse one order document, or None if no vendor reader claims it."""
    reader = order_reader_for(filename, data)
    return reader.parse(filename, data) if reader else None


# --------------------------------------------------------------------------- #
# Document organization (dump -> processed_document/<slug>/)
# --------------------------------------------------------------------------- #


@dataclass
class ProcessResult:
    """Outcome of organizing one raw order document."""
    source: str
    order: OrderDetail | None = None
    slug: str | None = None
    dest_dir: str | None = None
    # "processed" | "skipped-pre-start" | "unrecognized" | "unreadable" | "no-slug"
    status: str = ""
    warnings: list = field(default_factory=list)


def process_order_file(raw_path, processed_root, keep_raw: bool = True) -> ProcessResult:
    """Parse one raw order PDF (any registered vendor) and file it into
    processed_root/<slug>/ (raw original + a renamed <slug>.pdf, both flat).

    Files no vendor reader recognizes are left untouched (status
    "unrecognized"). Orders before DATA_START are skipped. Never deletes the
    source - the caller decides that after checking status.
    """
    raw_path = Path(raw_path)
    processed_root = Path(processed_root)
    res = ProcessResult(source=raw_path.name)

    try:
        data = raw_path.read_bytes()
    except Exception as e:  # noqa: BLE001
        res.status = "unreadable"
        res.warnings.append(f"{type(e).__name__}: {e}")
        return res

    reader = order_reader_for(raw_path.name, data)
    if reader is None:
        res.status = "unrecognized"
        return res

    try:
        order = reader.parse(raw_path.name, data)
    except Exception as e:  # noqa: BLE001
        res.status = "unreadable"
        res.warnings.append(f"{type(e).__name__}: {e}")
        return res

    res.order = order
    res.warnings = order.sanity()

    if order.date and order.date < DATA_START:
        res.status = "skipped-pre-start"
        return res

    slug = order_slug(order)
    if slug is None:
        res.status = "no-slug"
        return res
    res.slug = slug

    dest_dir = processed_root / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    renamed = dest_dir / f"{slug}.pdf"
    shutil.copyfile(raw_path, renamed)
    if keep_raw:
        raw_dest = dest_dir / raw_path.name
        if raw_dest.resolve() != renamed.resolve():
            shutil.copyfile(raw_path, raw_dest)
    res.dest_dir = str(dest_dir)
    res.status = "processed"
    return res


# Register built-in vendor readers (imported last to avoid circular imports).
from . import orders_walmart as _walmart  # noqa: E402,F401
from . import orders_amazon as _amazon  # noqa: E402,F401
from . import orders_target as _target  # noqa: E402,F401
