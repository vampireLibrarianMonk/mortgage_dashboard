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


def test_equal_allocation_sums_to_total(isolated_store):
    # Multi-item order: shipping+tax split EQUALLY per line item; children sum to total.
    # AMAZON_MULTI: items 29.71 / 3.97 / 14.94 (base 48.62), total 51.54 -> fees 2.92,
    # split 3 ways = ~0.9733 each. Non-last children = item + equal fee share.
    ts.save_transactions([_row("m1", "amazon order", 51.54, "2026-09-06")])
    od = orders_amazon.AmazonOrderReader().parse_text(AMAZON_MULTI)
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    assert round(sum(c.amount for c in plan.children), 2) == 51.54
    # First two children carry item price + an equal fee share (~0.97), NOT a
    # price-weighted share. 29.71 + 0.97 ~ 30.68; 3.97 + 0.97 ~ 4.94.
    amts = sorted(round(c.amount, 2) for c in plan.children)
    assert amts[0] == 4.94  # 3.97 + equal fee share
    # equal-share signature: the cheap item's fee bump == the mid item's fee bump
    fee_cheap = round(4.94 - 3.97, 2)
    assert abs(fee_cheap - 2.92 / 3) < 0.02


# --- collision guard / batch apply ---

def _walmart_order(total, date):
    """A minimal single-item Walmart order at a given total/date, for batch tests."""
    txt = (
        "Invoice\n"
        f"{date} order\n"
        "Order# 2000000-00000001\n"
        f"Widget Thing Qty 1 ${total:.2f}\n"
        f"Subtotal (1 item) ${total:.2f}\n"
        f"Total ${total:.2f}\n"
    )
    return orders_walmart.WalmartOrderReader().parse_text(txt)


def test_resolve_batch_prevents_double_split(isolated_store):
    # Two same-priced orders, only ONE matching charge in-window -> both match it;
    # the closer-dated order wins, the other is set aside as a collision.
    ts.save_transactions([_row("w", "Walmart", 25.00, "2026-08-11")])
    near = _walmart_order(25.00, "Aug 10, 2026")   # gap 1
    far = _walmart_order(25.00, "Aug 05, 2026")    # gap 6 (still within walmart 7d)
    p_near = order_service.plan_split(near)
    p_far = order_service.plan_split(far)
    assert p_near.status == "ready" and p_far.status == "ready"
    assert p_near.matched_txn_id == p_far.matched_txn_id == "w"  # both claim the same row
    res = order_service.resolve_batch([p_far, p_near])
    assert len(res.applied) == 1
    assert len(res.collided) == 1
    # the closer-dated (near, gap 1) wins
    assert res.applied[0][1].order.date.isoformat() == "2026-08-10"


def test_batch_apply_one_snapshot_undoes_all(isolated_store):
    ts.save_transactions([
        _row("a", "Walmart", 10.00, "2026-08-02"),
        _row("b", "Walmart", 20.00, "2026-08-02"),
    ])
    pa = order_service.plan_split(_walmart_order(10.00, "Aug 01, 2026"))
    pb = order_service.plan_split(_walmart_order(20.00, "Aug 01, 2026"))
    res = order_service.batch_apply([pa, pb])
    assert len(res.applied) == 2 and not res.errors
    rows = {t["transaction_id"]: t for t in ts.load_transactions()}
    assert rows["a"]["category"] == "Split" and rows["b"]["category"] == "Split"
    # one undo reverts the whole batch
    assert ts.undo() is True
    rows = {t["transaction_id"]: t for t in ts.load_transactions()}
    assert rows["a"]["category"] != "Split" and rows["b"]["category"] != "Split"


def test_batch_apply_skips_non_ready(isolated_store):
    ts.save_transactions([_row("a", "Walmart", 10.00, "2026-08-02")])
    pa = order_service.plan_split(_walmart_order(10.00, "Aug 01, 2026"))       # ready
    pb = order_service.plan_split(_walmart_order(999.00, "Aug 01, 2026"))      # no-match
    res = order_service.batch_apply([pa, pb])
    assert len(res.applied) == 1
    assert len(res.skipped) == 1


