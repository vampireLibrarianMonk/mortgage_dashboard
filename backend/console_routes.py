"""Command-line console for user-driven transaction categorization.

A single POST /console endpoint takes a command string and returns output lines,
like a shell. All bank/categorization work is driven here — the app GUI no longer
has a Plaid panel. Categorization is entirely user-driven (no LLM).

Commands:
  help
  status                         show connected banks + txn counts
  sync                           pull transactions from all linked banks (>= 2026-04-01)
  list [uncategorized|<category>]   list transactions (default: uncategorized), capped
  merchants [uncategorized]      list distinct merchants w/ counts + totals
  cat <merchant substring> <Category>   categorize all matching txns (creates a rule)
  rule ls                        list merchant rules
  rule rm <pattern>              remove a rule
  summary [year]                 per-category totals (month + year), regenerates actuals
  undo                           revert the last mutating command
  plaid [status|items|balances [slug]|link]   Plaid diagnostics (config, items,
                                 balances, link-token mint). This console is the
                                 only Plaid diagnostic surface; there is no GUI panel.
"""
from __future__ import annotations

import datetime as dt
import shlex
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

import credential_store as store
import txn_store as ts
from actuals import BUDGET_CATEGORIES, UNBUDGETED, export_actuals
from plaid_client import PlaidConfigError, build_client, credentials_available, get_plaid_env

router = APIRouter(prefix="/console", tags=["console"])

HISTORY = Path(__file__).resolve().parent / "console_history.log"
START_DATE = dt.date(2026, 4, 1)
LIST_CAP = 50


class Command(BaseModel):
    command: str


def _log(cmd: str) -> None:
    try:
        with HISTORY.open("a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}  {cmd}\n")
    except OSError:
        pass


def _fmt(n: float) -> str:
    return f"${n:,.2f}"


# --- command implementations (each returns list[str] output lines) ------------

def _cmd_help(_args) -> list[str]:
    return [
        "commands:",
        "  help                              this help",
        "  status                            connected banks + counts",
        "  sync                              pull transactions from linked banks",
        "  list [uncategorized|<Category>]   list transactions (default uncategorized)",
        "  merchants [uncategorized]         distinct merchants + counts/totals",
        "  cat <merchant text> <Category> [@mask]  categorize all matching (creates a rule;",
        "                                    @mask scopes it to one account, e.g. @0000)",
        "  set <match text> <Category> [@mask] [$amt]  one-off categorize, NO rule created",
        "  rule ls | rule rm <pattern>       manage merchant rules",
        "  label <match text> = <label> [$amt]  attach a note to matching txns",
        "  summary [year]                    per-category totals; refresh Budget vs Actual",
        "  import [go]                       preview (or `go` to load) statement files in dump/",
        "  undo                              revert the last change",
        "  plaid [status|items|balances|link]  Plaid diagnostics (no GUI panel)",
        f"  categories: {', '.join(ts.CATEGORIES)}",
    ]


def _cmd_status(_args) -> list[str]:
    items = store.list_items()
    txns = ts.load_transactions()
    uncat = sum(1 for t in txns if t["category"] == "Uncategorized")
    lines = [f"plaid configured: {credentials_available()}"]
    lines.append(f"banks: {', '.join(i['name'] for i in items) or '(none)'}")
    lines.append(f"transactions: {len(txns)} total, {uncat} uncategorized")
    lines.append(f"rules: {len(ts.load_rules())}")
    return lines


