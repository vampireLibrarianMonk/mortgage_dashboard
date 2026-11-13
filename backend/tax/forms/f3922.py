"""Form 3922 reader (informational): ESPP purchases — Fidelity transferor.

Carries the option/transfer dates, fair-market values, exercise price, and share
counts for the employee stock purchase plan. No income or deduction unless ESPP
shares were later sold (which would appear on a 1099-B/consolidated statement)."""
from __future__ import annotations

from tax.extraction.providers import ExtractedKV
from tax.forms import make_fact
from tax.models import ExtractionMethod, FormType
from tax.pii import mask_ssn

_FIELD_LABELS = {
    "transferor_name": "Transferor's name (Fidelity)",
    "corporation_name": "Corporation's name",
    "employee_name": "Employee name",
    "employee_ssn": "Employee SSN",
    "f3922_option_grant_date": "Date option granted (informational)",
    "f3922_option_exercise_date": "Date option exercised (informational)",
    "f3922_title_transfer_date": "Date legal transfer of title (informational)",
    "f3922_fmv_exercise": "Fair market value on exercise date (informational)",
    "f3922_fmv_transfer": "Fair market value on transfer date (informational)",
    "f3922_exercise_price": "Exercise price per share (informational)",
    "f3922_shares_transferred": "Number of shares transferred (informational)",
}

_MONEY_FIELDS = {"f3922_fmv_exercise", "f3922_fmv_transfer", "f3922_exercise_price"}

# Longest needles first so the two fair-market-value labels disambiguate.
_LABEL_CONTAINS = [
    ("transferor", "transferor_name"),
    ("corporation's name", "corporation_name"),
    ("employee's name", "employee_name"),
    ("social security number", "employee_ssn"),
    ("date option granted", "f3922_option_grant_date"),
    ("date option exercised", "f3922_option_exercise_date"),
    ("date legal transfer of title", "f3922_title_transfer_date"),
    ("fair market value of the stock on the exercise date", "f3922_fmv_exercise"),
    ("fair market value of the stock on the transfer date", "f3922_fmv_transfer"),
    ("exercise price", "f3922_exercise_price"),
    ("number of shares transferred", "f3922_shares_transferred"),
]

_MASKERS = {"employee_ssn": mask_ssn}


def _field_code_for(key: str) -> str | None:
    k = key.strip().lower()
    if not k:
        return None
    for needle, code in _LABEL_CONTAINS:
        if needle in k:
            return code
    return None


def extract_f3922_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.textract,
) -> list:
    """Map Form 3922 KVs into informational facts."""
    best: dict[str, tuple[float, ExtractedKV]] = {}
    for kv in kvs:
        code = _field_code_for(kv.key)
        if code is None:
            continue
        prior = best.get(code)
        if prior is None or kv.confidence > prior[0]:
            best[code] = (kv.confidence, kv)

    facts = []
    for code, (conf, kv) in best.items():
        facts.append(make_fact(
            document_id, tax_year, FormType.f3922, code,
            _FIELD_LABELS.get(code, code), kv.value,
            method=method, confidence=conf, page=kv.page, bbox=kv.bbox,
            money=code in _MONEY_FIELDS, mask=_MASKERS.get(code),
        ))
    facts.sort(key=lambda f: f.field_code)
    return facts
