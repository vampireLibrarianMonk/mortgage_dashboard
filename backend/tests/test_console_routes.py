"""Tests for the console command processor (parsing + dispatch + aggregation).

Only the pure categorization commands are exercised (cat/set/label/rule/list/
merchants/summary/undo/help). The sync/plaid subcommands are NOT tested here
because they reach the real Plaid API and Windows Credential Manager.

Isolation: the autouse isolated_store fixture (conftest) redirects the txn store
to tmp. This module adds an autouse fixture to redirect the console history log
and the actuals-export target to tmp so the real console_history.log and
plaid_actuals.json are never touched.
"""

import pytest

import actuals as actuals_mod
import console_routes as cr


@pytest.fixture(autouse=True)
def isolated_console(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "HISTORY", tmp_path / "console_history.log")
    # export_actuals (in the actuals module) writes plaid_actuals.json via
    # actuals_path(); redirect that so the real file is never touched.
    out_path = tmp_path / "plaid_actuals.json"
    monkeypatch.setattr(actuals_mod, "actuals_path", lambda: out_path)
    return out_path


def run(cmd: str) -> list[str]:
    """Invoke the console the same way the HTTP endpoint does."""
    return cr.run_command(cr.Command(command=cmd))["output"]


# --- parsing / dispatch --------------------------------------------------------

def test_empty_command_returns_empty():
    assert run("") == []


def test_unknown_command():
    out = run("frobnicate")
    assert len(out) == 1 and "unknown command" in out[0].lower()


def test_help_lists_commands_and_categories():
    out = run("help")
    joined = "\n".join(out)
    assert "commands:" in joined
    assert "cat <merchant text>" in joined
    # categories line includes the user-defined ones.
    assert "Medical" in joined and "ATM Withdrawals" in joined


# --- cat: rule creation, multi-word category, @mask ----------------------------

def test_cat_creates_rule_and_categorizes(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "Costco", 10.0)])
    out = run("cat Costco Household")
    assert "categorized 1" in out[0]
    assert ts.load_transactions()[0]["category"] == "Household"
    assert any(r["pattern"] == "costco" for r in ts.load_rules())


def test_cat_multiword_category(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "REDDICK AND SONS", 7000.0)])
    out = run("cat Reddick And Sons Home Improvement")
    assert "categorized 1" in out[0]
    assert ts.load_transactions()[0]["category"] == "Home Improvement"


def test_cat_rejects_unknown_category(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "Costco", 10.0)])
    out = run("cat Costco Nonsense")
    assert "unknown category" in out[0].lower()
    assert ts.load_transactions()[0]["category"] == "Uncategorized"


def test_cat_with_account_mask_scope(make_txn):
    import txn_store as ts
    ts.save_transactions([
        make_txn("t1", "USAA FUNDS TRANSFER", 100.0, account_mask="0000"),
        make_txn("t2", "USAA FUNDS TRANSFER", 100.0, account_mask="0001"),
    ])
    out = run("cat USAA FUNDS TRANSFER Ignore @0000")
    assert "on account 0000" in out[0]
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    assert cats == {"t1": "Ignore", "t2": "Uncategorized"}


# --- set: one-off, @mask + $amount --------------------------------------------

def test_set_no_rule_created(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "Transfer to Checking", 70.04)])
    out = run("set Transfer to Checking Utilities")
    assert "no rule created" in out[0]
    assert ts.load_transactions()[0]["category"] == "Utilities"
    assert ts.load_rules() == []


def test_set_with_amount_and_mask(make_txn):
    import txn_store as ts
    ts.save_transactions([
        make_txn("t1", "USAA FUNDS TRANSFER", 100.0, account_mask="0001"),
        make_txn("t2", "USAA FUNDS TRANSFER", 999.0, account_mask="0001"),
    ])
    out = run("set USAA FUNDS TRANSFER Income @0001 $100.00")
    assert "1 transaction" in out[0]
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    assert cats == {"t1": "Income", "t2": "Uncategorized"}


# --- label ---------------------------------------------------------------------

def test_label_adds_note(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "FCWA PAYMENT", 246.99)])
    out = run("label FCWA = Fairfax Water")
    assert "labeled 1" in out[0]
    assert ts.load_transactions()[0]["label"] == "Fairfax Water"


def test_label_with_amount_scope(make_txn):
    import txn_store as ts
    ts.save_transactions([
        make_txn("t1", "Paid Check", 318.0),
        make_txn("t2", "Paid Check", 954.0),
    ])
    out = run("label Paid Check = AUMC daycare $318.00")
    assert "labeled 1" in out[0]
    labels = {t["transaction_id"]: t.get("label") for t in ts.load_transactions()}
    assert labels == {"t1": "AUMC daycare", "t2": None}


# --- rule ls / rm --------------------------------------------------------------