def _cmd_sync(_args) -> list[str]:
    if not credentials_available():
        return ["plaid not configured (PLAID_CLIENT_ID/SECRET missing)."]
    try:
        client = build_client()
    except PlaidConfigError as e:
        return [f"error: {e}"]

    from plaid.model.transactions_get_request import TransactionsGetRequest
    from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

    items = store.list_items()
    if not items:
        return ["no linked banks. (linking is done via the Plaid connect flow.)"]

    out = []
    collected = []
    end = dt.date.today()
    for it in items:
        slug = it["slug"]
        token = store.get_access_token(slug)
        if not token:
            out.append(f"{slug}: no token, skipped")
            continue
        offset, total = 0, None
        try:
            while True:
                resp = client.transactions_get(TransactionsGetRequest(
                    access_token=token, start_date=START_DATE, end_date=end,
                    options=TransactionsGetRequestOptions(count=500, offset=offset),
                ))
                total = resp["total_transactions"]
                # Map account_id -> last-4 mask so each transaction records which
                # account it belongs to (needed to ignore internal transfers by
                # account, e.g. NFCU 0003 <-> USAA 0000 bill funding).
                masks = {a["account_id"]: a.get("mask") for a in resp["accounts"]}
                for t in resp["transactions"]:
                    posted = t["date"]
                    # authorized_date is when the card was actually swiped; the
                    # posted date can lag 1-3 days and push a late-month purchase
                    # into the next month. Bucket by authorized_date when present
                    # (card purchases), falling back to posted date (bank items).
                    auth = t.get("authorized_date")
                    effective = auth or posted
                    acct_id = t.get("account_id")
                    collected.append({
                        "transaction_id": t["transaction_id"],
                        "date": str(posted),
                        "authorized_date": str(auth) if auth else None,
                        "year": effective.year, "month": effective.month,
                        "name": t["name"], "merchant": t.get("merchant_name") or "",
                        "amount": float(t["amount"]),
                        "bank": slug,
                        "account_id": acct_id,
                        "account_mask": masks.get(acct_id),
                    })
                offset += len(resp["transactions"])
                if offset >= total or not resp["transactions"]:
                    break
            out.append(f"{slug}: fetched {offset}")
        except Exception as e:
            out.append(f"{slug}: sync error: {e}")

    ts.snapshot()
    added, skipped = ts.upsert_transactions(collected)
    out.append(f"added {added} new, {skipped} already known.")
    uncat = sum(1 for t in ts.load_transactions() if t["category"] == "Uncategorized")
    out.append(f"{uncat} uncategorized - use `list` then `cat <merchant> <Category>`.")
    return out


def _cmd_list(args) -> list[str]:
    txns = ts.load_transactions()
    # Join all args so multi-word categories work (e.g. "Other Home Costs").
    which = " ".join(args) if args else "uncategorized"
    if which.lower() == "uncategorized":
        sel = [t for t in txns if t["category"] == "Uncategorized"]
        title = "uncategorized"
    else:
        sel = [t for t in txns if t["category"].lower() == which.lower()]
        title = which
    sel.sort(key=lambda t: abs(t["amount"]), reverse=True)
    lines = [f"{len(sel)} {title} transaction(s) (top {min(LIST_CAP, len(sel))} by amount):"]
    for t in sel[:LIST_CAP]:
        name = (t["name"] or t["merchant"])[:44]
        note = f"  <{t['label']}>" if t.get("label") else ""
        lines.append(f"  {t['date']}  {_fmt(t['amount']):>12}  {name}{note}")
    return lines


def _cmd_merchants(args) -> list[str]:
    txns = ts.load_transactions()
    only_uncat = bool(args) and args[0].lower() == "uncategorized"
    agg = defaultdict(lambda: [0, 0.0, ""])
    for t in txns:
        if only_uncat and t["category"] != "Uncategorized":
            continue
        key = (t["merchant"] or t["name"] or "").strip()[:40]
        agg[key][0] += 1
        agg[key][1] += t["amount"]
        agg[key][2] = t["category"]
    rows = sorted(agg.items(), key=lambda kv: abs(kv[1][1]), reverse=True)
    lines = [f"{len(rows)} merchant(s){' (uncategorized)' if only_uncat else ''}:"]
    for name, (cnt, total, cat) in rows[:LIST_CAP]:
        lines.append(f"  {cnt:3}x {_fmt(total):>12}  [{cat}]  {name}")
    return lines


