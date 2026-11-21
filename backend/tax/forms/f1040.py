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
    "ret_fed_standard_deduction": "As-filed standard deduction (Form 1040)",
    "ret_fed_itemized_deduction": "As-filed itemized deductions (Schedule A)",
    "ret_fed_exemptions": "As-filed exemption deduction (pre-2018 Forms 1040/1040A)",
    "ret_fed_qbi_deduction": "As-filed qualified business income deduction (Form 8995)",
    "ret_fed_withheld": "As-filed federal income tax withheld (Forms W-2/1099)",
    "ret_fed_estimated_payments": "As-filed estimated tax payments",
    "ret_fed_penalty": "As-filed estimated tax penalty (Form 2210)",
    "ret_fed_wages": "As-filed wages (Form 1040 line 1a)",
    "ret_fed_taxable_interest": "As-filed taxable interest (Form 1040 line 2b)",
    "ret_fed_dividends_qualified": "As-filed qualified dividends (Form 1040 line 3a)",
    "ret_fed_dividends_ordinary": "As-filed ordinary dividends (Form 1040 line 3b)",
    "ret_fed_capital_gain_loss": "As-filed capital gain or loss (Form 1040 line 7a)",
    "ret_fed_additional_income": "As-filed additional income (Form 1040 line 8 / Schedule 1 line 10)",
    "ret_fed_total_income": "As-filed total income (Form 1040 line 9)",
    "ret_fed_capital_loss_net": "As-filed net capital loss (Schedule D line 16)",
    "ret_fed_capital_loss_limit": "As-filed capital loss deduction limit (Schedule D line 21)",
    "ret_fed_ctc_children": "As-filed qualifying children for the child tax credit (Schedule 8812 line 4)",
    "ret_fed_ctc_credit": "As-filed child tax credit claimed (Schedule 8812 line 14)",
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
# Same tail position, but whole-dollar amounts allowed ONLY when a literal $
# anchors them — "AMOUNT TO BE REFUNDED TO YOU.....$ 737" lifts 737, while a
# bare line-number token ("...total tax. 39") still cannot match.
_TAIL_MONEY_DOLLAR = re.compile(r"(-?\$[\s]*[\d,]+(?:\.\d{2})?)\s*$")

_STATE_MARKER = re.compile(
    r"Electronic Filing Instructions for your (\d{4})\s+(.+?)\s+Tax Return", re.I
)
# Older TaxAct/HRB prints phrase the block markers differently ("Federal
# Electronic Filing Instructions Tax Year 2014", "2014 Virginia Electronic
# Filing Instructions", "2015 Virginia Electronic Filing Instructions - …").
# Any "Electronic Filing Instructions" line starts/continues a block; the
# jurisdiction comes from the marker line plus its neighbors.
_EFI_MARKER = re.compile(r"(?i)electronic\s+filing\s+instructions")
# H&R Block-style summary sheets ("2021 Federal Tax Return Filing
# Instructions" / "2021 STATE TAX RETURN FILING INSTRUCTIONS VIRGINIA").
_HRB_MARKER = re.compile(
    r"(?i)(?:federal|state)\s+tax\s+return\s+filing\s+instructions"
)
# Preparer (Kang & Thomas) package page headers: "Filing Instructions" over
# "2024 U.S. INDIVIDUAL INCOME TAX RETURN" / "2024 VIRGINIA INCOME TAX RETURN".
_KANG_MARKER = re.compile(r"(?i)^\s*filing\s+instructions\b")
_EFI_JURISDICTIONS = (
    "federal", "virginia", "georgia", "north carolina", "maryland",
    "illinois", "north dakota", "south carolina", "west virginia",
)
_SLUG_ABBR = {"virginia": "va", "illinois": "il"}

