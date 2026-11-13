"""Tax Prep 2025-corpus tests — classification + the new form readers.

No AWS, no real files. The 1099s feed synthetic KVs (the shape Textract
delivers); the consolidated statement and the federal/Illinois returns feed
synthetic native text (the shape the local provider delivers for digital PDFs).
"""
from __future__ import annotations

from tax.classify import classify_form
from tax.extraction.providers import ExtractedKV
from tax.forms.f1040 import extract_f1040_facts
from tax.forms.f1095_c import extract_f1095_c_facts
from tax.forms.f1099_combined import extract_f1099_combined_facts
from tax.forms.f1099_int import extract_f1099_int_facts
from tax.forms.f1099_nec import extract_f1099_nec_facts
from tax.forms.f3922 import extract_f3922_facts
from tax.forms.il_1040 import extract_il_1040_facts
from tax.models import FormType
from tax.routes import _person_from_filename


def kv(key: str, value: str, conf: float = 0.98) -> ExtractedKV:
    return ExtractedKV(key=key, value=value, confidence=conf)


def native(text: str) -> list[ExtractedKV]:
    return [ExtractedKV(key="__native_text__", value=text, confidence=1.0)]


# --- classification -----------------------------------------------------------

def test_classify_1099_int():
    kvs = [kv("Form", "1099-INT"), kv("1 Interest income", "$1,234.56")]
    assert classify_form(kvs) is FormType.f1099_int


def test_classify_1099_nec():
    kvs = [kv("Form", "1099-NEC"), kv("1 Nonemployee compensation", "$5,000.00")]
    assert classify_form(kvs) is FormType.f1099_nec


def test_classify_1095_c():
    kvs = [kv("Form", "1095-C"), kv("14 Offer of Coverage", "1A")]
    assert classify_form(kvs) is FormType.f1095_c


def test_classify_3922():
    kvs = [kv("Form", "3922"), kv("Exercise price", "12.34")]
    assert classify_form(kvs) is FormType.f3922


def test_classify_consolidated_1099_routes_to_div_container():
    kvs = native(
        "Form 1099-DIV *  2025 Dividends and Distributions Copy B for Recipient\n"
        "1a Total Ordinary Dividends .. .... 100.00\n"
        "(IRS Form 1099-B box numbers are shown below in bold  type)\n"
    )
    assert classify_form(kvs) is FormType.f1099_div


def test_classify_federal_return():
    kvs = native(
        "Electronic Filing Instructions for your 2025 Federal Tax Return\n"
        "Form1040 2025U.S. Individual Income Tax Return\n"
        "Department of the Treasury\n"
    )
    assert classify_form(kvs) is FormType.f1040


def test_classify_il_return_even_with_federal_copy_inside():
    kvs = native(
        "File by Mail Instructions for your 2025 Illinois Tax Return\n"
        "Form1040 2025U.S. Individual Income Tax Return\n"
        "Illinois Department of Revenue\n"
    )
    assert classify_form(kvs) is FormType.f1040_il


def test_classify_w2_still_wins_for_w2s():
    kvs = [kv("Wage and Tax Statement", ""), kv("1 Wages, tips, other comp.", "$1.00")]
    assert classify_form(kvs) is FormType.w2


# --- 1099-INT reader ----------------------------------------------------------

def test_1099_int_boxes_and_masking():
    kvs = [
        kv("1 Interest income", "$1,234.56"),
        kv("Payer's name", "NAVY FEDERAL CREDIT UNION"),
        kv("Payer's TIN", "12-3456789"),
        kv("Recipient's TIN", "123-45-6789"),
    ]
    facts = extract_f1099_int_facts("doc1", 2025, kvs)
    by = {f.field_code: f for f in facts}
    assert by["box_1_interest_income"].value == "1234.56"
    assert by["payer_name"].value == "NAVY FEDERAL CREDIT UNION"
    assert by["payer_tin"].value.startswith("**-***")
    assert by["payer_tin"].value.endswith("6789")
    assert by["recipient_tin"].value.startswith("***-**-")
    # The raw TIN digits (except the masked last-4) must never survive.
    assert all("34567" not in str(f.value) for f in facts if f.field_code != "payer_tin")


