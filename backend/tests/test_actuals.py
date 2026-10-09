"""Tests for actuals.export_actuals — budget aggregation + the separately-tracked
Initial House Repair ledger.

export_actuals is a pure function: it takes a transaction list and writes the
aggregates JSON to actuals_path(). We redirect actuals_path() to a tmp file so
the real backend/plaid_actuals.json is never touched.
"""
import json

import pytest

import actuals


@pytest.fixture
def export(tmp_path, monkeypatch):
    """Return a helper that runs export_actuals(txns) and gives back the JSON."""
    out = tmp_path / "actuals.json"
    monkeypatch.setattr(actuals, "actuals_path", lambda: out)

    def run(txns):
        actuals.export_actuals(txns)
        return json.loads(out.read_text())

    return run


def _txn(**kw):
    base = {"year": 2026, "month": 7, "date": "2026-07-10", "name": "x",
            "category": "Household", "amount": 100.0}
    base.update(kw)
    return base


# --- budget exclusion ---------------------------------------------------------

def test_initial_house_repair_excluded_from_budget(export):
    data = export([
        _txn(category="Household", amount=120.0),
        _txn(category="Initial House Repair", amount=9046.35, name="Roof"),
    ])
    # The budget month's categories never carry the repair.
    jul = next(m for m in data["months"] if m["month"] == "2026-07")
    assert "Initial House Repair" not in jul["categories"]
    assert jul["categories"]["Household"] == 120.0
    # And it is reported in its own block instead.
    assert data["initial_house_repair"]["total"] == 9046.35


# --- the Initial House Repair block -------------------------------------------

def test_ihr_total_by_year_and_items(export):
    data = export([
        _txn(category="Initial House Repair", amount=9046.35,
             date="2026-09-15", name="American Home Co", label="roof"),
        _txn(category="Initial House Repair", amount=850.0,
             date="2026-07-27", name="Paid Check 2894", label="Sungho Lee"),
        _txn(year=2025, month=11, category="Initial House Repair", amount=1000.0,
             date="2025-11-02", name="Prior year repair", label="fence"),
    ])
    ihr = data["initial_house_repair"]
    assert ihr["total"] == pytest.approx(10896.35)
    assert ihr["count"] == 3
    assert ihr["by_year"] == {"2025": 1000.0, "2026": 9896.35}
    # Items are sorted by date; each carries date/name/amount/label.
    assert [it["date"] for it in ihr["items"]] == ["2025-11-02", "2026-07-27", "2026-09-15"]
    first = ihr["items"][0]
    assert first["name"] == "Prior year repair" and first["label"] == "fence"
    assert first["amount"] == 1000.0


def test_ihr_empty_when_no_repairs(export):
    data = export([_txn(category="Household", amount=50.0)])
    ihr = data["initial_house_repair"]
    assert ihr["total"] == 0.0
    assert ihr["count"] == 0
    assert ihr["items"] == []


# --- split distribution -------------------------------------------------------

def test_ihr_split_child_surfaced_and_sibling_budgeted(export):
    """A split whose children mix a repair and a budget line: the repair child
    shows up as a repair item (with the parent's date/name + child note), its
    amount counts toward the repair total, and the budget sibling still lands in
    its budget category — no double counting of the parent."""
    data = export([
        _txn(
            category="Split", amount=300.0, date="2026-07-05", name="Hardware store",
            split_children=[
                {"category": "Initial House Repair", "amount": 200.0, "note": "light fixture"},
                {"category": "Household", "amount": 100.0, "note": "cleaning supplies"},
            ],
        ),
    ])
    ihr = data["initial_house_repair"]
    assert ihr["total"] == 200.0
    assert ihr["count"] == 1
    item = ihr["items"][0]
    assert item["name"] == "Hardware store"      # parent's name
    assert item["date"] == "2026-07-05"          # parent's date
    assert item["amount"] == 200.0               # child's amount
    assert item["label"] == "light fixture"      # child's note

    # The budget sibling counts; the Split parent's own $300 never does.
    jul = next(m for m in data["months"] if m["month"] == "2026-07")
    assert jul["categories"]["Household"] == 100.0


def test_transfer_still_unbudgeted_not_repair(export):
    """Regression: the existing UNBUDGETED path (Transfer) is untouched by the
    new repair branch."""
    data = export([_txn(category="Transfer", amount=500.0)])
    jul = next(m for m in data["months"] if m["month"] == "2026-07")
    assert jul["unbudgeted_outflow"] == 500.0
    assert data["initial_house_repair"]["total"] == 0.0