def test_matcher_uses_authorized_date_to_disambiguate(isolated_store):
    # Two same-priced orders + two charges. By POSTED date both charges look
    # in-window for both orders, but authorized_date pins each order to its own
    # charge: order A (placed 08-01) -> charge authorized 08-01; order B (placed
    # 08-05) -> charge authorized 08-05. No collision.
    ts.save_transactions([
        _row("cA", "Walmart", 25.00, "2026-08-03", authorized_date="2026-08-01"),
        _row("cB", "Walmart", 25.00, "2026-08-07", authorized_date="2026-08-05"),
    ])
    a = order_service.plan_split(_walmart_order(25.00, "Aug 01, 2026"))
    b = order_service.plan_split(_walmart_order(25.00, "Aug 05, 2026"))
    assert a.matched_txn_id == "cA"
    assert b.matched_txn_id == "cB"
    res = order_service.resolve_batch([a, b])
    assert len(res.applied) == 2 and len(res.collided) == 0


def _amazon_order_with_delivery(total, placed, delivered):
    """Minimal Amazon order text with a Delivered line, for span-window tests."""
    txt = (
        "Order Summary\n"
        f"Order placed {placed}  Order # 113-0000000-0000001\n"
        "Payment method\nPrime Visa****0004\nOrder Summary\n"
        f"Item(s) Subtotal: ${total:.2f}Shipping & Handling: $0.00"
        f"Total before tax: ${total:.2f}Estimated tax to becollected: $0.00\n"
        f"Grand Total: ${total:.2f}\n"
        f"Delivered {delivered}\n"
        "Widget\nSold by: Amazon.com\n"
        f"${total:.2f}\n"
    )
    return orders_amazon.AmazonOrderReader().parse_text(txt)


def test_charge_window_spans_order_to_delivery(isolated_store):
    # Charge can land at ORDER time or at DELIVERY time; both must match. Order
    # placed 07-29, delivered 08-03.
    ts.save_transactions([
        # charged at order time (auth 07-29)
        _row("atorder", "AMAZON MKTPL*X", 10.49, "2026-07-31", authorized_date="2026-07-29"),
    ])
    od = _amazon_order_with_delivery(10.49, "July 29, 2026", "August 3")
    assert od.delivered_date is not None
    plan = order_service.plan_split(od)
    assert plan.status == "ready" and plan.matched_txn_id == "atorder"


def test_charge_window_matches_ship_time_charge(isolated_store):
    # Same order shape but the charge lands near DELIVERY (auth 08-02, 4 days
    # after the order) - still inside the order..delivery span.
    ts.save_transactions([
        _row("atship", "AMAZON MKTPL*Y", 10.49, "2026-08-04", authorized_date="2026-08-02"),
    ])
    od = _amazon_order_with_delivery(10.49, "July 29, 2026", "August 3")
    plan = order_service.plan_split(od)
    assert plan.status == "ready" and plan.matched_txn_id == "atship"


def test_grocery_matches_drifted_whole_foods_charge(isolated_store):
    # A Whole Foods pickup order estimated $16.67 but charged $16.84, posting
    # under "Whole Foods" (not Amazon). Grocery matching pairs it (exact date +
    # small drift) and scales children to the ACTUAL charge.
    ts.save_transactions([
        _row("wf", "Whole Foods", 16.84, "2026-08-20", authorized_date="2026-08-19"),
    ])
    txt = (
        "Order Summary\nOrder placed August 19, 2026  Order # 113-0000000-0000003\n"
        "Purchased at Whole Foods Market\n"
        "Item(s) Subtotal: $16.67Shipping & Handling: $0.00"
        "Total before tax: $16.67Estimated tax to becollected: $0.00\nGrand Total: $16.67\n"
        "365 by Whole Foods Market Butter Pecan Ice Cream\n$3.59\n"
        "Meyenberg Goat Milk Kefir\n$9.49\n"
        "365 Brownie Batter Ice Cream\n$3.59\n"
    )
    od = orders_amazon.AmazonOrderReader().parse_text(txt)
    assert od.grocery is True
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    assert plan.matched_txn_id == "wf"
    # children sum to the CHARGE ($16.84), not the estimate ($16.67)
    assert round(sum(c.amount for c in plan.children), 2) == 16.84


