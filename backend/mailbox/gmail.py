"""Gmail provider(s) (read-only) over IMAP with an app password.

Uses Python's stdlib ``imaplib`` + ``email`` (via the shared ``_imapbase``) - no
third-party dependency. The mailbox is opened read-only at the protocol level
(``EXAMINE``), and only ``SEARCH``/``FETCH`` are ever issued: no delete, move,
flag, or send.

Auth: a Gmail *app password* (16 chars, requires 2-Step Verification). The
address + app password are stored encrypted in the Windows Credential Manager via
``mailbox.creds`` - never in ``.env`` or git. IMAP must be enabled in Gmail
settings. Searches are constrained to the receipt-sender allowlist.

Multiple accounts: each Gmail account is its own provider (``gmail``, ``gmail2``,
...), sharing identical IMAP logic but a distinct credential slot, so several
Gmail mailboxes can be configured and queried side by side.
"""

from __future__ import annotations

import imaplib

from . import creds, register_provider
from ._imapbase import ImapProviderBase

_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993
_CRED_FIELD = "imap"  # stores {"address":..., "app_password":...} as JSON
# Gmail's All Mail holds every message regardless of label, so archived order
# mail is still found.
_ALL_MAIL = '"[Gmail]/All Mail"'


# --- credential helpers (parameterized by provider so each account is separate) --

def save_credentials(address: str, app_password: str, provider: str = "gmail") -> None:
    """Persist a Gmail address + app password (encrypted, Credential Manager)."""
    creds.set_json(provider, _CRED_FIELD, {
        "address": address.strip(),
        # Gmail displays app passwords with spaces; IMAP wants them stripped.
        "app_password": app_password.replace(" ", ""),
    })


def load_credentials(provider: str = "gmail") -> tuple[str, str] | None:
    blob = creds.get_json(provider, _CRED_FIELD)
    if not blob or not blob.get("address") or not blob.get("app_password"):
        return None
    return blob["address"], blob["app_password"]


def clear_credentials(provider: str = "gmail") -> bool:
    return creds.delete_secret(provider, _CRED_FIELD)


def credentials_available(provider: str = "gmail") -> bool:
    return load_credentials(provider) is not None


# --- provider ----------------------------------------------------------------

class _GmailImapProviderBase(ImapProviderBase):
    """Shared Gmail IMAP logic. Concrete accounts set `name` + `label`; the
    credential slot is keyed by `name`, so each account stores its own secret."""

    name = "gmail"
    label = "Gmail (IMAP, read-only)"

    def _open(self) -> imaplib.IMAP4:
        cred = load_credentials(self.name)
        if cred is None:
            raise RuntimeError(
                f"no {self.name} credentials stored. run the CLI `setup {self.name}` "
                "to save an app password."
            )
        address, app_password = cred
        imap = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
        try:
            imap.login(address, app_password)
        except imaplib.IMAP4.error as e:
            raise RuntimeError(f"{self.name} login failed: {e}") from e
        # EXAMINE = read-only. Fall back to INBOX if All Mail is unavailable.
        typ, _ = imap.select(_ALL_MAIL, readonly=True)
        if typ != "OK":
            imap.select("INBOX", readonly=True)
        return imap


@register_provider
class GmailImapProvider(_GmailImapProviderBase):
    name = "gmail"
    label = "Gmail (IMAP, read-only)"


@register_provider
class Gmail2ImapProvider(_GmailImapProviderBase):
    name = "gmail2"
    label = "Gmail #2 (IMAP, read-only)"
