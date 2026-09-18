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


def actuals_path() -> Path:
    """Location of the aggregates JSON the Budget vs Actual view reads. Factored
    into a helper so tests can redirect it away from the real file."""
    return Path(__file__).resolve().parent / "plaid_actuals.json"


def export_actuals(txns: list[dict]) -> None:
    """Write plaid_actuals.json (aggregates only) from user-categorized txns."""
    by_month = defaultdict(lambda: defaultdict(float))
    by_year = defaultdict(lambda: defaultdict(float))
    um, uy = defaultdict(float), defaultdict(float)
    for t in txns:
        y = int(t["year"])
        mk = f"{y:04d}-{int(t['month']):02d}"
        c = t["category"]
        if c in BUDGET_CATEGORIES:
            by_month[mk][c] += t["amount"]
            by_year[str(y)][c] += t["amount"]
        elif c in UNBUDGETED:
            um[mk] += t["amount"]
            uy[str(y)] += t["amount"]

    def cats(d):
        return {c: round(d.get(c, 0.0), 2) for c in BUDGET_CATEGORIES}

    out = {
        "available": True,
        "generated_from_count": len(txns),
        "months": [{"month": mk, "categories": cats(by_month[mk]), "unbudgeted_outflow": round(um.get(mk, 0.0), 2)}
                   for mk in sorted(set(by_month) | set(um))],
        "years": [{"year": y, "categories": cats(by_year[y]), "unbudgeted_outflow": round(uy.get(y, 0.0), 2)}
                  for y in sorted(set(by_year) | set(uy))],
    }
    actuals_path().write_text(json.dumps(out, indent=2))
