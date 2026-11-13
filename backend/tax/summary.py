"""Tax Year Summary: aggregated, facts-only view the Tax Prep UI renders.

Deterministic and honest: every number comes from a stored TaxFact or the
document inventory — nothing is invented, no tax is computed. The only derived
values are clearly-labeled ratios of two as-filed numbers (effective rate,
withholding coverage) and their shortfall. Missing data is simply absent — the
UI renders empty states, never estimates."""
from __future__ import annotations

import re

from tax import storage
from tax.models import FormType, TaxDocument, TaxFact

# Filename tokens that never describe an employer/payer.
_DROP_TOKENS = {
    "w2", "copy", "a", "b", "2023", "2024", "2025", "2026", "cover",
    "1099", "int", "nec", "div", "misc", "1095", "c", "3922", "1040", "il",
    "joint", "wros", "tod", "consolidated", "form", "return", "espp", "0625",
    "patrick", "sara", "employer", "coverage",
}

_STATE_NAMES = {"IL-1040": "Illinois", "VA-1040": "Virginia"}


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(str(value).replace(",", "").replace("$", "")), 2)
    except ValueError:
        return None


def _person_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    low = filename.lower()
    for name in ("Patrick", "Sara"):
        if name.lower() in low:
            return name
    return None


def _employer_from_filename(filename: str | None) -> str | None:
    """'W2_Patrick_Booz_Allen_2025_Copy_B.pdf' -> 'Booz Allen'.

    Deterministic token filter: form/year/person/copy markers are dropped and
    whatever remains is the payer/employer the filename was saved with."""
    if not filename:
        return None
    stem = filename.rsplit(".", 1)[0]
    tokens = [t for t in re.split(r"[_\-]", stem) if t]
    kept = [t for t in tokens if t.lower() not in _DROP_TOKENS and not t.isdigit()]
    return " ".join(kept) if kept else None


def _facts_map(facts: list[TaxFact]) -> dict[str, object]:
    return {f.field_code: f.value for f in facts}


def _w2_entry(doc: TaxDocument, fvals: dict[str, object]) -> dict:
    return {
        "person": doc.taxpayer or _person_from_filename(doc.original_filename),
        "employer": _employer_from_filename(doc.original_filename),
        "wages": _num(fvals.get("box_1_wages")),
        "fed_withholding": _num(fvals.get("box_2_fed_withholding")),
        "ss_wages": _num(fvals.get("box_3_ss_wages")),
        "medicare_wages": _num(fvals.get("box_5_medicare_wages")),
        "state": fvals.get("box_15_state"),
        "state_withholding": _num(fvals.get("box_17_state_tax")),
        "document_id": doc.id,
    }


def _investment_entry(doc: TaxDocument, fvals: dict[str, object]) -> dict:
    return {
        "payer": _employer_from_filename(doc.original_filename),
        "interest": _num(fvals.get("box_1_interest_income")),
        "interest_fed_withheld": _num(fvals.get("box_4_fed_withheld")),
        "dividends_ordinary": _num(fvals.get("div_1a_ordinary_dividends")),
        "dividends_qualified": _num(fvals.get("div_1b_qualified_dividends")),
        "dividends_199a": _num(fvals.get("div_5_section_199a")),
        "nondividend_distributions": _num(fvals.get("div_3_nondividend_dist")),
        "st_realized_gain": _num(fvals.get("b_boxa_st_realized_gain")),
        "st_realized_loss": _num(fvals.get("b_boxa_st_realized_loss")),
        "lt_realized_gain": _num(fvals.get("b_boxd_lt_realized_gain")),
        "lt_realized_loss": _num(fvals.get("b_boxd_lt_realized_loss")),
        "document_id": doc.id,
    }


def _side_income_entry(doc: TaxDocument, fvals: dict[str, object]) -> dict:
    return {
        "payer": _employer_from_filename(doc.original_filename),
        "person": doc.taxpayer or _person_from_filename(doc.original_filename),
        "amount": _num(fvals.get("box_1_nonemployee_comp")),
        "fed_withheld": _num(fvals.get("box_4_fed_withholding")),
        "state": fvals.get("box_6_state_number"),
        "document_id": doc.id,
    }


def _doc_ref(doc: TaxDocument) -> dict:
    return {
        "id": doc.id,
        "filename": doc.original_filename,
        "form_type": doc.form_type.value,
        "stage": doc.stage.value,
        "taxpayer": doc.taxpayer,
    }