# --- value clusters in the e-file print ----------------------------------------
# The e-file print software lays each page's filled values in a separate text
# run: the page prints its labels first, then a footer line, then the values as
# bare number tokens ending in a period, then a 'BAA REV' (federal) or
# 'REV mm/dd/yy' (Virginia) stamp. Two placements matter here:
#   • each Form 8889 copy: values sit between the 'Form 8889 (<year>) Created'
#     footer and the 'BAA REV' stamp — the last token is line 13 (the HSA
#     deduction), the one before it is line 12 (the allowable limit), and the
#     repeated early pair is lines 9/11 (employer contributions);
#   • the Virginia 760CG worksheet page: values sit after the 'VA760CG' header.
#     Anchored on the taxable income already lifted from the summary card, the
#     rows two back and three/four back are the line-13 deductions and the
#     exemptions/standard deduction, validated arithmetically below.
_MONEY_TOKEN = re.compile(r"\b\d[\d,]*\.\d{0,2}")
_BAA_STAMP = re.compile(r"BAA REV")
_VA760CG_HEADER = re.compile(r"VA760CG")
_VA_STAMP = re.compile(r"REV \d{2}/\d{2}/\d{2}")
_STATE_CARD_MARKER = re.compile(r"STATE TAX RETURN FILING INSTRUCTIONS", re.I)

# Footer regexes are year-parametrized: the e-file print stamps each form
# footer with its tax year ("Form 8889 (2025) Created"), so older years'
# packages carry their own year. Each factory derives the pattern from the
# tax_year argument instead of a hardcoded 2025.
def _f8889_footer_pat(tax_year: int) -> re.Pattern[str]:
    return re.compile(rf"Form 8889 \({tax_year}\) Created", re.I)


def _f1040_p1_footer_pat(tax_year: int) -> re.Pattern[str]:
    return re.compile(rf"Form 1040 \({tax_year}\) Created", re.I)


def _sch1_p1_footer_pat(tax_year: int) -> re.Pattern[str]:
    return re.compile(rf"Schedule 1 \(Form 1040\) {tax_year} Created", re.I)


def _sched_d_p2_footer_pat(tax_year: int) -> re.Pattern[str]:
    return re.compile(rf"^Schedule D \(Form 1040\) {tax_year}$")


def _ctc_footer_pat(tax_year: int) -> re.Pattern[str]:
    return re.compile(rf"Schedule 8812 \(Form 1040\) {tax_year} Created", re.I)

# Signed value runs (the 1040 page-1 income run carries negative losses as
# '-3,000.', Schedule D's as '(4,658.)' style).
_SIGNED_MONEY = re.compile(r"-?\(?\d[\d,]*\.\d{0,2}\)?")
_CTC_MULTIPLIER = re.compile(r"Multiply line 4 by \$([\d,]+)")


def _signed_value(token: str) -> float:
    """'-3,000.' -> -3000.0; '(3,000.)' -> -3000.0; '279,469.' -> 279469.0."""
    neg = token.startswith("-") or token.startswith("(")
    digits = token.strip("()").lstrip("-").replace(",", "")
    val = float(digits) if digits not in ("", ".") else 0.0
    return -val if neg else val


def _signed_cluster(
    lines: list[str], start_idx: int, stop_pat: re.Pattern[str], max_lines: int = 40
) -> list[float]:
    """Signed money tokens printed after `lines[start_idx]` until the stop stamp."""
    tokens: list[float] = []
    for ln in lines[start_idx + 1 : start_idx + 1 + max_lines]:
        if stop_pat.search(ln):
            break
        tokens.extend(_signed_value(t) for t in _SIGNED_MONEY.findall(ln))
    return tokens


def _va760cg_summary_rows(run: list[float]) -> dict | None:
    """Parse a VA 760CG page-1 value run into the as-filed card rows.

    Works across print eras (TurboTax 2025, CPA 2022-2023) because every row
    is validated by an arithmetic identity: FAGI == VAGI (no add/sub);
    standard + exemptions (+ deductions) == the deductions subtotal;
    VAGI - subtotal == taxable; net == tax - spouse adjustment; the
    settlement (refund/owe) echoes twice after the payments total, which
    equals the two withholdings. Anything that does not close returns None —
    honest absence, never a guessed row."""
    if len(run) < 9:
        return None
    fagi, vagi = run[0], run[2]
    if fagi <= 0 or abs(fagi - vagi) > 0.005:
        return None
    sub_idx = None
    for s in range(4, min(8, len(run) - 1)):
        mid = run[3:s]
        if len(mid) not in (2, 3):
            continue
        if abs(sum(mid) - run[s]) <= 0.005 and abs(vagi - run[s] - run[s + 1]) <= 0.005:
            sub_idx = s
            break
    if sub_idx is None:
        return None
    taxable = run[sub_idx + 1]
    tax_idx = sub_idx + 2
    if tax_idx >= len(run):
        return None
    tax = run[tax_idx]
    if tax <= 0:
        return None
    net = net_idx = None
    for idx in range(tax_idx + 1, min(tax_idx + 4, len(run))):
        sta = run[idx]
        if not (0 < sta < tax):
            continue
        for offset in (1, 2):
            j = idx + offset
            if j < len(run) and abs(tax - sta - run[j]) <= 0.005:
                net, net_idx = run[j], j
                break
        if net_idx is not None:
            break
    payments = settlement = None
    if net_idx is not None:
        for k in range(net_idx + 1, len(run) - 2):
            if (
                abs(run[k + 1] - run[k + 2]) <= 0.005
                and abs(run[k] - net - run[k + 1]) <= 0.005
            ):
                payments, settlement = run[k], run[k + 1]
                break
    out: dict = {"taxable": taxable, "tax": tax}
    if payments is not None and net is not None and settlement is not None:
        out["payments"] = payments
        if payments > net:
            out["refund"] = settlement
        else:
            out["balance_due"] = settlement
    return out


