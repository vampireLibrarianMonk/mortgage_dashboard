"""Consolidated 1099 statement reader (joint WROS/TOD brokerage): native text.

The statement is a real digital PDF (a 51K-char text layer), so the local
provider hands the reader a single __native_text__ KV — the same pattern the
paystub reader uses. The text walks each sub-form (1099-DIV, 1099-INT,
1099-MISC) with dot-leader box rows that end in the amount, and the per-lot
1099-B detail is summarized by "Box A/D realized gain/loss" rows. The statement
covers several accounts, so identical boxes are summed across occurrences."""
from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.forms import make_fact, native_text
from tax.models import ExtractionMethod, FormType

_FIELD_LABELS = {
    "div_1a_ordinary_dividends": "1099-DIV Box 1a — Total ordinary dividends",
    "div_1b_qualified_dividends": "1099-DIV Box 1b — Qualified dividends",
    "div_2a_capital_gain_dist": "1099-DIV Box 2a — Total capital gain distributions",
    "div_3_nondividend_dist": "1099-DIV Box 3 — Nondividend distributions (return of capital)",
    "div_4_fed_withheld": "1099-DIV Box 4 — Federal income tax withheld",
    "div_5_section_199a": "1099-DIV Box 5 — Section 199A dividends",
    "int_1_interest_income": "1099-INT Box 1 — Interest income",
    "int_2_early_withdrawal": "1099-INT Box 2 — Early withdrawal penalty",
    "int_4_fed_withheld": "1099-INT Box 4 — Federal income tax withheld",
    "misc_2_royalties": "1099-MISC Box 2 — Royalties",
    "misc_3_other_income": "1099-MISC Box 3 — Other income",
    "misc_4_fed_withheld": "1099-MISC Box 4 — Federal income tax withheld",
    "b_boxa_st_realized_gain": "1099-B Box A — Short-term realized gain",
    "b_boxa_st_realized_loss": "1099-B Box A — Short-term realized loss",
    "b_boxd_lt_realized_gain": "1099-B Box D — Long-term realized gain",
    "b_boxd_lt_realized_loss": "1099-B Box D — Long-term realized loss",
}

# Box rows: leading box number, a label, dot leaders, then the amount at EOL.
_BOX_LINE = re.compile(
    r"^\s*(\d{1,2}[a-z]?)\s+(.+?)\s*[.\s]*(-?\$?[\d,]+\.\d{2})\s*$"
)

_CODES = {
    ("div", "1a"): "div_1a_ordinary_dividends",
    ("div", "1b"): "div_1b_qualified_dividends",
    ("div", "2a"): "div_2a_capital_gain_dist",
    ("div", "3"): "div_3_nondividend_dist",
    ("div", "4"): "div_4_fed_withheld",
    ("div", "5"): "div_5_section_199a",
    ("int", "1"): "int_1_interest_income",
    ("int", "2"): "int_2_early_withdrawal",
    ("int", "4"): "int_4_fed_withheld",
    ("misc", "2"): "misc_2_royalties",
    ("misc", "3"): "misc_3_other_income",
    ("misc", "4"): "misc_4_fed_withheld",
}

_B_SUMMARY = re.compile(
    r"Box\s+([AD])\s+(Short-Term|Long-Term)\s+Realized\s+(Gain|Loss)\s+(-?[\d,]+\.\d{2})"
)


def extract_f1099_combined_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.native_pdf,
) -> list:
    """Parse the consolidated statement's native text into summed box facts.

    Zeros are skipped (they carry no information); identical boxes appearing on
    multiple accounts are summed into one fact per box code."""
    text = native_text(kvs)
    cur: str | None = None
    sums: dict[str, float] = {}
    for line in text.splitlines():
        s = line.strip()
        if "Form 1099-DIV" in s:
            cur = "div"
            continue
        if "Form 1099-INT" in s:
            cur = "int"
            continue
        if "Form 1099-MISC" in s:
            cur = "misc"
            continue
        if "Form 1099-B" in s:
            cur = "b"
            continue
        m = _BOX_LINE.match(s)
        if m and cur is not None:
            code = _CODES.get((cur, m.group(1).lower()))
            if code:
                amt = float(m.group(3).replace("$", "").replace(",", ""))
                sums[code] = sums.get(code, 0.0) + amt
            continue
        mb = _B_SUMMARY.search(s)
        if mb:
            grp, term, kind, amt = mb.groups()
            grp_c = {"A": "boxa", "D": "boxd"}[grp]
            term_c = {"Short-Term": "st", "Long-Term": "lt"}[term]
            code = f"b_{grp_c}_{term_c}_realized_{kind.lower()}"
            sums[code] = sums.get(code, 0.0) + float(amt.replace(",", ""))
    facts = []
    for code in sorted(sums):
        total = round(sums[code], 2)
        if abs(total) < 0.005:
            continue  # zeros carry no information
        facts.append(make_fact(
            document_id, tax_year, FormType.f1099_div, code,
            _FIELD_LABELS.get(code, code), f"{total:.2f}",
            method=method, confidence=1.0,
        ))
    return facts