def _deduction_entries(doc_id: str, fvals: dict[str, object]) -> list[dict]:
    """Deductions/adjustments the filed return shows, each with the jurisdiction
    it actually reduces. Only what the documents carry — an unclaimed deduction
    is shown as 0 with the reason the return itself gives (via Form 8889)."""
    entries: list[dict] = []

    if fvals.get("ret_fed_hsa_deduction") is not None:
        bits: list[str] = []
        employer = [
            (who, _num(fvals.get(f"ret_fed_hsa_employer_contrib_{who}")))
            for who in ("you", "spouse")
        ]
        if any(v is not None for _, v in employer):
            parts = ", ".join(f"{w} ${v:,.0f}" for w, v in employer if v is not None)
            bits.append(f"contributions ran through payroll — employer {parts} (Form 8889)")
        limit = _num(fvals.get("ret_fed_hsa_deduction_limit"))
        if limit:
            bits.append(f"${limit:,.0f} allowable but unclaimed (Form 8889 line 12)")
        dist = _num(fvals.get("ret_fed_hsa_taxable_distribution"))
        if dist:
            bits.append(f"${dist:,.0f} of distributions was taxable (Schedule 1 line 8f)")
        entries.append({
            "label": "Health savings account deduction",
            "source": "Schedule 1 (1040) line 13 · Form 8889 line 13",
            "jurisdiction": "Federal",
            "amount": _num(fvals.get("ret_fed_hsa_deduction")),
            "document_id": doc_id,
            "note": "; ".join(bits) or None,
        })

    va_529 = _num(fvals.get("ret_st_va_529_deduction"))
    if va_529 is not None:
        va_bits = [
            "reduces Virginia taxable income only — 529 contributions are not deductible on the federal return",
        ]
        if va_529 >= 3999.995:
            va_bits.append("$4,000 is the per-account Virginia529 annual maximum")
        entries.append({
            "label": "Virginia529 college savings deduction",
            "source": "VA 760 line 13 (Deductions)",
            "jurisdiction": "Virginia",
            "amount": va_529,
            "document_id": doc_id,
            "note": "; ".join(va_bits),
        })

    return entries


def _il_529_entry(doc_id: str) -> dict:
    return {
        "label": "Illinois 529 (Bright Start / Bright Directions) subtraction",
        "source": "IL-1040 Schedule M",
        "jurisdiction": "Illinois",
        "amount": None,
        "document_id": doc_id,
        "note": "No 529/college-savings subtraction appears in the filed IL-1040 package.",
    }


