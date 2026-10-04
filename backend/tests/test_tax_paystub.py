"""Tax Prep Phase 3 tests — paystub reader, year-rebuild, W-2 reconciliation.

No AWS, no real files. Paystubs are fed as synthetic native text (the shape the
local provider delivers: a single __native_text__ ExtractedKV), mirroring the
real Booz Allen layout including its two quirks — the Social Security wage-cap
column collapse and the broken final-stub YTD. W-2 facts are built directly as
TaxFact objects.
"""
import pytest
from starlette.testclient import TestClient

import main
from tax import storage
from tax.classify import classify_form
from tax.extraction.providers import ExtractedKV
from tax.forms.paystub import (
    NATIVE_TEXT_KEY,
    extract_paystub_facts,
    parse_paystub,
    rebuild_year,
)
from tax.models import ExtractionMethod, FactStatus, FormType, TaxFact
from tax.reconcile import Verdict, reconcile_household, reconcile_person

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture(autouse=True)
def isolated_tax(isolated_store, monkeypatch):
    monkeypatch.setattr(storage, "TAX_ROOT", isolated_store.DATA_DIR / "tax")


@pytest.fixture
def client():
    return TestClient(main.app)


def stub_kvs(text: str) -> list[ExtractedKV]:
    """Wrap paystub text as the local provider's native-text KV."""
    return [ExtractedKV(key=NATIVE_TEXT_KEY, value=text, confidence=1.0)]


def paystub_text(
    *,
    period: str,
    pay_date: str,
    gross_cur: str,
    gross_ytd: str,
    fed: tuple[str, str],
    ss: tuple[str, str] | tuple[str],   # 1-tuple => capped (YTD only)
    medicare: tuple[str, str],
    va: tuple[str, str],
    pretax: tuple[str, str],
    net: tuple[str, str],
    name: str = "Patrick Flanigan",
) -> str:
    ss_line = (
        f"  Social Security {ss[0]}"
        if len(ss) == 1
        else f"  Social Security {ss[0]} {ss[1]}"
    )
    return "\n".join([
        f"Employee Name: {name} Pay Date: {pay_date}",
        f"Employee #: 591245 Pay Period: {period}",
        "Pay Frequency: Semi-Monthly",
        "Federal Filing Status: Married",
        "Employer Name: Booz Allen Hamilton State Filing Status: (VA)",
        f"As of {period.split(' - ')[1]}",
        f"Earnings 88.00 {gross_cur} 2000.00 {gross_ytd}",
        f"Pre-Tax Deductions {pretax[0]} {pretax[1]}",
        "Taxes $0.00 $0.00",
        f"  Fed W/H {fed[0]} {fed[1]}",
        ss_line,
        f"  Medicare {medicare[0]} {medicare[1]}",
        f"  VA W/H {va[0]} {va[1]}",
        "Post-Tax Deductions $100.00 $1,000.00",
        f"Net Pay {net[0]} {net[1]}",
    ])


# A clean mid-year stub (all columns present).
MID = paystub_text(
    period="6/16/2025 - 6/30/2025", pay_date="7/7/2025",
    gross_cur="$8,360.30", gross_ytd="$106,090.89",
    fed=("$1,038.92", "$11,253.07"),
    ss=("$490.20", "$6,013.45"),
    medicare=("$114.64", "$1,406.37"),
    va=("$420.86", "$4,921.47"),
    pretax=("$461.43", "$9,000.00"),
    net=("$5,381.54", "$57,830.95"),
)

# The last 2025-PAID stub (period 12/1-12/15, paid 12/22/2025). Its YTD is the
# true full-year figure for the W-2.
DEC15 = paystub_text(
    period="12/1/2025 - 12/15/2025", pay_date="12/22/2025",
    gross_cur="$8,360.30", gross_ytd="$205,771.09",
    fed=("$955.58", "$24,590.52"),
    ss=("$10,918.20",),                       # capped -> single token
    medicare=("$114.64", "$2,848.21"),
    va=("$418.04", "$10,238.98"),
    pretax=("$461.43", "$17,964.11"),
    net=("$5,790.69", "$122,286.85"),
)

# The 12/31 period, PAID 1/7/2026 -> belongs to 2026. Its YTD column is the
# known-broken one (YTD == current period).
DEC31 = paystub_text(
    period="12/16/2025 - 12/31/2025", pay_date="1/7/2026",
    gross_cur="$8,360.30", gross_ytd="$8,360.30",
    fed=("$817.12", "$817.12"),
    ss=("$461.60", "$461.60"),
    medicare=("$107.96", "$107.96"),
    va=("$391.52", "$391.52"),
    pretax=("$922.64", "$922.64"),
    net=("$5,023.07", "$5,023.07"),
)


# --- classify + parse ---------------------------------------------------------

def test_classify_paystub():
    assert classify_form(stub_kvs(MID)) is FormType.paystub


