"""Tests for balances_store: single latest-balance slot per account (no history).

Isolation: the autouse isolated_store fixture (conftest) redirects txn_store's
DATA_DIR + Fernet key to tmp. balances_store computed BALANCES_PATH from the real
DATA_DIR at import, so we additionally redirect it here to the tmp dir.
"""

import balances_store as bs
import pytest


@pytest.fixture(autouse=True)
def isolated_balances(isolated_store, monkeypatch):
    # isolated_store already pointed txn_store.DATA_DIR at tmp; put the balances
    # file in that same tmp dir so nothing touches the real balances.json.enc.
    monkeypatch.setattr(bs, "BALANCES_PATH", isolated_store.DATA_DIR / "balances.json.enc")


def test_load_default_empty():
    assert bs.load_balances() == {}


def test_account_key_format():
    assert bs.account_key("usaa", "0000") == "usaa:0000"
    assert bs.account_key("chase", None) == "chase:----"  # missing mask placeholder


def test_upsert_creates_slot_and_roundtrips():
    key = bs.upsert_balance("usaa", "0000", 1234.56, "2026-09-24T14:37:00",
                            account_id="acc1", name="Checking")
    assert key == "usaa:0000"
    slot = bs.load_balances()["usaa:0000"]
    assert slot["balance"] == 1234.56
    assert slot["as_of"] == "2026-09-24T14:37:00"
    assert slot["bank"] == "usaa" and slot["mask"] == "0000"
    assert slot["name"] == "Checking"


def test_upsert_overwrites_single_slot_no_history():
    bs.upsert_balance("usaa", "0000", 1000.00, "2026-09-01T00:00:00")
    bs.upsert_balance("usaa", "0000", 2500.00, "2026-09-24T00:00:00")
    balances = bs.load_balances()
    # exactly ONE slot for the account; the latest value wins (no history kept)
    assert list(balances.keys()) == ["usaa:0000"]
    assert balances["usaa:0000"]["balance"] == 2500.00
    assert balances["usaa:0000"]["as_of"] == "2026-09-24T00:00:00"


def test_multiple_accounts_kept_separately():
    bs.upsert_balance("usaa", "0000", 100.0, "t1")
    bs.upsert_balance("chase", "2038", 200.0, "t1")
    balances = bs.load_balances()
    assert set(balances) == {"usaa:0000", "chase:2038"}


def test_data_encrypted_on_disk():
    bs.upsert_balance("usaa", "0000", 1234.56, "t1", name="SECRETACCTNAME")
    raw = bs.BALANCES_PATH.read_bytes()
    assert b"SECRETACCTNAME" not in raw  # Fernet-encrypted at rest
