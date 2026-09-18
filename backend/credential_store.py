"""Windows Credential Manager access for Plaid per-item secrets.

Stores each linked bank's access_token and transactions sync cursor as Generic
credentials so they are encrypted at rest and never written to plaintext files.
Uses the native Windows Credential API (advapi32) via ctypes; no third-party
dependency. Persistence is LocalMachine so the SYSTEM-run app can read them.

Credential target naming:
    plaid_item_<slug>_access_token
    plaid_item_<slug>_cursor
    plaid_items                      (JSON index: slug -> display name)
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CredReadW = advapi32.CredReadW
_CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
_CredReadW.restype = wintypes.BOOL

_CredWriteW = advapi32.CredWriteW
_CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
_CredWriteW.restype = wintypes.BOOL

_CredDeleteW = advapi32.CredDeleteW
_CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
_CredDeleteW.restype = wintypes.BOOL

_CredFree = advapi32.CredFree
_CredFree.argtypes = [ctypes.c_void_p]
_CredFree.restype = None


def get_secret(target: str) -> str | None:
    """Read a Generic credential's secret string, or None if not present."""
    cred_ptr = ctypes.POINTER(_CREDENTIAL)()
    ok = _CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr))
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None
        raise OSError(f"CredRead failed for '{target}' (Win32 error {err})")
    try:
        cred = cred_ptr.contents
        size = cred.CredentialBlobSize
        if size == 0 or not cred.CredentialBlob:
            return ""
        blob = ctypes.string_at(cred.CredentialBlob, size)
        return blob.decode("utf-16-le")
    finally:
        _CredFree(cred_ptr)


def set_secret(target: str, secret: str, username: str = "plaid") -> None:
    """Create or overwrite a Generic credential (LocalMachine persist)."""
    blob = secret.encode("utf-16-le")
    blob_buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)

    cred = _CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = username

    ok = _CredWriteW(ctypes.byref(cred), 0)
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(f"CredWrite failed for '{target}' (Win32 error {err})")


def delete_secret(target: str) -> bool:
    """Delete a Generic credential. Returns False if it did not exist."""
    ok = _CredDeleteW(target, CRED_TYPE_GENERIC, 0)
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return False
        raise OSError(f"CredDelete failed for '{target}' (Win32 error {err})")
    return True


# --- Plaid item-specific helpers (built on the generic store) -----------------

def _access_token_target(slug: str) -> str:
    return f"plaid_item_{slug}_access_token"


def _cursor_target(slug: str) -> str:
    return f"plaid_item_{slug}_cursor"


def save_item(slug: str, access_token: str) -> None:
    set_secret(_access_token_target(slug), access_token)


def get_access_token(slug: str) -> str | None:
    return get_secret(_access_token_target(slug))


def save_cursor(slug: str, cursor: str) -> None:
    set_secret(_cursor_target(slug), cursor)


def get_cursor(slug: str) -> str | None:
    return get_secret(_cursor_target(slug))


def delete_item(slug: str) -> None:
    delete_secret(_access_token_target(slug))
    delete_secret(_cursor_target(slug))
    _remove_from_index(slug)


# --- Item index: slug -> display name, stored as JSON in one credential --------

_INDEX_TARGET = "plaid_items"


def _load_index() -> dict[str, str]:
    import json
    raw = get_secret(_INDEX_TARGET)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def _save_index(index: dict[str, str]) -> None:
    import json
    set_secret(_INDEX_TARGET, json.dumps(index))


def add_to_index(slug: str, display_name: str) -> None:
    index = _load_index()
    index[slug] = display_name
    _save_index(index)


def _remove_from_index(slug: str) -> None:
    index = _load_index()
    if slug in index:
        del index[slug]
        _save_index(index)


def list_items() -> list[dict[str, str]]:
    """Return [{slug, name}] for every connected item."""
    return [{"slug": slug, "name": name} for slug, name in _load_index().items()]
