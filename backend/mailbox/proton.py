"""Proton Mail provider (read-only) via Proton Mail Bridge.

Proton has no public mail API; the only supported programmatic access is Proton
Mail Bridge, a local desktop app that decrypts your mailbox and re-serves it as
IMAP on localhost. So this provider talks to Bridge's local IMAP endpoint - it
never reaches Proton's servers directly, and Bridge must be installed and running.

Connection specifics (differ from Gmail):
* Host/port are local, default ``127.0.0.1:1143``, and the link is **STARTTLS**
  (plain socket upgraded), not SSL-on-connect. Bridge uses a self-signed cert,
  so TLS verification is relaxed for the loopback connection only.
* The password is the **Bridge-generated** password shown in the Bridge app for
  the account, NOT your Proton account password.

Everything else (search, fetch, parsing) is inherited from the shared read-only
IMAP base, so this module only handles connection + credentials. Credentials are
stored encrypted in the Windows Credential Manager via ``mailbox.creds``.
"""

from __future__ import annotations

import imaplib
import ssl

from . import creds, register_provider
from ._imapbase import ImapProviderBase

_PROVIDER = "proton"
_CRED_FIELD = "bridge"  # stores {host, port, address, password} as JSON

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 1143  # Proton Bridge default IMAP port


# --- credential helpers (used by the CLI harness to set up auth) -------------

def save_credentials(address: str, password: str,
                     host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT) -> None:
    """Persist Bridge connection details (encrypted, Credential Manager).

    `password` is the Bridge-generated password (from the Bridge app), not the
    Proton account password.
    """
    creds.set_json(_PROVIDER, _CRED_FIELD, {
        "address": address.strip(),
        "password": password.strip(),
        "host": host.strip() or _DEFAULT_HOST,
        "port": int(port) or _DEFAULT_PORT,
    })


def load_credentials() -> dict | None:
    blob = creds.get_json(_PROVIDER, _CRED_FIELD)
    if not blob or not blob.get("address") or not blob.get("password"):
        return None
    blob.setdefault("host", _DEFAULT_HOST)
    blob.setdefault("port", _DEFAULT_PORT)
    return blob


def clear_credentials() -> bool:
    return creds.delete_secret(_PROVIDER, _CRED_FIELD)


def credentials_available() -> bool:
    return load_credentials() is not None


# --- provider ----------------------------------------------------------------

@register_provider
class ProtonBridgeProvider(ImapProviderBase):
    name = _PROVIDER
    label = "Proton Mail (Bridge, read-only)"

    def _open(self) -> imaplib.IMAP4:
        cred = load_credentials()
        if cred is None:
            raise RuntimeError(
                "no Proton credentials stored. start Proton Mail Bridge, then run "
                "the CLI `setup proton` to save the Bridge password."
            )
        host, port = cred["host"], int(cred["port"])
        try:
            imap = imaplib.IMAP4(host, port)
        except OSError as e:
            raise RuntimeError(
                f"cannot reach Proton Bridge at {host}:{port} - is Proton Mail "
                f"Bridge running? ({e})"
            ) from e
        # Bridge serves a self-signed cert on loopback; upgrade with STARTTLS but
        # skip hostname/cert verification for this local-only connection.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            imap.starttls(ssl_context=ctx)
        except Exception as e:
            raise RuntimeError(f"Proton Bridge STARTTLS failed: {e}") from e
        try:
            imap.login(cred["address"], cred["password"])
        except imaplib.IMAP4.error as e:
            raise RuntimeError(
                f"Proton Bridge login failed (use the Bridge-generated password, "
                f"not your Proton password): {e}"
            ) from e
        # "All Mail" holds archived mail too; fall back to INBOX. EXAMINE = read-only.
        typ, _ = imap.select("All Mail", readonly=True)
        if typ != "OK":
            imap.select("INBOX", readonly=True)
        return imap