def _va_tax(taxable: float) -> float:
    """Virginia's statutory schedule (2/3/5/5.75% brackets, unchanged since
    1987). The printed tax tables track this formula within a few dollars, so
    it serves as a cross-era gate on which run token is the tax."""
    t = max(0.0, taxable)
    return (
        0.02 * min(t, 3000)
        + 0.03 * max(0.0, min(t, 5000) - 3000)
        + 0.05 * max(0.0, min(t, 17000) - 5000)
        + 0.0575 * max(0.0, t - 17000)
    )


def _va_card_summary_rows(run: list[float]) -> dict | None:
    """Parse a state-card / standalone-760 value run (H&R Block and TaxAct
    prints, 2008-2020 era) into the as-filed Virginia rows.

    The runs are label-polluted and unordered, so every row is anchored by
    arithmetic: FAGI is the first substantial token; the taxable income is
    found through the Virginia tax schedule (the formula reproduces the
    printed table tax within its drift); the spouse adjustment is the small
    token whose subtraction yields the printed net; payments are the adjacent
    withholding sum (or the doubled withholding echo); and the settlement
    must equal |payments - net| AND appear in the run. Anything that does not
    close returns None."""
    fagi = next((t for t in run if t > 5000), None)
    if fagi is None:
        return None
    fagi_idx = run.index(fagi)
    taxable = tax = None
    for t in run[fagi_idx + 1:]:
        if not (5000 < t < fagi):
            continue
        va = _va_tax(t)
        match = next((x for x in run if x > 0 and abs(x - va) <= 25), None)
        if match is not None:
            taxable, tax = t, match
            break
    if taxable is None:
        return None
    sta = net = None
    for s in run:
        if 0 < s < min(tax, 1000):
            target = round(tax - s, 2)
            if any(abs(x - target) <= 0.005 for x in run):
                sta, net = s, target
                break
    if net is None:
        net = tax
    payments = None
    for k in range(len(run) - 2):
        a, b, c = run[k], run[k + 1], run[k + 2]
        if a > 100 and abs(a + b - c) <= 0.005 and any(
            abs(x - abs(c - net)) <= 0.005 for x in run
        ):
            payments = c
            break
    if payments is None:
        for k in range(len(run) - 1):
            x = run[k]
            if (
                x > 100
                and abs(x - tax) > 0.005
                and abs(x - fagi) > 0.005
                and abs(run[k + 1] - x) <= 0.005
                and any(abs(y - abs(x - net)) <= 0.005 for y in run)
            ):
                payments = x
                break
    if payments is None:
        return {"taxable": taxable, "tax": tax}
    settlement = round(abs(payments - net), 2)
    out: dict = {"taxable": taxable, "tax": tax, "payments": payments}
    if any(abs(x - settlement) <= 0.005 for x in run):
        if payments > net:
            out["refund"] = settlement
        else:
            out["balance_due"] = settlement
    return out


