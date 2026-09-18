"""Tests for the order-details split pipeline (importers.orders* + order_service).

Parsers are tested against synthetic extracted *text* matching the real Walmart
and Amazon invoice layouts (no PDF needed). The matcher/split service runs against
the isolated tmp store from conftest, so real data is never touched.
"""

import datetime as dt

import pytest

import txn_store as ts
from importers import orders, order_service
from importers import orders_walmart, orders_amazon  # noqa: F401 (register readers)


# --------------------------------------------------------------------------- #
# Synthetic invoice text (mirrors real extracted PDF text)
# --------------------------------------------------------------------------- #

WALMART_SIMPLE = """Invoice
Sep 17, 2026 order
Order# 2000000-00000001
Buyer
John Doe
100 Example Ave, Anytown, VA 20000
Goo Gone Latex Paint Remover Spray Gel, Safer Choice Certified, 14 oz. Qty 1 $6.12
Subtotal (1 item) $6.12
Shipping (below $35 order minimum fee) $6.99
Taxes $0.37
Total $13.48
Order# 2000000-00000001
"""

# Wrapped item name (name spans two lines) + qty 4 + seller.
WALMART_WRAPPED = """Invoice
Aug 01, 2026 order
Order# 2000000-00000002
Seller
LIRUA Living Store
Buyer
John Doe
100 Example Ave, Anytown, VA 20000
Under Bed Storage, Below 4 Inches High Underbed Storage Containers Low Profile
Organizer Clothes with Clear Lid & Zipper, 2-Pack, 20x40x4in Qty 4 $74.36
Subtotal (4 items) $74.36
Taxes $4.46
Total $78.82
Order# 2000000-00000002
"""

# Savings/discount line + bare adjusted-subtotal line.
WALMART_SAVINGS = """Invoice
Jul 13, 2026 order
Order# 2000000-00000003
Seller
Ballucci
Ballucci 36" Floating Shelves, 2-Pack Wood Wall Shelf Set, White Qty 1 $47.99
Subtotal $47.99
Savings -$6.00
$41.99
Taxes $2.52
Total $44.51
Order# 2000000-00000003
"""

# Amazon: concatenated totals line, single item.
AMAZON_SIMPLE = """Order Summary
Order placed September 18, 2026  Order # 111-1111111-1111111
Ship to
john doe 100 EXAMPLE AVE ANYTOWN, VA 20000
Payment method
Prime Visa****0004
Order Summary
Item(s) Subtotal: $29.99Shipping & Handling: $0.00Total before tax: $29.99Estimated tax to becollected: $1.80
Grand Total: $31.79
Arriving Sunday
Pampers Sensitive Baby Wipes, Unscented, 1008 Wipes Total
Sold by: Amazon.com
Supplied by: Other
$29.99
Back to top
"""

# Amazon: multi-item, a qty-3 line, and a Free Shipping credit.
AMAZON_MULTI = """Order Summary
Order placed September 6, 2026  Order # 113-0000000-0000002
Payment method
Prime Visa****0004
Order Summary
Item(s) Subtotal: $48.62Shipping & Handling: $2.99Free Shipping: -$2.99Total before tax: $48.62Estimated tax to becollected: $2.92
Grand Total: $51.54
Delivered September 6
Your package was left near the front door or porch.
Nordic Naturals Children's DHA, Strawberry - 8 oz for Kids
Sold by: Nordic Naturals
Supplied by: Other
Return items: Eligible through October 6, 2026
$29.71
DEWALT DWA4970 Steel 1/2" Hp Cylinder Rotary Rasp File
Sold by: Amazon.com
Supplied by: Other
$3.97
3
Johnson's Baby Powder with Cornstarch, 15 oz
Sold by: Amazon.com
$4.98
Back to top
"""


# --------------------------------------------------------------------------- #
# Walmart reader
# --------------------------------------------------------------------------- #


