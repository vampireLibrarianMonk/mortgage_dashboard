"""W-2 ↔ paystub reconciliation.

Cross-checks a person's year-end W-2 against the full-year totals rebuilt from
their pay statements. The W-2 is the filing document; the paystubs are the
independent ground truth. Where they agree, we gain confidence the W-2 scan was
read correctly; where they differ, the difference should be *explainable* by the
structure of payroll (pre-tax deductions bridging gross to taxable wages, the
Social Security wage cap, a final-period timing gap), not a silent error.

Nothing here fabricates a number. Every figure traces to either a W-2 fact or a
paystub total; a line with only one source is reported as such (e.g. Sara has no
paystubs; Patrick's 2024 W-2 money boxes didn't read).
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from tax.forms.paystub import YearRebuild
from tax.models import TaxFact

# Match tolerance: within a dollar, or within 0.5% of the larger figure.
_ABS_TOL = 1.00
_REL_TOL = 0.005


class Verdict(str, Enum):
    match = "match"                      # W-2 and paystub agree within tolerance
    explainable = "explainable_delta"    # differ, but for a known payroll reason
    mismatch = "mismatch"                # differ with no known explanation
    w2_only = "w2_only"                  # only the W-2 has this (no paystub)
    paystub_only = "paystub_only"        # only the paystub has this (no/blank W-2)
    missing = "missing"                   # neither source has it


class ReconcileLine(BaseModel):
    """One reconciled quantity: a W-2 box vs its paystub equivalent."""
    key: str
    label: str
    w2_value: float | None = None
    paystub_value: float | None = None
    delta: float | None = None           # paystub - w2 (when both present)
    verdict: Verdict
    note: str = ""


class PersonReconciliation(BaseModel):
    """A person's full W-2↔paystub reconciliation for one tax year."""
    person: str
    employer: str | None = None
    tax_year: int
    has_w2: bool
    has_paystubs: bool
    paystubs_complete: bool = False
    lines: list[ReconcileLine] = []
    summary: str = ""


# W-2 field_code -> (reconcile key, human label, paystub code it maps to).
# Box 1 is handled specially (gross→taxable bridge), so it's not in this direct
# map; these are the lines that should match near-exactly.
_DIRECT_LINES: list[tuple[str, str, str, str]] = [
    ("box_2_fed_withholding", "fed_withholding", "Federal withholding", "ps_fed_withholding"),
    ("box_4_ss_tax", "ss_tax", "Social Security tax", "ps_ss_tax"),
    ("box_6_medicare_tax", "medicare_tax", "Medicare tax", "ps_medicare_tax"),
    ("box_17_state_tax", "va_withholding", "Virginia withholding", "ps_va_withholding"),
]

# 2025 Social Security employee tax cap (wage base $176,100 × 6.2%). Used only to
# recognize the known cap delta as explainable, never to compute a filing value.
_SS_TAX_CAP_2025 = 10918.20


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return None


def _w2_money(facts: list[TaxFact], field_code: str) -> float | None:
    for f in facts:
        if f.field_code == field_code:
            # Prefer a human-verified value when present.
            v = f.verified_value if f.verified_value is not None else f.value
            return _to_float(v)
    return None


def _within_tolerance(a: float, b: float) -> bool:
    if abs(a - b) <= _ABS_TOL:
        return True
    larger = max(abs(a), abs(b), 1.0)
    return abs(a - b) / larger <= _REL_TOL


def _reconcile_direct(
    label: str,
    key: str,
    w2: float | None,
    paystub: float | None,
    *,
    tax_year: int,
) -> ReconcileLine:
    if w2 is None and paystub is None:
        return ReconcileLine(key=key, label=label, verdict=Verdict.missing)
    if paystub is None:
        return ReconcileLine(
            key=key, label=label, w2_value=w2, verdict=Verdict.w2_only,
            note="No paystub source to cross-check this W-2 value.",
        )
    if w2 is None:
        return ReconcileLine(
            key=key, label=label, paystub_value=paystub, verdict=Verdict.paystub_only,
            note="W-2 value unavailable; showing the paystub total only.",
        )

    delta = round(paystub - w2, 2)
    if _within_tolerance(w2, paystub):
        return ReconcileLine(
            key=key, label=label, w2_value=w2, paystub_value=paystub,
            delta=delta, verdict=Verdict.match,
        )

    # Known explainable delta: Social Security tax at the annual cap. The W-2
    # caps Box 4 at the year's maximum; a paystub that kept withholding on a
    # final period can read higher. Recognize that specific case.
    note = ""
    verdict = Verdict.mismatch
    if key == "ss_tax" and tax_year == 2025:
        if abs(w2 - _SS_TAX_CAP_2025) <= _ABS_TOL and paystub >= w2:
            verdict = Verdict.explainable
            note = (
                f"W-2 Box 4 is capped at the 2025 Social Security maximum "
                f"(${_SS_TAX_CAP_2025:,.2f}); the paystub total is ${delta:,.2f} "
                f"higher, matching a final-period withholding past the cap."
            )
    if not note:
        note = (
            f"Paystub total differs from the W-2 by ${delta:,.2f} with no known "
            f"payroll explanation — worth a manual check."
        )
    return ReconcileLine(
        key=key, label=label, w2_value=w2, paystub_value=paystub,
        delta=delta, verdict=verdict, note=note,
    )