def _cmd_cat(args) -> list[str]:
    # Optional trailing @<mask> scopes the rule to one account (last-4), e.g.
    #   cat usaa funds transfer Ignore @0000
    # A scoped rule only touches transactions on that account.
    mask = None
    if args and args[-1].startswith("@") and len(args[-1]) > 1:
        mask = args[-1][1:]
        args = args[:-1]
    if len(args) < 2:
        return ["usage: cat <merchant text> <Category> [@<account_mask>]"]

    # Categories can be multiple words (e.g. "Other Home Costs"). Match the
    # longest trailing run of tokens that forms a known category, so the rest is
    # the pattern. Fall back to the single last token for the error message.
    category = None
    pattern = None
    for split in range(1, len(args)):
        candidate = " ".join(args[split:])
        if candidate in ts.CATEGORIES:
            category = candidate
            pattern = " ".join(args[:split])
            break
    if category is None:
        return [f"unknown category '{args[-1]}'. valid: {', '.join(ts.CATEGORIES)}"]

    ts.snapshot()
    n = ts.add_rule(pattern, category, account_mask=mask)
    scope = f" on account {mask}" if mask else ""
    return [f"rule '{pattern.lower()}'{scope} -> {category}; categorized {n} transaction(s)."]


def _cmd_set(args) -> list[str]:
    # One-off categorize specific transactions WITHOUT creating a rule:
    #   set <match text> <Category> [@<mask>] [$<amount>]
    # Use when the description is too generic for a rule (e.g. a one-time bill
    # that looks like an ordinary transfer). Optional $amount pins a single row.
    mask = None
    amount = None
    # Strip optional trailing @mask and $amount in any order.
    while args and (args[-1].startswith("@") or args[-1].startswith("$")):
        tok = args[-1]
        if tok.startswith("@") and len(tok) > 1:
            mask = tok[1:]
        elif tok.startswith("$") and len(tok) > 1:
            try:
                amount = float(tok[1:])
            except ValueError:
                return ["bad amount after '$' (e.g. $70.04 or $-610)"]
        args = args[:-1]
    if len(args) < 2:
        return ["usage: set <match text> <Category> [@<mask>] [$<amount>]"]
    category = None
    match_text = None
    for split in range(1, len(args)):
        candidate = " ".join(args[split:])
        if candidate in ts.CATEGORIES:
            category = candidate
            match_text = " ".join(args[:split])
            break
    if category is None:
        return [f"unknown category '{args[-1]}'. valid: {', '.join(ts.CATEGORIES)}"]
    ts.snapshot()
    n = ts.set_category(match_text, category, amount=amount, account_mask=mask)
    where = []
    if mask:
        where.append(f"account {mask}")
    if amount is not None:
        where.append(f"amount {amount}")
    scope = f" ({', '.join(where)})" if where else ""
    return [f"set {n} transaction(s) matching '{match_text.lower()}'{scope} -> {category} (no rule created)."]


def _cmd_label(args) -> list[str]:
    # label <match text> = <label> [@<mask>] [$<amount>]
    #   label transfer from pedro = bidet reimbursement - John Doe $-610
    #   label usaa funds transfer = internal move @0001
    # Optional trailing @mask / $amount narrow which transactions get the note.
    # A label is a human note only; it does not change category or totals.
    amount = None
    mask = None
    while args and (args[-1].startswith("@") or args[-1].startswith("$")):
        tok = args[-1]
        if tok.startswith("@") and len(tok) > 1:
            mask = tok[1:]
        elif tok.startswith("$") and len(tok) > 1:
            try:
                amount = float(tok[1:])
            except ValueError:
                return ["bad amount after '$' (e.g. $-610)"]
        args = args[:-1]
    if "=" not in args:
        return ["usage: label <match text> = <label> [@<mask>] [$<amount>]"]
    eq = args.index("=")
    match_text = " ".join(args[:eq]).strip()
    label = " ".join(args[eq + 1:]).strip()
    if not match_text or not label:
        return ["usage: label <match text> = <label> [@<mask>] [$<amount>]"]
    ts.snapshot()
    n = ts.set_label(match_text, label, amount=amount, account_mask=mask)
    return [f"labeled {n} transaction(s) as '{label}'."]