def test_rule_ls_shows_scope(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "USAA FUNDS TRANSFER", 100.0, account_mask="0000")])
    run("cat USAA FUNDS TRANSFER Ignore @0000")
    out = run("rule ls")
    assert any("@0000" in line and "Ignore" in line for line in out)


def test_rule_rm(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "Costco", 10.0)])
    run("cat Costco Household")
    out = run("rule rm costco")
    assert out == ["removed."]
    assert ts.load_transactions()[0]["category"] == "Uncategorized"


# --- undo ----------------------------------------------------------------------

def test_undo_via_console(make_txn):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "Costco", 10.0)])
    run("cat Costco Household")
    out = run("undo")
    assert "reverted" in out[0].lower()
    assert ts.load_transactions()[0]["category"] == "Uncategorized"


# --- summary / _export_actuals aggregation -------------------------------------

def test_summary_aggregates_budget_and_unbudgeted(make_txn):
    import txn_store as ts
    ts.save_transactions([
        make_txn("t1", "Mortgage Pmt", 2000.0, category="Mortgage", year=2026, month=7),
        make_txn("t2", "Grocery", 150.0, category="Household", year=2026, month=7),
        make_txn("t3", "Xfer", 500.0, category="Transfer", year=2026, month=7),
        make_txn("t4", "Paycheck", -4000.0, category="Income", year=2026, month=7),
    ])
    out = run("summary")
    joined = "\n".join(out)
    # Budget categories appear; Income is excluded from the per-category budget
    # totals (it is not a spend bucket).
    assert "Mortgage" in joined
    assert "Household" in joined
    # Transfer shows as unbudgeted outflow.
    assert "unbudgeted" in joined.lower()


# --- budget (month-by-month vs profile targets) --------------------------------

def _fixed_targets(monkeypatch):
    """Pin budget targets so the command doesn't need a saved profile."""
    targets = {"Mortgage": 2000.0, "Household": 500.0, "Utilities": 100.0,
               "Vehicle": 300.0, "ChildCare": 400.0, "PetCare": 50.0,
               "Discretionary": 250.0}
    monkeypatch.setattr(cr, "_budget_targets", lambda: (targets, "123 Test St"))
    return targets


def test_budget_no_profile_message(make_txn, monkeypatch):
    import txn_store as ts
    ts.save_transactions([make_txn("t1", "x", 10.0, category="Household")])
    monkeypatch.setattr(cr, "_budget_targets", lambda: (None, None))
    out = run("budget")
    assert any("no saved profile" in ln.lower() for ln in out)


def test_budget_monthly_table(make_txn, monkeypatch):
    import txn_store as ts
    _fixed_targets(monkeypatch)
    ts.save_transactions([
        make_txn("t1", "Mortgage", 2000.0, category="Mortgage", year=2026, month=7),
        make_txn("t2", "Grocery", 800.0, category="Household", year=2026, month=7),
        make_txn("t3", "Grocery", 300.0, category="Household", year=2026, month=8),
    ])
    out = run("budget")
    text = "\n".join(out)
    assert "Budget vs Actual - monthly" in out[0]
    assert "2026-07" in text and "2026-08" in text
    # July actual = 2000 + 800 = 2800; over the 3600 monthly target -> under
    assert "under" in text


def test_budget_single_month_category_breakdown(make_txn, monkeypatch):
    import txn_store as ts
    _fixed_targets(monkeypatch)
    ts.save_transactions([
        make_txn("t1", "Grocery", 800.0, category="Household", year=2026, month=7),
    ])
    out = run("budget 2026-07")
    text = "\n".join(out)
    assert "2026-07" in out[0]
    assert "Household" in text
    # Household actual 800 vs budget 500 -> +300 over
    assert "+" in text and "TOTAL" in text


def test_budget_split_children_counted(make_txn, monkeypatch):
    import txn_store as ts
    _fixed_targets(monkeypatch)
    # A Split parent contributes via its children, not its own amount.
    ts.save_transactions([
        make_txn("t1", "Amazon", 0.0, category="Split", year=2026, month=7,
                 split_children=[{"amount": 120.0, "category": "Household", "note": "x"},
                                 {"amount": -120.0, "category": "Rewards", "note": "pts"}]),
    ])
    out = run("budget 2026-07")
    text = "\n".join(out)
    # Household child (120) counts; Rewards child excluded (not a budget category).
    assert "Household" in text
    assert "$120.00" in text


def test_budget_unknown_month(make_txn, monkeypatch):
    import txn_store as ts
    _fixed_targets(monkeypatch)
    ts.save_transactions([make_txn("t1", "x", 10.0, category="Household", year=2026, month=7)])
    out = run("budget 2026-99")
    assert any("no actuals for 2026-99" in ln for ln in out)
