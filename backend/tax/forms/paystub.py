"""Paystub (pay statement) reader: digital-PDF text -> period + YTD facts.

Booz Allen semi-monthly statements are digital PDFs with a real text layer, so
the local provider reads them for free (no Textract). This reader parses that
text into a structured PaystubReading and a flat list of TaxFacts.

Two real-world quirks the parser is built around (confirmed on the 2024 + 2025
corpus):

  * Column collapse. A money row is normally "<label> [cur_hours] <cur$>
    [ytd_hours] <ytd$>". When Social Security hits the annual wage cap, the
    current-period column drops out and only the YTD dollar remains. So we parse
    by matching the row label and reading the trailing dollar tokens, never by a
    fixed column position.

  * Broken final-stub YTD. The last stub of the year (pay period ending 12/31)
    shows its YTD column reset to the single-period value (YTD == current). The
    true full-year total therefore needs the prior stub's YTD plus this stub's
    current period. That reconstruction lives in the year-rebuild step, not here
    — this reader faithfully reports whatever the stub says, per period and YTD.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from tax.extraction.providers import ExtractedKV
from tax.models import ExtractionMethod, FactStatus, FormType, TaxFact

# The local provider exposes a PDF's native text under this synthetic key.
NATIVE_TEXT_KEY = "__native_text__"

_MONEY = re.compile(r"-?\$[\d,]+\.\d{2}")
_PERIOD = re.compile(r"Pay Period:\s*([\d/]+)\s*-\s*([\d/]+)")
_PAY_DATE = re.compile(r"Pay Date:\s*([\d/]+)")
_EMP_NAME = re.compile(r"Employee Name:\s*(.+?)\s+Pay Date:")
_EMPLOYER = re.compile(r"Employer Name:\s*(.+?)\s+(?:State Filing|$)")
_FED_STATUS = re.compile(r"Federal Filing Status:\s*(\w+)")

# Row labels we lift into facts. Each maps a stub line label -> field_code stem.
# Order matters only for readability; matching is by startswith on the stripped
# line, longest-label-first so "Social Security" wins over a bare "Social".
_TAX_ROWS: list[tuple[str, str]] = [
    ("Fed W/H", "ps_fed_withholding"),
    ("Social Security", "ps_ss_tax"),
    ("Medicare", "ps_medicare_tax"),
    ("VA W/H", "ps_va_withholding"),
]

# Section-total rows (the bold line that sums a section's children).
_TOTAL_ROWS: list[tuple[str, str]] = [
    ("Earnings", "ps_gross_earnings"),
    ("Pre-Tax Deductions", "ps_pretax_total"),
    ("Taxes", "ps_taxes_total"),
    ("Post-Tax Deductions", "ps_posttax_total"),
    ("Net Pay", "ps_net_pay"),
]

# Human labels for the review UI.
FIELD_LABELS: dict[str, str] = {
    "ps_gross_earnings": "Gross earnings",
    "ps_pretax_total": "Pre-tax deductions (total)",
    "ps_taxes_total": "Taxes (total)",
    "ps_posttax_total": "Post-tax deductions (total)",
    "ps_net_pay": "Net pay",
    "ps_fed_withholding": "Federal withholding",
    "ps_ss_tax": "Social Security tax",
    "ps_medicare_tax": "Medicare tax",
    "ps_va_withholding": "Virginia withholding",
}


@dataclass
class PaystubAmount:
    """One stub line's current-period and year-to-date dollar amounts.

    ytd is None when the row shows no YTD column (rare); current is None when the
    column collapsed (e.g. Social Security after the wage cap)."""
    current: float | None
    ytd: float | None


@dataclass
class PaystubReading:
    """Everything parsed from a single pay statement."""
    employee_name: str | None = None
    employer_name: str | None = None
    period_start: str | None = None       # "M/D/YYYY" as printed
    period_end: str | None = None
    pay_date: str | None = None
    federal_filing_status: str | None = None
    amounts: dict[str, PaystubAmount] = field(default_factory=dict)

    @property
    def is_final_period_of_year(self) -> bool:
        """True for the 12/31 stub, whose YTD column is the known-broken one."""
        return bool(self.period_end and re.search(r"12/31/\d{4}$", self.period_end))

    @property
    def end_date(self) -> dt.date | None:
        """period_end as a date, for ordering stubs. None if unparseable."""
        return _parse_mdy(self.period_end)

    @property
    def pay_date_parsed(self) -> dt.date | None:
        """pay_date as a date. The W-2 is cash-basis: wages belong to the year
        the check is *paid*, not the period worked, so a period ending 12/31 but
        paid in January counts toward the next year's W-2."""
        return _parse_mdy(self.pay_date)


