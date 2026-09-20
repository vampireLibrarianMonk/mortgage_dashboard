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


# --- split parents must survive rule re-resolution ----------------------------

def test_add_rule_does_not_clobber_split_parent(make_txn):
    # A Split parent (itemized order) must never be recategorized by a merchant
    # rule - doing so drops the split and double-counts in actuals.
    parent = make_txn("t1", "Walmart", 50.0)
    parent["category"] = "Split"
    parent["split_children"] = [{"amount": 50.0, "category": "Household", "note": "x"}]
    other = make_txn("t2", "Walmart Grocery", 20.0)  # a normal Walmart txn
    ts.save_transactions([parent, other])

    ts.add_rule("walmart", "Household")

    rows = {t["transaction_id"]: t for t in ts.load_transactions()}
    assert rows["t1"]["category"] == "Split"          # parent untouched
    assert rows["t1"]["split_children"]               # children intact
    assert rows["t2"]["category"] == "Household"       # normal txn categorized


def test_remove_rule_does_not_clobber_split_parent(make_txn):
    parent = make_txn("t1", "Target", 30.0)
    parent["category"] = "Split"
    parent["split_children"] = [{"amount": 30.0, "category": "Household", "note": "x"}]
    ts.save_transactions([parent])
    ts.add_rule("target", "Household")   # parent already skipped by add_rule
    ts.remove_rule("target")             # removal must also skip the parent

    row = ts.load_transactions()[0]
    assert row["category"] == "Split"
    assert row["split_children"]


# --- unsplit clears the order stamp (regression) ------------------------------

def test_unsplit_clears_split_order_no(make_txn):
    # A split stamped with an order_no, when unsplit, must NOT keep the stamp -
    # a stale split_order_no would make the already-applied guard skip this row
    # forever, stranding the order so it can't re-match to its real charge.
    ts.save_transactions([make_txn("t1", "Amazon", 36.13)])
    ts.split_transaction("t1", [{"amount": 36.13, "category": "ChildCare", "note": "x"}],
                         order_no="11119355373525811")
    row = ts.load_transactions()[0]
    assert row["category"] == "Split"
    assert row["split_order_no"] == "11119355373525811"

    ts.unsplit_transaction("t1", "Uncategorized")
    row = ts.load_transactions()[0]
    assert row["category"] == "Uncategorized"
    assert "split_children" not in row
    assert "split_order_no" not in row  # the stamp is gone


# --- pending transactions: skip on ingest + reconcile posted-over-pending ------
#
# transactions_get returns BOTH the pending and (later) the posted copy of a
# charge as separate rows. The pending copy has a temporary id, a bare merchant
# name (no reference code), and authorized_date == posted date. Without handling,
# it persists forever next to the posted row - a phantom duplicate that
# double-counts. upsert must (a) never store a pending row, and (b) when a posted
# row arrives carrying pending_transaction_id, drop the superseded pending row.


def test_upsert_skips_pending_transaction(make_txn):
    added, skipped = ts.upsert_transactions(
        [make_txn("p1", "Amazon.com", 36.13, raw=True, pending=True)]
    )
    assert (added, skipped) == (0, 1)
    assert ts.load_transactions() == []  # nothing stored


def test_upsert_stores_posted_transaction_normally(make_txn):
    added, skipped = ts.upsert_transactions(
        [make_txn("t1", "Amazon.com*ABC", 36.13, raw=True, pending=False)]
    )
    assert (added, skipped) == (1, 0)
    assert ts.load_transactions()[0]["transaction_id"] == "t1"


def test_posted_supersedes_stored_pending_row(make_txn):
    # A pending row slipped in from an earlier sync (before this fix).
    ts.save_transactions([make_txn("pending_id", "Amazon.com", 36.13)])
    # The posted copy arrives, pointing back at the pending id.
    posted = make_txn("posted_id", "Amazon.com*5R0Q13D01", 36.13, raw=True,
                      pending=False, pending_transaction_id="pending_id")
    added, skipped = ts.upsert_transactions([posted])
    rows = ts.load_transactions()
    ids = {r["transaction_id"] for r in rows}
    assert ids == {"posted_id"}          # pending row removed, only posted remains
    assert added == 1


def test_posted_supersedes_pending_within_same_batch(make_txn):
    # Both pending and posted copies arrive in ONE sync batch (common): the pending
    # is skipped, the posted is stored, and no duplicate remains.
    batch = [
        make_txn("pending_id", "Amazon.com", 36.13, raw=True, pending=True),
        make_txn("posted_id", "Amazon.com*5R0Q13D01", 36.13, raw=True,
                 pending=False, pending_transaction_id="pending_id"),
    ]
    ts.upsert_transactions(batch)
    ids = {r["transaction_id"] for r in ts.load_transactions()}
    assert ids == {"posted_id"}


