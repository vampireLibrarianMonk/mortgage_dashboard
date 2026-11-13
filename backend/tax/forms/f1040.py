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
    "ret_fed_hsa_deduction": "As-filed HSA deduction (Schedule 1 line 13 / Form 8889 line 13)",
    "ret_fed_hsa_deduction_limit": "As-filed HSA allowable limit (Form 8889 line 12)",
    "ret_fed_hsa_employer_contrib_you": "As-filed HSA employer contributions — taxpayer (Form 8889 line 9)",
    "ret_fed_hsa_employer_contrib_spouse": "As-filed HSA employer contributions — spouse (Form 8889 line 9)",
    "ret_st_va_fagi": "As-filed Virginia FAGI (VA 760 line 1)",
    "ret_st_va_standard_deduction": "As-filed Virginia standard deduction (VA 760 line 11)",
    "ret_st_va_exemptions": "As-filed Virginia exemptions (VA 760 line 12)",
    "ret_st_va_529_deduction": "As-filed Virginia line-13 deductions (Virginia529 deduction when claimed)",
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

# --- value clusters in the e-file print ----------------------------------------
# The e-file print software lays each page's filled values in a separate text
# run: the page prints its labels first, then a footer line, then the values as
# bare number tokens ending in a period, then a 'BAA REV' (federal) or
# 'REV mm/dd/yy' (Virginia) stamp. Two placements matter here:
#   • each Form 8889 copy: values sit between the 'Form 8889 (2025) Created'
#     footer and the 'BAA REV' stamp — the last token is line 13 (the HSA
#     deduction), the one before it is line 12 (the allowable limit), and the
#     repeated early pair is lines 9/11 (employer contributions);
#   • the Virginia 760CG worksheet page: values sit after the 'VA760CG' header.
#     Anchored on the taxable income already lifted from the summary card, the
#     rows two back and three/four back are the line-13 deductions and the
#     exemptions/standard deduction, validated arithmetically below.
_MONEY_TOKEN = re.compile(r"\b\d[\d,]*\.\d{0,2}")
_F8889_FOOTER = re.compile(r"Form 8889 \(2025\) Created", re.I)
_BAA_STAMP = re.compile(r"BAA REV")
_VA760CG_HEADER = re.compile(r"VA760CG")
_VA_STAMP = re.compile(r"REV \d{2}/\d{2}/\d{2}")


def _money_cluster(
    lines: list[str], start_idx: int, stop_pat: re.Pattern[str], max_lines: int = 40
) -> list[float]:
    """Bare money tokens printed after `lines[start_idx]` until the stop stamp.

    Money-shaped tokens only: line numbers ('13.'), SSNs, routing/account
    numbers and ZIPs carry no trailing period and never match."""
    tokens: list[float] = []
    for ln in lines[start_idx + 1 : start_idx + 1 + max_lines]:
        if stop_pat.search(ln):
            break
        tokens.extend(
            float(t.replace(",", "").rstrip(".")) for t in _MONEY_TOKEN.findall(ln)
        )
    return tokens


def _f8889_copies(lines: list[str]) -> list[list[float]]:
    """The value cluster of each Form 8889 copy in the package."""
    clusters: list[list[float]] = []
    for i, ln in enumerate(lines):
        if _F8889_FOOTER.search(ln):
            tokens = _money_cluster(lines, i, _BAA_STAMP, max_lines=15)
            if tokens:
                clusters.append(tokens)
    return clusters


