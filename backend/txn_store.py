"""Encrypted transaction + merchant-rule store for the categorization console.

Holds raw transactions (id, date, year, month, name/merchant, amount, category)
and a user-owned merchant-rule map (pattern -> category). Everything is stored as
an AES-encrypted (Fernet) JSON blob on disk; the key lives in Windows Credential
Manager. This is a single-user, local tool, so the app backend reads/writes this
store directly (that is how the console does CRUD on transactions).

Categorization is entirely user-driven: rules are created by the user's console
commands. There is NO automatic/LLM categorization.
"""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet

import credential_store as cred

DATA_DIR = Path(__file__).resolve().parent / "txn_data"
TXN_PATH = DATA_DIR / "transactions.json.enc"
RULES_PATH = DATA_DIR / "merchant_rules.json.enc"
KEY_TARGET = "mortgage_dashboard_txn_key"

# Categories the console/app understands. "Uncategorized" is the default state.
CATEGORIES = [
    "Mortgage", "Household", "Utilities", "Vehicle", "ChildCare",
    "PetCare", "Discretionary",
    # "Medical" (doctors, pharmacy, labs, clinics), "Skill Improvement"
    # (work/dev tools, courses), "Security" (home security/monitoring),
    # "Insurance" (home/auto/property), "Legal" (attorneys, background checks),
    # "Home Improvement" (contractor/renovation work, HVAC), "College Savings"
    # (529 contributions) and "Investments" (brokerage contributions) are
    # user-defined categories.
    "Medical", "Skill Improvement", "Security", "Insurance", "Legal",
    "Home Improvement", "College Savings", "Investments",
    # ATM cash activity, tracked as three separate lines so each is traceable:
    # withdrawals (cash out), fees (surcharges), rebates (fee refunds).
    "ATM Withdrawals", "ATM Fees", "ATM Rebates",
    # "Other Home Costs" holds annual/one-off home expenses (contractor jobs,
    # appliances). Reimbursements (negative amounts) filed here net the cost down.
    "Other Home Costs",
    "Income", "Transfer", "Ignore",
    # "Review" parks transactions the user wants to revisit (unclear/worrying
    # items) so they stay visible instead of being filed into a budget bucket.
    # "Reference" keeps zero-dollar / informational entries (e.g. $0 autopay
    # confirmations) on record without affecting any totals.
    "Review", "Reference", "Uncategorized",
]


def _key() -> bytes:
    existing = cred.get_secret(KEY_TARGET)
    if existing:
        return existing.encode("ascii")
    key = Fernet.generate_key()
    cred.set_secret(KEY_TARGET, key.decode("ascii"))
    return key


def _fernet() -> Fernet:
    return Fernet(_key())


def _read_enc(path: Path, default):
    if not path.exists():
        return default
    raw = _fernet().decrypt(path.read_bytes())
    return json.loads(raw.decode("utf-8"))


def _write_enc(path: Path, obj) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    data = json.dumps(obj).encode("utf-8")
    path.write_bytes(_fernet().encrypt(data))


# --- Transactions -------------------------------------------------------------

def load_transactions() -> list[dict]:
    return _read_enc(TXN_PATH, [])


def save_transactions(txns: list[dict]) -> None:
    _write_enc(TXN_PATH, txns)


def set_category(match_text: str, category: str, amount: float | None = None,
                 account_mask: str | None = None) -> int:
    """Set the category on specific matching transactions WITHOUT creating a rule.

    For one-off categorizations that should not auto-apply to future syncs (e.g. a
    generic "Transfer to Checking" that happens to be a one-time bill). Matches by
    case-insensitive substring on name/merchant, optionally narrowed by exact
    amount and/or account. Returns the count updated.
    """
    match_text = match_text.strip().lower()
    txns = load_transactions()
    n = 0
    for t in txns:
        text = f"{t.get('name','')} {t.get('merchant','')}".lower()
        if match_text not in text:
            continue
        if amount is not None and abs(t["amount"] - amount) >= 0.005:
            continue
        if account_mask and t.get("account_mask") != account_mask:
            continue
        t["category"] = category
        n += 1
    save_transactions(txns)
    return n


