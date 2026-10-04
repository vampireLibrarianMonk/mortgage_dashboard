"""Tax Prep Phase 2 tests — W-2 extraction, classification, masking, verify.

These never call AWS. A Textract-shaped response fixture (the real block shape
AnalyzeDocument returns) is fed through `_parse_textract`, so the provider parse
and the W-2 reader are both exercised offline. The route tests stub the provider
so no network/credentials are needed.

Isolation mirrors test_tax.py: repoint storage.TAX_ROOT at the tmp data dir.
"""
import pytest
from starlette.testclient import TestClient

import main
from tax import storage
from tax.classify import classify_form
from tax.extraction.providers import ExtractedKV, _parse_textract
from tax.forms.w2 import extract_w2_facts
from tax.models import DocStage, FactStatus, FormType

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture(autouse=True)
def isolated_tax(isolated_store, monkeypatch):
    monkeypatch.setattr(storage, "TAX_ROOT", isolated_store.DATA_DIR / "tax")


@pytest.fixture
def client():
    return TestClient(main.app)


# --- Textract response fixture ------------------------------------------------
# Builds a minimal-but-realistic AnalyzeDocument(FORMS) response: KEY_VALUE_SET
# KEY blocks linked to VALUE blocks, each with CHILD WORD/SELECTION_ELEMENT
# blocks and Geometry. This is the exact shape _parse_textract consumes.

_next_id = 0


def _bid() -> str:
    global _next_id
    _next_id += 1
    return f"b{_next_id}"


def _geo():
    return {"BoundingBox": {"Left": 0.1, "Top": 0.2, "Width": 0.3, "Height": 0.04}}


def _kv_block(key_text, value_text, key_conf, val_conf, *, selected=False, page=1):
    """Produce the (key, value, word) blocks for one KEY_VALUE_SET pair."""
    blocks = []
    word_ids = []
    if selected:
        sid = _bid()
        blocks.append({
            "Id": sid, "BlockType": "SELECTION_ELEMENT",
            "SelectionStatus": "SELECTED", "Confidence": val_conf,
        })
        word_ids.append(sid)
    else:
        for w in value_text.split():
            wid = _bid()
            blocks.append({"Id": wid, "BlockType": "WORD", "Text": w,
                           "Confidence": val_conf})
            word_ids.append(wid)

    key_word_ids = []
    for w in key_text.split():
        wid = _bid()
        blocks.append({"Id": wid, "BlockType": "WORD", "Text": w, "Confidence": key_conf})
        key_word_ids.append(wid)

    value_id = _bid()
    blocks.append({
        "Id": value_id, "BlockType": "KEY_VALUE_SET", "EntityTypes": ["VALUE"],
        "Confidence": val_conf, "Page": page, "Geometry": _geo(),
        "Relationships": [{"Type": "CHILD", "Ids": word_ids}] if word_ids else [],
    })
    key_id = _bid()
    blocks.append({
        "Id": key_id, "BlockType": "KEY_VALUE_SET", "EntityTypes": ["KEY"],
        "Confidence": key_conf, "Page": page, "Geometry": _geo(),
        "Relationships": [
            {"Type": "CHILD", "Ids": key_word_ids},
            {"Type": "VALUE", "Ids": [value_id]},
        ],
    })
    return blocks


def _w2_textract_response() -> dict:
    """A realistic W-2 response: all mapped boxes, a duplicate copy of Box 1 at
    lower confidence (multi-copy dedupe), the Box 13 checkbox, and PII fields."""
    global _next_id
    _next_id = 0
    blocks = []
    blocks += _kv_block("1 Wages, tips, other comp.", "52,000.00", 97.0, 94.1)
    # Duplicate (second copy) of Box 1 at LOWER confidence -> must be dropped.
    blocks += _kv_block("1 Wages, tips, other comp.", "52,000.00", 90.0, 88.0, page=2)
    blocks += _kv_block("2 Federal income tax withheld", "$6,240.00", 96.0, 95.0)
    blocks += _kv_block("3 Social security wages", "52,000.00", 96.0, 93.0)
    blocks += _kv_block("4 Social security tax withheld", "3,224.00", 96.0, 93.0)
    blocks += _kv_block("5 Medicare wages and tips", "52,000.00", 96.0, 93.0)
    blocks += _kv_block("6 Medicare tax withheld", "754.00", 96.0, 93.0)
    blocks += _kv_block("13 Retirement plan", "", 95.0, 95.0, selected=True)
    blocks += _kv_block("15 State", "VA", 95.0, 87.6)   # < 0.90 -> needs_review
    blocks += _kv_block("16 State wages, tips, etc.", "52,000.00", 95.0, 92.0)
    blocks += _kv_block("17 State income tax", "2,600.00", 95.0, 85.0)  # needs_review
    blocks += _kv_block("b Employer's FED ID number", "54-1234443", 96.0, 93.0)
    blocks += _kv_block("a Employee's SSA number", "123-45-6665", 96.0, 93.0)
    blocks += _kv_block("e Employee's name", "Sara Inova", 96.0, 93.0)
    return {"Blocks": blocks}


