"""Latest-known account balances (single slot per account, no history).

The Timeline Builder's funding/account-dip lines start from the most recent
balance we've seen for an account. `sync` refreshes these; each account keeps
exactly ONE slot that is overwritten each time — this is deliberately NOT a
time series (see new_spec/timeline_builder.md).

Stored as an AES-Fernet-encrypted JSON blob in the same txn_data/ dir, reusing
txn_store's encryption (same key in Windows Credential Manager). Shape:

    { "<bank>:<mask>": {"balance": float, "as_of": iso8601,
                         "account_id": str, "bank": str, "mask": str,
                         "name": str} , ... }

The key "<bank>:<mask>" matches the `purchase.account` earmark the projection
engine reads, so a funded purchase lines up with its account's snapshot.
"""
from __future__ import annotations

import txn_store as ts  # reuse the encrypted-store helpers + DATA_DIR

BALANCES_PATH = ts.DATA_DIR / "balances.json.enc"


def account_key(bank: str, mask: str | None) -> str:
    """The stable per-account key used everywhere (funding earmark, snapshot)."""
    return f"{bank}:{mask or '----'}"


def load_balances() -> dict:
    """Map of account_key -> latest balance slot. {} when nothing stored yet."""
    return ts._read_enc(BALANCES_PATH, {})


def save_balances(balances: dict) -> None:
    ts._write_enc(BALANCES_PATH, balances)


def upsert_balance(bank: str, mask: str | None, balance: float, as_of: str,
                   account_id: str | None = None, name: str | None = None) -> str:
    """Overwrite the single latest-balance slot for one account. Returns its key."""
    balances = load_balances()
    key = account_key(bank, mask)
    balances[key] = {
        "balance": round(float(balance), 2),
        "as_of": as_of,
        "account_id": account_id,
        "bank": bank,
        "mask": mask,
        "name": name or "",
    }
    save_balances(balances)
    return key