def set_label(match_text: str, label: str, amount: float | None = None,
              account_mask: str | None = None) -> int:
    """Attach a custom label (a human note) to matching transactions.

    Matches by case-insensitive substring against name/merchant, optionally
    narrowed to an exact amount and/or account. An empty label removes any
    existing label. Labels are informational only; they do not affect
    categorization or budget totals. Returns the count labeled.
    """
    match_text = match_text.strip().lower()
    txns = load_transactions()
    n = 0
    for t in txns:
        text = f"{t.get('name','')} {t.get('merchant','')}".lower()
        if match_text not in text:
            continue
        if amount is not None and abs(t["amount"] - amount) >= 0.005:
            continue
        if account_mask and t.get("account_mask") != account_mask:
            continue
        if label:
            t["label"] = label
        else:
            t.pop("label", None)
        n += 1
    save_transactions(txns)
    return n


# Metadata fields that may be backfilled onto already-known transactions on
# re-sync (they were not captured by earlier versions of the sync). The user's
# category is never touched here.
_BACKFILL_FIELDS = ("bank", "account_id", "account_mask", "merchant", "authorized_date")


def upsert_transactions(new_txns: list[dict]) -> tuple[int, int]:
    """Merge new transactions by transaction_id. Returns (added, skipped).

    Applies existing merchant rules to newly added transactions so known merchants
    are auto-categorized on arrival; unknown ones stay Uncategorized.

    For transactions already known, this backfills newly captured metadata (bank,
    account_id, account_mask, authorized_date) when it is missing, without
    disturbing the user's chosen category. When authorized_date is backfilled, the
    year/month bucket is recomputed from it (swipe date) so monthly actuals reflect
    when spending happened, not when it posted. This lets a re-sync enrich and
    re-bucket older rows in place.
    """
    existing = load_transactions()
    by_id = {t["transaction_id"]: t for t in existing}
    rules = load_rules()
    added = skipped = 0
    for t in new_txns:
        tid = t["transaction_id"]
        if tid in by_id:
            cur = by_id[tid]
            for f in _BACKFILL_FIELDS:
                if not cur.get(f) and t.get(f):
                    cur[f] = t[f]
            # Re-bucket to the incoming sync's authoritative year/month (derived
            # from authorized_date when available). Category is left untouched.
            if t.get("year") and t.get("month"):
                cur["year"], cur["month"] = t["year"], t["month"]
            skipped += 1
            continue
        t.setdefault("category", _match_rule(t, rules) or "Uncategorized")
        by_id[tid] = t
        added += 1
    save_transactions(list(by_id.values()))
    return added, skipped


# --- Merchant rules -----------------------------------------------------------

def load_rules() -> list[dict]:
    """Each rule: {pattern, category, account_mask?}.

    pattern       lowercase substring matched against "name merchant".
    category      target category.
    account_mask  optional last-4 of an account; when set, the rule only applies
                  to transactions on that account (e.g. scope "usaa funds transfer"
                  to account 0000 so it never touches other USAA checking accounts).
    """
    return _read_enc(RULES_PATH, [])


def save_rules(rules: list[dict]) -> None:
    _write_enc(RULES_PATH, rules)


def _rule_matches(rule: dict, txn: dict) -> bool:
    text = f"{txn.get('name','')} {txn.get('merchant','')}".lower()
    if rule["pattern"] not in text:
        return False
    mask = rule.get("account_mask")
    if mask and txn.get("account_mask") != mask:
        return False
    return True


def _rule_specificity(rule: dict) -> int:
    """Higher = more specific. Account-scoped rules outrank text-only ones, and
    longer patterns outrank shorter ones."""
    score = len(rule["pattern"])
    if rule.get("account_mask"):
        score += 1000  # an account-scoped rule always wins over a text-only one
    return score