@pytest.fixture
def w2_kvs() -> list[ExtractedKV]:
    return _parse_textract(_w2_textract_response())


# --- parse + classify ----------------------------------------------------------

def test_parse_textract_yields_kvs(w2_kvs):
    assert w2_kvs, "expected key/value pairs from the fixture"
    # The checkbox value is normalized to the "[X]" marker.
    box13 = next(kv for kv in w2_kvs if kv.key.startswith("13"))
    assert box13.value == "[X]" and box13.is_selection is True
    # Confidence is normalized to 0-1 and bbox is carried through.
    box1 = next(kv for kv in w2_kvs if kv.key.startswith("1 Wages"))
    assert 0.0 < box1.confidence <= 1.0
    assert box1.bbox is not None and len(box1.bbox) == 4


def test_classify_detects_w2_from_content(w2_kvs):
    assert classify_form(w2_kvs) is FormType.w2


def test_classify_unknown_on_empty():
    assert classify_form([]) is FormType.unknown


# --- W-2 reader ---------------------------------------------------------------

def test_extract_w2_facts_shape(w2_kvs):
    facts = extract_w2_facts("docabc", 2025, w2_kvs)
    by_code = {f.field_code: f for f in facts}
    # Every mapped box present exactly once (deduped).
    expected = {
        "box_1_wages", "box_2_fed_withholding", "box_3_ss_wages", "box_4_ss_tax",
        "box_5_medicare_wages", "box_6_medicare_tax", "box_13_retirement_plan",
        "box_15_state", "box_16_state_wages", "box_17_state_tax",
        "employer_ein", "employee_ssn", "employee_name",
    }
    assert set(by_code) == expected
    assert len(facts) == len(expected)  # no duplicate Box 1


def test_money_is_normalized(w2_kvs):
    facts = {f.field_code: f for f in extract_w2_facts("d", 2025, w2_kvs)}
    assert facts["box_1_wages"].value == "52000.00"
    assert facts["box_2_fed_withholding"].value == "6240.00"  # $ and comma stripped
    assert facts["box_17_state_tax"].value == "2600.00"


def test_box13_is_bool(w2_kvs):
    facts = {f.field_code: f for f in extract_w2_facts("d", 2025, w2_kvs)}
    val = facts["box_13_retirement_plan"].value
    assert val is True and isinstance(val, bool)


def test_low_confidence_flags_needs_review(w2_kvs):
    facts = {f.field_code: f for f in extract_w2_facts("d", 2025, w2_kvs)}
    # Box 15 (0.876) and Box 17 (0.85) are below the 0.90 review threshold.
    assert facts["box_15_state"].status is FactStatus.needs_review
    assert facts["box_17_state_tax"].status is FactStatus.needs_review
    # Box 1 (0.94) is clean.
    assert facts["box_1_wages"].status is FactStatus.extracted


def test_pii_is_masked(w2_kvs):
    facts = {f.field_code: f for f in extract_w2_facts("d", 2025, w2_kvs)}
    ssn = facts["employee_ssn"]
    ein = facts["employer_ein"]
    assert ssn.value == "***-**-6665" and "123-45" not in str(ssn.value)
    assert ein.value == "**-***4443" and "54-123" not in str(ein.value)
    # The masked value is also the audit baseline (raw never stored).
    assert ssn.extracted_value == "***-**-6665"


