"""Target "Order details" invoice reader.

Observed layout::

    Invoice 1 of 1
    Ship to
    John Doe
    100 Example Ave
    Anytown, VA 20000
    Invoice date: Tue, Aug 18, 2026
    Invoice number: 60000000000000001
    Item
    76115711 - Sterilite 30 Qt. Ultra Latch Box, Clear Storage Organizer Bins ...
    & Garage Organization Stackable Plastic Containers, 6 Pack
    Qty.
    1
    Unit price
    $54.99
    Amount
    $54.99
    SHIP_2024 Global SW 35 FreeShip FS -$5.99
    Item subtotal $49.00
    Standard shipping $5.99
    Sales tax $3.30
    Item total $58.29
    Invoice total $58.29
    Visa

Unlike Walmart (inline "Qty n $x") and Amazon (concatenated totals), Target puts
each item's Qty / Unit price / Amount on their own *labeled* lines, and the item
name (prefixed by an item number) can wrap across lines. The "Amount" value is
the extended line price. A promo line like "... FreeShip FS -$5.99" is a discount.
Totals: Item subtotal, Standard shipping, Sales tax, Invoice total.
"""

from __future__ import annotations

import re

from .orders import (
    OrderDetail,
    OrderItem,
    OrderReader,
    money,
    register_order_reader,
)

_DATE_RE = re.compile(r"Invoice date:\s*(?:[A-Za-z]{3},\s*)?([A-Z][a-z]{2,8})\s+(\d{1,2}),\s+(\d{4})")
_ORDER_RE = re.compile(r"Invoice number:\s*([0-9]+)")
# Item name line: "<itemnumber> - <name...>"
_ITEM_START_RE = re.compile(r"^(\d{6,})\s*-\s*(.+)$")
_MONEY_RE = re.compile(r"^\$?(-?[\d,]+\.\d{2})$")
_SUBTOTAL_RE = re.compile(r"Item subtotal\s+\$?([\d,]+\.\d{2})", re.IGNORECASE)
_SHIPPING_RE = re.compile(r"(?:Standard )?shipping\s+\$?([\d,]+\.\d{2})", re.IGNORECASE)
_TAX_RE = re.compile(r"Sales tax\s+\$?([\d,]+\.\d{2})", re.IGNORECASE)
_TOTAL_RE = re.compile(r"Invoice total\s+\$?([\d,]+\.\d{2})", re.IGNORECASE)
# Discount/promo line ending in "-$x.xx".
_DISCOUNT_RE = re.compile(r"(?:FreeShip|Promo|Discount|Savings)\b.*?-\$([\d,]+\.\d{2})", re.IGNORECASE)

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


@register_order_reader
class TargetOrderReader(OrderReader):
    vendor = "target"

    def matches(self, filename: str, data: bytes) -> bool:
        low = filename.lower()
        if not low.endswith(".pdf"):
            return False
        if "target" in low:
            return True
        try:
            from .orders import extract_text
            text = extract_text(data)[:2000].lower()
        except Exception:
            return False
        return "invoice number:" in text and "target" in text

    def parse_text(self, text: str, source_file: str = "") -> OrderDetail:
        order = OrderDetail(vendor=self.vendor, order_no=None,
                            date=_parse_date(text), source_file=source_file)
        mo = _ORDER_RE.search(text)
        if mo:
            order.order_no = mo.group(1)

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        order.items = _parse_items(lines)

        joined = "\n".join(lines)
        m = _TAX_RE.search(joined)
        if m:
            order.tax = money(m.group(1))
        m = _TOTAL_RE.search(joined)
        if m:
            order.total = money(m.group(1))
        shipping = 0.0
        m = _SHIPPING_RE.search(joined)
        if m:
            shipping = money(m.group(1))
        # A "FreeShip" / promo discount offsets shipping (it is a free-shipping
        # credit), so net it against the shipping charge rather than treating it
        # as a subtotal reduction. Target's printed "Item subtotal" is already
        # post-discount; we instead build the subtotal from the item Amounts (the
        # pre-discount extended prices) so items reconcile to it, and let the
        # net-shipping + tax bridge to the invoice total.
        md = _DISCOUNT_RE.search(joined)
        discount = money(md.group(1)) if md else 0.0
        order.shipping = round(shipping - discount, 2)
        order.savings = 0.0  # folded into net shipping above
        order.subtotal = round(sum(i.price for i in order.items), 2) if order.items else None
        return order


def _parse_date(text: str):
    import datetime as dt
    m = _DATE_RE.search(text)
    if not m:
        return None
    mon = m.group(1)[:3].title()
    if mon not in _MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), _MONTHS[mon], int(m.group(2)))
    except ValueError:
        return None


def _parse_items(lines: list[str]) -> list[OrderItem]:
    """Parse Target's item blocks.

    Each item starts with a "<num> - <name>" line (name may wrap onto following
    lines), then labeled 'Qty.'/value and 'Unit price'/$ and 'Amount'/$ lines.
    We use the 'Amount' value as the extended line price and read Qty from the
    value after the 'Qty.' label.
    """
    items: list[OrderItem] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _ITEM_START_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name_parts = [m.group(2).strip()]
        j = i + 1
        # Accumulate wrapped name lines until we hit the 'Qty.' label.
        while j < n and lines[j].lower() != "qty.":
            # Stop if we run into a totals/label section without a Qty (defensive).
            if _SUBTOTAL_RE.search(lines[j]) or lines[j].lower().startswith("item subtotal"):
                break
            name_parts.append(lines[j].strip())
            j += 1
        qty = 1
        amount = None
        if j < n and lines[j].lower() == "qty.":
            # value line after 'Qty.'
            if j + 1 < n and lines[j + 1].isdigit():
                qty = int(lines[j + 1])
            # find the 'Amount' label and take the next money line as extended price
            k = j
            while k < n and lines[k].lower() != "amount":
                k += 1
            if k + 1 < n:
                mm = _MONEY_RE.match(lines[k + 1])
                if mm:
                    amount = money(mm.group(1))
            i = k + 2
        else:
            i = j
        if amount is not None:
            items.append(OrderItem(name=" ".join(name_parts).strip(), qty=qty, price=amount))
    return items