def test_parse_header_and_amounts():
    r = parse_paystub(stub_kvs(MID))
    assert r.employee_name == "Patrick Flanigan"
    assert r.employer_name == "Booz Allen Hamilton"
    assert r.period_start == "6/16/2025" and r.period_end == "6/30/2025"
    assert r.pay_date == "7/7/2025"
    assert r.federal_filing_status == "Married"
    assert r.amounts["ps_gross_earnings"].ytd == pytest.approx(106090.89)
    assert r.amounts["ps_fed_withholding"].current == pytest.approx(1038.92)
    assert r.amounts["ps_fed_withholding"].ytd == pytest.approx(11253.07)


def test_ss_cap_column_collapse():
    r = parse_paystub(stub_kvs(DEC15))
    ss = r.amounts["ps_ss_tax"]
    assert ss.current is None          # collapsed: no current column
    assert ss.ytd == pytest.approx(10918.20)


def test_broken_final_stub_flagged():
    r = parse_paystub(stub_kvs(DEC31))
    assert r.is_final_period_of_year is True
    # YTD == current on the broken stub.
    assert r.amounts["ps_gross_earnings"].ytd == r.amounts["ps_gross_earnings"].current


def test_extract_paystub_facts():
    facts = extract_paystub_facts("docp", 2025, stub_kvs(DEC15))
    by = {f.field_code: f for f in facts}
    assert by["ps_fed_withholding"].value == "24590.52"
    # The capped SS row still produces a fact (from its YTD).
    assert by["ps_ss_tax"].value == "10918.20"
    assert by["ps_ss_tax"].status is FactStatus.extracted
    assert by["ps_ss_tax"].confidence == 1.0
    assert by["ps_gross_earnings"].form_type is FormType.paystub
    # Pay period is stashed for the UI.
    assert by["ps_fed_withholding"].payer_tin_masked == "12/1/2025 - 12/15/2025"


# --- year rebuild -------------------------------------------------------------

def test_rebuild_pay_date_excludes_jan_paid_december():
    """Pay-date boundary: the 12/31 period paid in January is NOT in 2025, so
    the 2025 total is the 12/15 stub's YTD exactly."""
    readings = [parse_paystub(stub_kvs(t)) for t in (MID, DEC15, DEC31)]
    rb = rebuild_year(readings, 2025, boundary="pay_date")
    assert rb.totals["ps_fed_withholding"] == pytest.approx(24590.52)
    assert rb.totals["ps_ss_tax"] == pytest.approx(10918.20)
    assert rb.totals["ps_gross_earnings"] == pytest.approx(205771.09)
    # Last 2025-paid check is 12/15 (paid 12/22); 12/31 routed to 2026.
    assert rb.last_period_end == "12/15/2025"


def test_rebuild_period_boundary_corrects_broken_final():
    """Period boundary: all three periods are in calendar 2025; the broken
    12/31 YTD is corrected by adding its current period to the 12/15 YTD."""
    readings = [parse_paystub(stub_kvs(t)) for t in (MID, DEC15, DEC31)]
    rb = rebuild_year(readings, 2025, boundary="period")
    # 12/15 YTD 205,771.09 + 12/31 current 8,360.30
    assert rb.totals["ps_gross_earnings"] == pytest.approx(214131.39)
    assert rb.totals["ps_fed_withholding"] == pytest.approx(24590.52 + 817.12)


def test_rebuild_partial_year_flagged():
    readings = [parse_paystub(stub_kvs(MID))]  # single mid-year stub
    rb = rebuild_year(readings, 2025, boundary="pay_date")
    assert rb.complete is False
    assert any("Partial year" in n for n in rb.notes)


# --- reconciliation -----------------------------------------------------------

def _w2(**boxes) -> list[TaxFact]:
    return [
        TaxFact(
            tax_year=2025, document_id="w2", form_type=FormType.w2,
            field_code=code, value=f"{val:.2f}",
            extraction_method=ExtractionMethod.textract, confidence=0.95,
        )
        for code, val in boxes.items()
    ]


PATRICK_W2 = _w2(
    box_1_wages=192733.37, box_2_fed_withholding=24590.52,
    box_4_ss_tax=10918.20, box_6_medicare_tax=2848.21, box_17_state_tax=10238.98,
)


def _patrick_rebuild():
    readings = [parse_paystub(stub_kvs(t)) for t in (MID, DEC15, DEC31)]
    return rebuild_year(readings, 2025, boundary="pay_date")


def test_reconcile_withholdings_match_to_the_penny():
    rec = reconcile_person("Patrick", 2025, PATRICK_W2, _patrick_rebuild())
    by = {ln.key: ln for ln in rec.lines}
    assert by["fed_withholding"].verdict is Verdict.match
    assert by["medicare_tax"].verdict is Verdict.match
    assert by["va_withholding"].verdict is Verdict.match
    assert by["fed_withholding"].delta == pytest.approx(0.0, abs=0.01)


def test_reconcile_box1_explainable_bridge():
    rec = reconcile_person("Patrick", 2025, PATRICK_W2, _patrick_rebuild())
    box1 = next(ln for ln in rec.lines if ln.key == "taxable_wages")
    # gross 205,771.09 - pretax 17,964.11 = 187,806.98 vs W-2 192,733.37
    assert box1.paystub_value == pytest.approx(187806.98)
    assert box1.verdict in (Verdict.explainable, Verdict.mismatch)