def _cmd_rule(args) -> list[str]:
    if not args:
        return ["usage: rule ls | rule rm <pattern>"]
    if args[0] == "ls":
        rules = ts.load_rules()
        if not rules:
            return ["(no rules)"]
        return [
            f"  {r['pattern']}"
            + (f" @{r['account_mask']}" if r.get("account_mask") else "")
            + f" -> {r['category']}"
            for r in rules
        ]
    if args[0] == "rm" and len(args) >= 2:
        ts.snapshot()
        ok = ts.remove_rule(" ".join(args[1:]))
        return ["removed." if ok else "no such rule."]
    return ["usage: rule ls | rule rm <pattern>"]


def _cmd_summary(args) -> list[str]:
    txns = ts.load_transactions()
    year = args[0] if args else None
    by_year_cat = defaultdict(lambda: defaultdict(float))
    unbud = defaultdict(float)
    for t in txns:
        y = str(t["year"])
        if year and y != year:
            continue
        c = t["category"]
        if c in BUDGET_CATEGORIES:
            by_year_cat[y][c] += t["amount"]
        elif c in UNBUDGETED:
            unbud[y] += t["amount"]
    # Regenerate the aggregates JSON the Budget vs Actual view reads.
    export_actuals(txns)
    lines = ["per-category totals (also refreshed Budget vs Actual):"]
    for y in sorted(by_year_cat):
        lines.append(f"  {y}:")
        for c in BUDGET_CATEGORIES:
            v = by_year_cat[y].get(c, 0.0)
            if v:
                lines.append(f"    {c:14} {_fmt(v)}")
        if unbud.get(y):
            lines.append(f"    {'(unbudgeted)':14} {_fmt(unbud[y])}")
    if len(lines) == 1:
        lines.append("  (no categorized spending yet)")
    return lines


def _cmd_import(args) -> list[str]:
    """Import statement files staged in the dump/ directory.

    Usage:
      import                preview what would be imported (dry run - writes nothing)
      import go             perform the import (snapshots first, so `undo` reverts it)

    Files are read from the repo `dump/` folder (drop the PayPal `statement-*.zip`
    or the individual PDFs there). Parsing is handled by the pluggable importer
    framework; the same preview/commit logic backs the GUI upload button.
    """
    from importers import service

    dump_dir = Path(__file__).resolve().parent.parent / "dump"
    if not dump_dir.is_dir():
        return [f"no dump directory at {dump_dir}"]

    # Gather stageable files (zips and pdfs), expanding zips into members.
    staged: list[tuple[str, bytes]] = []
    staged_names: list[str] = []
    for p in sorted(dump_dir.iterdir()):
        if not p.is_file() or p.name == ".gitkeep":
            continue
        if p.suffix.lower() not in (".zip", ".pdf", ".csv"):
            continue
        staged_names.append(p.name)
        staged.extend(service.collect_files(p.name, p.read_bytes()))

    if not staged:
        return [f"no statement files in {dump_dir} (drop a PayPal statement-*.zip or .pdf there)"]

    preview = service.preview_files(staged)

    do_commit = bool(args) and args[0].lower() in ("go", "commit", "load", "confirm")

    lines = [f"staged from dump/: {', '.join(staged_names)}"]
    for pf in preview.files:
        if pf.error:
            lines.append(f"  {pf.filename}: ERROR {pf.error}")
        else:
            lines.append(f"  {pf.filename}: {len(pf.txns)} transaction(s) via {pf.reader}")
    for prob in preview.problems:
        lines.append(f"  ! {prob}")

    lines.append("")
    lines.append(f"would import {preview.import_count} transaction(s) on/after {service.DATA_START}:")
    for r in preview.to_import[:LIST_CAP]:
        tag = "  [offset->Ignore]" if r.get("category") == "Ignore" else ""
        lines.append(f"  {r['date']}  {_fmt(r['amount']):>12}  {r['name'][:44]}{tag}")
    if preview.import_count > LIST_CAP:
        lines.append(f"  ... and {preview.import_count - LIST_CAP} more")

    if preview.pre_start:
        lines.append(f"excluding {len(preview.pre_start)} transaction(s) before data start "
                     f"{service.DATA_START} (partial history, would skew budgets)")
    if preview.reconciled:
        lines.append(f"reconciling {len(preview.reconciled)} opaque 'PAYPAL PURCHASE' bank row(s) "
                     f"-> Ignore (superseded by itemized detail):")
        for m in preview.reconciled[:LIST_CAP]:
            lines.append(f"  {m.paypal_date}  {_fmt(m.amount):>12}  {m.paypal_name[:40]}")

    if do_commit:
        lines.append("")
        lines.append("committing...")
        lines.extend(f"  {s}" for s in service.commit(preview))
        lines.append("done. run `summary` to refresh Budget vs Actual, `undo` to revert.")
    else:
        lines.append("")
        lines.append("dry run - nothing written. run `import go` to commit.")
    return lines


