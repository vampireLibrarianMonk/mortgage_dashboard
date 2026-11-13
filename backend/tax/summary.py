"""Tax Year Summary: aggregated, facts-only view the Tax Prep UI renders.

Deterministic and honest: every number comes from a stored TaxFact or the
document inventory — nothing is invented, no tax is computed. The only derived
values are clearly-labeled ratios of two as-filed numbers (effective rate,
withholding coverage) and their shortfall in dollars. Missing data is simply
absent so the UI can render empty states."""
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

_STATE_NAMES = {"IL-1040": "Illinois"}

_TAIL_NUM = re.compile(r"^-?\d+(\.\d+)?$")


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
    kept = [
        t for t in tokens
        if t.lower() not in _DROP_TOKENS and not t.isdigit()
    ]
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


def build_summary(year: int, docs: list[TaxDocument], facts_by_doc: dict[str, list[TaxFact]]) -> dict:
    """One year's tax picture, aggregated purely from stored facts."""
    salary_people: list[dict] = []
    investments: list[dict] = []
    side_income: list[dict] = []
    informational: list[dict] = []
    as_filed_federal: dict = {}
    as_filed_state: dict = {}
    doc_refs: list[dict] = []

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
        elif ft is FormType.f1040_il:
            as_filed_state = {
                "name": _STATE_NAMES.get(doc.form_type.value, doc.form_type.value),
                "taxable_income": _num(fvals.get("il_taxable_income")),
                "total_tax": _num(fvals.get("il_tax")),
                "balance_due": _num(fvals.get("il_balance_due")),
                "document_id": doc.id,
            }
        elif ft in (FormType.f1095_c, FormType.f3922):
            informational.append({
                "form_type": ft.value,
                "label": _employer_from_filename(doc.original_filename),
                "document_id": doc.id,
            })

    # Totals over what the facts actually carry (None is treated as absent).
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
            "state": as_filed_state or None,
            "derived": derived or None,
        },
        "hourly": None,  # lights up when a final-2025-paid paystub (with hours) is on file
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
