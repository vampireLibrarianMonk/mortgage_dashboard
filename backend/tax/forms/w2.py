"""W-2 reader: extraction key/values -> TaxFacts.

Maps a W-2's boxes (federal 1-6/12/13 + the Virginia state boxes 15-17) from the
provider's key/value pairs into normalized TaxFacts with provenance. Handles the
real-world messiness confirmed on the scanned corpus: the form is multi-copy so
every box appears several times (we keep the highest-confidence instance), and
OCR'd labels vary slightly (we match by leading box number first, then by a
fuzzy label contains). PII (SSN/EIN) is masked before the fact is stored.
"""
from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.models import ExtractionMethod, FactStatus, FormType, TaxFact
from tax.pii import mask_field

# Confidence below which a fact is flagged for human review.
REVIEW_THRESHOLD = 0.90

# Human labels for each field_code (shown in the review UI).
FIELD_LABELS: dict[str, str] = {
    "box_1_wages": "Box 1 — Wages, tips, other comp.",
    "box_2_fed_withholding": "Box 2 — Federal income tax withheld",
    "box_3_ss_wages": "Box 3 — Social security wages",
    "box_4_ss_tax": "Box 4 — Social security tax withheld",
    "box_5_medicare_wages": "Box 5 — Medicare wages and tips",
    "box_6_medicare_tax": "Box 6 — Medicare tax withheld",
    "box_12a": "Box 12a",
    "box_12b": "Box 12b",
    "box_12c": "Box 12c",
    "box_12d": "Box 12d",
    "box_13_retirement_plan": "Box 13 — Retirement plan",
    "box_15_state": "Box 15 — State",
    "box_16_state_wages": "Box 16 — State wages, tips, etc.",
    "box_17_state_tax": "Box 17 — State income tax",
    "employer_ein": "Employer's FED ID number (EIN)",
    "employee_ssn": "Employee's SSN",
    "employee_name": "Employee's name",
}

# Boxes whose value is a dollar amount (normalized to a float string).
_MONEY_FIELDS = {
    "box_1_wages", "box_2_fed_withholding", "box_3_ss_wages", "box_4_ss_tax",
    "box_5_medicare_wages", "box_6_medicare_tax", "box_16_state_wages",
    "box_17_state_tax",
}

# Match by leading box number: "1 Wages, tips..." -> field_code.
_BOX_NUMBER_TO_CODE = {
    "1": "box_1_wages",
    "2": "box_2_fed_withholding",
    "3": "box_3_ss_wages",
    "4": "box_4_ss_tax",
    "5": "box_5_medicare_wages",
    "6": "box_6_medicare_tax",
    "16": "box_16_state_wages",
    "17": "box_17_state_tax",
}

# Match by a fuzzy label substring when there's no leading box number.
_LABEL_CONTAINS: list[tuple[str, str]] = [
    ("employer's fed id", "employer_ein"),
    ("employer's federal id", "employer_ein"),
    ("fed id number", "employer_ein"),
    ("employee's ssa", "employee_ssn"),
    ("employee's social security", "employee_ssn"),
    ("ssa number", "employee_ssn"),
    ("employee's name", "employee_name"),
    ("retirement plan", "box_13_retirement_plan"),
    ("ret. plan", "box_13_retirement_plan"),
    ("ret, plan", "box_13_retirement_plan"),
    ("ret plan", "box_13_retirement_plan"),
]

_LEADING_NUM = re.compile(r"^\s*(\d{1,2})\b")
_BOX12 = re.compile(r"\b12([a-d])\b", re.IGNORECASE)
_MONEY_CLEAN = re.compile(r"[^\d.\-]")


def _normalize_money(value: str) -> str:
    """Strip $, commas, OCR mask artifacts (*) -> a plain numeric string. If the
    result isn't parseable, return the original (surfaced for review)."""
    cleaned = _MONEY_CLEAN.sub("", value.replace("*", ""))
    if cleaned in ("", "-", ".", "-."):
        return value
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return value


def _field_code_for(key: str) -> str | None:
    """Resolve an extraction key to a W-2 field_code, or None if unmatched."""
    k = key.strip().lower()
    if not k:
        return None

    # Box 12 variants ("12a", "12a See instructions for box 12", ...).
    m12 = _BOX12.search(k)
    if m12:
        return f"box_12{m12.group(1).lower()}"

    # Leading box number ("1 Wages, tips, other comp.").
    mnum = _LEADING_NUM.match(key)
    if mnum and mnum.group(1) in _BOX_NUMBER_TO_CODE:
        return _BOX_NUMBER_TO_CODE[mnum.group(1)]

    # 'State' label -> box 15 (the two-letter state code). Guard against matching
    # 'state wages' / 'state income tax' which carry box numbers handled above.
    if k == "state" or k.endswith(" state"):
        return "box_15_state"

    for needle, code in _LABEL_CONTAINS:
        if needle in k:
            return code
    return None


def extract_w2_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.textract,
) -> list[TaxFact]:
    """Map a W-2's extracted key/values into deduped, provenance-carrying facts.

    Dedupe rule: a W-2 copy repeats every box, so for each field_code we keep the
    single highest-confidence instance. Money is normalized; the Box 13 checkbox
    becomes a yes/no; PII is masked before the fact is built.
    """
    best: dict[str, tuple[float, ExtractedKV]] = {}
    for kv in kvs:
        code = _field_code_for(kv.key)
        if code is None:
            continue
        prior = best.get(code)
        if prior is None or kv.confidence > prior[0]:
            best[code] = (kv.confidence, kv)

    facts: list[TaxFact] = []
    for code, (conf, kv) in best.items():
        # Normalize the value by field type.
        if code == "box_13_retirement_plan":
            value: str | bool = kv.is_selection or kv.value.strip() == "[X]"
        elif code in _MONEY_FIELDS:
            value = _normalize_money(kv.value)
        else:
            value = kv.value.strip()

        # Mask PII before anything is stored.
        stored_value = mask_field(code, value if isinstance(value, str) else str(value))
        if code == "box_13_retirement_plan":
            stored_value = value  # keep the bool

        status = FactStatus.extracted if conf >= REVIEW_THRESHOLD else FactStatus.needs_review

        facts.append(
            TaxFact(
                tax_year=tax_year,
                document_id=document_id,
                form_type=FormType.w2,
                field_code=code,
                field_label=FIELD_LABELS.get(code, code),
                value=stored_value,
                page=kv.page,
                bbox=kv.bbox,
                extraction_method=method,
                confidence=round(conf, 4),
                status=status,
                extracted_value=stored_value,  # audit baseline (already masked)
            )
        )

    # Stable, human-sensible order: by field_code.
    facts.sort(key=lambda f: f.field_code)
    return facts