def test_reconcile_w2_only_when_no_paystubs():
    rec = reconcile_person("Sara", 2025, PATRICK_W2, None)
    assert rec.has_w2 and not rec.has_paystubs
    assert all(ln.verdict is Verdict.w2_only for ln in rec.lines)
    assert "W-2 only" in rec.summary


def test_reconcile_paystub_only_when_no_w2():
    rec = reconcile_person("Patrick", 2025, None, _patrick_rebuild())
    assert rec.has_paystubs and not rec.has_w2
    assert all(ln.verdict is Verdict.paystub_only for ln in rec.lines)


# --- household rollup ---------------------------------------------------------

def test_household_rollup_sums_and_flags_missing():
    sara_w2 = _w2(
        box_1_wages=86736.42, box_2_fed_withholding=10696.04,
        box_4_ss_tax=5605.68, box_6_medicare_tax=1311.00, box_17_state_tax=4232.59,
    )
    household = reconcile_household(2025, {
        "Patrick": (PATRICK_W2, _patrick_rebuild()),
        "Sara": (sara_w2, None),
    })
    t = household.totals
    assert t.total_wages == pytest.approx(192733.37 + 86736.42)
    assert t.total_fed_withheld == pytest.approx(24590.52 + 10696.04)
    assert t.total_state_withheld == pytest.approx(10238.98 + 4232.59)
    assert set(t.people_counted) == {"Patrick", "Sara"}
    assert t.people_missing_w2 == []
    assert "not computed yet" in household.summary.lower()


def test_household_flags_person_without_readable_w2():
    household = reconcile_household(2025, {
        "Patrick": (None, _patrick_rebuild()),   # paystubs only, no W-2 money
        "Sara": (_w2(box_1_wages=86736.42), None),
    })
    assert household.totals.people_missing_w2 == ["Patrick"]
    assert household.totals.people_counted == ["Sara"]
    assert household.totals.total_wages == pytest.approx(86736.42)


# --- HTTP routes: paystub extract branch + household reconcile ----------------

def test_route_extract_paystub_branch(client, monkeypatch):
    """A paystub document extracts via the paystub branch and is attributed to
    the right person (here, from its filename)."""
    r = client.post("/tax/2025/documents",
                    files={"file": ("2025-06-30_Patrick.pdf", JPEG, "image/jpeg")})
    doc_id = r.json()["document"]["id"]

    class _Stub:
        def extract(self, data, kind):
            return stub_kvs(MID)

    monkeypatch.setattr("tax.routes.get_provider", lambda choice: _Stub())
    r = client.post(f"/tax/2025/documents/{doc_id}/extract", json={"provider": "local"})
    body = r.json()
    assert body["ok"] is True
    assert body["form_type"] == "Paystub"
    assert body["taxpayer"] == "Patrick"
    assert body["fact_count"] >= 5


def test_route_household_reconcile(client, monkeypatch):
    """End-to-end through the API: a W-2 (stubbed Textract KVs) + a paystub
    (stubbed native text) reconcile into a household rollup."""
    # Upload + extract Patrick's W-2 (stub the provider with W-2-shaped facts via
    # a fake that returns KVs the w2 reader maps). Simpler: upload the W-2 doc and
    # directly seed its facts through storage, then a paystub through the route.
    # Distinct bytes per upload — identical bytes would dedupe to one doc
    # (SHA-256 identity), which is correct behavior but not what this test wants.
    w2_bytes = JPEG + b"w2"
    ps_bytes = JPEG + b"paystub"

    rw = client.post("/tax/2025/documents",
                     files={"file": ("W2_Patrick_2025.pdf", w2_bytes, "image/jpeg")})
    w2_id = rw.json()["document"]["id"]
    storage.save_facts(2025, w2_id, PATRICK_W2)
    storage.update_document(2025, w2_id, form_type=FormType.w2, taxpayer="Patrick")

    # Upload + extract a paystub via the route (stubbed provider).
    rp = client.post("/tax/2025/documents",
                     files={"file": ("2025-12-15_Patrick.pdf", ps_bytes, "image/jpeg")})
    ps_id = rp.json()["document"]["id"]

    class _Stub:
        def extract(self, data, kind):
            return stub_kvs(DEC15)

    monkeypatch.setattr("tax.routes.get_provider", lambda choice: _Stub())
    client.post(f"/tax/2025/documents/{ps_id}/extract", json={"provider": "local"})

    r = client.get("/tax/2025/reconcile")
    rec = r.json()["reconciliation"]
    assert rec is not None
    patrick = next(p for p in rec["people"] if p["person"] == "Patrick")
    by = {ln["key"]: ln for ln in patrick["lines"]}
    assert by["fed_withholding"]["verdict"] == "match"
    assert rec["totals"]["total_wages"] == pytest.approx(192733.37)


def test_route_reconcile_empty(client):
    r = client.get("/tax/2025/reconcile")
    body = r.json()
    assert body["ok"] is True
    assert body["reconciliation"] is None
    assert "note" in body