def _reconcile_box1(
    w2_box1: float | None, rebuild: YearRebuild
) -> ReconcileLine:
    """Box 1 (federal taxable wages) vs the gross→taxable bridge.

    Box 1 = gross earnings − federally pre-tax deductions (traditional 401(k),
    medical/dental/vision premiums, HSA, FSA). The paystub reports a single
    "Pre-Tax Deductions" total, which is exactly that set, so:

        expected Box 1 ≈ gross − pre-tax total
    """
    label = "Taxable wages (Box 1)"
    key = "taxable_wages"
    gross = rebuild.totals.get("ps_gross_earnings")
    pretax = rebuild.totals.get("ps_pretax_total")

    if gross is None:
        if w2_box1 is None:
            return ReconcileLine(key=key, label=label, verdict=Verdict.missing)
        return ReconcileLine(
            key=key, label=label, w2_value=w2_box1, verdict=Verdict.w2_only,
            note="No paystub gross to derive taxable wages.",
        )

    bridged = round(gross - (pretax or 0.0), 2)
    if w2_box1 is None:
        return ReconcileLine(
            key=key, label=label, paystub_value=bridged, verdict=Verdict.paystub_only,
            note=(
                f"W-2 Box 1 unavailable. Paystub-derived taxable wages = gross "
                f"${gross:,.2f} − pre-tax ${pretax or 0:,.2f}."
            ),
        )

    delta = round(bridged - w2_box1, 2)
    if _within_tolerance(w2_box1, bridged):
        verdict = Verdict.match
        note = (
            f"Gross ${gross:,.2f} − pre-tax ${pretax or 0:,.2f} = ${bridged:,.2f}, "
            f"matching W-2 Box 1."
        )
    else:
        verdict = Verdict.explainable if abs(delta) <= max(1.0, 0.03 * w2_box1) else Verdict.mismatch
        note = (
            f"Gross ${gross:,.2f} − pre-tax ${pretax or 0:,.2f} = ${bridged:,.2f}; "
            f"W-2 Box 1 is ${w2_box1:,.2f} (Δ ${delta:,.2f}). "
            + (
                "Small gaps are typical when a pre-tax item (e.g. Roth is NOT pre-tax) "
                "is categorized differently."
                if verdict == Verdict.explainable
                else "Difference is larger than expected — worth a manual check."
            )
        )
    return ReconcileLine(
        key=key, label=label, w2_value=w2_box1, paystub_value=bridged,
        delta=delta, verdict=verdict, note=note,
    )


def reconcile_person(
    person: str,
    tax_year: int,
    w2_facts: list[TaxFact] | None,
    rebuild: YearRebuild | None,
) -> PersonReconciliation:
    """Reconcile one person's W-2 facts against their paystub year-rebuild.

    Either source may be absent: a person with only a W-2 (no paystubs) still
    gets a report (every line w2_only); a person whose W-2 money didn't read but
    who has paystubs gets the paystub side (paystub_only).
    """
    w2_facts = w2_facts or []
    has_w2 = any(_w2_money(w2_facts, c) is not None for c in (
        "box_1_wages", "box_2_fed_withholding", "box_4_ss_tax",
        "box_6_medicare_tax", "box_17_state_tax",
    ))
    has_paystubs = rebuild is not None and bool(rebuild.totals)

    employer = None
    if rebuild and rebuild.employer_name:
        employer = rebuild.employer_name

    lines: list[ReconcileLine] = []
    empty_rebuild = rebuild or YearRebuild(
        employee_name=person, employer_name=None, tax_year=tax_year
    )
    lines.append(_reconcile_box1(_w2_money(w2_facts, "box_1_wages"), empty_rebuild))

    for w2_code, key, label, ps_code in _DIRECT_LINES:
        lines.append(
            _reconcile_direct(
                label, key,
                _w2_money(w2_facts, w2_code),
                empty_rebuild.totals.get(ps_code),
                tax_year=tax_year,
            )
        )

    recon = PersonReconciliation(
        person=person,
        employer=employer,
        tax_year=tax_year,
        has_w2=has_w2,
        has_paystubs=has_paystubs,
        paystubs_complete=bool(rebuild and rebuild.complete),
        lines=lines,
    )
    recon.summary = _summarize(recon, rebuild)
    return recon


