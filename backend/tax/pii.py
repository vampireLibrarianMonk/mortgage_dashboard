"""PII masking for tax data.

Sensitive identifiers (SSN, EIN) must never be stored in cleartext, displayed in
full, or logged. We keep only the last few digits so a human can still recognize
which document a value came from. Masking happens at the earliest point (when a
fact is created from extraction) so the raw value is never persisted.
"""
from __future__ import annotations

import re

_DIGITS = re.compile(r"\d")


def _last4_digits(s: str) -> str:
    return "".join(_DIGITS.findall(s))[-4:]


def mask_ssn(value: str) -> str:
    """A Social Security number -> ***-**-#### (last 4 kept)."""
    last4 = _last4_digits(value)
    return f"***-**-{last4}" if last4 else "***-**-****"


def mask_ein(value: str) -> str:
    """An Employer ID number -> **-***#### (last 4 kept)."""
    last4 = _last4_digits(value)
    return f"**-***{last4}" if last4 else "**-*******"


# Which field_codes carry PII and how to mask each.
_PII_MASKERS = {
    "employee_ssn": mask_ssn,
    "employer_ein": mask_ein,
}


def mask_field(field_code: str, value: str | None) -> str | None:
    """Mask a value if its field is PII; otherwise return it unchanged."""
    if value is None:
        return None
    masker = _PII_MASKERS.get(field_code)
    return masker(str(value)) if masker else value


def is_pii_field(field_code: str) -> bool:
    return field_code in _PII_MASKERS