def _va760cg_deduction_rows(lines: list[str], taxable: float | None) -> dict[str, float]:
    """Deduction rows from the VA 760CG worksheet's value cluster.

    Anchored on the as-filed taxable income; kept only when the visual row
    order checks out arithmetically (standard deduction + exemptions +
    deductions == the deductions subtotal). Returns {} when the page or the
    anchor isn't found — absence is honest, a wrong guess is not."""
    out: dict[str, float] = {}
    if taxable is None:
        return out
    for i, ln in enumerate(lines):
        if not _VA760CG_HEADER.search(ln):
            continue
        tokens = _money_cluster(lines, i, _VA_STAMP)
        for j, tok in enumerate(tokens):
            if j < 4 or abs(tok - taxable) > 0.005:
                continue
            deductions, subtotal = tokens[j - 2], tokens[j - 1]
            exemptions, std = tokens[j - 3], tokens[j - 4]
            if abs(std + exemptions + deductions - subtotal) > 0.5:
                continue
            out["deductions"] = deductions
            out["standard_deduction"] = std
            out["exemptions"] = exemptions
            if j >= 7 and abs(tokens[j - 7] - tokens[j - 5]) <= 0.005:
                out["fagi"] = tokens[j - 7]  # FAGI == VAGI (no additions/subtractions)
            break
        if out:
            break
    return out

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
    federal_seen = False

    def add(code: str, label: str, value: str, conf: float = 1.0, money: bool = True) -> None:
        seen.add(code)
        facts.append(make_fact(
            document_id, tax_year, FormType.f1040, code, label, value,
            method=method, confidence=conf, money=money,
        ))

    for jurisdiction, block in _state_blocks(lines):
        if jurisdiction == "Federal":
            federal_seen = True
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
        st_vals: dict[str, str] = {}
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
                st_vals[code] = amt
                st_add(code, amt)
                break

        # The 760CG worksheet page in the same block carries the deduction
        # detail the summary card lacks — FAGI, standard deduction, exemptions
        # and the line-13 'Deductions' (the Virginia529 deduction when
        # claimed). Stored only when the row mapping validates arithmetically.
        if slug == "va":
            taxable = None
            raw = st_vals.get("taxable_income")
            if raw is not None:
                try:
                    taxable = float(str(raw).replace(",", "").replace("$", ""))
                except ValueError:
                    taxable = None
            va_rows = _va760cg_deduction_rows(block, taxable)
            if va_rows:
                st_add("529_deduction", f"{va_rows['deductions']:.2f}")
                st_add("standard_deduction", f"{va_rows['standard_deduction']:.2f}")
                st_add("exemptions", f"{va_rows['exemptions']:.2f}")
                if "fagi" in va_rows:
                    st_add("fagi", f"{va_rows['fagi']:.2f}")

    # Federal-form value clusters, scanned across the WHOLE package exactly
    # once (after the block loop — _state_blocks yields an empty pre-marker
    # 'Federal' block, and the e-file print's duplicate taxpayer copy can sit
    # after a state's instructions block).

    # Form 8889 copies: line 13 is the HSA deduction as filed (the
    # Schedule 1 line-13 amount), line 12 the allowable limit, lines 9/11
    # the employer contributions. Copies are per spouse. Deliberately NOT
    # inferred here: Schedule 1 Part I's footer cluster (two agreeing tokens)
    # cannot distinguish line 8f (taxable HSA distributions) from line 3
    # (business income) — the 2025 return proved that ambiguity real, so no
    # 8f fact is lifted from it.
    if federal_seen:
        copies = _f8889_copies(lines)
        if copies:
            ded = sum(c[-1] for c in copies)
            add("ret_fed_hsa_deduction", _FIELD_LABELS["ret_fed_hsa_deduction"],
                f"{ded:.2f}", conf=0.9)
            limit = sum(c[-2] for c in copies if len(c) >= 2)
            add("ret_fed_hsa_deduction_limit",
                _FIELD_LABELS["ret_fed_hsa_deduction_limit"], f"{limit:.2f}", conf=0.9)
            for n, cluster in enumerate(copies):
                if len(cluster) >= 3 and abs(cluster[1] - cluster[2]) <= 0.005:
                    who = "you" if n == 0 else "spouse"
                    add(f"ret_fed_hsa_employer_contrib_{who}",
                        _FIELD_LABELS[f"ret_fed_hsa_employer_contrib_{who}"],
                        f"{cluster[1]:.2f}", conf=0.9)

    facts.sort(key=lambda f: f.field_code)
    return facts