def _native_text(kvs: list[ExtractedKV]) -> str:
    """The paystub's raw text. Prefer the local provider's synthetic native-text
    KV; otherwise join whatever text the KVs carry (keeps the reader usable even
    if a future provider feeds it differently)."""
    for kv in kvs:
        if kv.key == NATIVE_TEXT_KEY:
            return kv.value
    return "\n".join(f"{kv.key} {kv.value}" for kv in kvs)


def _money(token: str) -> float:
    return float(token.replace("$", "").replace(",", ""))


def _parse_mdy(value: str | None) -> dt.date | None:
    """Parse an 'M/D/YYYY' paystub date. None when absent/unparseable."""
    if not value:
        return None
    try:
        m, d, y = (int(x) for x in value.strip().split("/"))
        return dt.date(y, m, d)
    except (ValueError, TypeError):
        return None


def _amounts_from_line(line: str) -> PaystubAmount:
    """Pull current + YTD dollars from a row.

    A normal row has two dollar tokens (current, then YTD). A collapsed row (SS
    after the cap) has one — treat the lone value as YTD, current unknown. More
    than two tokens shouldn't happen on these rows, but if so the last is YTD and
    the first is current."""
    tokens = _MONEY.findall(line)
    if not tokens:
        return PaystubAmount(current=None, ytd=None)
    if len(tokens) == 1:
        return PaystubAmount(current=None, ytd=_money(tokens[0]))
    return PaystubAmount(current=_money(tokens[0]), ytd=_money(tokens[-1]))


def _match_row(stripped: str, label: str) -> bool:
    """A row belongs to `label` when the line (ignoring leading spaces/bullets)
    starts with that label followed by whitespace or a dollar sign."""
    if not stripped.startswith(label):
        return False
    rest = stripped[len(label):]
    return rest[:1] in ("", " ", "\t", "$", "-")


def parse_paystub(kvs: list[ExtractedKV]) -> PaystubReading:
    """Parse a pay statement's text into a PaystubReading."""
    text = _native_text(kvs)
    reading = PaystubReading()

    if m := _EMP_NAME.search(text):
        reading.employee_name = m.group(1).strip()
    if m := _EMPLOYER.search(text):
        reading.employer_name = m.group(1).strip()
    if m := _PERIOD.search(text):
        reading.period_start, reading.period_end = m.group(1), m.group(2)
    if m := _PAY_DATE.search(text):
        reading.pay_date = m.group(1)
    if m := _FED_STATUS.search(text):
        reading.federal_filing_status = m.group(1)

    # Longest label first so "Social Security" is tried before any prefix, and
    # total rows (e.g. "Earnings") aren't shadowed by a child line.
    rows = sorted(_TAX_ROWS + _TOTAL_ROWS, key=lambda r: -len(r[0]))

    for raw in text.splitlines():
        stripped = raw.strip().lstrip("•").strip()
        for label, code in rows:
            if code in reading.amounts:
                continue  # keep the first (section-total) occurrence
            if _match_row(stripped, label):
                amt = _amounts_from_line(stripped)
                if amt.current is not None or amt.ytd is not None:
                    reading.amounts[code] = amt
                break

    return reading


def extract_paystub_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.native_pdf,
) -> list[TaxFact]:
    """Map a parsed pay statement into TaxFacts.

    Each money row becomes one fact whose value is the YTD figure (the useful
    cumulative number for reconciliation); the current-period amount and the pay
    period are carried in payer_name/field_label context so nothing is lost.
    Digital-text extraction is exact, so confidence is high and facts land as
    `extracted` (not needs_review).
    """
    reading = parse_paystub(kvs)
    facts: list[TaxFact] = []

    period = ""
    if reading.period_start and reading.period_end:
        period = f"{reading.period_start} - {reading.period_end}"

    for code, amt in reading.amounts.items():
        # The YTD figure is what reconciliation consumes; fall back to current
        # when a row has no YTD at all.
        value = amt.ytd if amt.ytd is not None else amt.current
        if value is None:
            continue
        label = FIELD_LABELS.get(code, code)
        facts.append(
            TaxFact(
                tax_year=tax_year,
                document_id=document_id,
                form_type=FormType.paystub,
                payer_name=reading.employer_name,
                taxpayer_name=reading.employee_name,
                field_code=code,
                field_label=f"{label} (YTD)" if amt.ytd is not None else f"{label} (period)",
                value=f"{value:.2f}",
                extraction_method=method,
                confidence=1.0,  # exact digital-text read
                status=FactStatus.extracted,
                extracted_value=f"{value:.2f}",
                # Stash the pay period + current-period amount for the UI/debug;
                # payer_tin_masked is unused for stubs so it's free to repurpose.
                payer_tin_masked=period or None,
            )
        )

    facts.sort(key=lambda f: f.field_code)
    return facts


