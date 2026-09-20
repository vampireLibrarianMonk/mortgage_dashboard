"""Order-split service: match an itemized order to a stored transaction and split it.

Ties the order-detail readers to the transaction store. Given an
:class:`OrderDetail` (parsed from a Walmart/Amazon invoice PDF), it:

1. **Matches** the order to the one stored transaction that actually carries the
   spend, by absolute total + date proximity. It deliberately skips rows that
   net out or are excluded (offset/Ignore-categorized), and prefers a row whose
   name/merchant looks like the vendor. Ambiguity is reported, not guessed.
2. **Builds a split plan**: one child per line item, with shipping + tax − savings
   distributed *proportionally* across the items so the children sum to the
   transaction total (fees are counted, not set aside). Each item's category is
   drawn from the existing merchant-rule engine matched on the *item name* (so it
   learns over time); unmatched items default to Uncategorized.
3. **Applies** the split via ``txn_store.split_transaction`` (snapshotted/undoable).

Preview and commit are separate so callers (console/GUI) can show the plan first.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

import txn_store as ts

from . import DATA_START
from .orders import OrderDetail, order_slug

# How far AFTER the order date a matching bank charge may post - and it is
# vendor-specific, because it depends on the payment rail:
#   * PayPal-funded vendors (Walmart): the charge is a PAYPAL PURCHASE that posts
#     to the bank up to ~1 week after the order (PayPal -> bank settlement lag).
#   * Card-funded vendors (Amazon on the Prime Visa): the charge posts within a
#     few days. Amazon amounts repeat (same item re-bought), so a tight window is
#     the main defense against pairing an order with an unrelated same-amount
#     charge - a wide window here re-introduces false matches.
_MATCH_DAYS_AFTER_BY_VENDOR = {"walmart": 7, "amazon": 3}
_DEFAULT_MATCH_DAYS_AFTER = 3
_MATCH_DAYS_BEFORE = 1  # a charge may pre-auth at most 1 day before the order
_AMOUNT_TOLERANCE = 0.01
# Grocery (Whole Foods / Amazon Fresh) final charge drifts from the estimate
# (weight-priced produce, substitutions). Allow the greater of a percent or a
# flat dollar amount - but only on a vendor/alias-named, in-span charge.
_GROCERY_DRIFT_PCT = 0.08
_GROCERY_DRIFT_ABS = 3.00


def _days_after(vendor: str) -> int:
    return _MATCH_DAYS_AFTER_BY_VENDOR.get(vendor.lower(), _DEFAULT_MATCH_DAYS_AFTER)
# Categories that mean "this row does not carry real budget spend" - never split.
_EXCLUDED_MATCH_CATEGORIES = {"Ignore", "Split"}

# A stored row whose name matches any of these is a payment/transfer/deposit, not
# a purchase, and can never be an itemizable order - excluded from candidates.
_NON_PURCHASE_RE = re.compile(
    r"crd\s*epay|credit\s*card\s*payment|card\s*epay|"
    r"\btransfer\b|\bpayroll\b|\bdeposit\b|funds\s*transfer|"
    r"ach\s*(?:debit|transaction)|autopay|bill\s*pay|paid\s*check",
    re.IGNORECASE)


@dataclass
class SplitChildPlan:
    amount: float
    category: str
    note: str  # the item name (+ qty when > 1)


@dataclass
class OrderSplitPlan:
    """What splitting one order would do - computed without writing anything."""

    order: OrderDetail
    matched_txn_id: str | None = None
    matched_txn: dict | None = None
    children: list[SplitChildPlan] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)  # when ambiguous
    status: str = ""  # "ready" | "no-match" | "ambiguous" | "no-total"
    warnings: list[str] = field(default_factory=list)
    # For an order billed as two charges (goods + a separate tip charge): the
    # second parent and its children. The primary matched_txn is the goods charge.
    tip_txn_id: str | None = None
    tip_txn: dict | None = None
    tip_children: list[SplitChildPlan] = field(default_factory=list)

    @property
    def child_dicts(self) -> list[dict]:
        return [{"amount": c.amount, "category": c.category, "note": c.note}
                for c in self.children]

    @property
    def tip_child_dicts(self) -> list[dict]:
        return [{"amount": c.amount, "category": c.category, "note": c.note}
                for c in self.tip_children]


def _txn_name(t: dict) -> str:
    return f"{t.get('name', '')} {t.get('merchant', '')}"


def _charge_date(t: dict) -> dt.date | None:
    """The date the card was actually charged: authorized_date (swipe/ship time)
    when present, else the posted date. Authorized date tracks the order timing
    far better than the posted date (which lags 1-3 days), which is what lets two
    same-priced orders be told apart by when each actually charged."""
    for key in ("authorized_date", "date"):
        v = t.get(key)
        if v:
            try:
                return dt.date.fromisoformat(v)
            except ValueError:
                continue
    return None


import datetime as _dt

# Padding on the charge-date range. A charge can post a day before the order
# (pre-auth) and a few days after delivery (settlement lag).
_PAD_BEFORE = 1
_PAD_AFTER = 3


def _charge_window(order: OrderDetail) -> tuple[dt.date | None, dt.date | None]:
    """The [low, high] date range the bank charge for this order may fall in.

    A retailer can charge anywhere from when the order is placed (charged up
    front) to when it ships/delivers (charged at ship - Subscribe & Save, slow
    ship). So the valid range spans order_date .. delivery_date, padded a day
    before (pre-auth) and a few days after (settlement lag). When there is no
    delivery date, fall back to order_date + the vendor's forward window.
    """
    order_d = order.date
    deliv = order.delivered_date
    if order_d is None and deliv is None:
        return None, None
    if deliv is not None and order_d is not None:
        low = min(order_d, deliv) - _dt.timedelta(days=_PAD_BEFORE)
        high = max(order_d, deliv) + _dt.timedelta(days=_PAD_AFTER)
        return low, high
    anchor = order_d or deliv
    return (anchor - _dt.timedelta(days=_MATCH_DAYS_BEFORE),
            anchor + _dt.timedelta(days=_days_after(order.vendor)))


def _candidate_txns(order: OrderDetail) -> list[dict]:
    """Stored transactions that could plausibly be this order.

    Filters: |amount| == total; category not excluded; not an offset deposit; not
    a payment/transfer/deposit row (by name); and the charge date within the
    window around the anchor (delivery date when known, else order date). The
    date guard rules out coincidental same-amount rows in the wrong timeframe.
    """
    if order.total is None:
        return []
    total = round(order.total, 2)
    low, high = _charge_window(order)
    # Grocery orders (Whole Foods / Amazon Fresh) charge under the store name and
    # the final amount drifts from the estimate (weight/substitutions). Allow a
    # small amount tolerance for those, but REQUIRE the charge to be
    # vendor/alias-named AND dated within the span - the tighter identity guards
    # keep the looser amount from admitting an unrelated same-ish-amount row.
    amt_tol = max(_AMOUNT_TOLERANCE, round(total * _GROCERY_DRIFT_PCT, 2), _GROCERY_DRIFT_ABS) \
        if order.grocery else _AMOUNT_TOLERANCE
    out: list[dict] = []
    for t in ts.load_transactions():
        if t.get("category") in _EXCLUDED_MATCH_CATEGORIES:
            continue
        if t.get("offset"):
            continue
        if _NON_PURCHASE_RE.search(_txn_name(t)):
            continue
        if abs(round(abs(float(t.get("amount", 0.0))), 2) - total) > amt_tol:
            continue
        # For grocery, the looser amount is only safe on a vendor/alias-named row.
        if order.grocery and not _name_matches(order, t):
            continue
        if low is not None and high is not None:
            td = _charge_date(t)  # prefer authorized (charge) date over posted
            if td is not None and not (low <= td <= high):
                continue
        out.append(t)
    return out


def _name_matches(order: OrderDetail, cand: dict) -> bool:
    """True if the charge's name contains the vendor OR any of the order's match
    aliases (e.g. a Whole Foods charge for an Amazon grocery order)."""
    name = _txn_name(cand).lower()
    if order.vendor.lower() in name:
        return True
    return any(alias in name for alias in order.match_names)


def _is_vendor_named(order: OrderDetail, cand: dict) -> bool:
    return _name_matches(order, cand)


def _netted_purchase_ids() -> set[str]:
    """transaction_ids of PayPal purchases that are offset (netted to zero) by a
    matching Credit-Card-Deposit row. These are NOT the real budget spend - the
    standalone bank/card row is - so the matcher deprioritizes them."""
    txns = ts.load_transactions()
    ids = {t["transaction_id"] for t in txns}
    netted: set[str] = set()
    for t in txns:
        if t.get("offset") and t.get("offsets_id") in ids:
            netted.add(t["offsets_id"])
    return netted


def _gap(order: OrderDetail, cand: dict) -> int:
    """Distance (days) from the charge date to the order's expected charge span
    [order_date .. delivery_date]. Zero when the charge falls inside the span;
    otherwise the days to the nearer endpoint. Used for ranking + collisions."""
    cd = _charge_date(cand)
    if cd is None:
        return 999
    dates = [d for d in (order.date, order.delivered_date) if d is not None]
    if not dates:
        return 0
    lo, hi = min(dates), max(dates)
    if cd < lo:
        return (lo - cd).days
    if cd > hi:
        return (cd - hi).days
    return 0


def _rank(order: OrderDetail, cand: dict, netted: set[str]) -> tuple:
    """Sort key; lower is better. Prefer (1) a row that carries real net spend
    (not a netted PayPal purchase), (2) a vendor-named row, (3) closest to the
    anchor date."""
    is_netted = 1 if cand["transaction_id"] in netted else 0
    vendor_hit = 0 if _name_matches(order, cand) else 1
    return (is_netted, vendor_hit, _gap(order, cand))


def _allocate_children(order: OrderDetail, fallback_category: str = "Uncategorized",
                       target_total: float | None = None) -> list[SplitChildPlan]:
    """One child per line item; shipping + tax - savings split EQUALLY across the
    line items (each item carries the same share of fees, regardless of price) so
    the children sum to `target_total` (defaults to the order total).

    `target_total` lets a grocery order's children sum to the ACTUAL bank charge
    when it drifted from the estimate (weight/substitution). The per-item fee
    bucket (target - item_sum) absorbs the drift; the last child takes the
    rounding remainder so the children sum exactly to the target.

    Equal (not proportional) by design: for a household budget the fee amounts are
    small and it keeps the split simple and consistent for both shipping and tax.

    Category precedence per item: (1) an item-name merchant rule if one matches,
    else (2) the fallback - normally the parent transaction's existing category,
    so splitting an already-categorized row (e.g. a Household Walmart charge)
    keeps that categorization on its items instead of dropping to Uncategorized.
    """
    total = round(target_total if target_total is not None else (order.total or 0.0), 2)
    items = order.items
    rules = ts.load_rules()
    n = len(items)

    base_sum = round(sum(i.price for i in items), 2)
    # Fees net of discounts (shipping + tax - savings), spread EQUALLY per item.
    extra = round(total - base_sum, 2)
    per_item_fee = extra / n if n else 0.0

    children: list[SplitChildPlan] = []
    running = 0.0
    for idx, it in enumerate(items):
        # Last child absorbs any rounding remainder so children sum exactly.
        if idx == n - 1:
            amount = round(total - running, 2)
        else:
            amount = round(it.price + per_item_fee, 2)
            running = round(running + amount, 2)
        cat = _category_for_item(it.name, rules) or fallback_category
        note = it.name if it.qty <= 1 else f"{it.name} (x{it.qty})"
        children.append(SplitChildPlan(amount=amount, category=cat, note=note))
    return children


def _rewards_child(order: OrderDetail) -> SplitChildPlan:
    """A negative "Rewards" child carrying the redeemed points as a funding
    source. Added when points paid for part of the order so the item children
    (full consumed value) plus this negative line sum to the actual card charge -
    the budget then shows full consumption AND a rewards income line."""
    note = f"redeemed points ({order.vendor} Visa)" if order.vendor == "amazon" \
        else f"redeemed points ({order.vendor})"
    return SplitChildPlan(amount=-round(order.rewards_points, 2), category="Rewards", note=note)


def _fallback_category(txn: dict) -> str:
    """Category a split child inherits when no item-rule matches: the parent's
    existing category, unless it is a non-informative state."""
    cat = txn.get("category")
    if cat and cat not in ("Uncategorized", "Split"):
        return cat
    return "Uncategorized"


def _category_for_item(item_name: str, rules: list[dict]) -> str | None:
    """Reuse the existing merchant-rule engine, matched on the item name, so
    itemized splits learn from the same `cat` rules the user already builds."""
    pseudo = {"name": item_name, "merchant": ""}
    return ts._match_rule(pseudo, rules)


def _applied_order_nos() -> set[str]:
    """Order numbers already itemized (stamped on an existing Split parent). An
    order is itemized once - re-planning it must not re-match it to a different
    (wrong) charge after its real charge is already a Split."""
    return {t["split_order_no"] for t in ts.load_transactions() if t.get("split_order_no")}


def plan_split(order: OrderDetail) -> OrderSplitPlan:
    """Match the order to a transaction and build the split plan (writes nothing)."""
    plan = OrderSplitPlan(order=order)
    if order.total is None:
        plan.status = "no-total"
        plan.warnings.append("order has no parseable total")
        return plan

    if order.order_no and order.order_no in _applied_order_nos():
        plan.status = "already-applied"
        plan.warnings.append(f"order {order.order_no} is already itemized")
        return plan

    cands = _candidate_txns(order)
    if not cands:
        plan.status = "no-match"
        plan.warnings.append(
            f"no stored transaction for {order.vendor} total ${order.total:.2f} "
            f"near {order.date} - sync/import the transaction first")
        return plan

    netted = _netted_purchase_ids()
    cands.sort(key=lambda c: _rank(order, c, netted))
    best = cands[0]
    plan.candidates = cands

    # Ambiguous only if two candidates tie on the ranking key.
    if len(cands) > 1 and _rank(order, cands[1], netted) == _rank(order, best, netted):
        plan.status = "ambiguous"
        plan.warnings.append(f"{len(cands)} transactions match ${order.total:.2f}; pick one")
        return plan

    plan.matched_txn = best
    plan.matched_txn_id = best["transaction_id"]
    charge_amt = round(abs(float(best.get("amount", 0.0))), 2)
    if order.rewards_points > 0:
        # Points paid for part of the order. Item children carry the FULL consumed
        # value; a negative Rewards child brings the total down to the actual card
        # charge. Budget then shows full consumption + a rewards income line.
        plan.children = _allocate_children(order, _fallback_category(best),
                                           target_total=order.consumed_value)
        plan.children.append(_rewards_child(order))
        plan.warnings.append(
            f"funded by ${charge_amt:.2f} cash + ${order.rewards_points:.2f} reward points "
            f"(full consumed ${order.consumed_value:.2f})")
    else:
        # For a grocery order the charge can drift from the estimate; scale the
        # split so children sum to the ACTUAL charge, not the PDF estimate.
        target = charge_amt if order.grocery else None
        plan.children = _allocate_children(order, _fallback_category(best), target_total=target)
        if order.grocery and abs(charge_amt - round(order.total, 2)) > _AMOUNT_TOLERANCE:
            plan.warnings.append(
                f"grocery amount drift: estimate ${order.total:.2f} -> charged "
                f"${charge_amt:.2f} (weight/substitution); split scaled to the charge")
    plan.warnings.extend(order.sanity())

    # Confidence: a vendor-named row (e.g. "Walmart") is a strong match. A generic
    # row (opaque "PAYPAL PURCHASE", a bare card line) matched only by amount+date
    # is weak - surface it for confirmation rather than auto-applying, so an
    # unrelated same-amount charge is never silently split.
    if _is_vendor_named(order, best):
        plan.status = "ready"
    else:
        plan.status = "needs-confirm"
        plan.warnings.append(
            f"matched {best.get('name','?')[:30]} by amount+date only (not named "
            f"'{order.vendor}') - confirm this is the right transaction")
    return plan


def plan_manual_split(order: OrderDetail, transaction_id: str) -> OrderSplitPlan:
    """Build a split plan against a SPECIFIC transaction, bypassing the matcher.

    For the case where the user knows the right transaction but the auto-matcher
    won't pair them (e.g. an Amazon item that shipped - and so was charged - well
    after the order date, outside the window). Still validates that the chosen
    transaction's amount equals the order total, so a typo can't split the wrong
    amount. Status "ready" on success, else no-match/no-total.
    """
    plan = OrderSplitPlan(order=order)
    if order.total is None:
        plan.status = "no-total"
        plan.warnings.append("order has no parseable total")
        return plan
    by_id = {t["transaction_id"]: t for t in ts.load_transactions()}
    txn = by_id.get(transaction_id)
    if txn is None:
        plan.status = "no-match"
        plan.warnings.append(f"no transaction with id {transaction_id}")
        return plan
    if abs(round(abs(float(txn.get("amount", 0.0))), 2) - round(order.total, 2)) > _AMOUNT_TOLERANCE:
        plan.status = "no-match"
        plan.warnings.append(
            f"transaction amount {txn.get('amount')} != order total {order.total} "
            "- refusing to split a mismatched amount")
        return plan
    plan.matched_txn = txn
    plan.matched_txn_id = transaction_id
    plan.children = _allocate_children(order, _fallback_category(txn))
    plan.warnings.extend(order.sanity())
    plan.status = "ready"
    return plan


def is_fully_points_funded(order: OrderDetail) -> bool:
    """True if reward points covered the entire order (grand total ~ $0), so no
    card charge exists in any bank feed to split."""
    return (order.rewards_points > 0 and order.total is not None
            and round(order.total, 2) <= _AMOUNT_TOLERANCE)


def _points_txn_id(order: OrderDetail) -> str:
    return f"points_{order.vendor}_{order.order_no or order_slug(order)}"


def plan_points_purchase(order: OrderDetail) -> OrderSplitPlan:
    """Build a split plan for a 100%-points order as a SYNTHETIC $0 transaction.

    These orders never hit a card ($0 cash), so there is no bank row to match.
    We record a $0 transaction (id 'points_<vendor>_<order#>', stable so re-runs
    dedupe) whose children are the full-value items plus a negative Rewards child
    equal to the points - summing to $0. The budget then reflects the goods
    consumed and the reward points that funded them, with no cash outflow.
    """
    plan = OrderSplitPlan(order=order)
    if not is_fully_points_funded(order):
        plan.status = "no-match"
        plan.warnings.append("not a fully-points-funded order")
        return plan
    if order.order_no and order.order_no in _applied_order_nos():
        plan.status = "already-applied"
        plan.warnings.append(f"order {order.order_no} is already itemized")
        return plan
    # children: full consumed value in item categories + a negative Rewards child
    # equal to the points -> sums to $0.
    plan.children = _allocate_children(order, target_total=order.consumed_value)
    plan.children.append(_rewards_child(order))
    plan.matched_txn_id = _points_txn_id(order)
    plan.matched_txn = None  # synthetic - created at apply time
    plan.warnings.extend(order.sanity())
    plan.warnings.append(
        f"100% reward points (${order.rewards_points:.2f}); recorded as a $0 "
        f"points-purchase (consumed ${order.consumed_value:.2f})")
    plan.status = "points-purchase"
    return plan


def apply_points_purchase(plan: OrderSplitPlan) -> dict:
    """Create the synthetic $0 transaction for a 100%-points order and split it.
    Snapshots first. Idempotent via the stable synthetic id (upsert dedupes)."""
    if plan.status != "points-purchase" or not plan.matched_txn_id:
        raise ValueError(f"cannot apply points-purchase: status={plan.status}")
    order = plan.order
    d = order.date or DATA_START
    synth = {
        "transaction_id": plan.matched_txn_id,
        "date": d.isoformat(),
        "authorized_date": d.isoformat(),
        "year": d.year, "month": d.month,
        "name": f"{order.vendor.title()} order (reward points)",
        "merchant": order.vendor,
        "amount": 0.0,
        "bank": "rewards",
        "account_id": None, "account_mask": None,
        "source": "points_purchase",
    }
    ts.snapshot()
    ts.upsert_transactions([synth])  # dedupes by id if re-run
    return ts.split_transaction(plan.matched_txn_id, plan.child_dicts,
                                order_no=order.order_no)


# --- goods + separate-tip charge (grocery/Fresh delivery) ---------------------
#
# Discovery (grounded in the data): an Amazon order's delivery tip is SOMETIMES
# bundled into the one order charge (then the existing single-charge path already
# spreads it across items like tax) and SOMETIMES billed as its OWN charge named
# "Amazon Tips". Observed only on a Fresh/Whole Foods grocery order so far, where
# the goods also drift (weight/substitution).
#
# Pairing identity (strong, so the date-residual risk is acceptable): pair an
# order (tip > 0) with a separate tip charge only when a charge named "Amazon
# Tips" exists whose amount EQUALS order.tip to the cent AND is dated within the
# charge window, AND a goods charge also exists for (total - tip) (+/- grocery
# drift) in that window. Then both charges are split; the tip is distributed
# across the SAME item categories (like tax), not left as a standalone line.

_TIP_NAME_RE = re.compile(r"amazon\s*tips", re.IGNORECASE)


def _find_tip_charge(order: OrderDetail) -> dict | None:
    """A separate 'Amazon Tips' charge equal to order.tip, in the charge window,
    not already split/ignored. None if the tip was bundled (no such charge)."""
    tip = round(getattr(order, "tip", 0.0) or 0.0, 2)
    if tip <= 0:
        return None
    low, high = _charge_window(order)
    for t in ts.load_transactions():
        if t.get("category") in _EXCLUDED_MATCH_CATEGORIES:
            continue
        if not _TIP_NAME_RE.search(_txn_name(t)):
            continue
        if abs(round(abs(float(t.get("amount", 0.0))), 2) - tip) > _AMOUNT_TOLERANCE:
            continue
        td = _charge_date(t)
        if low is not None and high is not None and td is not None and not (low <= td <= high):
            continue
        return t
    return None


def _find_goods_charge(order: OrderDetail, goods_total: float) -> dict | None:
    """The goods charge for a split-tip order: amount ~ (total - tip), grocery
    drift allowed, vendor/alias-named when grocery, in-window, not excluded."""
    goods_total = round(goods_total, 2)
    low, high = _charge_window(order)
    amt_tol = max(_AMOUNT_TOLERANCE, round(goods_total * _GROCERY_DRIFT_PCT, 2),
                  _GROCERY_DRIFT_ABS) if order.grocery else _AMOUNT_TOLERANCE
    best = None
    for t in ts.load_transactions():
        if t.get("category") in _EXCLUDED_MATCH_CATEGORIES or t.get("offset"):
            continue
        if _NON_PURCHASE_RE.search(_txn_name(t)) or _TIP_NAME_RE.search(_txn_name(t)):
            continue
        if abs(round(abs(float(t.get("amount", 0.0))), 2) - goods_total) > amt_tol:
            continue
        if order.grocery and not _name_matches(order, t):
            continue
        td = _charge_date(t)
        if low is not None and high is not None and td is not None and not (low <= td <= high):
            continue
        if best is None or _gap(order, t) < _gap(order, best):
            best = t
    return best


def _tip_children(order: OrderDetail, tip_charge_amt: float,
                  item_children: list[SplitChildPlan]) -> list[SplitChildPlan]:
    """Distribute the tip charge across the SAME item categories as the goods
    (proportional to each item child's amount), so the tip lands like tax rather
    than as a standalone line. Children sum exactly to the tip charge."""
    tip_charge_amt = round(tip_charge_amt, 2)
    base = round(sum(c.amount for c in item_children), 2) or 1.0
    out: list[SplitChildPlan] = []
    running = 0.0
    n = len(item_children)
    for idx, ch in enumerate(item_children):
        if idx == n - 1:
            amt = round(tip_charge_amt - running, 2)
        else:
            amt = round(tip_charge_amt * (ch.amount / base), 2)
            running = round(running + amt, 2)
        out.append(SplitChildPlan(amount=amt, category=ch.category, note=f"tip: {ch.note}"))
    return out


def plan_grocery_tip_split(order: OrderDetail) -> OrderSplitPlan:
    """Plan a two-charge split for an order billed as goods + a separate tip.

    Only used when the single-charge matcher found nothing and the order has a
    tip that was billed separately (a matching 'Amazon Tips' charge exists). The
    goods charge is itemized (drift-scaled for grocery); the tip charge is split
    across the same item categories so the tip is spread like tax.
    """
    plan = OrderSplitPlan(order=order)
    if order.total is None:
        plan.status = "no-total"
        return plan
    if order.order_no and order.order_no in _applied_order_nos():
        plan.status = "already-applied"
        plan.warnings.append(f"order {order.order_no} is already itemized")
        return plan
    tip = round(getattr(order, "tip", 0.0) or 0.0, 2)
    if tip <= 0:
        plan.status = "no-match"
        return plan
    tip_charge = _find_tip_charge(order)
    if tip_charge is None:
        plan.status = "no-match"  # tip was bundled (or no tip charge synced yet)
        return plan
    goods_charge = _find_goods_charge(order, round(order.total, 2) - tip)
    if goods_charge is None:
        plan.status = "no-match"
        plan.warnings.append(
            f"found a ${tip:.2f} tip charge but no goods charge near "
            f"${round(order.total,2)-tip:.2f} - not itemizing half an order")
        return plan

    goods_amt = round(abs(float(goods_charge["amount"])), 2)
    tip_amt = round(abs(float(tip_charge["amount"])), 2)
    # Goods items scaled to the ACTUAL goods charge (grocery drift).
    plan.matched_txn = goods_charge
    plan.matched_txn_id = goods_charge["transaction_id"]
    plan.children = _allocate_children(order, _fallback_category(goods_charge),
                                       target_total=goods_amt)
    # Tip charge -> spread across the same item categories.
    plan.tip_txn = tip_charge
    plan.tip_txn_id = tip_charge["transaction_id"]
    plan.tip_children = _tip_children(order, tip_amt, plan.children)
    plan.warnings.extend(order.sanity())
    plan.warnings.append(
        f"billed as goods ${goods_amt:.2f} + separate tip ${tip_amt:.2f}; tip "
        f"spread across item categories")
    if abs(goods_amt - (round(order.total, 2) - tip)) > _AMOUNT_TOLERANCE:
        plan.warnings.append(
            f"grocery drift on goods: estimate ${round(order.total,2)-tip:.2f} -> "
            f"charged ${goods_amt:.2f}; items scaled to the charge")
    plan.status = "ready-tip-split"
    return plan


def apply_grocery_tip_split(plan: OrderSplitPlan) -> list[dict]:
    """Split BOTH the goods charge and the tip charge (one snapshot). Both parents
    are stamped with the order_no so neither is ever re-matched."""
    if plan.status != "ready-tip-split" or not plan.matched_txn_id or not plan.tip_txn_id:
        raise ValueError(f"cannot apply tip-split: status={plan.status}")
    order = plan.order
    ts.snapshot()
    a = ts.split_transaction(plan.matched_txn_id, plan.child_dicts, order_no=order.order_no)
    b = ts.split_transaction(plan.tip_txn_id, plan.tip_child_dicts, order_no=order.order_no)
    return [a, b]


_APPLICABLE = {"ready", "needs-confirm"}


def apply_split(plan: OrderSplitPlan) -> dict:
    """Apply a plan to the store (snapshot first, so `undo` reverts it).

    Accepts "ready" (vendor-named, high confidence) and "needs-confirm" (matched
    by amount+date only) - the caller applying a needs-confirm plan is the
    confirmation. Rejects no-match/ambiguous/no-total.
    """
    if plan.status not in _APPLICABLE or not plan.matched_txn_id:
        raise ValueError(f"cannot apply split: status={plan.status}")
    ts.snapshot()
    return ts.split_transaction(plan.matched_txn_id, plan.child_dicts,
                                order_no=plan.order.order_no)


@dataclass
class BatchResult:
    """Outcome of a collision-guarded batch apply/preview."""
    applied: list = field(default_factory=list)      # (order, plan) actually split
    collided: list = field(default_factory=list)     # (order, plan) lost a collision
    skipped: list = field(default_factory=list)      # (order, plan) not ready/needs-confirm
    errors: list = field(default_factory=list)        # (order, message)


def _collision_gap(plan: OrderSplitPlan) -> int:
    """Gap from the matched charge to the order's anchor (delivery date when
    known, else order date), for picking the best claimant."""
    if not plan.matched_txn:
        return 999
    return _gap(plan.order, plan.matched_txn)


def resolve_batch(plans: list[OrderSplitPlan]) -> BatchResult:
    """Resolve a set of plans so each transaction is claimed at most once.

    When two orders match the same transaction (repeat-priced purchases where only
    one charge is in the matcher's window), the one with the closer order->charge
    date wins; the other is set aside as a collision for manual pairing rather
    than double-splitting the same charge. Writes nothing.
    """
    res = BatchResult()
    claimants: dict[str, OrderSplitPlan] = {}
    for plan in plans:
        if plan.status not in _APPLICABLE or not plan.matched_txn_id:
            res.skipped.append((plan.order, plan))
            continue
        tid = plan.matched_txn_id
        cur = claimants.get(tid)
        if cur is None:
            claimants[tid] = plan
        else:
            # keep the closer-dated match; bump the other to collided
            if _collision_gap(plan) < _collision_gap(cur):
                res.collided.append((cur.order, cur))
                claimants[tid] = plan
            else:
                res.collided.append((plan.order, plan))
    res.applied = [(p.order, p) for p in claimants.values()]
    return res


def batch_apply(plans: list[OrderSplitPlan]) -> BatchResult:
    """Collision-guard a set of plans, then apply the winners in ONE snapshot.

    A single ts.snapshot() wraps the whole batch, so one `undo` reverts every
    split applied here. Collisions and non-applicable plans are reported, not
    written. Returns the BatchResult (with any per-row errors captured).
    """
    res = resolve_batch(plans)
    if not res.applied:
        return res
    ts.snapshot()
    for order, plan in list(res.applied):
        try:
            ts.split_transaction(plan.matched_txn_id, plan.child_dicts,
                                 order_no=order.order_no)
        except Exception as e:  # noqa: BLE001
            res.errors.append((order, f"{type(e).__name__}: {e}"))
    return res
