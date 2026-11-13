"""1099-NEC reader: extraction KVs -> TaxFacts (nonemployee compensation).

Sara's Fay Nutrition contract income. Box 1 feeds a future Schedule C; the
withholding boxes (4/5) and the payer/recipient identities carry the usual
provenance and masking."""
from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.forms import is_money_value, make_fact
from tax.models import ExtractionMethod, FormType
from tax.pii import mask_ein, mask_ssn

_FIELD_LABELS = {
    "box_1_nonemployee_comp": "Box 1 — Nonemployee compensation",
    "box_4_fed_withholding": "Box 4 — Federal income tax withheld",
    "box_5_state_withholding": "Box 5 — State tax withheld",
    "box_6_state_number": "Box 6 — State/Payer's state no.",
    "box_7_state_number": "Box 7 — Payer's state no.",
    "payer_name": "Payer's name",
    "payer_tin": "Payer's TIN (EIN)",
    "recipient_name": "Recipient's name",
    "recipient_tin": "Recipient's TIN (SSN)",
}

_MONEY_FIELDS = {"box_1_nonemployee_comp", "box_4_fed_withholding", "box_5_state_withholding"}

_BOX_NUMBERS = {
    "1": "box_1_nonemployee_comp",
    "4": "box_4_fed_withholding",
    "5": "box_5_state_withholding",
    "6": "box_6_state_number",
    "7": "box_7_state_number",
}

_LABEL_CONTAINS = [
    ("payer's name", "payer_name"),
    ("payer's tin", "payer_tin"),
    ("recipient's name", "recipient_name"),
    ("recipient's tin", "recipient_tin"),
]

_MASKERS = {"payer_tin": mask_ein, "recipient_tin": mask_ssn}

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


def extract_f1099_nec_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.textract,
) -> list:
    """Map 1099-NEC KVs into deduped, provenance-carrying facts."""
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
        if code in _MONEY_FIELDS and not is_money_value(kv.value):
            continue  # an empty/junk money box carries no information
        facts.append(make_fact(
            document_id, tax_year, FormType.f1099_nec, code,
            _FIELD_LABELS.get(code, code), kv.value,
            method=method, confidence=conf, page=kv.page, bbox=kv.bbox,
            money=code in _MONEY_FIELDS, mask=_MASKERS.get(code),
        ))
    facts.sort(key=lambda f: f.field_code)
    return facts