def _rule_key(rule: dict) -> tuple:
    """Identity of a rule for dedupe/removal: (pattern, account_mask)."""
    return (rule["pattern"], rule.get("account_mask") or None)


def _match_rule(txn: dict, rules: list[dict]) -> str | None:
    """Return the category of the most specific rule matching this transaction.

    When more than one rule matches (e.g. "costco" and "costco gas", or a
    text-only rule and an account-scoped one), the most specific wins:
    account-scoped beats text-only, then longer pattern beats shorter.
    """
    best_cat = None
    best_score = -1
    for r in rules:
        if _rule_matches(r, txn):
            score = _rule_specificity(r)
            if score > best_score:
                best_cat = r["category"]
                best_score = score
    return best_cat


def add_rule(pattern: str, category: str, account_mask: str | None = None) -> int:
    """Add/replace a rule, then re-resolve every transaction.

    An optional account_mask scopes the rule to a single account (last-4). Rules
    are keyed by (pattern, account_mask), so a scoped rule and a text-only rule
    with the same pattern can coexist. Returns the number of transactions this
    rule now owns (it is the most specific match for them).
    """
    pattern = pattern.strip().lower()
    mask = account_mask.strip() if account_mask else None
    new_rule = {"pattern": pattern, "category": category}
    if mask:
        new_rule["account_mask"] = mask

    rules = load_rules()
    rules = [r for r in rules if _rule_key(r) != _rule_key(new_rule)]  # replace if exists
    rules.append(new_rule)
    save_rules(rules)

    txns = load_transactions()
    n = 0
    for t in txns:
        matched = _match_rule(t, rules)
        if matched is not None:
            t["category"] = matched
            # Count the txns this specific new rule directly owns (it is the winner).
            if _rule_matches(new_rule, t) and matched == category:
                # Confirm no other rule outranks it for this txn.
                if _rule_specificity(new_rule) == max(
                    _rule_specificity(r) for r in rules if _rule_matches(r, t)
                ):
                    n += 1
    save_transactions(txns)
    return n


def remove_rule(pattern: str) -> bool:
    """Remove every rule with this pattern (scoped or not) and re-resolve.

    After removal, transactions that were owned by the removed rule are
    re-categorized from the remaining rules. If nothing else matches, they fall
    back to Uncategorized so a removed rule never leaves a stale category behind.
    """
    pattern = pattern.strip().lower()
    rules = load_rules()
    new = [r for r in rules if r["pattern"] != pattern]
    if len(new) == len(rules):
        return False
    save_rules(new)

    # Re-resolve any transaction that no longer has a matching rule.
    txns = load_transactions()
    for t in txns:
        matched = _match_rule(t, new)
        if matched is not None:
            t["category"] = matched
        elif t["category"] != "Uncategorized":
            # Only reset rows that a rule had set; leave nothing stale. We cannot
            # perfectly tell rule-set vs hand-set categories apart, but since all
            # categorization here is rule-driven, falling back is correct.
            text = f"{t.get('name','')} {t.get('merchant','')}".lower()
            if pattern in text:
                t["category"] = "Uncategorized"
    save_transactions(txns)
    return True


# --- Undo support -------------------------------------------------------------
# A small bounded snapshot stack of (transactions, rules) taken before each
# mutating command, so the console `undo` can revert the last change.

_UNDO_STACK: list[tuple[list[dict], list[dict]]] = []
_UNDO_MAX = 20


def snapshot() -> None:
    _UNDO_STACK.append((load_transactions(), load_rules()))
    if len(_UNDO_STACK) > _UNDO_MAX:
        _UNDO_STACK.pop(0)


def undo() -> bool:
    if not _UNDO_STACK:
        return False
    txns, rules = _UNDO_STACK.pop()
    save_transactions(txns)
    save_rules(rules)
    return True
