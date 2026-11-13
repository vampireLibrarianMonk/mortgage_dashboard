"""1095-C reader (informational): employer health coverage — no $ unless noted.

Extracts the employer/employee identities (masked TINs), the Box 14 offer code,
the Box 15 employee contribution, and the Box 16 safe-harbor code. This form
carries no income or deductible amount for a household return; it documents
coverage for the year."""
from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.forms import make_fact
from tax.models import ExtractionMethod, FormType
from tax.pii import mask_ein, mask_ssn

_FIELD_LABELS = {
    "employer_name": "Employer name",
    "employer_ein": "Employer EIN",
    "employee_name": "Employee name",
    "employee_ssn": "Employee SSN",
    "box_14_offer_code": "Box 14 — Offer of Coverage code (informational)",
    "box_15_employee_contribution": "Box 15 — Employee required contribution (informational)",
    "box_16_safe_harbor": "Box 16 — Section 4980H Safe Harbor code (informational)",
}

_MONEY_FIELDS = {"box_15_employee_contribution"}

_BOX_NUMBERS = {
    "14": "box_14_offer_code",
    "15": "box_15_employee_contribution",
    "16": "box_16_safe_harbor",
}

_LABEL_CONTAINS = [
    ("employer identification number", "employer_ein"),
    ("employer name", "employer_name"),
    ("employee name", "employee_name"),
    ("employee's ssn", "employee_ssn"),
    ("employee ssn", "employee_ssn"),
    ("offer of coverage", "box_14_offer_code"),
    ("safe harbor", "box_16_safe_harbor"),
    ("employee required contribution", "box_15_employee_contribution"),
]

_MASKERS = {"employer_ein": mask_ein, "employee_ssn": mask_ssn}

_LEADING_NUM = re.compile(r"^\s*(\d{1,2})\b")


def _field_code_for(key: str) -> str | None:
    k = key.strip().lower()
    if not k:
        return None
    m = _LEADING_NUM.match(k)
    if m and m.group(1) in _BOX_NUMBERS:
        return _BOX_NUMBERS[m.group(1)]
    for needle, code in _LABEL_CONTAINS:
        if needle in k:
            return code
    return None


def extract_f1095_c_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.textract,
) -> list:
    """Map 1095-C KVs into informational facts (identities + coverage codes)."""
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
            document_id, tax_year, FormType.f1095_c, code,
            _FIELD_LABELS.get(code, code), kv.value,
            method=method, confidence=conf, page=kv.page, bbox=kv.bbox,
            money=code in _MONEY_FIELDS, mask=_MASKERS.get(code),
        ))
    facts.sort(key=lambda f: f.field_code)
    return facts
