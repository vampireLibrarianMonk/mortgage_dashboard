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
             date="2026-07-27", name="Paid Check 2894",
             vendor="Sungho Lee", work="Drywall repair", source="NFCU check"),
        _txn(year=2025, month=11, category="Initial House Repair", amount=1000.0,
             date="2025-11-02", name="raw", vendor="Fence Co", work="New fence",
             source="card"),
    ])
    ihr = data["initial_house_repair"]
    assert ihr["total"] == pytest.approx(10896.35)
    assert ihr["count"] == 3
    assert ihr["by_year"] == {"2025": 1000.0, "2026": 9896.35}
    # Items are sorted by date; each carries structured vendor/work/source.
    assert [it["date"] for it in ihr["items"]] == ["2025-11-02", "2026-07-27", "2026-09-15"]
    first = ihr["items"][0]
    assert first["vendor"] == "Fence Co"
    assert first["work"] == "New fence"
    assert first["source"] == "card"
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
    assert item["vendor"] == "Hardware store"    # parent's name -> vendor
    assert item["date"] == "2026-07-05"          # parent's date
    assert item["amount"] == 200.0               # child's amount
    assert item["work"] == "light fixture"       # child's note -> work

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


# --- per-profile repair ledger ------------------------------------------------

def test_repair_grouped_by_profile(export):
    data = export([
        _txn(category="Initial House Repair", amount=9046.35, name="Roof A",
             profile_id="aaaa1111"),
        _txn(category="Initial House Repair", amount=500.00, name="Vent A",
             profile_id="aaaa1111", date="2026-07-05"),
        _txn(category="Initial House Repair", amount=300.00, name="Fix B",
             profile_id="bbbb2222"),
    ])
    bp = data["initial_house_repair_by_profile"]
    assert set(bp) == {"aaaa1111", "bbbb2222"}
    assert bp["aaaa1111"]["total"] == pytest.approx(9546.35)
    assert bp["aaaa1111"]["count"] == 2
    assert bp["bbbb2222"]["total"] == pytest.approx(300.0)
    # Global block still carries the grand total across all properties.
    assert data["initial_house_repair"]["total"] == pytest.approx(9846.35)


def test_untagged_repairs_fall_into_unassigned(export):
    data = export([
        _txn(category="Initial House Repair", amount=695.00, name="Inspection"),
        _txn(category="Initial House Repair", amount=400.00, name="Fireplace",
             profile_id="cccc3333"),
    ])
    bp = data["initial_house_repair_by_profile"]
    assert bp["unassigned"]["total"] == pytest.approx(695.0)
    assert bp["cccc3333"]["total"] == pytest.approx(400.0)


def test_profile_with_no_repairs_absent_from_map(export):
    """A profile that has only budget spend never appears in the repair map; the
    endpoint turns a missing profile into an empty skeleton."""
    data = export([_txn(category="Household", amount=120.0, profile_id="dddd4444")])
    assert data["initial_house_repair_by_profile"] == {}
    assert data["initial_house_repair"]["count"] == 0


def test_split_child_repair_grouped_by_parent_profile(export):
    """A split's repair child is attributed to the split parent's profile_id."""
    data = export([
        _txn(
            category="Split", amount=300.0, date="2026-07-05", name="Hardware",
            profile_id="eeee5555",
            split_children=[
                {"category": "Initial House Repair", "amount": 200.0, "note": "fixture"},
                {"category": "Household", "amount": 100.0, "note": "supplies"},
            ],
        ),
    ])
    bp = data["initial_house_repair_by_profile"]
    assert bp["eeee5555"]["total"] == pytest.approx(200.0)
    assert bp["eeee5555"]["items"][0]["work"] == "fixture"


# --- endpoint scoping (GET /plaid/actuals?profile=) ---------------------------

def test_endpoint_scopes_repair_by_profile(tmp_path, monkeypatch):
    """The /plaid/actuals route returns a profile's repair block when ?profile=
    is given, an empty skeleton for an unknown profile, and the global total when
    no profile is passed."""
    from starlette.testclient import TestClient

    import main
    import plaid_routes

    out = tmp_path / "actuals.json"
    monkeypatch.setattr(actuals, "actuals_path", lambda: out)
    monkeypatch.setattr(plaid_routes, "_actuals_path", lambda: out)

    actuals.export_actuals([
        _txn(category="Initial House Repair", amount=9046.35, profile_id="aaaa1111"),
        _txn(category="Initial House Repair", amount=300.00, profile_id="bbbb2222"),
    ])

    client = TestClient(main.app)

    # No param -> global grand total.
    glob = client.get("/plaid/actuals").json()
    assert glob["initial_house_repair"]["total"] == pytest.approx(9346.35)

    # Scoped to a known property.
    a = client.get("/plaid/actuals", params={"profile": "aaaa1111"}).json()
    assert a["initial_house_repair"]["total"] == pytest.approx(9046.35)
    assert a["initial_house_repair"]["count"] == 1

    # Unknown property -> empty skeleton (not another property's data).
    empty = client.get("/plaid/actuals", params={"profile": "nope9999"}).json()
    assert empty["initial_house_repair"] == {
        "total": 0.0, "by_year": {}, "items": [], "count": 0,
    }
