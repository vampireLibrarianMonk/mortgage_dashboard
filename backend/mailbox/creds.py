"""Encrypted credential storage for mailbox providers.

Thin wrapper over ``credential_store`` (Windows Credential Manager) so provider
secrets are encrypted at rest and never touch ``.env`` or git. Each provider
namespaces its secrets under the shared CRED_PREFIX, e.g.::

    mortgage_dashboard_mail_gmail_app_password
    mortgage_dashboard_mail_proton_imap_password

Secrets are stored as strings; a provider that needs multiple fields (host, port,
user, password) stores a small JSON blob under one target via set_json/get_json.
"""

from __future__ import annotations

import json

import credential_store as cred

from . import CRED_PREFIX


def _target(provider: str, field: str) -> str:
    return f"{CRED_PREFIX}_{provider}_{field}"


def set_secret(provider: str, field: str, value: str) -> None:
    cred.set_secret(_target(provider, field), value, username=provider)


def get_secret(provider: str, field: str) -> str | None:
    return cred.get_secret(_target(provider, field))


def delete_secret(provider: str, field: str) -> bool:
    return cred.delete_secret(_target(provider, field))


def set_json(provider: str, field: str, obj: dict) -> None:
    set_secret(provider, field, json.dumps(obj))


def get_json(provider: str, field: str) -> dict | None:
    raw = get_secret(provider, field)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
