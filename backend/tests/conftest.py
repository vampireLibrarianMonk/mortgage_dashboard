"""Shared pytest fixtures.

CRITICAL SAFETY: the transaction store (txn_store) normally reads/writes the
user's REAL encrypted financial data at backend/txn_data/*.json.enc and pulls its
Fernet key from the Windows Credential Manager. Tests must NEVER touch either.

The `isolated_store` fixture (autouse) redirects txn_store's data paths to a
throwaway tmp directory and replaces its Fernet key with a fixed in-test key, so
every test runs against an empty, disposable store and the real 390-transaction
dataset and credential manager are left completely untouched.
"""

import pytest
from cryptography.fernet import Fernet

# A fixed key for tests only. Not a secret; never used for real data.
_TEST_KEY = Fernet.generate_key()


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point txn_store at a tmp dir + a fixed Fernet key; reset undo stack."""
    import txn_store as ts

    data_dir = tmp_path / "txn_data"
    data_dir.mkdir()
    monkeypatch.setattr(ts, "DATA_DIR", data_dir)
    monkeypatch.setattr(ts, "TXN_PATH", data_dir / "transactions.json.enc")
    monkeypatch.setattr(ts, "RULES_PATH", data_dir / "merchant_rules.json.enc")
    # Replace the key source so the real Windows Credential Manager is never hit.
    monkeypatch.setattr(ts, "_key", lambda: _TEST_KEY)
    # The undo stack is process-global module state; clear it per test.
    ts._UNDO_STACK.clear()

    yield ts

    ts._UNDO_STACK.clear()


@pytest.fixture
def make_txn():
    """Factory for a minimal transaction dict with sensible defaults."""
    def _make(transaction_id, name, amount, raw=False, **extra):
        """Build a transaction dict.

        By default includes category="Uncategorized" to mirror the on-disk shape
        of a persisted transaction. Pass raw=True to omit the category key, which
        mimics a fresh transaction straight from Plaid before upsert assigns one
        (upsert uses setdefault, so it only categorizes rows that lack a category).
        """
        t = {
            "transaction_id": transaction_id,
            "date": "2026-07-15",
            "authorized_date": "2026-07-15",
            "year": 2026,
            "month": 7,
            "name": name,
            "merchant": "",
            "amount": amount,
            "bank": "testbank",
            "account_id": "acct_1",
            "account_mask": "1234",
        }
        if not raw:
            t["category"] = "Uncategorized"
        t.update(extra)
        return t
    return _make