def _cmd_undo(_args) -> list[str]:
    return ["reverted last change." if ts.undo() else "nothing to undo."]


def _cmd_plaid(args) -> list[str]:
    """Plaid diagnostics. This is the only Plaid diagnostic surface (no GUI panel).

    Subcommands:
      plaid | plaid status        config, environment, connected items
      plaid items                 list connected banks with per-item token/cursor state
      plaid balances [slug]       current account balances (all items, or one slug)
      plaid link                  mint a link_token to verify the auth path works
    """
    sub = args[0].lower() if args else "status"

    if sub == "status":
        lines = [
            f"configured: {credentials_available()}",
            f"environment: {get_plaid_env()}",
        ]
        items = store.list_items()
        lines.append(f"connected banks: {', '.join(i['name'] for i in items) or '(none)'}")
        return lines

    if sub == "items":
        items = store.list_items()
        if not items:
            return ["(no connected banks)"]
        lines = [f"{len(items)} item(s):"]
        for it in items:
            slug = it["slug"]
            has_token = store.get_access_token(slug) is not None
            cursor = store.get_cursor(slug)
            cursor_state = "fresh (no cursor)" if not cursor else "synced"
            lines.append(f"  {slug}  ({it['name']})  token={'yes' if has_token else 'MISSING'}  {cursor_state}")
        return lines

    if sub == "balances":
        if not credentials_available():
            return ["plaid not configured (PLAID_CLIENT_ID/SECRET missing)."]
        try:
            client = build_client()
        except PlaidConfigError as e:
            return [f"error: {e}"]
        from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

        items = store.list_items()
        if len(args) >= 2:
            wanted = args[1].lower()
            items = [i for i in items if i["slug"] == wanted]
            if not items:
                return [f"no connected bank '{args[1]}'."]
        if not items:
            return ["(no connected banks)"]

        lines = []
        for it in items:
            slug = it["slug"]
            token = store.get_access_token(slug)
            if not token:
                lines.append(f"{slug}: no token, skipped")
                continue
            try:
                resp = client.accounts_balance_get(AccountsBalanceGetRequest(access_token=token))
            except Exception as e:
                lines.append(f"{slug}: balance error: {e}")
                continue
            lines.append(f"{slug} ({it['name']}):")
            for a in resp["accounts"]:
                bal = a["balances"]
                cur = bal["current"]
                sub_t = str(a["subtype"]) if a.get("subtype") else str(a["type"])
                cur_str = _fmt(cur) if cur is not None else "n/a"
                lines.append(f"  {a['name'][:30]:30} [{sub_t}]  {cur_str:>14}")
        return lines

    if sub == "link":
        if not credentials_available():
            return ["plaid not configured (PLAID_CLIENT_ID/SECRET missing)."]
        try:
            client = build_client()
        except PlaidConfigError as e:
            return [f"error: {e}"]
        from plaid.model.country_code import CountryCode
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.products import Products
        try:
            resp = client.link_token_create(LinkTokenCreateRequest(
                user=LinkTokenCreateRequestUser(client_user_id="mortgage-dashboard-user"),
                client_name="Mortgage Dashboard",
                products=[Products("transactions")],
                country_codes=[CountryCode("US")],
                language="en",
            ))
            token = resp["link_token"]
            return [
                f"link_token_create OK (env={get_plaid_env()}, products=[transactions])",
                f"token length: {len(token)} (auth path reachable)",
            ]
        except Exception as e:
            return [f"link_token_create FAILED (env={get_plaid_env()}): {e}"]

    return ["usage: plaid [status | items | balances [slug] | link]"]