def _cpa_fed_rows(run: list[float], agi_ref: float | None) -> dict | None:
    """CPA-era federal 1040 page-1 value run: [wages, ..., total income,
    AGI, standard, QBI, taxable, ...]. The AGI must equal the VA 760's
    FAGI from the same package (line 1 of the 760 IS the federal AGI),
    and the chain AGI - standard (- QBI) == taxable must close over a
    sliding window (an AGI echo token can sit between rows). Otherwise
    None."""
    if len(run) < 5:
        return None
    wages = run[0]
    if wages <= 5000:
        return None
    agi = None
    if agi_ref is not None:
        agi = next((t for t in run[1:] if abs(t - agi_ref) <= 0.005), None)
    if agi is None:
        return None
    a_idx = run.index(agi)
    for j in range(a_idx + 1, len(run) - 2):
        std, qbi, taxable = run[j], run[j + 1], run[j + 2]
        if std > 5000 and qbi >= 0 and abs(agi - std - qbi - taxable) <= 0.005:
            return {"wages": wages, "agi": agi, "taxable": taxable}
    for j in range(a_idx + 1, len(run) - 1):
        std, taxable = run[j], run[j + 1]
        if std > 5000 and abs(agi - std - taxable) <= 0.005:
            return {"wages": wages, "agi": agi, "taxable": taxable}
    return None



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


def _f8889_copies(lines: list[str], tax_year: int) -> list[list[float]]:
    """The value cluster of each Form 8889 copy in the package."""
    footer = _f8889_footer_pat(tax_year)
    clusters: list[list[float]] = []
    for i, ln in enumerate(lines):
        if footer.search(ln):
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
    if m:
        return m.group(1)
    m = _TAIL_MONEY_DOLLAR.search(s)
    if m:
        val = m.group(1).replace("$", "").replace(" ", "")
        # normalize whole-dollar to two decimals so downstream num() parses
        return val if "." in val else val + ".00"
    return None