def _summarize(recon: PersonReconciliation, rebuild: YearRebuild | None) -> str:
    if not recon.has_w2 and not recon.has_paystubs:
        return f"No W-2 or paystub data for {recon.person} in {recon.tax_year}."
    if recon.has_w2 and not recon.has_paystubs:
        return (
            f"{recon.person}: W-2 only — no paystubs to cross-check "
            f"(the W-2 stands on its own)."
        )
    if recon.has_paystubs and not recon.has_w2:
        base = (
            f"{recon.person}: paystubs only — the W-2 money boxes could not be "
            f"read, so figures below are paystub-derived."
        )
        if rebuild and not rebuild.complete:
            base += f" Paystubs are partial ({rebuild.first_period_end}–{rebuild.last_period_end})."
        return base

    matches = sum(1 for ln in recon.lines if ln.verdict == Verdict.match)
    explain = sum(1 for ln in recon.lines if ln.verdict == Verdict.explainable)
    mism = sum(1 for ln in recon.lines if ln.verdict == Verdict.mismatch)
    checked = matches + explain + mism
    parts = [f"{recon.person}: {matches}/{checked} lines match the W-2"]
    if explain:
        parts.append(f"{explain} explainable")
    if mism:
        parts.append(f"{mism} need review")
    tail = ""
    if rebuild and not rebuild.complete:
        tail = f" Paystubs partial ({rebuild.first_period_end}–{rebuild.last_period_end})."
    return "; ".join(parts) + "." + tail


# --- Household rollup ---------------------------------------------------------

class HouseholdTotals(BaseModel):
    """Summed W-2 figures across everyone in the household for one year.

    These are the raw inputs a filing calculation would start from (wages and
    tax already withheld). We stop here on purpose: this phase does not compute
    tax owed or a refund — that needs the filing engine (a later phase).
    """
    tax_year: int
    total_wages: float = 0.0            # sum of Box 1
    total_fed_withheld: float = 0.0     # sum of Box 2
    total_ss_tax: float = 0.0           # sum of Box 4
    total_medicare_tax: float = 0.0     # sum of Box 6
    total_state_withheld: float = 0.0   # sum of Box 17
    people_counted: list[str] = []
    people_missing_w2: list[str] = []


class HouseholdReconciliation(BaseModel):
    """Everyone's per-person reconciliation plus the household W-2 rollup."""
    tax_year: int
    people: list[PersonReconciliation] = []
    totals: HouseholdTotals
    summary: str = ""


def reconcile_household(
    tax_year: int,
    per_person: dict[str, tuple[list[TaxFact] | None, YearRebuild | None]],
) -> HouseholdReconciliation:
    """Reconcile every person and roll their W-2 figures into a household total.

    `per_person` maps a display name -> (that person's W-2 facts, their paystub
    year-rebuild). Either may be None. The household total sums only W-2 figures
    that were actually read; a person with no readable W-2 is listed under
    `people_missing_w2` so the total is never silently understated.
    """
    people: list[PersonReconciliation] = []
    totals = HouseholdTotals(tax_year=tax_year)

    for name in sorted(per_person):
        w2_facts, rebuild = per_person[name]
        recon = reconcile_person(name, tax_year, w2_facts, rebuild)
        people.append(recon)

        box1 = _w2_money(w2_facts or [], "box_1_wages")
        if box1 is None:
            totals.people_missing_w2.append(name)
            continue
        totals.people_counted.append(name)
        totals.total_wages += box1
        totals.total_fed_withheld += _w2_money(w2_facts or [], "box_2_fed_withholding") or 0.0
        totals.total_ss_tax += _w2_money(w2_facts or [], "box_4_ss_tax") or 0.0
        totals.total_medicare_tax += _w2_money(w2_facts or [], "box_6_medicare_tax") or 0.0
        totals.total_state_withheld += _w2_money(w2_facts or [], "box_17_state_tax") or 0.0

    for fld in ("total_wages", "total_fed_withheld", "total_ss_tax",
                "total_medicare_tax", "total_state_withheld"):
        setattr(totals, fld, round(getattr(totals, fld), 2))

    counted = ", ".join(totals.people_counted) or "no one"
    summary = (
        f"{tax_year} household W-2 totals from {counted}: wages "
        f"${totals.total_wages:,.2f}, federal withheld ${totals.total_fed_withheld:,.2f}, "
        f"Virginia withheld ${totals.total_state_withheld:,.2f}."
    )
    if totals.people_missing_w2:
        summary += (
            f" Not included (W-2 unreadable/missing): "
            f"{', '.join(totals.people_missing_w2)}."
        )
    summary += " Tax owed/refund is not computed yet (filing engine is a later phase)."

    return HouseholdReconciliation(
        tax_year=tax_year, people=people, totals=totals, summary=summary
    )
