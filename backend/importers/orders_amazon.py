"""Amazon "Order Details" invoice reader.

Observed layout (fields on the totals line run together with no spaces)::

    Order Summary
    Order placed September 18, 2026  Order # 111-1111111-1111111
    Ship to
    john doe 100 EXAMPLE AVE ANYTOWN, VA ...
    Payment method
    Prime Visa****0004
    View related transactions
    Order Summary
    Item(s) Subtotal: $29.99Shipping & Handling: $0.00Total before tax: $29.99Estimated tax to becollected: $1.80
    Grand Total: $31.79
    Arriving Sunday
    Pampers Sensitive Baby Wipes, ... (18X Flip-Top Packs)
    Sold by: Amazon.com
    Supplied by: Other
    $29.99
    ...

Differences from Walmart handled here:

* Totals labels are searched anywhere in the text (they are concatenated on one
  line), not line-anchored.
* Grand Total is the transaction amount (subtotal + tax; shipping usually $0).
* Item names have no "Qty" marker; each item block is
  ``<name>`` / ``Sold by: ...`` / (``Supplied by: ...``) / ``$<price>``. We pair
  the name with the price that follows its "Sold by" marker. Qty is assumed 1
  (Amazon order-details PDFs here do not show a separate qty column).
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

_ORDER_RE = re.compile(r"Order\s*#\s*([0-9\-]+)")
# Labeled amounts, searched anywhere (fields are concatenated without spaces).
_SUBTOTAL_RE = re.compile(r"Item\(s\)\s*Subtotal:\s*\$([\d,]+\.\d{2})", re.IGNORECASE)
_SHIPPING_RE = re.compile(r"Shipping\s*&\s*Handling:\s*\$([\d,]+\.\d{2})", re.IGNORECASE)
# A shipping credit that offsets the S&H charge. Covers "Free Shipping: -$2.99"
# and "$0 delivery on your 1st order: -$9.95" and similar free-delivery lines.
_FREESHIP_RE = re.compile(
    r"(?:Free\s*Shipping|\$0\s*delivery[^:]*|Free\s*delivery[^:]*):\s*-?\$([\d,]+\.\d{2})",
    re.IGNORECASE)
# "Driver tip: $5.00" / "Tip: $5.00" is a real added charge included in the total.
_TIP_RE = re.compile(r"(?:Driver\s*)?tip:\s*\$([\d,]+\.\d{2})", re.IGNORECASE)
_TAX_RE = re.compile(r"tax\s*to\s*be\s*collected:\s*\$([\d,]+\.\d{2})", re.IGNORECASE)
_PROMO_RE = re.compile(r"(?:Promotion|Discount|Coupon)[^$]*-?\$([\d,]+\.\d{2})", re.IGNORECASE)
_TOTAL_RE = re.compile(r"Grand\s*Total:\s*\$([\d,]+\.\d{2})", re.IGNORECASE)
_PRICE_LINE_RE = re.compile(r"^\$([\d,]+\.\d{2})\s*$")


@register_order_reader
class AmazonOrderReader(OrderReader):
    vendor = "amazon"

    def matches(self, filename: str, data: bytes) -> bool:
        low = filename.lower()
        if not low.endswith(".pdf"):
            return False
        if "amazon" in low:
            return True
        try:
            from .orders import extract_text
            text = extract_text(data)[:2000].lower()
        except Exception:
            return False
        return "amazon.com" in text and ("grand total" in text or "order #" in text)

    def parse_text(self, text: str, source_file: str = "") -> OrderDetail:
        order = OrderDetail(vendor=self.vendor, order_no=None,
                            date=parse_month_day_year(text), source_file=source_file)
        mo = _ORDER_RE.search(text)
        if mo:
            order.order_no = mo.group(1).replace("-", "")

        def grab(rx):
            m = rx.search(text)
            return money(m.group(1)) if m else None

        order.subtotal = grab(_SUBTOTAL_RE)
        shipping = grab(_SHIPPING_RE) or 0.0
        free_ship = grab(_FREESHIP_RE) or 0.0
        order.shipping = round(shipping - free_ship, 2)  # net of any free-shipping credit
        order.tax = grab(_TAX_RE) or 0.0
        order.savings = grab(_PROMO_RE) or 0.0
        order.tip = grab(_TIP_RE) or 0.0
        order.total = grab(_TOTAL_RE)

        order.items = _parse_items(text)
        return order


_BARE_QTY_RE = re.compile(r"^(\d{1,3})$")
# Item-block boilerplate to ignore when assembling names (matched on lowercase).
_ITEM_SKIP_PREFIXES = (
    "arriving", "delivered", "your package", "sold by:", "supplied by:",
    "return", "back to top", "conditions of use", "your ads",
    "consumer health", "get product support", "view related", "order summary",
    "\u00a9", "©",
)


def _parse_items(text: str) -> list[OrderItem]:
    """Extract Amazon line items with quantity.

    Item block shape (after the Grand Total line)::

        [Delivered .../Your package ...]     status noise (skip)
        [<bare qty number>]                  optional; default 1
        <name>                               may wrap across lines
        Sold by: ...
        [Supplied by: ...]
        [Return ...: Eligible through ...]
        $<unit price>

    The extended line price is unit price x qty. A bare number line before a name
    is the quantity; status/return/boilerplate lines are skipped.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    start = 0
    for i, ln in enumerate(lines):
        if ln.lower().startswith("grand total"):
            start = i + 1
            break

    items: list[OrderItem] = []
    name_buf: list[str] = []
    pending_qty = 1
    for ln in lines[start:]:
        low = ln.lower()
        if any(low.startswith(pfx) for pfx in _ITEM_SKIP_PREFIXES):
            if low.startswith(("arriving", "delivered")):
                # Start of a new item block: reset name buffer + qty.
                name_buf.clear()
                pending_qty = 1
            continue
        # A bare number before a name is the quantity for the next item.
        if not name_buf and _BARE_QTY_RE.match(ln):
            pending_qty = int(ln)
            continue
        m = _PRICE_LINE_RE.match(ln)
        if m:
            name = " ".join(name_buf).strip()
            if name:
                unit = money(m.group(1))
                items.append(OrderItem(name=name, qty=pending_qty,
                                       price=round(unit * pending_qty, 2)))
            name_buf.clear()
            pending_qty = 1
            continue
        name_buf.append(ln)
    return items