DISPATCH = {
    "help": _cmd_help, "status": _cmd_status, "sync": _cmd_sync, "list": _cmd_list,
    "merchants": _cmd_merchants, "cat": _cmd_cat, "set": _cmd_set, "rule": _cmd_rule,
    "label": _cmd_label,
    "summary": _cmd_summary, "undo": _cmd_undo, "plaid": _cmd_plaid,
    "import": _cmd_import,
}


@router.post("/")
def run_command(body: Command):
    raw = body.command.strip()
    if not raw:
        return {"output": []}
    _log(raw)
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = raw.split()
    cmd, args = parts[0].lower(), parts[1:]
    fn = DISPATCH.get(cmd)
    if not fn:
        return {"output": [f"unknown command '{cmd}'. type `help`."]}
    try:
        return {"output": fn(args)}
    except Exception as e:
        return {"output": [f"error: {e}"]}


# --- Statement import (GUI upload) --------------------------------------------
#
# The console `import` command works off files staged in dump/. The GUI instead
# uploads a file directly. Both share the same importer service, so behaviour
# (data-start filter, offset handling, reconciliation) is identical. Two stateless
# endpoints: /import/preview shows what a commit would do (writes nothing),
# /import/commit performs it. The upload is re-sent to commit rather than held in
# server memory, keeping the endpoints stateless.

# Cap uploads at a sane size - a year of PayPal PDFs is well under this.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _preview_to_dict(preview) -> dict:
    """Serialize an ImportPreview for the frontend."""
    from importers import service

    return {
        "files": [
            {"filename": pf.filename, "reader": pf.reader,
             "count": len(pf.txns), "error": pf.error}
            for pf in preview.files
        ],
        "problems": preview.problems,
        "import_count": preview.import_count,
        "data_start": str(service.DATA_START),
        "to_import": [
            {"date": r["date"], "amount": r["amount"], "name": r["name"],
             "category": r.get("category")}
            for r in preview.to_import
        ],
        "pre_start_count": len(preview.pre_start),
        "offsets_count": len(preview.offsets),
        "reconciled": [
            {"date": m.paypal_date, "amount": m.amount, "name": m.paypal_name}
            for m in preview.reconciled
        ],
    }


async def _read_upload(upload: UploadFile) -> tuple[str, bytes]:
    data = await upload.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValueError(f"upload too large ({len(data)} bytes; max {_MAX_UPLOAD_BYTES})")
    return upload.filename or "upload", data


@router.post("/import/preview")
async def import_preview(file: UploadFile = File(...)):
    """Parse an uploaded statement file/zip and return a preview (writes nothing)."""
    from importers import service

    try:
        name, data = await _read_upload(file)
        files = service.collect_files(name, data)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not files:
        return {"ok": False, "error": "no importable files found in upload"}
    preview = service.preview_files(files)
    return {"ok": True, "preview": _preview_to_dict(preview)}


@router.post("/import/commit")
async def import_commit(file: UploadFile = File(...)):
    """Parse an uploaded statement file/zip and commit it to the store."""
    from importers import service

    try:
        name, data = await _read_upload(file)
        files = service.collect_files(name, data)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not files:
        return {"ok": False, "error": "no importable files found in upload"}
    _log(f"import/commit {name}")
    preview = service.preview_files(files)
    summary = service.commit(preview)
    return {"ok": True, "preview": _preview_to_dict(preview), "summary": summary}