def test_walmart_simple():
    r = orders_walmart.WalmartOrderReader()
    od = r.parse_text(WALMART_SIMPLE)
    assert od.vendor == "walmart"
    assert od.order_no == "200000000000001"
    assert od.date == dt.date(2026, 9, 17)
    assert od.total == 13.48 and od.subtotal == 6.12
    assert od.shipping == 6.99 and od.tax == 0.37
    assert len(od.items) == 1
    assert od.items[0].qty == 1 and od.items[0].price == 6.12
    assert "Goo Gone" in od.items[0].name
    assert od.sanity() == []


def test_walmart_wrapped_name_and_qty():
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_WRAPPED)
    assert od.total == 78.82 and od.seller == "LIRUA Living Store"
    assert len(od.items) == 1 and od.items[0].qty == 4
    # Full wrapped name reconstructed.
    assert "Under Bed Storage" in od.items[0].name
    assert "Organizer Clothes" in od.items[0].name
    assert od.sanity() == []


def test_walmart_savings():
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_SAVINGS)
    assert od.subtotal == 47.99 and od.savings == 6.00
    assert od.total == 44.51 and od.seller == "Ballucci"
    # subtotal - savings + tax == total
    assert od.sanity() == []


# --------------------------------------------------------------------------- #
# Amazon reader
# --------------------------------------------------------------------------- #


def test_amazon_simple():
    od = orders_amazon.AmazonOrderReader().parse_text(AMAZON_SIMPLE)
    assert od.vendor == "amazon"
    assert od.order_no == "11111111111111111"
    assert od.date == dt.date(2026, 9, 18)
    assert od.subtotal == 29.99 and od.tax == 1.80 and od.total == 31.79
    assert len(od.items) == 1 and od.items[0].price == 29.99
    assert "Pampers" in od.items[0].name
    assert od.sanity() == []


def test_amazon_multi_item_qty_and_free_shipping():
    od = orders_amazon.AmazonOrderReader().parse_text(AMAZON_MULTI)
    assert od.total == 51.54 and od.subtotal == 48.62
    assert od.shipping == 0.0  # 2.99 charge netted by 2.99 free-shipping credit
    assert len(od.items) == 3
    by_price = {round(i.price, 2) for i in od.items}
    assert 29.71 in by_price and 3.97 in by_price
    # qty-3 item: unit $4.98 -> extended $14.94
    qty3 = next(i for i in od.items if i.qty == 3)
    assert qty3.price == 14.94
    assert od.sanity() == []  # items sum to subtotal, reconciles to total


# --------------------------------------------------------------------------- #
# Routing + slug
# --------------------------------------------------------------------------- #


def test_reader_routing_by_filename():
    assert orders.order_reader_for("walmart-order.pdf", b"").vendor == "walmart"
    assert orders.order_reader_for("Order Details 3 amazon.pdf", b"").vendor == "amazon"
    assert orders.order_reader_for("random.txt", b"") is None


def test_order_slug_uses_qty_units():
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_WRAPPED)
    # 1 line item, qty 4 -> "4items"
    assert orders.order_slug(od) == "2026-08-01-walmart-4items-78.82"


# --------------------------------------------------------------------------- #
# Matcher + split service (isolated store)
# --------------------------------------------------------------------------- #


def _row(tid, name, amount, date="2026-08-01", cat="Uncategorized", **extra):
    d = {"transaction_id": tid, "date": date,
         "year": int(date[:4]), "month": int(date[5:7]),
         "name": name, "merchant": "", "amount": amount,
         "bank": "usaa", "account_id": "a", "account_mask": "0002", "category": cat}
    d.update(extra)
    return d


def test_matcher_vendor_named_is_ready(isolated_store):
    ts.save_transactions([_row("w1", "Walmart", 78.82, "2026-08-01")])
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_WRAPPED)
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    assert plan.matched_txn_id == "w1"
    assert round(sum(c.amount for c in plan.children), 2) == 78.82


