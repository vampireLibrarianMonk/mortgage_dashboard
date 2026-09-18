"""Tests for the encrypted transaction/rule store and its categorization engine.

All tests run against the isolated tmp store (see conftest.isolated_store), so the
real financial data and Windows Credential Manager are never touched.
"""
import txn_store as ts

# --- round-trip / encryption ---------------------------------------------------

def test_load_empty_store_returns_empty_list():
    assert ts.load_transactions() == []
    assert ts.load_rules() == []


def test_save_and_load_roundtrip(make_txn):
    txns = [make_txn("t1", "Costco", 50.0)]
    ts.save_transactions(txns)
    loaded = ts.load_transactions()
    assert loaded == txns


def test_data_is_encrypted_on_disk(make_txn):
    ts.save_transactions([make_txn("t1", "SECRETMERCHANT", 12.34)])
    raw = ts.TXN_PATH.read_bytes()
    # The plaintext merchant name must not appear in the encrypted file.
    assert b"SECRETMERCHANT" not in raw


# --- upsert: dedup, backfill, rebucket -----------------------------------------

def test_upsert_adds_new_and_dedups_by_id(make_txn):
    added, skipped = ts.upsert_transactions(
        [make_txn("t1", "A", 1.0, raw=True), make_txn("t2", "B", 2.0, raw=True)]
    )
    assert (added, skipped) == (2, 0)
    # Re-upsert same ids: all skipped.
    added, skipped = ts.upsert_transactions(
        [make_txn("t1", "A", 1.0, raw=True), make_txn("t2", "B", 2.0, raw=True)]
    )
    assert (added, skipped) == (0, 2)
    assert len(ts.load_transactions()) == 2


def test_upsert_new_txn_defaults_to_uncategorized(make_txn):
    ts.upsert_transactions([make_txn("t1", "Mystery", 9.0, raw=True)])
    assert ts.load_transactions()[0]["category"] == "Uncategorized"


def test_upsert_applies_existing_rule_to_new_txn(make_txn):
    ts.add_rule("costco", "Household")
    ts.upsert_transactions([make_txn("t1", "Costco Wholesale", 80.0, raw=True)])
    assert ts.load_transactions()[0]["category"] == "Household"


def test_upsert_backfills_missing_metadata_without_touching_category(make_txn):
    # Seed a known txn lacking account metadata, hand-categorized.
    seed = make_txn("t1", "Shell", 40.0)
    seed["category"] = "Vehicle"
    seed["account_mask"] = None
    ts.save_transactions([seed])
    # Re-sync brings the same id with metadata now present.
    incoming = make_txn("t1", "Shell", 40.0, account_mask="9999")
    added, skipped = ts.upsert_transactions([incoming])
    assert (added, skipped) == (0, 1)
    row = ts.load_transactions()[0]
    assert row["account_mask"] == "9999"      # backfilled
    assert row["category"] == "Vehicle"        # user category preserved


def test_upsert_rebuckets_year_month_from_authorized_date(make_txn):
    # Known txn bucketed in September (posted date).
    seed = make_txn("t1", "Circle Auto", 100.0, date="2026-09-01", year=2026, month=9)
    seed["category"] = "Vehicle"
    ts.save_transactions([seed])
    # Re-sync supplies an earlier swipe month via year/month (derived upstream).
    incoming = make_txn("t1", "Circle Auto", 100.0, year=2026, month=8,
                        authorized_date="2026-08-31")
    ts.upsert_transactions([incoming])
    row = ts.load_transactions()[0]
    assert (row["year"], row["month"]) == (2026, 8)   # re-bucketed to swipe month
    assert row["category"] == "Vehicle"                # category untouched


# --- rule matching + specificity -----------------------------------------------

def test_add_rule_applies_to_all_matching(make_txn):
    ts.save_transactions([
        make_txn("t1", "Costco", 10.0),
        make_txn("t2", "Costco Gas", 30.0),
        make_txn("t3", "Target", 5.0),
    ])
    n = ts.add_rule("costco", "Household")
    assert n == 2  # both Costco rows
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    assert cats == {"t1": "Household", "t2": "Household", "t3": "Uncategorized"}


def test_longer_pattern_wins_over_shorter(make_txn):
    ts.save_transactions([
        make_txn("t1", "Costco", 10.0),
        make_txn("t2", "Costco Gas", 30.0),
    ])
    ts.add_rule("costco", "Household")
    ts.add_rule("costco gas", "Vehicle")
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    # The more specific "costco gas" wins for t2; plain "costco" keeps t1.
    assert cats == {"t1": "Household", "t2": "Vehicle"}


def test_account_scoped_rule_beats_textonly(make_txn):
    ts.save_transactions([
        make_txn("t1", "USAA FUNDS TRANSFER", 100.0, account_mask="0000"),
        make_txn("t2", "USAA FUNDS TRANSFER", 100.0, account_mask="0001"),
    ])
    ts.add_rule("usaa funds transfer", "Ignore")            # text-only
    ts.add_rule("usaa funds transfer", "Income", account_mask="0001")  # scoped
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    assert cats == {"t1": "Ignore", "t2": "Income"}  # scoped wins on 0001 only


