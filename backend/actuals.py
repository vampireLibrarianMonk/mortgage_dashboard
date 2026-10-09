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


def _repair_items(txns: list[dict]) -> list[dict]:
    """Per-line-item detail for the Initial House Repair ledger.

    One entry per contributing line: a plain repair transaction yields one item;
    a split transaction yields one item per child categorized as a repair (the
    parent's date/name with the child's amount + note). Sorted by date.
    """
    items: list[dict] = []
    for t in txns:
        date = t.get("date", "")
        name = t.get("name", "")
        label = t.get("label", "")
        if t.get("category") == "Split" and t.get("split_children"):
            for child in t["split_children"]:
                if child.get("category") == INITIAL_HOUSE_REPAIR:
                    items.append({
                        "date": date,
                        "name": name,
                        "amount": round(float(child.get("amount", 0.0)), 2),
                        "label": child.get("note", "") or label,
                    })
        elif t.get("category") == INITIAL_HOUSE_REPAIR:
            items.append({
                "date": date,
                "name": name,
                "amount": round(float(t.get("amount", 0.0)), 2),
                "label": label,
            })
    items.sort(key=lambda it: (it["date"], -it["amount"]))
    return items


def export_actuals(txns: list[dict]) -> None:
    """Write plaid_actuals.json (aggregates only) from user-categorized txns."""
    by_month = defaultdict(lambda: defaultdict(float))
    by_year = defaultdict(lambda: defaultdict(float))
    um, uy = defaultdict(float), defaultdict(float)
    repair_by_year: dict[str, float] = defaultdict(float)
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
            elif c == INITIAL_HOUSE_REPAIR:
                repair_by_year[str(y)] += amt

    def cats(d):
        return {c: round(d.get(c, 0.0), 2) for c in BUDGET_CATEGORIES}

    repair_items = _repair_items(txns)
    initial_house_repair = {
        # Running grand total across all years — the headline number that grows as
        # older emails/checks/bank records are backfilled.
        "total": round(sum(repair_by_year.values()), 2),
        "by_year": {y: round(v, 2) for y, v in sorted(repair_by_year.items())},
        "items": repair_items,
        "count": len(repair_items),
    }

    out = {
        "available": True,
        "generated_from_count": len(txns),
        "months": [{"month": mk, "categories": cats(by_month[mk]), "unbudgeted_outflow": round(um.get(mk, 0.0), 2)}
                   for mk in sorted(set(by_month) | set(um))],
        "years": [{"year": y, "categories": cats(by_year[y]), "unbudgeted_outflow": round(uy.get(y, 0.0), 2)}
                  for y in sorted(set(by_year) | set(uy))],
        "initial_house_repair": initial_house_repair,
    }
    actuals_path().write_text(json.dumps(out, indent=2))