def test_matcher_generic_row_needs_confirm(isolated_store):
    # Same amount/date but NOT vendor-named -> needs-confirm, not auto-ready.
    ts.save_transactions([_row("p1", "PAYPAL PURCHASE", 31.79, "2026-09-18",
                               account_mask="0000")])
    od = orders_amazon.AmazonOrderReader().parse_text(AMAZON_SIMPLE)
    plan = order_service.plan_split(od)
    assert plan.status == "needs-confirm"
    assert plan.matched_txn_id == "p1"


def test_matcher_excludes_payment_rows(isolated_store):
    # A credit-card payment at the same amount must NOT be a candidate.
    ts.save_transactions([_row("c1", "CHASE CREDIT CRD EPAY", 31.79, "2026-09-18")])
    od = orders_amazon.AmazonOrderReader().parse_text(AMAZON_SIMPLE)
    plan = order_service.plan_split(od)
    assert plan.status == "no-match"


def test_matcher_excludes_backwards_date(isolated_store):
    # Charge dated well BEFORE the order is not this order.
    ts.save_transactions([_row("b1", "PAYPAL PURCHASE", 31.79, "2026-09-10",
                               account_mask="0000")])
    od = orders_amazon.AmazonOrderReader().parse_text(AMAZON_SIMPLE)  # order 09-18
    plan = order_service.plan_split(od)
    assert plan.status == "no-match"


def test_matcher_prefers_card_over_netted_paypal(isolated_store):
    # The Walmart order paid via a card row AND a PayPal purchase that is offset
    # (netted) by a deposit. The matcher must pick the real card row.
    ts.save_transactions([
        _row("card", "Walmart", 78.82, "2026-08-01", account_mask="0002"),
        _row("pp", "PreApproved Payment Bill User Payment", -78.82, "2026-08-01",
             source="paypal_statement", account_mask="0000"),
        _row("dep", "General Credit Card Deposit", 78.82, "2026-08-01",
             cat="Ignore", offset=True, offsets_id="pp",
             source="paypal_statement", account_mask="0000"),
    ])
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_WRAPPED)
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    assert plan.matched_txn_id == "card"


def test_matcher_ambiguous_tie(isolated_store):
    # Two vendor-named rows, same amount + date -> ambiguous, no guess.
    ts.save_transactions([
        _row("a", "Walmart", 78.82, "2026-08-01"),
        _row("b", "Walmart", 78.82, "2026-08-01"),
    ])
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_WRAPPED)
    plan = order_service.plan_split(od)
    assert plan.status == "ambiguous"
    assert len(plan.candidates) == 2


def test_apply_split_writes_and_is_undoable(isolated_store):
    ts.save_transactions([_row("w1", "Walmart", 44.51, "2026-07-13")])
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_SAVINGS)
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    order_service.apply_split(plan)

    row = {t["transaction_id"]: t for t in ts.load_transactions()}["w1"]
    assert row["category"] == "Split"
    assert round(sum(c["amount"] for c in row["split_children"]), 2) == 44.51
    assert ts.undo() is True
    row = {t["transaction_id"]: t for t in ts.load_transactions()}["w1"]
    assert row["category"] == "Uncategorized" and "split_children" not in row


def test_apply_rejects_unmatched(isolated_store):
    ts.save_transactions([])
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_SIMPLE)
    plan = order_service.plan_split(od)
    assert plan.status == "no-match"
    with pytest.raises(ValueError):
        order_service.apply_split(plan)


def test_proportional_allocation_sums_to_total(isolated_store):
    # Multi-item order: shipping/tax fold into items, children sum to total.
    ts.save_transactions([_row("m1", "Walmart", 51.54, "2026-09-06")])
    od = orders_amazon.AmazonOrderReader().parse_text(AMAZON_MULTI)
    # Re-point vendor match: seed a vendor-named row so status is ready.
    ts.save_transactions([_row("m1", "amazon order", 51.54, "2026-09-06")])
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    assert round(sum(c.amount for c in plan.children), 2) == 51.54