def test_scoped_rule_only_touches_its_account(make_txn):
    ts.save_transactions([
        make_txn("t1", "TRANSFER TO SAVINGS", 500.0, account_mask="0003"),
        make_txn("t2", "TRANSFER TO SAVINGS", 500.0, account_mask="0005"),
    ])
    n = ts.add_rule("transfer to savings", "Ignore", account_mask="0003")
    assert n == 1
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    assert cats == {"t1": "Ignore", "t2": "Uncategorized"}


def test_add_rule_replaces_same_key(make_txn):
    ts.save_transactions([make_txn("t1", "Netflix", 20.0)])
    ts.add_rule("netflix", "Household")
    ts.add_rule("netflix", "Discretionary")  # same (pattern, no-mask) key -> replace
    rules = ts.load_rules()
    netflix_rules = [r for r in rules if r["pattern"] == "netflix"]
    assert len(netflix_rules) == 1
    assert netflix_rules[0]["category"] == "Discretionary"
    assert ts.load_transactions()[0]["category"] == "Discretionary"


# --- remove_rule: re-resolve + fallback ----------------------------------------

def test_remove_rule_falls_back_to_uncategorized(make_txn):
    ts.save_transactions([make_txn("t1", "Costco", 10.0)])
    ts.add_rule("costco", "Household")
    assert ts.load_transactions()[0]["category"] == "Household"
    ok = ts.remove_rule("costco")
    assert ok is True
    assert ts.load_transactions()[0]["category"] == "Uncategorized"


def test_remove_rule_reresolves_to_next_best_rule(make_txn):
    ts.save_transactions([make_txn("t1", "Costco Gas", 30.0)])
    ts.add_rule("costco", "Household")
    ts.add_rule("costco gas", "Vehicle")
    assert ts.load_transactions()[0]["category"] == "Vehicle"
    ts.remove_rule("costco gas")  # remove the specific one
    # Falls back to the still-present broader "costco" rule.
    assert ts.load_transactions()[0]["category"] == "Household"


def test_remove_nonexistent_rule_returns_false():
    assert ts.remove_rule("does-not-exist") is False


# --- set_category: one-off, no rule --------------------------------------------

def test_set_category_no_rule_created(make_txn):
    ts.save_transactions([make_txn("t1", "Transfer to Checking", 70.04)])
    n = ts.set_category("transfer to checking", "Utilities")
    assert n == 1
    assert ts.load_transactions()[0]["category"] == "Utilities"
    assert ts.load_rules() == []  # no rule persisted


def test_set_category_narrows_by_amount(make_txn):
    ts.save_transactions([
        make_txn("t1", "Transfer to Checking", 70.04),
        make_txn("t2", "Transfer to Checking", 500.0),
    ])
    n = ts.set_category("transfer to checking", "Utilities", amount=70.04)
    assert n == 1
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    assert cats == {"t1": "Utilities", "t2": "Uncategorized"}


def test_set_category_narrows_by_account(make_txn):
    ts.save_transactions([
        make_txn("t1", "USAA FUNDS TRANSFER", 100.0, account_mask="0001"),
        make_txn("t2", "USAA FUNDS TRANSFER", 100.0, account_mask="0000"),
    ])
    n = ts.set_category("usaa funds transfer", "Income", account_mask="0001")
    assert n == 1
    cats = {t["transaction_id"]: t["category"] for t in ts.load_transactions()}
    assert cats == {"t1": "Income", "t2": "Uncategorized"}


# --- set_label -----------------------------------------------------------------

def test_set_label_adds_note(make_txn):
    ts.save_transactions([make_txn("t1", "FCWA PAYMENT", 246.99)])
    n = ts.set_label("fcwa", "Fairfax Water")
    assert n == 1
    assert ts.load_transactions()[0]["label"] == "Fairfax Water"


def test_set_label_empty_removes_note(make_txn):
    seed = make_txn("t1", "FCWA PAYMENT", 246.99)
    seed["label"] = "old note"
    ts.save_transactions([seed])
    ts.set_label("fcwa", "")
    assert "label" not in ts.load_transactions()[0]


def test_set_label_scoped_by_account(make_txn):
    ts.save_transactions([
        make_txn("t1", "USAA FUNDS TRANSFER", 100.0, account_mask="0001"),
        make_txn("t2", "USAA FUNDS TRANSFER", 100.0, account_mask="0000"),
    ])
    n = ts.set_label("usaa funds transfer", "internal wash", account_mask="0001")
    assert n == 1
    labels = {t["transaction_id"]: t.get("label") for t in ts.load_transactions()}
    assert labels == {"t1": "internal wash", "t2": None}


# --- snapshot / undo -----------------------------------------------------------

def test_undo_reverts_last_mutation(make_txn):
    ts.save_transactions([make_txn("t1", "Costco", 10.0)])
    ts.snapshot()
    ts.add_rule("costco", "Household")
    assert ts.load_transactions()[0]["category"] == "Household"
    assert ts.undo() is True
    # Reverted: category back to the pre-snapshot state and rule gone.
    assert ts.load_transactions()[0]["category"] == "Uncategorized"
    assert ts.load_rules() == []


def test_undo_with_empty_stack_returns_false():
    assert ts.undo() is False