def build_summary(year: int, docs: list[TaxDocument], facts_by_doc: dict[str, list[TaxFact]]) -> dict:
    """One year's tax picture, aggregated purely from stored facts."""
    salary_people: list[dict] = []
    investments: list[dict] = []
    side_income: list[dict] = []
    informational: list[dict] = []
    as_filed_federal: dict = {}
    as_filed_states: list[dict] = []
    doc_refs: list[dict] = []
    deductions: list[dict] = []
    il_doc_id: str | None = None

    for doc in sorted(docs, key=lambda d: d.original_filename):
        fvals = _facts_map(facts_by_doc.get(doc.id, []))
        doc_refs.append(_doc_ref(doc))
        ft = doc.form_type

        if ft is FormType.w2:
            salary_people.append(_w2_entry(doc, fvals))
        elif ft is FormType.f1099_int:
            investments.append(_investment_entry(doc, fvals))
        elif ft is FormType.f1099_div:
            investments.append(_investment_entry(doc, fvals))
        elif ft is FormType.f1099_nec:
            side_income.append(_side_income_entry(doc, fvals))
        elif ft is FormType.f1040:
            as_filed_federal = {
                "agi": _num(fvals.get("ret_agi")),
                "taxable_income": _num(fvals.get("ret_taxable_income")),
                "total_tax": _num(fvals.get("ret_total_tax")),
                "total_payments": _num(fvals.get("ret_total_payments")),
                "balance_due": _num(fvals.get("ret_amount_owed")),
                "refund": _num(fvals.get("ret_refund")),
                "filing_status": fvals.get("ret_filing_status"),
                "document_id": doc.id,
            }
            # State summaries embedded in the same e-file package (e.g. the
            # Virginia 760 block) — one entry per state found.
            st: dict[str, dict] = {}
            for code, val in fvals.items():
                m = re.match(r"ret_st_([a-z]+)_(.+)$", code)
                if m:
                    st.setdefault(m.group(1), {})[m.group(2)] = val
            for slug in sorted(st):
                kv = st[slug]
                as_filed_states.append({
                    "name": kv.get("state_name"),
                    "taxable_income": _num(kv.get("taxable_income")),
                    "total_tax": _num(kv.get("total_tax")),
                    "payments": _num(kv.get("total_payments")),
                    "refund": _num(kv.get("refund")),
                    "balance_due": _num(kv.get("balance_due")),
                    "document_id": doc.id,
                })
            # Deductions & adjustments the filed package shows, with the
            # jurisdiction each one actually reduces.
            deductions.extend(_deduction_entries(doc.id, fvals))
        elif ft is FormType.f1040_il:
            il_doc_id = doc.id
            as_filed_states.append({
                "name": _STATE_NAMES.get(doc.form_type.value, doc.form_type.value),
                "taxable_income": _num(fvals.get("il_taxable_income")),
                "total_tax": _num(fvals.get("il_tax")),
                "payments": None,
                "refund": None,
                "balance_due": _num(fvals.get("il_balance_due")),
                "document_id": doc.id,
            })
        elif ft in (FormType.f1095_c, FormType.f3922):
            informational.append({
                "form_type": ft.value,
                "label": _employer_from_filename(doc.original_filename),
                "document_id": doc.id,
            })

    # Totals over what the facts actually carry (None is treated as absent).
    if il_doc_id is not None and not any(
        d["jurisdiction"] == "Illinois" for d in deductions
    ):
        deductions.append(_il_529_entry(il_doc_id))
    total_wages = round(sum(p["wages"] or 0 for p in salary_people), 2)
    total_fed_wh = round(sum(p["fed_withholding"] or 0 for p in salary_people), 2)
    total_state_wh = round(sum(p["state_withholding"] or 0 for p in salary_people), 2)
    total_interest = round(sum(i["interest"] or 0 for i in investments if i["interest"]), 2)
    total_side = round(sum(s["amount"] or 0 for s in side_income if s["amount"]), 2)
    net_realized = round(sum(
        (i.get(k) or 0) for i in investments
        for k in ("st_realized_gain", "st_realized_loss", "lt_realized_gain", "lt_realized_loss")
    ), 2)

    # Derived ratios — arithmetic over two as-filed numbers, never a computation
    # of tax. Fed withholding coverage uses salary withholding only (the docs
    # that prove it); the as-filed balance due is the authoritative shortfall.
    derived: dict = {}
    fed = as_filed_federal
    if fed.get("total_tax") is not None and fed.get("agi"):
        derived["effective_rate"] = round(fed["total_tax"] / fed["agi"], 4)
    if fed.get("total_tax") is not None:
        derived["withholding_coverage"] = (
            round(total_fed_wh / fed["total_tax"], 4) if fed["total_tax"] else None
        )
        derived["withholding_shortfall"] = round(fed["total_tax"] - total_fed_wh, 2)

    # Combined as-filed outcome across all filings (federal + states) — the
    # figure the year chip shows. Owes add up; refunds net against them.
    filings = ([as_filed_federal] if as_filed_federal else []) + as_filed_states
    balance_total = round(sum((x.get("balance_due") or 0) for x in filings), 2)
    refund_total = round(sum((x.get("refund") or 0) for x in filings), 2)
    combined = None
    if filings:
        combined = {
            "balance_due_total": balance_total,
            "refund_total": refund_total,
            "net_owed": round(balance_total - refund_total, 2),
        }

    return {
        "year": year,
        "salary": {
            "people": salary_people,
            "total_wages": total_wages,
            "total_fed_withholding": total_fed_wh,
            "total_state_withholding": total_state_wh,
        },
        "investments": {
            "statements": investments,
            "total_interest": total_interest,
            "net_realized_gain_loss": net_realized,
        },
        "side_income": {
            "entries": side_income,
            "total": total_side,
        },
        "as_filed": {
            "federal": as_filed_federal or None,
            "states": as_filed_states,
            "combined": combined,
            "derived": derived or None,
        },
        "deductions": deductions,
        "hourly": None,  # lights up when a final-of-year paystub (with hours) is on file
        "dependents": None,  # needs a column-aware parse of the 1040 dependents table
        "informational": informational,
        "documents": doc_refs,
    }


def summaries_for_years(years: list[int]) -> list[dict]:
    """Per-year summaries; years without documents return an empty skeleton."""
    out = []
    for year in years:
        docs = storage.list_documents(year)
        facts = storage.load_all_facts(year)
        summary = build_summary(year, docs, facts)
        summary["has_documents"] = bool(docs)
        out.append(summary)
    return out
