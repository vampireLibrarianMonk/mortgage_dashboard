"""As-filed Illinois return (IL-1040 e-file package) reader: native text.

Same ground-truth role as the federal return reader: lift the as-filed Illinois
figures (federal AGI, base/net income, exemption, tax, payments, refund/balance)
so every extracted document fact can be cross-checked against what was actually
filed. Nothing is computed here."""
from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.forms import make_fact, native_text
from tax.models import ExtractionMethod, FormType

_FIELD_LABELS = {
    "il_taxable_income": "As-filed Taxable income (IL-1040)",
    "il_tax": "As-filed Total tax (IL-1040)",
    "il_balance_due": "As-filed Payment due (IL-1040)",
}

# Label -> code, matched on the IL-1040 summary's own wording with a dollar
# amount at end-of-line. The IL e-file package's summary block shows exactly
# these three rows (no AGI row); the package also embeds federal form pages
# without amounts, so the $ requirement keeps the summary unambiguous.
_ROWS = [
    (re.compile(r"taxable income", re.I), "il_taxable_income"),
    (re.compile(r"total tax", re.I), "il_tax"),
    (re.compile(r"payment due", re.I), "il_balance_due"),
]

_TAIL_MONEY = re.compile(r"(-?\$?[\d,]+\.\d{2})\s*$")


def extract_il_1040_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.native_pdf,
) -> list:
    """Lift the as-filed Illinois figures (first match per code)."""
    text = native_text(kvs)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    facts = []
    seen: set[str] = set()
    for line in lines:
        for pat, code in _ROWS:
            if code in seen or not pat.search(line):
                continue
            m = _TAIL_MONEY.search(line)
            if m is None:
                continue
            seen.add(code)
            facts.append(make_fact(
                document_id, tax_year, FormType.f1040_il, code,
                _FIELD_LABELS[code], m.group(1), method=method, confidence=1.0,
                money=True,
            ))
    facts.sort(key=lambda f: f.field_code)
    return facts
