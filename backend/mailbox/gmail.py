"""Gmail provider (read-only) over IMAP with an app password.

Uses Python's stdlib ``imaplib`` + ``email`` (via the shared ``_imapbase``) - no
third-party dependency. The mailbox is opened read-only at the protocol level
(``EXAMINE``), and only ``SEARCH``/``FETCH`` are ever issued: no delete, move,
flag, or send.

Auth: a Gmail *app password* (16 chars, requires 2-Step Verification). The
address + app password are stored encrypted in the Windows Credential Manager via
``mailbox.creds`` - never in ``.env`` or git. IMAP must be enabled in Gmail
settings. Searches are constrained to the receipt-sender allowlist.
"""

from __future__ import annotations

import imaplib

from . import creds, register_provider
from ._imapbase import ImapProviderBase

_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993
_PROVIDER = "gmail"
_CRED_FIELD = "imap"  # stores {"address":..., "app_password":...} as JSON
# Gmail's All Mail holds every message regardless of label, so archived order
# mail is still found.
_ALL_MAIL = '"[Gmail]/All Mail"'


# --- credential helpers (used by the CLI harness to set up auth) -------------

def save_credentials(address: str, app_password: str) -> None:
    """Persist the Gmail address + app password (encrypted, Credential Manager)."""
    creds.set_json(_PROVIDER, _CRED_FIELD, {
        "address": address.strip(),
        # Gmail displays app passwords with spaces; IMAP wants them stripped.
        "app_password": app_password.replace(" ", ""),
    })


def load_credentials() -> tuple[str, str] | None:
    blob = creds.get_json(_PROVIDER, _CRED_FIELD)
    if not blob or not blob.get("address") or not blob.get("app_password"):
        return None
    return blob["address"], blob["app_password"]


def clear_credentials() -> bool:
    return creds.delete_secret(_PROVIDER, _CRED_FIELD)


def credentials_available() -> bool:
    return load_credentials() is not None


# --- provider ----------------------------------------------------------------

@register_provider
class GmailImapProvider(ImapProviderBase):
    name = _PROVIDER
    label = "Gmail (IMAP, read-only)"

    def _open(self) -> imaplib.IMAP4:
        cred = load_credentials()
        if cred is None:
            raise RuntimeError(
                "no Gmail credentials stored. run the CLI `setup gmail` to save an app password."
            )
        address, app_password = cred
        imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
        try:
            imap.login(address, app_password)
        except imaplib.IMAP4.error as e:
            raise RuntimeError(f"Gmail login failed: {e}") from e
        # EXAMINE = read-only. Fall back to INBOX if All Mail is unavailable.
        typ, _ = imap.select(_ALL_MAIL, readonly=True)
        if typ != "OK":
            imap.select("INBOX", readonly=True)
        return imap
