"""Tests for the statement-import framework (importers package).

Parsing is tested against extracted statement *text* (via paypal.parse_text) so
no real PDF is needed - this mirrors the exact layout PayPal produces, including
the quirks the parser must handle (line-wrapped dates, funding-source lines,
offsetting credit-card deposits, page-footer bleed). Service-level tests run
against the isolated tmp store from conftest, so the real data is never touched.
"""


import pytest

from importers import parse_files, paypal, service

# A synthetic statement in PayPal's extracted-text layout. Covers:
# - a plain purchase (Apple, pre-start)
# - a line-wrapped date (07/08/202 \n 6)
# - a purchase + offsetting "General Credit Card Deposit" pair (Ref ID)
# - a post-start purchase
# - boilerplate that must be skipped (money-waiting banner, error paragraph, footer)
SAMPLE_TEXT = """You have money waiting:  USD 1.66. Log in to accept it
Statement Period PayPal Account ID
Jul 1, 2026 - Jul 31, 2026 user@example.com
DATE DESCRIPTION CURRENCY AMOUNT FEES TOTAL*
06/10/2026 PreApproved Payment Bill User Payment:
Apple Services
  USAA FEDERAL SAVINGS BANK -
  Checking x-0000                                         2.99
USD
ID: AAA111
USD -2.99 0.00 -2.99
07/08/202
6
PreApproved Payment Bill User Payment:
Apple Services
ID: BBB222
USD -19.99 0.00 -19.99
07/16/2026 Express Checkout Payment: LIVER TECHNOLOGY CO., LIMITED
ID: CCC333
USD -269.00 0.00 -269.00
07/16/2026 General Credit Card Deposit
ID: DDD444
Ref ID: CCC333
USD 269.00 0.00 269.00
In case of errors or questions about your electronic transfers,
Telephone us at 555-555-0100;
ACCOUNT STATEMENTS
doe, john
Page 1
"""


def test_parse_text_counts_and_ids():
    txns = paypal.parse_text(SAMPLE_TEXT)
    # 4 real transactions; all boilerplate skipped.
    assert len(txns) == 4
    ids = {t.transaction_id for t in txns}
    assert ids == {"paypal_AAA111", "paypal_BBB222", "paypal_CCC333", "paypal_DDD444"}


def test_parse_text_unwraps_split_date():
    txns = {t.transaction_id: t for t in paypal.parse_text(SAMPLE_TEXT)}
    # 07/08/202 + 6 must rejoin into 2026-07-08.
    assert txns["paypal_BBB222"].date == "2026-07-08"


def test_parse_text_amounts_and_names():
    txns = {t.transaction_id: t for t in paypal.parse_text(SAMPLE_TEXT)}
    assert txns["paypal_AAA111"].amount == -2.99
    assert "Apple Services" in txns["paypal_AAA111"].name
    # Funding-source line must be dropped from the display name.
    assert "USAA" not in txns["paypal_AAA111"].name
    assert "0000" not in txns["paypal_AAA111"].name


def test_parse_text_footer_not_in_name():
    txns = {t.transaction_id: t for t in paypal.parse_text(SAMPLE_TEXT)}
    # The last txn on a page can pick up the footer; it must be stripped.
    assert "ACCOUNT STATEMENTS" not in txns["paypal_DDD444"].name


def test_offset_pairing():
    txns = {t.transaction_id: t for t in paypal.parse_text(SAMPLE_TEXT)}
    deposit = txns["paypal_DDD444"]
    assert deposit.offsets_id == "paypal_CCC333"
    assert deposit.offset is True  # positive amount referencing a parsed purchase
    # The purchase itself is not an offset.
    assert txns["paypal_CCC333"].offset is False


def test_reader_matches_by_filename_and_header():
    r = paypal.PayPalPdfReader()
    assert r.matches("statement-Jul-2026.pdf", b"")
    assert r.matches("paypal-export.pdf", b"")
    assert not r.matches("chase.csv", b"")
    assert not r.matches("random.pdf", b"nothing relevant here")


