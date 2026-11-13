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
]

_TAIL_MONEY = re.compile(r"(-?\$?[\d,]+\.\d{2})\s*$")


def _last_amount(s: str) -> str | None:
    m = _TAIL_MONEY.search(s)
    return m.group(1) if m else None


def extract_f1040_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.native_pdf,
) -> list:
    """Lift the as-filed summary figures (and refund/owe + filing status)."""
    text = native_text(kvs)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    facts = []
    seen: set[str] = set()

    def add(code: str, value: str, conf: float = 1.0, money: bool = True) -> None:
        seen.add(code)
        facts.append(make_fact(
            document_id, tax_year, FormType.f1040, code,
            _FIELD_LABELS[code], value, method=method, confidence=conf,
            money=money,
        ))

    for line in lines:
        for pat, code in _ROWS:
            if code in seen or not pat.search(line):
                continue
            amt = _last_amount(line)
            if amt is None:
                continue
            add(code, amt.replace("$", "").replace(",", "") if False else amt)

    # Refund vs owe — the return shows whichever applies (with an amount).
    for line in lines:
        low = line.lower()
        if "ret_amount_owed" not in seen and "amount you owe" in low:
            amt = _last_amount(line)
            if amt:
                add("ret_amount_owed", amt)
        if "ret_refund" not in seen and ("overpaid" in low or "refunded to you" in low):
            amt = _last_amount(line)
            if amt:
                add("ret_refund", amt)

    if "married filing jointly" in text.lower():
        add("ret_filing_status", "Married filing jointly", money=False)

    facts.sort(key=lambda f: f.field_code)
    return facts