def test_reconcile_carries_user_category_and_split_to_posted(make_txn):
    # User itemized the charge while it was pending; when it posts, the split must
    # move to the posted row (amounts match), not be lost.
    ts.save_transactions([make_txn("pending_id", "Amazon.com", 36.13)])
    ts.split_transaction("pending_id",
                         [{"amount": 36.13, "category": "ChildCare", "note": "Kate Farms"}],
                         order_no="11300637303230655")
    posted = make_txn("posted_id", "Amazon.com*5R0Q13D01", 36.13, raw=True,
                      pending=False, pending_transaction_id="pending_id")
    ts.upsert_transactions([posted])
    rows = {r["transaction_id"]: r for r in ts.load_transactions()}
    assert "pending_id" not in rows
    p = rows["posted_id"]
    assert p["category"] == "Split"
    assert p["split_children"][0]["category"] == "ChildCare"
    assert p["split_order_no"] == "11300637303230655"


def test_reconcile_user_pending_category_beats_a_merchant_rule(make_txn):
    # The user manually categorized the charge while pending. That explicit choice
    # must survive the posted row - and it takes precedence over a merchant rule
    # that would otherwise fire (manual intent beats an auto-rule), consistent with
    # how a one-off `set` overrides rule-driven categorization elsewhere.
    ts.add_rule("amazon", "Household")
    ts.save_transactions([make_txn("pending_id", "Amazon.com", 36.13, category="Discretionary")])
    posted = make_txn("posted_id", "Amazon.com*ABC", 36.13, raw=True,
                      pending=False, pending_transaction_id="pending_id")
    ts.upsert_transactions([posted])
    rows = {r["transaction_id"]: r for r in ts.load_transactions()}
    assert "pending_id" not in rows
    assert rows["posted_id"]["category"] == "Discretionary"  # user's pending choice wins


def test_reconcile_carries_label_when_posted_has_none(make_txn):
    seed = make_txn("pending_id", "FCWA", 40.0)
    seed["label"] = "Fairfax Water"
    ts.save_transactions([seed])
    posted = make_txn("posted_id", "FCWA*X", 40.0, raw=True, pending=False,
                      pending_transaction_id="pending_id")
    ts.upsert_transactions([posted])
    rows = {r["transaction_id"]: r for r in ts.load_transactions()}
    assert "pending_id" not in rows
    assert rows["posted_id"]["label"] == "Fairfax Water"


def test_posted_with_unknown_pending_ref_is_just_added(make_txn):
    # pending_transaction_id points at a row we never stored (already reconciled or
    # this fix was added after that pending row aged out) - just add the posted row.
    added, skipped = ts.upsert_transactions(
        [make_txn("posted_id", "Amazon.com*ABC", 36.13, raw=True, pending=False,
                  pending_transaction_id="never_seen")]
    )
    assert added == 1
    assert ts.load_transactions()[0]["transaction_id"] == "posted_id"


def test_non_pending_missing_field_behaves_as_before(make_txn):
    # Rows without any pending fields (older sync shape) are treated as posted.
    added, _ = ts.upsert_transactions([make_txn("t1", "Costco", 10.0, raw=True)])
    assert added == 1
    assert ts.load_transactions()[0]["transaction_id"] == "t1"


def test_regression_kate_farms_pending_posted_no_phantom_duplicate(make_txn):
    """Regression for the real incident: a $36.13 Kate Farms charge arrived from
    Plaid as a bare-name pending row (id P, name 'Amazon.com', authorized==posted)
    AND, a day later, as the posted row (id Q, name 'Amazon.com*5R0Q13D01') that
    references P. Before the fix both persisted -> a phantom second $36.13 that
    looked like a separate order. After the fix, exactly one row survives (the
    posted one) and there is no duplicate to chase."""
    # First sync: only the pending copy is available.
    ts.upsert_transactions([
        make_txn("P", "Amazon.com", 36.13, raw=True, date="2026-09-17",
                 authorized_date="2026-09-17", pending=True),
    ])
    assert ts.load_transactions() == []  # pending not stored

    # Next sync: the posted copy arrives (references the pending id). Even if the
    # pending copy is re-sent in the same batch, only the posted row remains.
    ts.upsert_transactions([
        make_txn("P", "Amazon.com", 36.13, raw=True, date="2026-09-17",
                 authorized_date="2026-09-17", pending=True),
        make_txn("Q", "Amazon.com*5R0Q13D01", 36.13, raw=True, date="2026-09-18",
                 authorized_date="2026-09-17", pending=False,
                 pending_transaction_id="P"),
    ])
    rows = ts.load_transactions()
    amazon_3613 = [r for r in rows if abs(r["amount"] - 36.13) < 0.005]
    assert len(amazon_3613) == 1                       # no phantom duplicate
    assert amazon_3613[0]["transaction_id"] == "Q"     # the posted one
    assert "*" in amazon_3613[0]["name"]               # carries the reference code