def _state_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split the e-file package into (jurisdiction, lines) blocks.

    Each 'Electronic Filing Instructions' marker starts a block; everything
    before the first marker is the Federal block. The 2025 package carries
    Federal + Virginia blocks in the '...for your 2025 Virginia Tax Return'
    phrasing; older TaxAct/HRB prints phrase the same markers differently
    ('Federal Electronic Filing Instructions Tax Year 2014', '2014 Virginia
    Electronic Filing Instructions'), possibly repeating the header on every
    page of one block — a repeated marker for the jurisdiction we are already
    in is treated as a page header, not a new block."""
    blocks: list[tuple[str, list[str]]] = []
    current_name = "Federal"
    current: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if (_EFI_MARKER.search(line) or _HRB_MARKER.search(line)
                or _STATE_MARKER.search(line) or _KANG_MARKER.search(line)):
            # Jurisdiction from the marker line plus following lines UP TO the
            # next marker - a lookahead that crosses into the next marker
            # would attribute this block to the wrong jurisdiction.
            window_parts = [line]
            j = i + 1
            while (j < n and len(window_parts) < 6
                   and not (_EFI_MARKER.search(lines[j])
                            or _HRB_MARKER.search(lines[j])
                            or _STATE_MARKER.search(lines[j])
                            or _KANG_MARKER.search(lines[j]))):
                window_parts.append(lines[j])
                j += 1
            window = " ".join(window_parts)
            jurisdiction = current_name
            if re.search(r"(?i)virginia\s+income\s+tax\s+return", window):
                jurisdiction = "Virginia"
            elif re.search(r"(?i)u\.s\.\s+individual\s+income\s+tax\s+return", window):
                jurisdiction = "Federal"
            else:
                for name in _EFI_JURISDICTIONS:
                    if name != "federal" and re.search(
                        r"(?i)\b" + re.escape(name) + r"\b", window
                    ):
                        jurisdiction = name.title()
                        break
            if jurisdiction != current_name or not current:
                blocks.append((current_name, current))
                current_name = jurisdiction.title()
                current = []
            i += 1
            continue
        current.append(line)
        i += 1
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

    # Year-derived footer patterns (the e-file print stamps its tax year).
    f1040_p1_footer = _f1040_p1_footer_pat(tax_year)
    sch1_p1_footer = _sch1_p1_footer_pat(tax_year)
    sched_d_p2_footer = _sched_d_p2_footer_pat(tax_year)
    ctc_footer = _ctc_footer_pat(tax_year)

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
            used_lines: set[int] = set()
            for pat, code in _ROWS:
                if code in seen:
                    continue
                for idx, line in enumerate(block):
                    if idx in used_lines or not pat.search(line):
                        continue
                    amt = _last_amount(line)
                    if amt is None:
                        continue
                    used_lines.add(idx)
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
        copies = _f8889_copies(lines, tax_year)
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

        # Schedule 1 Part I's footer cluster: its LAST token is line 10 (the
        # additional-income total — the last row of Part I, in visual order).
        # Used purely as a cross-document gate for the 1040 page-1 parse below;
        # line 3 vs 8f cannot be told apart inside the cluster, so no per-line
        # fact is lifted from it (the 2025 return proved that ambiguity real).
        sch1_total: float | None = None
        for i, ln in enumerate(lines):
            if sch1_p1_footer.search(ln):
                run = _signed_cluster(lines, i, _BAA_STAMP, max_lines=8)
                if run:
                    sch1_total = run[-1]
                break

        # Form 1040 page 1's income run: [1a, 1h, 1z, 2b, 3a, 3b, 7a, 8, 9,
        # 11a] as filled on this return. Stored only when every arithmetic
        # identity checks out (1z = 1a + 1h; line 9 = 1z + 2b + 3b + 7a + 8;
        # AGI = line 9 with zero Schedule 1 adjustments; line 8 equals the
        # Schedule 1 line-10 total; AGI equals the summary-block AGI).
        agi_val = next(
            (
                float(str(f.value).replace(",", ""))
                for f in facts
                if f.field_code == "ret_agi"
            ),
            None,
        )
        for i, ln in enumerate(lines):
            if not f1040_p1_footer.search(ln):
                continue
            run = _signed_cluster(lines, i, _BAA_STAMP, max_lines=16)
            if len(run) == 10:
                wages, other, wages_total, interest, div_q, div_o, capital = run[:7]
                additional, total_income, agi = run[7:]
                checks = (
                    abs(wages_total - (wages + other)) <= 0.005
                    and abs(total_income - (wages_total + interest + div_o + capital + additional)) <= 0.005
                    and abs(agi - total_income) <= 0.005
                    and sch1_total is not None
                    and abs(additional - sch1_total) <= 0.005
                    and agi_val is not None
                    and abs(agi - agi_val) <= 0.005
                )
                if checks:
                    for code, val in (
                        ("ret_fed_wages", wages),
                        ("ret_fed_taxable_interest", interest),
                        ("ret_fed_dividends_qualified", div_q),
                        ("ret_fed_dividends_ordinary", div_o),
                        ("ret_fed_capital_gain_loss", capital),
                        ("ret_fed_additional_income", additional),
                        ("ret_fed_total_income", total_income),
                    ):
                        add(code, _FIELD_LABELS[code], f"{val:.2f}", conf=0.9)
            break

        # Schedule D page 2's footer run: [line 16 net capital loss (signed),
        # line 21 loss limit]. The applied 1040 line-7a loss is the statutory
        # limit; anything beyond it carries forward — derived in the summary.
        for i, ln in enumerate(lines):
            if not sched_d_p2_footer.search(ln):
                continue
            run = _signed_cluster(lines, i, _BAA_STAMP, max_lines=8)
            if len(run) == 2 and run[0] < 0 and run[1] > 0 and abs(run[0]) >= run[1]:
                add("ret_fed_capital_loss_net", _FIELD_LABELS["ret_fed_capital_loss_net"],
                    f"{run[0]:.2f}", conf=0.9)
                add("ret_fed_capital_loss_limit", _FIELD_LABELS["ret_fed_capital_loss_limit"],
                    f"{run[1]:.2f}", conf=0.9)
            break

        # Schedule 8812's footer run: the qualifying-children count rides on
        # line 5 ("Multiply line 4 by $2,200" — the multiplier is read from the
        # form's own text so the divisor is never hardcoded). Count only, no
        # names — line 5 / multiplier.
        multiplier: float | None = None
        for ln in lines:
            m = _CTC_MULTIPLIER.search(ln)
            if m:
                multiplier = float(m.group(1).replace(",", ""))
                break
        if multiplier and multiplier > 0:
            for i, ln in enumerate(lines):
                if not ctc_footer.search(ln):
                    continue
                run = _signed_cluster(lines, i, _BAA_STAMP, max_lines=20)
                pair = next(
                    (
                        j
                        for j in range(len(run) - 3)
                        if run[j] > 50000 and abs(run[j + 3] - run[j]) <= 0.005
                    ),
                    None,
                )
                if pair is not None and pair + 4 < len(run):
                    line5, credit = run[pair + 4], run[-1]
                    if (
                        line5 > 0
                        and abs(line5 % multiplier) <= 0.005
                        and abs(credit % multiplier) <= 0.005
                        and credit <= line5
                    ):
                        count = int(round(line5 / multiplier))
                        if 1 <= count <= 10:
                            add("ret_fed_ctc_children",
                                _FIELD_LABELS["ret_fed_ctc_children"], str(count),
                                conf=0.9, money=False)
                            add("ret_fed_ctc_credit", _FIELD_LABELS["ret_fed_ctc_credit"],
                                f"{credit:.2f}", conf=0.9)
                break

        # VA 760CG form pages inside CPA/older packages (2008-2023 era): the
        # value run after the VA760CG marker parses into the as-filed Virginia
        # card rows when every arithmetic identity closes. Skipped when the
        # state block above already produced Virginia facts (2025-style
        # e-file packages carry the instructions card this handles already).
        if not any(f.field_code == "ret_st_va_taxable_income" for f in facts):
            def _st_add(code: str, value: str, money: bool = True) -> None:
                add(f"ret_st_va_{code}",
                    f"As-filed Virginia {code.replace('_', ' ')}",
                    value, conf=0.9, money=money)

            def _emit_va_rows(rows: dict) -> None:
                _st_add("state_name", "Virginia", money=False)
                _st_add("taxable_income", f"{rows['taxable']:.2f}")
                _st_add("total_tax", f"{rows['tax']:.2f}")
                if rows.get("payments") is not None:
                    _st_add("total_payments", f"{rows['payments']:.2f}")
                if rows.get("refund") is not None:
                    _st_add("refund", f"{rows['refund']:.2f}")
                if rows.get("balance_due") is not None:
                    _st_add("balance_due", f"{rows['balance_due']:.2f}")

            # CPA-era packages: the VA760CG page's own value run.
            for i, ln in enumerate(lines):
                if not _VA760CG_HEADER.search(ln):
                    continue
                rows = _va760cg_summary_rows(
                    _signed_cluster(lines, i, _BAA_STAMP, max_lines=25)
                )
                if rows:
                    _emit_va_rows(rows)
                    break
        # CPA-era packages (2022-2024): the federal 1040 page-1 value
            # run parses with the AGI tied to the VA 760's FAGI (line 1 of
            # the 760 IS the federal AGI) and the AGI - standard - QBI ==
            # taxable chain.
        if not any(f.field_code == "ret_fed_wages" for f in facts):
            va_fagi = None
            for i, ln in enumerate(lines):
                if _VA760CG_HEADER.search(ln):
                    va_run = _signed_cluster(lines, i, _BAA_STAMP, max_lines=25)
                    if va_run:
                        va_fagi = va_run[0]
                    break
            for i, ln in enumerate(lines):
                if not re.search(r"U\.S\. Individual Income Tax Return", ln):
                    continue
                run = _signed_cluster(lines, i, _BAA_STAMP, max_lines=40)
                rows = _cpa_fed_rows(run, va_fagi)
                if rows:
                    codes = ("ret_fed_wages", "ret_agi", "ret_taxable_income")
                    facts[:] = [f for f in facts if not (
                        f.field_code in codes and f.value in (None, ""))]
                    for code, val in (("ret_fed_wages", rows["wages"]),
                                      ("ret_agi", rows["agi"]),
                                      ("ret_taxable_income", rows["taxable"])):
                        if not any(f.field_code == code for f in facts):
                            add(code, _FIELD_LABELS.get(code, code),
                                f"{val:.2f}", conf=0.9)
                    break

            # Still nothing: H&R Block state cards and standalone TaxAct 760
            # prints (2008-2020 era) — the universal card parser over both
            # markers, tolerant of the label pollution those prints carry
            # (the TaxAct label block runs ~140 lines before the values).
            if not any(f.field_code == "ret_st_va_taxable_income" for f in facts):
                for marker in (_STATE_CARD_MARKER, _VA760CG_HEADER):
                    for i, ln in enumerate(lines):
                        if not marker.search(ln):
                            continue
                        rows = _va_card_summary_rows(
                            _signed_cluster(lines, i, _BAA_STAMP, max_lines=170)
                        )
                        if rows:
                            _emit_va_rows(rows)
                            break
                    if any(f.field_code == "ret_st_va_taxable_income" for f in facts):
                        break

    facts.sort(key=lambda f: f.field_code)
    return facts
