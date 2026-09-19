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
from dataclasses import dataclass, field

import txn_store as ts

from .orders import OrderDetail

import re

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

    @property
    def child_dicts(self) -> list[dict]:
        return [{"amount": c.amount, "category": c.category, "note": c.note}
                for c in self.children]


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


def _candidate_txns(order: OrderDetail) -> list[dict]:
    """Stored transactions that could plausibly be this order.

    Filters: |amount| == total; category not excluded; not an offset deposit; not
    a payment/transfer/deposit row (by name); and dated on/after the order (with a
    1-day pre-auth tolerance) up to the forward window. The date-direction guard
    rules out coincidental same-amount rows that predate the order.
    """
    if order.total is None:
        return []
    total = round(order.total, 2)
    days_after = _days_after(order.vendor)
    out: list[dict] = []
    for t in ts.load_transactions():
        if t.get("category") in _EXCLUDED_MATCH_CATEGORIES:
            continue
        if t.get("offset"):
            continue
        if _NON_PURCHASE_RE.search(_txn_name(t)):
            continue
        if abs(round(abs(float(t.get("amount", 0.0))), 2) - total) > _AMOUNT_TOLERANCE:
            continue
        if order.date is not None:
            td = _charge_date(t)  # prefer authorized (charge) date over posted
            if td is not None:
                delta = (td - order.date).days
                if delta < -_MATCH_DAYS_BEFORE or delta > days_after:
                    continue
        out.append(t)
    return out


def _is_vendor_named(order: OrderDetail, cand: dict) -> bool:
    return order.vendor.lower() in _txn_name(cand).lower()


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


def _rank(order: OrderDetail, cand: dict, netted: set[str]) -> tuple:
    """Sort key; lower is better. Prefer (1) a row that carries real net spend
    (not a netted PayPal purchase), (2) a vendor-named row, (3) closest date."""
    is_netted = 1 if cand["transaction_id"] in netted else 0
    name = f"{cand.get('name','')} {cand.get('merchant','')}".lower()
    vendor_hit = 0 if order.vendor.lower() in name else 1
    if order.date is not None:
        cd = _charge_date(cand)
        gap = abs((cd - order.date).days) if cd else 999
    else:
        gap = 0
    return (is_netted, vendor_hit, gap)


def _allocate_children(order: OrderDetail, fallback_category: str = "Uncategorized") -> list[SplitChildPlan]:
    """One child per line item; shipping + tax - savings split EQUALLY across the
    line items (each item carries the same share of fees, regardless of price) so
    the children sum to the order total.

    Equal (not proportional) by design: for a household budget the fee amounts are
    small and it keeps the split simple and consistent for both shipping and tax.
    Any rounding remainder lands on the last child so the children sum exactly.

    Category precedence per item: (1) an item-name merchant rule if one matches,
    else (2) the fallback - normally the parent transaction's existing category,
    so splitting an already-categorized row (e.g. a Household Walmart charge)
    keeps that categorization on its items instead of dropping to Uncategorized.
    """
    total = round(order.total or 0.0, 2)
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


def plan_split(order: OrderDetail) -> OrderSplitPlan:
    """Match the order to a transaction and build the split plan (writes nothing)."""
    plan = OrderSplitPlan(order=order)
    if order.total is None:
        plan.status = "no-total"
        plan.warnings.append("order has no parseable total")
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
    plan.children = _allocate_children(order, _fallback_category(best))
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
    return ts.split_transaction(plan.matched_txn_id, plan.child_dicts)


@dataclass
class BatchResult:
    """Outcome of a collision-guarded batch apply/preview."""
    applied: list = field(default_factory=list)      # (order, plan) actually split
    collided: list = field(default_factory=list)     # (order, plan) lost a collision
    skipped: list = field(default_factory=list)      # (order, plan) not ready/needs-confirm
    errors: list = field(default_factory=list)        # (order, message)


def _collision_gap(plan: OrderSplitPlan) -> int:
    """Days between order and matched charge (for picking the best claimant),
    using the charge's authorized date when present."""
    o, m = plan.order, plan.matched_txn
    if not o.date or not m:
        return 999
    cd = _charge_date(m)
    return abs((cd - o.date).days) if cd else 999


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
            ts.split_transaction(plan.matched_txn_id, plan.child_dicts)
        except Exception as e:  # noqa: BLE001
            res.errors.append((order, f"{type(e).__name__}: {e}"))
    return res