# --- Year rebuild: reconstruct a validated full-year total from many stubs ----

# The YTD codes a full-year total is meaningful for (money that accumulates).
_YTD_CODES = (
    "ps_gross_earnings",
    "ps_pretax_total",
    "ps_taxes_total",
    "ps_posttax_total",
    "ps_net_pay",
    "ps_fed_withholding",
    "ps_ss_tax",
    "ps_medicare_tax",
    "ps_va_withholding",
)


@dataclass
class YearRebuild:
    """A person's reconstructed full-year totals from their pay statements.

    `totals` is field_code -> dollars. `complete` is False when the stubs don't
    cover the whole calendar year (e.g. only July-December on disk), so callers
    can label the number "partial (from <first> to <last>)" instead of implying
    a true annual figure.
    """
    employee_name: str | None
    employer_name: str | None
    tax_year: int
    totals: dict[str, float] = field(default_factory=dict)
    stub_count: int = 0
    first_period_end: str | None = None
    last_period_end: str | None = None
    complete: bool = False
    notes: list[str] = field(default_factory=list)


def rebuild_year(
    readings: list[PaystubReading],
    tax_year: int,
    boundary: str = "pay_date",
) -> YearRebuild:
    """Reconstruct full-year totals from one person's stubs.

    `boundary` chooses which checks belong to the year:

      * "pay_date" (default, used for W-2 reconciliation). The W-2 is cash-basis:
        wages count in the year the check is *paid*. We keep stubs whose pay date
        falls in `tax_year` and read the YTD of the last such check — the exact
        cumulative figure the W-2 reflects. This naturally excludes a
        period-ending-12/31 check paid in January (it belongs to next year) and
        sidesteps that final stub's broken YTD column entirely. Verified on
        Patrick's 2025 W-2: all four withholding boxes matched to the penny.

      * "period". Keep stubs whose pay *period* falls in `tax_year`, then correct
        the broken final-12/31 YTD by taking the largest trustworthy YTD plus any
        later period. Totals wages earned in the calendar year regardless of pay.

    `complete` is True when the kept stubs span a full year (January through
    December); otherwise the total is honestly partial.
    """
    if boundary == "pay_date":
        def key(r: PaystubReading) -> dt.date | None:
            return r.pay_date_parsed
        in_year = [r for r in readings if r.pay_date_parsed and r.pay_date_parsed.year == tax_year]
    else:
        def key(r: PaystubReading) -> dt.date | None:
            return r.end_date
        in_year = [r for r in readings if r.end_date and r.end_date.year == tax_year]

    ordered = sorted(in_year, key=key)
    name = next((r.employee_name for r in ordered if r.employee_name), None)
    employer = next((r.employer_name for r in ordered if r.employer_name), None)
    result = YearRebuild(
        employee_name=name,
        employer_name=employer,
        tax_year=tax_year,
        stub_count=len(ordered),
    )
    if not ordered:
        result.notes.append(f"No {tax_year} pay statements found.")
        return result

    result.first_period_end = ordered[0].period_end
    result.last_period_end = ordered[-1].period_end

    if boundary == "pay_date":
        # The last in-year check's YTD IS the year total (cumulative, trustworthy
        # — a Jan-paid 12/31 check was already excluded, so no broken YTD here).
        last = ordered[-1]
        for code in _YTD_CODES:
            amt = last.amounts.get(code)
            if amt and amt.ytd is not None:
                result.totals[code] = round(amt.ytd, 2)
            elif amt and amt.current is not None:
                result.totals[code] = round(amt.current, 2)
    else:
        for code in _YTD_CODES:
            base_candidates = [
                r for r in ordered
                if not r.is_final_period_of_year
                and r.amounts.get(code) and r.amounts[code].ytd is not None
            ]
            if not base_candidates:
                periods = [r.amounts[code].current for r in ordered
                           if r.amounts.get(code) and r.amounts[code].current is not None]
                if periods:
                    result.totals[code] = round(sum(periods), 2)
                continue
            base = max(base_candidates, key=lambda r: r.amounts[code].ytd)
            total = base.amounts[code].ytd
            base_end = base.end_date
            for r in ordered:
                if r is base or r.end_date is None or base_end is None:
                    continue
                if r.end_date > base_end:
                    amt = r.amounts.get(code)
                    if amt and amt.current is not None:
                        total += amt.current
            result.totals[code] = round(total, 2)

    first, last_d = key(ordered[0]), key(ordered[-1])
    if first and last_d:
        result.complete = first.month <= 1 and last_d.month == 12
        if not result.complete:
            result.notes.append(
                f"Partial year: stubs cover {result.first_period_end} "
                f"through {result.last_period_end} ({len(ordered)} statements)."
            )
    return result
