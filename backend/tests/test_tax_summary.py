"""Tax Year Summary tests — facts-only aggregation, synthetic documents.

No store, no AWS: documents and facts are constructed in-memory and fed straight
to summary.build_summary, mirroring exactly what storage.list_documents and
storage.load_all_facts return."""
from __future__ import annotations

from tax import summary
from tax.models import DocKind, DocStage, FormType, TaxDocument, TaxFact


def doc(filename: str, form_type: FormType, taxpayer: str | None = None) -> TaxDocument:
    return TaxDocument(
        id="id_" + filename,
        tax_year=2025,
        original_filename=filename,
        kind=DocKind.pdf,
        size_bytes=100,
        uploaded_at="2026-11-13T12:00:00",
        stage=DocStage.extracted,
        form_type=form_type,
        taxpayer=taxpayer,
        page_count=1,
        note="",
    )


def facts_for(doc: TaxDocument, pairs: list[tuple[str, str]], form_type: FormType) -> list[TaxFact]:
    return [
        TaxFact(
            tax_year=2025, document_id=doc.id, form_type=form_type,
            field_code=code, value=val, extracted_value=val,
        )
        for code, val in pairs
    ]


def test_summary_salary_investments_and_as_filed():
    w2p = doc("W2_Patrick_Booz_Allen_2025_Copy_B.pdf", FormType.w2, "Patrick")
    w2s = doc("W2_Sara_Inova_2025.pdf", FormType.w2, "Sara")
    int99 = doc("1099-INT_Navy_Federal_2025.pdf", FormType.f1099_int)
    div = doc("2025-Joint-WROS-TOD-0625-Consolidated-Form-1099.pdf", FormType.f1099_div)
    nec = doc("1099-NEC_Fay_Nutrition_Sara_2025.pdf", FormType.f1099_nec, "Sara")
    ret = doc("2025_return.pdf", FormType.f1040)
    il = doc("2025_return_il.pdf", FormType.f1040_il)
    docs = [w2p, w2s, int99, div, nec, ret, il]
    fb = {
        w2p.id: facts_for(w2p, [
            ("box_1_wages", "192733.37"), ("box_2_fed_withholding", "24590.52"),
            ("box_15_state", "VA"), ("box_17_state_tax", "10238.98"),
        ], FormType.w2),
        w2s.id: facts_for(w2s, [
            ("box_1_wages", "86736.42"), ("box_2_fed_withholding", "10696.04"),
            ("box_15_state", "VA"), ("box_17_state_tax", "4232.59"),
        ], FormType.w2),
        int99.id: facts_for(int99, [("box_1_interest_income", "580.45")], FormType.f1099_int),
        div.id: facts_for(div, [
            ("div_1a_ordinary_dividends", "1666.59"),
            ("div_1b_qualified_dividends", "1629.58"),
            ("div_5_section_199a", "20.36"),
            ("b_boxa_st_realized_gain", "1919.97"),
            ("b_boxa_st_realized_loss", "-2814.31"),
        ], FormType.f1099_div),
        nec.id: facts_for(nec, [("box_1_nonemployee_comp", "240.00")], FormType.f1099_nec),
        ret.id: facts_for(ret, [
            ("ret_agi", "282819.00"), ("ret_total_tax", "44076.00"),
            ("ret_amount_owed", "8934.00"),
            ("ret_filing_status", "Married filing jointly"),
            ("ret_fed_hsa_deduction", "0.00"),
            ("ret_fed_hsa_deduction_limit", "8110.00"),
            ("ret_fed_hsa_employer_contrib_you", "4495.00"),
            ("ret_fed_hsa_employer_contrib_spouse", "4495.00"),
            ("ret_st_va_state_name", "Virginia"),
            ("ret_st_va_taxable_income", "258529.00"),
            ("ret_st_va_total_tax", "14349.00"),
            ("ret_st_va_total_payments", "14495.00"),
            ("ret_st_va_refund", "146.00"),
            ("ret_st_va_529_deduction", "4000.00"),
        ], FormType.f1040),
        il.id: facts_for(il, [
            ("il_taxable_income", "463.00"), ("il_tax", "23.00"),
            ("il_balance_due", "23.00"),
        ], FormType.f1040_il),
    }

    s = summary.build_summary(2025, docs, fb)

    assert s["salary"]["people"][0]["employer"] == "Booz Allen"
    assert s["salary"]["people"][0]["wages"] == 192733.37
    assert s["salary"]["people"][1]["employer"] == "Inova"
    assert s["salary"]["total_wages"] == 279469.79
    assert s["salary"]["total_fed_withholding"] == 35286.56
    assert s["salary"]["total_state_withholding"] == 14471.57
    assert s["investments"]["total_interest"] == 580.45
    assert s["investments"]["statements"][0]["payer"] == "Navy Federal"
    assert s["investments"]["net_realized_gain_loss"] == -894.34
    assert s["side_income"]["entries"][0]["payer"] == "Fay Nutrition"
    assert s["side_income"]["total"] == 240.00
    assert s["as_filed"]["federal"]["agi"] == 282819.00
    assert s["as_filed"]["federal"]["balance_due"] == 8934.00
    # Two state filings for 2025: Illinois (separate return) and Virginia
    # (embedded in the federal e-file package).
    assert [st["name"] for st in s["as_filed"]["states"]] == ["Virginia", "Illinois"]
    va = s["as_filed"]["states"][0]
    assert va["taxable_income"] == 258529.00
    assert va["total_tax"] == 14349.00
    assert va["refund"] == 146.00

    # Deductions & adjustments, each tagged with the jurisdiction it reduces:
    # the HSA deduction was claimed at 0 (payroll-funded contributions), the
    # 529 deduction is Virginia-only, and the IL return carries no 529
    # subtraction in its filed package.
    ded = s["deductions"]
    assert [(d["jurisdiction"], d["amount"]) for d in ded] == [
        ("Federal", 0.0), ("Virginia", 4000.0), ("Illinois", None),
    ]
    assert ded[0]["label"] == "Health savings account deduction"
    assert "payroll" in ded[0]["note"]
    assert "8,110" in ded[0]["note"]
    assert ded[1]["label"] == "Virginia529 college savings deduction"
    assert "not deductible on the federal return" in ded[1]["note"]
    assert ded[2]["label"].startswith("Illinois 529")
    assert ded[2]["amount"] is None

    derived = s["as_filed"]["derived"]
    assert derived["effective_rate"] == round(44076.00 / 282819.00, 4)
    assert derived["withholding_coverage"] == round(35286.56 / 44076.00, 4)
    assert derived["withholding_shortfall"] == round(44076.00 - 35286.56, 2)


def test_summary_empty_year_is_an_honest_skeleton():
    s = summary.build_summary(2024, [], {})
    assert s["salary"]["people"] == []
    assert s["salary"]["total_wages"] == 0.0
    assert s["as_filed"]["federal"] is None
    assert s["as_filed"]["states"] == []
    assert s["as_filed"]["derived"] is None
    assert s["deductions"] == []
    assert s["documents"] == []


def test_summary_informational_forms():
    c = doc("1095-C_Booz_Allen_Employer_Coverage_2025.pdf", FormType.f1095_c)
    docs = [c]
    fb = {c.id: facts_for(c, [("box_14_offer_code", "1A")], FormType.f1095_c)}
    s = summary.build_summary(2025, docs, fb)
    assert s["informational"][0]["form_type"] == "1095-C"
    assert s["informational"][0]["label"] == "Booz Allen"
    assert s["salary"]["people"] == []  # informational forms are not income