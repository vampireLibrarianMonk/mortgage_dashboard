"""Walmart "Order details" invoice reader.

Observed layout::

    Invoice
    Jul 13, 2026 order
    Order# 2000000-00000003
    Seller
    Ballucci
    Buyer
    John Doe
    100 Example Ave, Anytown, VA 20000
    Ballucci 36" Floating Shelves, 2-Pack ... White Qty 1 $47.99
    Subtotal $47.99
    Savings -$6.00
    $41.99
    Taxes $2.52
    Total $44.51
    Order# 2000000-00000003

Item lines end with ``Qty <n> $<price>`` (the extended line price). A long item
name can wrap onto the line(s) *above* the Qty/$ line. Item prices sum to the
subtotal; the total is subtotal - savings + shipping + tax, so the transaction
amount equals the TOTAL.
"""

from __future__ import annotations

import re

from .orders import (
    OrderDetail,
    OrderItem,
    OrderReader,
    money,
    parse_month_day_year,
    register_order_reader,
)

_ORDER_RE = re.compile(r"Order#\s*([0-9\-]+)")
_SELLER_RE = re.compile(r"^Seller\s*$", re.IGNORECASE)
_ITEM_RE = re.compile(r"^(.*?)\s+Qty\s+(\d+)\s+\$([\d,]+\.\d{2})\s*$", re.IGNORECASE)
_SUBTOTAL_RE = re.compile(r"^Subtotal\b.*?\$([\d,]+\.\d{2})\s*$", re.IGNORECASE)
_SAVINGS_RE = re.compile(r"^(?:Savings|Discount|Promo\w*)\b.*?-?\$([\d,]+\.\d{2})\s*$", re.IGNORECASE)
_SHIPPING_RE = re.compile(r"^Shipping\b.*?\$([\d,]+\.\d{2})\s*$", re.IGNORECASE)
_TAX_RE = re.compile(r"^Tax(?:es)?\b.*?\$([\d,]+\.\d{2})\s*$", re.IGNORECASE)
_TOTAL_RE = re.compile(r"^Total\b.*?\$([\d,]+\.\d{2})\s*$", re.IGNORECASE)
_BARE_MONEY_RE = re.compile(r"^\$([\d,]+\.\d{2})\s*$")
_HEADER_SKIP = re.compile(
    r"^(Invoice|Seller|Buyer|Order#|.*\d{4} order$|Patrick|\d+ .+ (?:St|Ave|Rd|Dr)\b|"
    r"[A-Za-z ]+,\s*[A-Z]{2}\s+\d{5})", re.IGNORECASE)


@register_order_reader
class WalmartOrderReader(OrderReader):
    vendor = "walmart"

    def matches(self, filename: str, data: bytes) -> bool:
        low = filename.lower()
        if not low.endswith(".pdf"):
            return False
        if "walmart" in low:
            return True
        try:
            from .orders import extract_text
            text = extract_text(data)[:2000].lower()
        except Exception:
            return False
        return "order#" in text and "walmart" in text

    def parse_text(self, text: str, source_file: str = "") -> OrderDetail:
        order = OrderDetail(vendor=self.vendor, order_no=None,
                            date=parse_month_day_year(text), source_file=source_file)
        mo = _ORDER_RE.search(text)
        if mo:
            order.order_no = mo.group(1).replace("-", "")

        expect_seller = False
        pending: list[str] = []  # buffered fragments of a wrapped item name
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if expect_seller:
                order.seller = line
                expect_seller = False
                continue
            if _SELLER_RE.match(line):
                expect_seller = True
                pending.clear()
                continue
            m = _TOTAL_RE.match(line)
            if m:
                order.total = money(m.group(1)); pending.clear(); continue
            m = _SUBTOTAL_RE.match(line)
            if m:
                order.subtotal = money(m.group(1)); pending.clear(); continue
            m = _SAVINGS_RE.match(line)
            if m:
                order.savings = money(m.group(1)); pending.clear(); continue
            m = _SHIPPING_RE.match(line)
            if m:
                order.shipping = money(m.group(1)); pending.clear(); continue
            m = _TAX_RE.match(line)
            if m:
                order.tax = money(m.group(1)); pending.clear(); continue
            m = _ITEM_RE.match(line)
            if m:
                tail = m.group(1).strip()
                full = " ".join([*pending, tail]).strip().rstrip(".").strip()
                order.items.append(OrderItem(name=full, qty=int(m.group(2)),
                                             price=money(m.group(3))))
                pending.clear()
                continue
            if _BARE_MONEY_RE.match(line):
                pending.clear()
                continue
            if not _HEADER_SKIP.match(line):
                pending.append(line)
        return order