def _sample_files():
    """A fake 'file' the registry can route: matches on the statement- name,
    and parse() is monkeypatched in the service tests to use parse_text."""
    return [("statement-Jul-2026.pdf", b"%PDF-fake")]


@pytest.fixture
def patch_pdf(monkeypatch):
    """Make the PayPal reader parse SAMPLE_TEXT instead of real PDF bytes."""
    monkeypatch.setattr(paypal, "_extract_text", lambda data: SAMPLE_TEXT)


def test_preview_applies_data_start_filter(patch_pdf):
    pv = service.preview_files(_sample_files())
    # AAA111 is dated 06/10 (before 2026-06-18) -> excluded.
    assert len(pv.pre_start) == 1
    imported_ids = {r["transaction_id"] for r in pv.to_import}
    assert "paypal_AAA111" not in imported_ids
    # The three July rows survive.
    assert imported_ids == {"paypal_BBB222", "paypal_CCC333", "paypal_DDD444"}


def test_preview_marks_offset_ignore(patch_pdf):
    pv = service.preview_files(_sample_files())
    offsets = [r for r in pv.to_import if r.get("category") == "Ignore"]
    assert len(offsets) == 1
    assert offsets[0]["transaction_id"] == "paypal_DDD444"


def test_preview_reconciles_opaque_bank_row(patch_pdf, isolated_store):
    ts = isolated_store
    # Seed an opaque Plaid PAYPAL PURCHASE row matching the BBB222 purchase:
    # PayPal -19.99 on 07/08; Plaid records +19.99 posting a few days later.
    ts.save_transactions([{
        "transaction_id": "plaid_x", "date": "2026-07-10",
        "year": 2026, "month": 7, "name": "PAYPAL PURCHASE", "merchant": "",
        "amount": 19.99, "bank": "usaa", "account_id": "a", "account_mask": "0000",
        "category": "Uncategorized",
    }])
    pv = service.preview_files(_sample_files())
    assert len(pv.reconciled) == 1
    assert pv.reconciled[0].bank_txn_id == "plaid_x"


def test_commit_writes_and_reconciles(patch_pdf, isolated_store):
    ts = isolated_store
    ts.save_transactions([{
        "transaction_id": "plaid_x", "date": "2026-07-10",
        "year": 2026, "month": 7, "name": "PAYPAL PURCHASE", "merchant": "",
        "amount": 19.99, "bank": "usaa", "account_id": "a", "account_mask": "0000",
        "category": "Uncategorized",
    }])
    pv = service.preview_files(_sample_files())
    summary = service.commit(pv)

    rows = {t["transaction_id"]: t for t in ts.load_transactions()}
    # Opaque bank row flipped to Ignore (no double count).
    assert rows["plaid_x"]["category"] == "Ignore"
    # Itemized PayPal rows imported.
    assert "paypal_BBB222" in rows and "paypal_CCC333" in rows
    # Offset deposit is Ignore; pre-start row was not imported.
    assert rows["paypal_DDD444"]["category"] == "Ignore"
    assert "paypal_AAA111" not in rows
    assert any("imported" in s for s in summary)


def test_commit_is_undoable(patch_pdf, isolated_store):
    ts = isolated_store
    ts.save_transactions([])
    pv = service.preview_files(_sample_files())
    service.commit(pv)
    assert len(ts.load_transactions()) == 3
    assert ts.undo() is True
    assert ts.load_transactions() == []


def test_collect_files_unzips():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("statement-Jul-2026.pdf", b"%PDF-fake")
        zf.writestr("__MACOSX/._junk", b"junk")
    members = service.collect_files("statement-2026.zip", buf.getvalue())
    names = [n for n, _ in members]
    assert names == ["statement-Jul-2026.pdf"]  # macOS noise skipped


def test_unknown_file_reported_not_raised():
    results = parse_files([("mystery.xyz", b"data")])
    assert results[0].reader is None
    assert results[0].error is not None
