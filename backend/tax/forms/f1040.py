"""As-filed federal return (1040 e-file package) reader: native text.

The e-file print package carries a real text layer and a compact summary block
(Adjusted Gross Income / Taxable Income / Total Tax / Total Payments/Credits).
This reader lifts those as-filed figures as ground-truth facts — the cross-check
anchor every other document's extracted numbers are validated against. Nothing
is computed: the filed return already is the truth."""
from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.forms import make_fact, native_text
from tax.models import ExtractionMethod, FormType

_FIELD_LABELS = {
    "ret_agi": "As-filed Adjusted Gross Income (1040)",
    "ret_taxable_income": "As-filed Taxable income (1040)",
    "ret_total_tax": "As-filed Total tax (1040)",
    "ret_total_payments": "As-filed Total payments/credits (1040)",
    "ret_amount_owed": "As-filed Amount you owe (1040)",
    "ret_refund": "As-filed Overpaid / refunded (1040)",
    "ret_filing_status": "As-filed Filing status (1040)",
}

# Summary rows: matched on the label with a dollar amount at end-of-line (the
# detailed 1040 pages print the same labels without amounts, so requiring a
# trailing $ keeps the summary unambiguous). First match per code wins.
_ROWS = [
    (re.compile(r"adjusted gross income", re.I), "ret_agi"),
    (re.compile(r"taxable income", re.I), "ret_taxable_income"),
    (re.compile(r"total tax", re.I), "ret_total_tax"),
    (re.compile(r"total payments/credits", re.I), "ret_total_payments"),
    (re.compile(r"balance due", re.I), "ret_amount_owed"),
    (re.compile(r"amount you owe", re.I), "ret_amount_owed"),
    (re.compile(r"refunded to you", re.I), "ret_refund"),
    (re.compile(r"overpaid", re.I), "ret_refund"),
]

_TAIL_MONEY = re.compile(r"(-?\$?[\d,]+\.\d{2})\s*$")

_STATE_MARKER = re.compile(
    r"Electronic Filing Instructions for your (\d{4})\s+(.+?)\s+Tax Return", re.I
)
_SLUG_ABBR = {"virginia": "va", "illinois": "il"}

# Per-state summary rows inside a state's e-file block (same $-at-EOL rule).
_ST_ROWS = [
    (re.compile(r"taxable income", re.I), "taxable_income"),
    (re.compile(r"total tax", re.I), "total_tax"),
    (re.compile(r"total payments/credits", re.I), "total_payments"),
    (re.compile(r"amount to be refunded", re.I), "refund"),
    (re.compile(r"balance due", re.I), "balance_due"),
    (re.compile(r"amount you owe", re.I), "balance_due"),
]


def _last_amount(s: str) -> str | None:
    m = _TAIL_MONEY.search(s)
    return m.group(1) if m else None


def _state_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split the e-file package into (jurisdiction, lines) blocks.

    Each 'Electronic Filing Instructions for your <year> <jurisdiction> Tax
    Return' marker starts a block; everything before the first marker is the
    Federal block. The real 2025 package carries Federal + Virginia blocks."""
    blocks: list[tuple[str, list[str]]] = []
    current_name = "Federal"
    current: list[str] = []
    for line in lines:
        m = _STATE_MARKER.search(line)
        if m:
            blocks.append((current_name, current))
            current_name = m.group(2).strip().title()
            current = []
            continue
        current.append(line)
    blocks.append((current_name, current))
    return blocks


def extract_f1040_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.native_pdf,
) -> list:
    """Lift the as-filed figures: the federal summary plus every state summary
    block embedded in the same e-file package (e.g. Virginia Form 760)."""
    text = native_text(kvs)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    facts = []
    seen: set[str] = set()

    def add(code: str, label: str, value: str, conf: float = 1.0, money: bool = True) -> None:
        seen.add(code)
        facts.append(make_fact(
            document_id, tax_year, FormType.f1040, code, label, value,
            method=method, confidence=conf, money=money,
        ))

    for jurisdiction, block in _state_blocks(lines):
        if jurisdiction == "Federal":
            for pat, code in _ROWS:
                if code in seen:
                    continue
                for line in block:
                    if not pat.search(line):
                        continue
                    amt = _last_amount(line)
                    if amt is None:
                        continue
                    add(code, _FIELD_LABELS[code], amt)
                    break
            if "married filing jointly" in " ".join(block).lower():
                add("ret_filing_status", _FIELD_LABELS["ret_filing_status"],
                    "Married filing jointly", money=False)
            continue

        # A state block (e.g. Virginia Form 760): slug-stable state facts.
        slug = _SLUG_ABBR.get(jurisdiction.lower(), jurisdiction.lower().replace(" ", ""))
        st_add = lambda code, value, money=True: add(
            f"ret_st_{slug}_{code}",
            f"As-filed {jurisdiction} {code.replace('_', ' ')}",
            value, money=money,
        )
        st_seen: set[str] = set()
        state_name_done = False
        for line in block:
            if not state_name_done:
                st_add("state_name", jurisdiction, money=False)
                state_name_done = True
            for pat, code in _ST_ROWS:
                if code in st_seen or not pat.search(line):
                    continue
                amt = _last_amount(line)
                if amt is None:
                    continue
                st_seen.add(code)
                st_add(code, amt)
                break

    facts.sort(key=lambda f: f.field_code)
    return facts