def test_dedupe_keeps_highest_confidence(w2_kvs):
    facts = {f.field_code: f for f in extract_w2_facts("d", 2025, w2_kvs)}
    # Two Box 1 copies (0.941 and 0.88); the higher one wins.
    assert facts["box_1_wages"].confidence == pytest.approx(0.941, abs=1e-3)


# --- persistence + verify audit trail -----------------------------------------

def test_save_load_facts_roundtrip(w2_kvs):
    facts = extract_w2_facts("docroundtrip", 2025, w2_kvs)
    storage.save_facts(2025, "docroundtrip", facts)
    loaded = storage.load_facts(2025, "docroundtrip")
    assert {f.field_code for f in loaded} == {f.field_code for f in facts}
    # Box 13 bool survives the encrypted round trip.
    b13 = next(f for f in loaded if f.field_code == "box_13_retirement_plan")
    assert b13.value is True


def test_update_fact_correction_preserves_audit(w2_kvs):
    facts = extract_w2_facts("docaudit", 2025, w2_kvs)
    storage.save_facts(2025, "docaudit", facts)
    updated = storage.update_fact(
        2025, "docaudit", "box_1_wages",
        {"verified_value": "53000.00", "value": "53000.00",
         "status": FactStatus.corrected.value, "corrected_at": "2026-01-01T00:00:00"},
    )
    assert updated is not None
    assert updated.value == "53000.00"
    assert updated.verified_value == "53000.00"
    assert updated.extracted_value == "52000.00"  # original NEVER overwritten
    assert updated.status is FactStatus.corrected


# --- HTTP routes --------------------------------------------------------------

def test_route_extract_local_scan_is_honest(client, monkeypatch):
    """Local provider on a scan returns nothing -> honest note, no false facts."""
    r = client.post("/tax/2025/documents",
                    files={"file": ("scan.jpg", JPEG, "image/jpeg")})
    doc_id = r.json()["document"]["id"]

    r = client.post(f"/tax/2025/documents/{doc_id}/extract", json={"provider": "local"})
    body = r.json()
    assert body["ok"] is True
    assert body["fact_count"] == 0
    assert body["form_type"] == "unknown"
    assert "textract" in body["note"].lower() or "aws" in body["note"].lower()


def test_route_extract_with_stubbed_provider(client, monkeypatch, w2_kvs):
    """Stub the provider so a W-2's facts flow through extract -> facts -> verify
    without touching AWS."""
    r = client.post("/tax/2025/documents",
                    files={"file": ("anything.jpg", JPEG, "image/jpeg")})
    doc_id = r.json()["document"]["id"]

    class _Stub:
        def extract(self, data, kind):
            return w2_kvs

    monkeypatch.setattr("tax.routes.get_provider", lambda choice: _Stub())

    r = client.post(f"/tax/2025/documents/{doc_id}/extract", json={"provider": "aws"})
    body = r.json()
    assert body["ok"] is True
    assert body["form_type"] == "W-2"
    assert body["stage"] == DocStage.extracted.value
    assert body["fact_count"] >= 10

    # Facts are retrievable and PII is masked over the wire.
    r = client.get(f"/tax/2025/documents/{doc_id}/facts")
    facts = {f["field_code"]: f for f in r.json()["facts"]}
    assert facts["employee_ssn"]["value"] == "***-**-6665"

    # Verify (accept) a clean fact.
    r = client.post(f"/tax/2025/documents/{doc_id}/facts/box_1_wages/verify", json={})
    f = r.json()["fact"]
    assert f["status"] == FactStatus.verified.value
    assert f["verified_value"] == "52000.00"

    # Correct a fact -> status corrected, original preserved.
    r = client.post(
        f"/tax/2025/documents/{doc_id}/facts/box_2_fed_withholding/verify",
        json={"value": "6300.00"},
    )
    f = r.json()["fact"]
    assert f["status"] == FactStatus.corrected.value
    assert f["verified_value"] == "6300.00"
    assert f["extracted_value"] == "6240.00"


def test_route_verify_missing_fact(client):
    r = client.post("/tax/2025/documents",
                    files={"file": ("x.jpg", JPEG, "image/jpeg")})
    doc_id = r.json()["document"]["id"]
    r = client.post(f"/tax/2025/documents/{doc_id}/facts/box_1_wages/verify", json={})
    assert r.json()["ok"] is False
