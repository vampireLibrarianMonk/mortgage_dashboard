"""1099-INT reader: extraction KVs -> TaxFacts (interest boxes + payer/recipient).

Matches boxes by leading box number (the scanned form repeats them across
copies; we keep the highest-confidence instance) and by label for the
payer/recipient identities. Money is normalized; TINs are masked (the payer's
EIN through the employer_ein masker, the recipient's TIN through the SSN one).
"""
from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.forms import is_money_value, make_fact
from tax.models import ExtractionMethod, FormType
from tax.pii import mask_ein, mask_ssn

_FIELD_LABELS = {
    "box_1_interest_income": "Box 1 — Interest income",
    "box_2_early_withdrawal": "Box 2 — Early withdrawal penalty",
    "box_3_savings_interest": "Box 3 — Interest on U.S. savings bonds & Treas. obligations",
    "box_4_fed_withholding": "Box 4 — Federal income tax withheld",
    "box_6_foreign_tax": "Box 6 — Foreign tax paid",
    "box_8_tax_exempt_interest": "Box 8 — Tax-exempt interest",
    "box_17_state_tax": "Box 17 — State tax withheld",
    "payer_name": "Payer's name",
    "payer_tin": "Payer's TIN (EIN)",
    "recipient_name": "Recipient's name",
    "recipient_tin": "Recipient's TIN (SSN)",
    "nfcu_svgs_interest": "Navy Federal savings interest (informational)",
    "nfcu_mmsa_interest": "Navy Federal money-market interest (informational)",
    "nfcu_checking_interest": "Navy Federal checking interest (informational)",
}

_MONEY_FIELDS = {
    "box_1_interest_income", "box_2_early_withdrawal", "box_3_savings_interest",
    "box_4_fed_withholding", "box_6_foreign_tax", "box_8_tax_exempt_interest",
    "box_17_state_tax", "nfcu_svgs_interest", "nfcu_mmsa_interest",
    "nfcu_checking_interest",
}

_BOX_NUMBERS = {
    "1": "box_1_interest_income",
    "2": "box_2_early_withdrawal",
    "3": "box_3_savings_interest",
    "4": "box_4_fed_withholding",
    "6": "box_6_foreign_tax",
    "8": "box_8_tax_exempt_interest",
    "17": "box_17_state_tax",
}

# NFCU's 1099-INT prints per-account rows keyed by the account's product name,
# each ending in that account's interest amount.
_NFCU_ACCOUNT_ROWS = {"svgs": "nfcu_svgs_interest", "mmsa": "nfcu_mmsa_interest", "checking": "nfcu_checking_interest"}

_LABEL_CONTAINS = [
    ("payer's name", "payer_name"),
    ("payer's tin", "payer_tin"),
    ("recipient's name", "recipient_name"),
    ("recipient's tin", "recipient_tin"),
    ("ein", "payer_tin"),
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


def extract_f1099_int_facts(
    document_id: str,
    tax_year: int,
    kvs: list[ExtractedKV],
    method: ExtractionMethod = ExtractionMethod.textract,
) -> list:
    """Map 1099-INT KVs into deduped, provenance-carrying facts.

    Handles the standard box layout AND Navy Federal's own layout (a summary
    strip reading "AMOUNT REPORTED TO IRS: $box1 $box2 $box3 $box4" plus
    per-account interest rows). Standard boxes win; the NFCU rows fill only the
    gaps so nothing double-counts."""
    specials: list[tuple[str, ExtractedKV]] = []
    best: dict[str, tuple[float, ExtractedKV]] = {}
    for kv in kvs:
        k = kv.key.strip().lower()
        if "amount reported to irs" in k:
            specials.append(("irs", kv))
            continue
        if k in _NFCU_ACCOUNT_ROWS:
            specials.append(("nfcu", kv))
            continue
        code = _field_code_for(kv.key)
        if code is None:
            continue
        prior = best.get(code)
        if prior is None or kv.confidence > prior[0]:
            best[code] = (kv.confidence, kv)

    facts = []
    for code, (conf, kv) in best.items():
        if code in _MONEY_FIELDS and not is_money_value(kv.value):
            continue  # an empty money box carries no information (OCR junk keys)
        facts.append(make_fact(
            document_id, tax_year, FormType.f1099_int, code,
            _FIELD_LABELS.get(code, code), kv.value,
            method=method, confidence=conf, page=kv.page, bbox=kv.bbox,
            money=code in _MONEY_FIELDS, mask=_MASKERS.get(code),
        ))

    seen = {f.field_code for f in facts}
    for tag, kv in specials:
        if tag == "irs":
            # Four summary columns: boxes 1, 2, 3, 4 in that order.
            amounts = re.findall(r"([\d,]+\.\d{2})", kv.value)
            codes = (
                "box_1_interest_income", "box_2_early_withdrawal",
                "box_3_savings_interest", "box_4_fed_withholding",
            )
            for code, amt in zip(codes, amounts, strict=False):
                if code in seen:
                    continue
                seen.add(code)
                facts.append(make_fact(
                    document_id, tax_year, FormType.f1099_int, code,
                    _FIELD_LABELS[code], amt.replace(",", ""),
                    method=method, confidence=kv.confidence, page=kv.page,
                    bbox=kv.bbox, money=True,
                ))
        else:
            code = _NFCU_ACCOUNT_ROWS[kv.key.strip().lower()]
            m = re.search(r"([\d,]+\.\d{2})\s*$", kv.value)
            if m and code not in seen:
                seen.add(code)
                facts.append(make_fact(
                    document_id, tax_year, FormType.f1099_int, code,
                    _FIELD_LABELS[code], m.group(1),
                    method=method, confidence=kv.confidence, page=kv.page,
                    bbox=kv.bbox, money=True,
                ))

    facts.sort(key=lambda f: f.field_code)
    return facts
