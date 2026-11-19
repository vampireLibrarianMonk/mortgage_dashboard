"""Legacy (pre-2025) e-file package parsing: block splitting + refunds.

All fixtures are synthetic - names, SSNs and amounts are invented.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tax.extraction.providers import ExtractedKV
from tax.forms.f1040 import extract_f1040_facts, _state_blocks
from tax.models import ExtractionMethod


def _kvs(text: str) -> list[ExtractedKV]:
    return [ExtractedKV(key="__native_text__", value=text, confidence=1.0)]


LEGACY_2014_STYLE = (
    "Federal Electronic Filing Instructions\n"
    "Tax Year 2014\n"
    "Adjusted gross income. . . . . . . . . . . . . . . . . . $ 141,250.00\n"
    "Amount you owe. . . . . . . . . . . . . . . . . . . . . . $ 250.00\n"
    "2014 Virginia Electronic Filing Instructions\n"
    "Virginia taxable income. . . . . . . . . . . . . . . . . $ 135,000.00\n"
    "AMOUNT TO BE REFUNDED TO YOU.......................$          570\n"
)


def test_legacy_markers_split_federal_and_virginia_blocks():
    blocks = _state_blocks(LEGACY_2014_STYLE.splitlines())
    names = [name for name, _ in blocks]
    assert "Federal" in names and "Virginia" in names


def test_legacy_package_lifts_federal_and_virginia_facts():
    facts = extract_f1040_facts(
        "doc-legacy", 2014, _kvs(LEGACY_2014_STYLE),
        method=ExtractionMethod.native_pdf,
    )
    codes = {f.field_code: f.value for f in facts}
    assert codes["ret_agi"] == "141250.00"
    assert codes["ret_amount_owed"] == "250.00"
    assert codes["ret_st_va_state_name"] == "Virginia"
    assert codes["ret_st_va_refund"] == "570.00"


def test_repeated_page_header_does_not_reblock():
    text = (
        "Virginia Electronic Filing Instructions\n"
        "page one values\n"
        "Virginia Electronic Filing Instructions - 03/19/16 Page 2\n"
        "more page two values\n"
    )
    blocks = _state_blocks(text.splitlines())
    # one pre-marker Federal block + ONE Virginia block (page header ignored)
    va = [b for name, b in blocks if name == "Virginia"]
    assert len(va) == 1 and len(va[0]) == 2


KANG_2024_STYLE = (
    "Filing Instructions\n"
    "PATRICK M. & SARA C. FLANIGAN\n"
    "2024 U.S. INDIVIDUAL INCOME TAX RETURN\n"
    "YOU HAVE A BALANCE DUE OF..........................$        1,515\n"
    "Filing Instructions\n"
    "2024 VIRGINIA INCOME TAX RETURN\n"
    "YOU HAVE A BALANCE DUE OF..........................$          625\n"
)


def test_kang_package_splits_federal_and_virginia():
    blocks = _state_blocks(KANG_2024_STYLE.splitlines())
    names = [name for name, _ in blocks]
    assert "Federal" in names and "Virginia" in names


def test_kang_package_lifts_federal_and_virginia_balance_due():
    facts = extract_f1040_facts(
        "doc-kang", 2024, _kvs(KANG_2024_STYLE),
        method=ExtractionMethod.native_pdf,
    )
    codes = {f.field_code: f.value for f in facts}
    assert codes["ret_amount_owed"] == "1515.00"
    assert codes["ret_st_va_state_name"] == "Virginia"
    assert codes["ret_st_va_balance_due"] == "625.00"