# --- 1099-NEC reader ----------------------------------------------------------

def test_1099_nec_box1_and_withholding():
    kvs = [
        kv("1 Nonemployee compensation", "$8,410.00"),
        kv("4 Federal income tax withheld", "$0.00"),
    ]
    facts = extract_f1099_nec_facts("doc2", 2025, kvs)
    by = {f.field_code: f for f in facts}
    assert by["box_1_nonemployee_comp"].value == "8410.00"
    assert by["box_4_fed_withholding"].value == "0.00"


# --- consolidated 1099 (native text) ------------------------------------------

CONSOLIDATED_SAMPLE = (
    "Form 1099-DIV *  2025 Dividends and Distributions Copy B for Recipient\n"
    "1a Total Ordinary Dividends .. .... ................... 1,666.59\n"
    "1b Qualified Dividends ...... ................... 1,629.58\n"
    "2a Total Capital Gain Distributions .......... 0.00\n"
    "3  Nondividend Distributions ....... 3,585.57\n"
    "4  Federal Income Tax Withheld .......... 0.00\n"
    "5  Section 199A Dividends .......... 20.36\n"
    "Form 1099-INT *  2025 Interest Income                Copy B for Recipient\n"
    "1  Interest Income .... 0.00\n"
    "Box A Short-Term Realized Gain 1,919.97\n"
    "Box A Short-Term Realized Loss -2,814.31\n"
    "Box D Long-Term Realized Gain 17.00\n"
    "Box D Long-Term Realized Loss -5,960.30\n"
)


def test_consolidated_boxes_summed_and_zeros_skipped():
    facts = extract_f1099_combined_facts("doc3", 2025, native(CONSOLIDATED_SAMPLE))
    by = {f.field_code: f for f in facts}
    assert by["div_1a_ordinary_dividends"].value == "1666.59"
    assert by["div_1b_qualified_dividends"].value == "1629.58"
    assert by["div_3_nondividend_dist"].value == "3585.57"
    assert by["div_5_section_199a"].value == "20.36"
    assert "div_2a_capital_gain_dist" not in by  # zero -> skipped
    assert by["b_boxa_st_realized_gain"].value == "1919.97"
    assert by["b_boxa_st_realized_loss"].value == "-2814.31"
    assert by["b_boxd_lt_realized_loss"].value == "-5960.30"


# --- as-filed federal return (native text) ------------------------------------

FEDERAL_SAMPLE = (
    "Electronic Filing Instructions for your 2025 Federal Tax Return\n"
    "Patrick & Sara C Flanigan\n"
    "2025 | Adjusted Gross Income                   $    282,819.00\n"
    "Federal | Taxable Income                          $    251,267.00\n"
    "Tax | Total Tax                               $     44,076.00\n"
    "Return | Total Payments/Credits                  $     35,287.00\n"
    "Refund | Amount of line 34 you want refunded to you $ 12,345.00\n"
    "Married filing jointly\n"
)


def test_f1040_summary_facts():
    facts = extract_f1040_facts("doc4", 2025, native(FEDERAL_SAMPLE))
    by = {f.field_code: f for f in facts}
    assert by["ret_agi"].value == "282819.00"
    assert by["ret_taxable_income"].value == "251267.00"
    assert by["ret_total_tax"].value == "44076.00"
    assert by["ret_total_payments"].value == "35287.00"
    assert by["ret_refund"].value == "12345.00"
    assert by["ret_filing_status"].value == "Married filing jointly"
    assert "ret_amount_owed" not in by  # a refund year, not a balance-due year


# --- as-filed Illinois return (native text) -----------------------------------

IL_SAMPLE = (
    "File by Mail Instructions for your 2025 Illinois Tax Return\n"
    "Your Illinois state tax return (Form IL-1040) shows you owe a balance\n"
    "2025 | Taxable Income                          $        463.00\n"
    "Illinois | Total Tax                               $         23.00\n"
    "Tax | Payment Due                             $         23.00\n"
)