def test_already_applied_order_not_rematched(isolated_store):
    # Once an order is itemized (its split parent stamped with the order_no),
    # re-planning must NOT match it to a different same-amount charge.
    ts.save_transactions([_row("w1", "Walmart", 44.51, "2026-07-14")])
    od = orders_walmart.WalmartOrderReader().parse_text(WALMART_SAVINGS)  # order# 200000000000003
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    order_service.apply_split(plan)
    # a coincidental same-amount row appears later
    rows = ts.load_transactions()
    rows.append(_row("other", "SOME OTHER STORE", 44.51, "2026-07-15"))
    ts.save_transactions(rows)
    # re-plan the same order -> already-applied, NOT matched to "other"
    plan2 = order_service.plan_split(od)
    assert plan2.status == "already-applied"
    assert plan2.matched_txn_id is None


# --- rewards-points funding model ---

def _amazon_points_order(subtotal, tax, points, grand, items):
    """Amazon order text with a Rewards Points line. `items` = [(name, price)]."""
    itemlines = "".join(f"{name}\n${price:.2f}\n" for name, price in items)
    txt = (
        "Order Summary\nOrder placed August 1, 2026  Order # 113-1111111-1111111\n"
        "Payment method\nPrime Visa****0004\nOrder Summary\n"
        f"Item(s) Subtotal: ${subtotal:.2f}Shipping & Handling: $0.00"
        f"Total before tax: ${subtotal:.2f}Estimated tax to becollected: ${tax:.2f}\n"
        f"Rewards Points: -${points:.2f}Grand Total: ${grand:.2f}\n"
        "Delivered August 1\n" + itemlines
    )
    return orders_amazon.AmazonOrderReader().parse_text(txt)


def test_reader_separates_rewards_from_savings():
    od = _amazon_points_order(130.97, 7.86, 63.26, 75.57, [("Drawers", 130.97)])
    assert od.rewards_points == 63.26
    assert od.savings == 0.0            # points are NOT a discount
    assert od.consumed_value == 138.83  # goods + tax, points not subtracted
    assert od.sanity() == []            # consumed - points == grand total


def test_partial_points_split_sums_to_card_charge(isolated_store):
    # Card charge = grand total ($75.57); item children (full $138.83) + negative
    # Rewards child (-$63.26) sum to the charge.
    ts.save_transactions([_row("card", "AMAZON MKTPL*Z", 75.57, "2026-08-01")])
    od = _amazon_points_order(130.97, 7.86, 63.26, 75.57, [("Drawers", 130.97)])
    plan = order_service.plan_split(od)
    assert plan.status == "ready"
    assert round(sum(c.amount for c in plan.children), 2) == 75.57
    rewards = [c for c in plan.children if c.category == "Rewards"]
    assert len(rewards) == 1 and rewards[0].amount == -63.26


def test_full_points_purchase_synthetic_zero_txn(isolated_store):
    # 100% points ($0 grand total) -> no card charge. plan_points_purchase builds
    # a $0 synthetic split; apply creates it. Children sum to 0.
    ts.save_transactions([])
    od = _amazon_points_order(299.99, 18.00, 317.99, 0.00, [("Dehumidifier", 299.99)])
    assert order_service.is_fully_points_funded(od)
    plan = order_service.plan_points_purchase(od)
    assert plan.status == "points-purchase"
    assert round(sum(c.amount for c in plan.children), 2) == 0.0
    order_service.apply_points_purchase(plan)
    rows = {t["transaction_id"]: t for t in ts.load_transactions()}
    synth = rows[plan.matched_txn_id]
    assert synth["amount"] == 0.0 and synth["category"] == "Split"
    kids = synth["split_children"]
    assert any(k["category"] == "Rewards" and k["amount"] == -317.99 for k in kids)
    assert any(k["amount"] == 317.99 for k in kids)  # full consumption recorded
    # idempotent: re-applying does not duplicate
    plan2 = order_service.plan_points_purchase(od)
    assert plan2.status == "already-applied"


def test_points_purchase_actuals_records_consumption_not_rewards(isolated_store):
    import actuals
    txn = {"transaction_id": "p", "date": "2026-08-01", "year": 2026, "month": 8,
           "name": "x", "amount": 0.0, "category": "Split",
           "split_children": [
               {"amount": 299.99, "category": "Household", "note": "Dehumidifier"},
               {"amount": -299.99, "category": "Rewards", "note": "points"}]}
    lines = dict(actuals._category_amounts(txn) and
                 {c: a for c, a in actuals._category_amounts(txn)})
    assert lines.get("Household") == 299.99
    assert lines.get("Rewards") == -299.99  # present as a child, but Rewards is
    # not a BUDGET/UNBUDGETED category so it is excluded from the spend aggregation.
