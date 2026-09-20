"""Standalone CLI harness for the mailbox subsystem (phase-1 dev surface).

This is the tool used to develop and prove the email-ingest subsystem BEFORE it
is wired into the app. It is deliberately separate from the FastAPI app: run it
directly with::

    python -m mailbox.cli <command> ...

(from the backend/ directory, with the venv active).

Commands
--------
  providers                       list registered providers
  status                          show which providers have stored credentials
  setup <provider>                store credentials (secure prompt; nothing echoed)
  clear <provider>                delete stored credentials for a provider
  test <provider>                 connect read-only and disconnect (proves auth)
  search <provider> [opts]        list receipt emails matching the allowlist
  dump <provider> [opts]          save raw .eml samples for parser development

Search/dump options:
  --since YYYY-MM-DD   only mail on/after this date
  --until YYYY-MM-DD   only mail before this date
  --limit N            cap results (default 25)
  --vendor NAME        restrict to one allowlisted vendor (amazon/walmart/...)
  --uid U [U ...]      (dump) specific uids instead of the newest matches

Safety: credentials are read via getpass (never shown, never written to a file),
stored encrypted in the Windows Credential Manager. Connections are read-only.
Dumped samples go to backend/mailbox/_samples/ which is gitignored.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import sys
from pathlib import Path

from . import (
    RECEIPT_SENDERS,
    SearchCriteria,
    get_provider,
    is_order_confirmation as _is_order_confirmation,
    registered_providers,
)

_SAMPLES_DIR = Path(__file__).resolve().parent / "_samples"

# Per-provider credential modules (kept in a small map so the CLI stays generic).
# The two Gmail accounts share one module; its cred helpers take the provider name
# so each account's secret is stored under its own key.
from . import gmail as _gmail
from . import proton as _proton

_CRED_MODULES = {"gmail": _gmail, "gmail2": _gmail, "proton": _proton}
_GMAIL_PROVIDERS = ("gmail", "gmail2")


def _parse_date(s: str | None) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


def _vendor_senders(vendor: str) -> tuple[str, ...]:
    """Explicit FROM terms for one vendor, for a narrowed search."""
    for s in RECEIPT_SENDERS:
        if s.vendor == vendor:
            return s.addresses or s.domains
    raise SystemExit(f"unknown vendor '{vendor}'. known: {[s.vendor for s in RECEIPT_SENDERS]}")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_providers(_args) -> int:
    print("registered providers:")
    for name in registered_providers():
        p = get_provider(name)
        print(f"  {name:8} {p.label}")
    return 0


def cmd_status(_args) -> int:
    for name in registered_providers():
        mod = _CRED_MODULES.get(name)
        if not mod:
            have = False
        elif name in _GMAIL_PROVIDERS:
            have = mod.credentials_available(name)  # gmail helpers take the provider
        else:
            have = mod.credentials_available()
        print(f"  {name:8} credentials: {'stored' if have else '(none)'}")
    return 0


def cmd_setup(args) -> int:
    name = args.provider
    if name in _GMAIL_PROVIDERS:
        label = "Gmail" if name == "gmail" else f"Gmail ({name})"
        address = input(f"{label} address: ").strip()
        print("Paste the 16-char app password (input hidden; requires 2FA on the account).")
        pw = getpass.getpass("App password: ")
        if not address or not pw:
            print("aborted: address and app password required.")
            return 1
        _gmail.save_credentials(address, pw, provider=name)
        print(f"stored {name} credentials (encrypted, Credential Manager).")
        return 0
    if name == "proton":
        print("Proton Mail Bridge must be installed and running. Use the "
              "Bridge-generated password, NOT your Proton account password.")
        address = input("Proton address: ").strip()
        host = input(f"Bridge IMAP host [{_proton._DEFAULT_HOST}]: ").strip() or _proton._DEFAULT_HOST
        port_raw = input(f"Bridge IMAP port [{_proton._DEFAULT_PORT}]: ").strip()
        port = int(port_raw) if port_raw else _proton._DEFAULT_PORT
        pw = getpass.getpass("Bridge password: ")
        if not address or not pw:
            print("aborted: address and Bridge password required.")
            return 1
        _proton.save_credentials(address, pw, host=host, port=port)
        print("stored Proton credentials (encrypted, Credential Manager).")
        return 0
    print(f"unknown provider '{name}'. known: {list(_CRED_MODULES)}")
    return 1


def cmd_clear(args) -> int:
    mod = _CRED_MODULES.get(args.provider)
    if not mod:
        print(f"unknown provider '{args.provider}'.")
        return 1
    removed = (mod.clear_credentials(args.provider) if args.provider in _GMAIL_PROVIDERS
               else mod.clear_credentials())
    print("cleared." if removed else "no credentials were stored.")
    return 0


def cmd_test(args) -> int:
    p = get_provider(args.provider)
    print(f"connecting to {p.label} (read-only)...")
    try:
        p.connect()
        print("  connected OK (read-only session established).")
    except Exception as e:
        print(f"  FAILED: {e}")
        return 1
    finally:
        p.close()
    print("  disconnected.")
    return 0


def _criteria(args) -> SearchCriteria:
    senders = _vendor_senders(args.vendor) if getattr(args, "vendor", None) else ()
    return SearchCriteria(
        since=_parse_date(getattr(args, "since", None)),
        until=_parse_date(getattr(args, "until", None)),
        senders=senders,
        limit=getattr(args, "limit", 25),
    )


def cmd_search(args) -> int:
    p = get_provider(args.provider)
    try:
        p.connect()
        uids = p.search(_criteria(args))
        if not uids:
            print("no matching receipt emails found.")
            return 0
        receipts = p.fetch(uids)
        if getattr(args, "orders_only", False):
            receipts = [r for r in receipts if _is_order_confirmation(r)]
        print(f"{len(receipts)} receipt email(s):")
        for r in receipts:
            vendor = r.vendor or "?"
            date = r.date.isoformat() if r.date else "????-??-??"
            kind = "ORDER" if _is_order_confirmation(r) else "     "
            print(f"  [{vendor:7}] {date}  uid={r.uid:<6} {kind}  {r.subject[:56]}")
    except Exception as e:
        print(f"error: {e}")
        return 1
    finally:
        p.close()
    return 0


def cmd_dump(args) -> int:
    p = get_provider(args.provider)
    _SAMPLES_DIR.mkdir(exist_ok=True)
    try:
        p.connect()
        if args.uid:
            uids = list(args.uid)
        else:
            uids = p.search(_criteria(args))
            if getattr(args, "orders_only", False):
                # Fetch to inspect subjects, keep only order confirmations.
                uids = [r.uid for r in p.fetch(uids) if _is_order_confirmation(r)]
        if not uids:
            print("nothing to dump (no matching uids).")
            return 0
        n = 0
        for uid in uids:
            raw = p.fetch_raw(uid)
            if raw is None:
                continue
            out = _SAMPLES_DIR / f"{args.provider}_{uid}.eml"
            out.write_bytes(raw)
            n += 1
            print(f"  wrote {out.relative_to(_SAMPLES_DIR.parent.parent)}")
        print(f"dumped {n} sample(s) to {_SAMPLES_DIR} (gitignored).")
    except Exception as e:
        print(f"error: {e}")
        return 1
    finally:
        p.close()
    return 0


# --------------------------------------------------------------------------- #
# argparse wiring
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mailbox.cli", description="Mailbox subsystem dev harness (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("providers", help="list registered providers").set_defaults(func=cmd_providers)
    sub.add_parser("status", help="show which providers have stored credentials").set_defaults(func=cmd_status)

    sp = sub.add_parser("setup", help="store credentials for a provider")
    sp.add_argument("provider")
    sp.set_defaults(func=cmd_setup)

    cp = sub.add_parser("clear", help="delete stored credentials")
    cp.add_argument("provider")
    cp.set_defaults(func=cmd_clear)

    tp = sub.add_parser("test", help="connect read-only then disconnect")
    tp.add_argument("provider")
    tp.set_defaults(func=cmd_test)

    def _add_search_opts(x):
        x.add_argument("provider")
        x.add_argument("--since")
        x.add_argument("--until")
        x.add_argument("--limit", type=int, default=25)
        x.add_argument("--vendor")
        x.add_argument("--orders-only", action="store_true",
                       help="only itemized order confirmations (skip tracking/login noise)")

    xp = sub.add_parser("search", help="list matching receipt emails")
    _add_search_opts(xp)
    xp.set_defaults(func=cmd_search)

    dp = sub.add_parser("dump", help="save raw .eml samples for parser development")
    _add_search_opts(dp)
    dp.add_argument("--uid", nargs="*", default=[])
    dp.set_defaults(func=cmd_dump)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