def test_il_1040_summary_facts():
    facts = extract_il_1040_facts("doc5", 2025, native(IL_SAMPLE))
    by = {f.field_code: f for f in facts}
    assert by["il_taxable_income"].value == "463.00"
    assert by["il_tax"].value == "23.00"
    assert by["il_balance_due"].value == "23.00"


# --- 1095-C / 3922 (informational) --------------------------------------------

def test_1095_c_informational_fields_and_masking():
    kvs = [
        kv("Employer name", "BOOZ ALLEN HAMILTON INC."),
        kv("Employer Identification Number (EIN)", "12-3456789"),
        kv("14 Offer of Coverage (enter required code)", "1A"),
        kv("15 Employee Required Contribution (see instr)", "$2,345.00"),
        kv("16 Section 4980H Safe Harbor and Other Relief", "2C"),
    ]
    facts = extract_f1095_c_facts("doc6", 2025, kvs)
    by = {f.field_code: f for f in facts}
    assert by["box_14_offer_code"].value == "1A"
    assert by["box_16_safe_harbor"].value == "2C"
    assert by["box_15_employee_contribution"].value == "2345.00"
    assert by["employer_ein"].value.startswith("**-***")


def test_3922_informational_fields():
    kvs = [
        kv("Transferor's name", "Fidelity Brokerage Services"),
        kv("Corporation's name", "SOME EMPLOYER INC."),
        kv("Date option exercised", "06/15/2025"),
        kv("Exercise price", "$45.00"),
        kv("Number of shares transferred", "120"),
    ]
    facts = extract_f3922_facts("doc7", 2025, kvs)
    by = {f.field_code: f for f in facts}
    assert by["transferor_name"].value == "Fidelity Brokerage Services"
    assert by["f3922_option_exercise_date"].value == "06/15/2025"
    assert by["f3922_exercise_price"].value == "45.00"
    assert by["f3922_shares_transferred"].value == "120"


# --- Navy Federal's own 1099-INT layout ---------------------------------------

NFCU_INT_SAMPLE = [
    kv("EIN.", "53-0116705"),
    kv("OMB NO.", "1545-0112"),
    kv("AMOUNT REPORTED TO IRS:", "$580.45 $0.00 $0.00 $0.00"),
    kv("FOR TAX YEAR", "2025"),
    kv("TAXPAYER ID NUMBER", "XXX-XX-9665"),
    kv("SVGS", "1879190005 $31.88"),
    kv("MMSA", "3228279117 $546.44"),
    kv("CHECKING", "7007893691 $2.13"),
]


def test_classify_nfcu_1099_int():
    assert classify_form(NFCU_INT_SAMPLE) is FormType.f1099_int


def test_nfcu_1099_int_summary_and_account_rows():
    facts = extract_f1099_int_facts("doc8", 2025, NFCU_INT_SAMPLE)
    by = {f.field_code: f for f in facts}
    assert by["box_1_interest_income"].value == "580.45"
    assert by["payer_tin"].value.startswith("**-***")
    assert by["payer_tin"].value.endswith("6705")
    assert by["nfcu_svgs_interest"].value == "31.88"
    assert by["nfcu_mmsa_interest"].value == "546.44"
    assert by["nfcu_checking_interest"].value == "2.13"
    # The summary strip's zero columns are stored too (they prove no withholding).
    assert by["box_4_fed_withholding"].value == "0.00"
    # Per-account rows sum back to Box 1 — no double-counting.
    total = sum(float(by[c].value) for c in (
        "nfcu_svgs_interest", "nfcu_mmsa_interest", "nfcu_checking_interest"))
    assert abs(total - float(by["box_1_interest_income"].value)) < 0.005


# --- person attribution fallback ----------------------------------------------

def test_person_from_filename_covers_1099_nec():
    assert _person_from_filename("1099-NEC_Fay_Nutrition_Sara_2025.pdf") == "Sara"
    assert _person_from_filename(
        "2025-Joint-WROS-TOD-0625-Consolidated-Form-1099.pdf"
    ) is None
