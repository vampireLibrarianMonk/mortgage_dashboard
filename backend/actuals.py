"""Budget-vs-actual aggregation.

Turns the user-categorized transactions into the aggregates-only JSON that the
frontend Budget vs Actual view reads (per-month and per-year category totals,
plus unbudgeted outflow). This is kept separate from the console command layer
so the aggregation logic is independently testable and has no console/router
coupling.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

# The seven monthly budget categories the Budget vs Actual view compares against.
BUDGET_CATEGORIES = [
    "Mortgage", "Household", "Utilities", "Vehicle", "ChildCare", "PetCare", "Discretionary",
]

# Real outflow with no budget line to compare against (internal/person transfers
# the user chose to keep). Income, Ignore, Uncategorized and the various
# tracking-only categories are intentionally excluded from actuals.
UNBUDGETED = ["Transfer"]

# One-time move-in house repairs. Excluded from budget-vs-actual (it is NOT a
# recurring budget line), but unlike the other excluded categories it is tracked
# with its own running grand total + per-line-item detail — a capital-improvement
# / cost-basis ledger that grows as older records are backfilled.
INITIAL_HOUSE_REPAIR = "Initial House Repair"


def actuals_path() -> Path:
    """Location of the aggregates JSON the Budget vs Actual view reads. Factored
    into a helper so tests can redirect it away from the real file."""
    return Path(__file__).resolve().parent / "plaid_actuals.json"


def _category_amounts(t: dict):
    """Yield (category, amount) lines a transaction contributes to actuals.

    A normal transaction contributes one line (its own category + amount). A
    *split* transaction (category "Split" with split_children) contributes one
    line per child - so an itemized order lands in the children's categories, not
    the parent container, without double-counting.
    """
    if t.get("category") == "Split" and t.get("split_children"):
        for child in t["split_children"]:
            yield child.get("category"), float(child.get("amount", 0.0))
    else:
        yield t.get("category"), float(t.get("amount", 0.0))


# Bucket key for repair transactions not yet tagged to a profile/property.
UNASSIGNED_PROFILE = "unassigned"


def _repair_lines(t: dict):
    """Yield each Initial House Repair line a transaction contributes, as
    (amount, item dict). A plain repair txn yields one; a split yields one per
    repair-categorized child (parent's date/name + the child's amount/note)."""
    date = t.get("date", "")
    name = t.get("name", "")
    label = t.get("label", "")
    if t.get("category") == "Split" and t.get("split_children"):
        for child in t["split_children"]:
            if child.get("category") == INITIAL_HOUSE_REPAIR:
                amt = round(float(child.get("amount", 0.0)), 2)
                yield amt, {"date": date, "name": name, "amount": amt,
                            "label": child.get("note", "") or label}
    elif t.get("category") == INITIAL_HOUSE_REPAIR:
        amt = round(float(t.get("amount", 0.0)), 2)
        yield amt, {"date": date, "name": name, "amount": amt, "label": label}


def _repair_block(txns: list[dict]) -> dict:
    """Build the Initial House Repair ledger block for a set of transactions:
    running grand total, per-year totals, sorted line items, and a count."""
    items: list[dict] = []
    by_year: dict[str, float] = defaultdict(float)
    for t in txns:
        y = str(int(t["year"]))
        for amt, item in _repair_lines(t):
            items.append(item)
            by_year[y] += amt
    items.sort(key=lambda it: (it["date"], -it["amount"]))
    return {
        "total": round(sum(by_year.values()), 2),
        "by_year": {y: round(v, 2) for y, v in sorted(by_year.items())},
        "items": items,
        "count": len(items),
    }


def _repair_items(txns: list[dict]) -> list[dict]:
    """Back-compat helper: just the sorted line items (see _repair_block)."""
    return _repair_block(txns)["items"]


def export_actuals(txns: list[dict]) -> None:
    """Write plaid_actuals.json (aggregates only) from user-categorized txns."""
    by_month = defaultdict(lambda: defaultdict(float))
    by_year = defaultdict(lambda: defaultdict(float))
    um, uy = defaultdict(float), defaultdict(float)
    for t in txns:
        y = int(t["year"])
        mk = f"{y:04d}-{int(t['month']):02d}"
        for c, amt in _category_amounts(t):
            if c in BUDGET_CATEGORIES:
                by_month[mk][c] += amt
                by_year[str(y)][c] += amt
            elif c in UNBUDGETED:
                um[mk] += amt
                uy[str(y)] += amt

    def cats(d):
        return {c: round(d.get(c, 0.0), 2) for c in BUDGET_CATEGORIES}

    # Global repair block (grand total across all properties) — kept for
    # back-compat with any caller that reads the flat `initial_house_repair`.
    initial_house_repair = _repair_block(txns)

    # Per-property repair blocks, keyed by profile_id. Repairs with no profile
    # tag fall into the UNASSIGNED bucket so nothing is silently dropped.
    repair_txns: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        is_repair = t.get("category") == INITIAL_HOUSE_REPAIR or (
            t.get("category") == "Split"
            and any(c.get("category") == INITIAL_HOUSE_REPAIR
                    for c in t.get("split_children", []))
        )
        if is_repair:
            repair_txns[t.get("profile_id") or UNASSIGNED_PROFILE].append(t)
    initial_house_repair_by_profile = {
        pid: _repair_block(rows) for pid, rows in repair_txns.items()
    }

    out = {
        "available": True,
        "generated_from_count": len(txns),
        "months": [{"month": mk, "categories": cats(by_month[mk]), "unbudgeted_outflow": round(um.get(mk, 0.0), 2)}
                   for mk in sorted(set(by_month) | set(um))],
        "years": [{"year": y, "categories": cats(by_year[y]), "unbudgeted_outflow": round(uy.get(y, 0.0), 2)}
                  for y in sorted(set(by_year) | set(uy))],
        "initial_house_repair": initial_house_repair,
        "initial_house_repair_by_profile": initial_house_repair_by_profile,
    }
    actuals_path().write_text(json.dumps(out, indent=2))
