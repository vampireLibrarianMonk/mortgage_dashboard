"""Content-based form classification.

Identifies a tax form from its extracted key/value text, NOT its filename — a
file named "Document123.pdf" is still recognized as a W-2 if its content says so.
Phase 2 only classifies W-2; other form types fall through to `unknown` and are
added in later phases.
"""
from __future__ import annotations

from __future__ import annotations

import re

from tax.extraction.providers import ExtractedKV
from tax.models import FormType

# OCR splits form tokens ("1099 INT", "1099-INT", "1099INT") — match
# spacing-tolerantly.
_RE_1099_INT = re.compile(r"1099[\s-]*int", re.I)
_RE_1099_DIV = re.compile(r"1099[\s-]*div", re.I)
_RE_1099_R = re.compile(r"1099[\s-]*r\b", re.I)


def _corpus(kvs: list[ExtractedKV]) -> str:
    """All key + value text, lowercased, for keyword/structure checks."""
    parts: list[str] = []
    for kv in kvs:
        parts.append(kv.key)
        parts.append(kv.value)
    return " ".join(parts).lower()


def classify_form(kvs: list[ExtractedKV]) -> FormType:
    """Best-effort form type from extracted content. `unknown` when unsure."""
    text = _corpus(kvs)
    if not text.strip():
        return FormType.unknown

    # Paystub (pay statement). Check BEFORE W-2: a stub also mentions wages and
    # withholding, so match it on its own distinctive earnings-statement markers.
    # Guard against a W-2 by requiring the pay-period/net-pay cadence a stub has
    # and a W-2 does not.
    paystub_markers = sum(
        marker in text
        for marker in (
            "pay period",
            "pay frequency",
            "net pay",
            "deposit advice",
            "pay date",
            "ytd",
            "pre-tax deductions",
            "earnings statement",
            "pay statement",
        )
    )
    if paystub_markers >= 2 and "wage and tax statement" not in text:
        return FormType.paystub

    # Specific 1099s and informational forms — checked before the W-2 fallback so
    # a form's own title wins. Order matters: the IL e-file package embeds a copy
    # of the federal 1040, and the consolidated statement mentions several
    # sub-forms, so the strongest document-level markers are matched first.
    if "1095-c" in text:
        return FormType.f1095_c
    # OMB-number discriminators (printed on the federal forms themselves, on
    # no state form): they must run BEFORE the IL branch, because the back of
    # a 1099-R talks about Illinois income tax and would otherwise trip it.
    if "1545-0074" in text:
        return FormType.f1040
    if "1545-0118" in text:
        return FormType.f1099_r
    # Health-savings / coverage statements with no dedicated reader yet —
    # honest 'other' (routing still sends them to the Health categories).
    if "1099-sa" in text or "5498-sa" in text:
        return FormType.other
    if "1095-b" in text:
        return FormType.other
    # Schedule K-1 (partnership/S-corp shareholder statement).
    if "schedule k-1" in text or "form k-1" in text:
        return FormType.k1
    if "illinois" in text and "income tax" in text:
        return FormType.f1040_il
    # A genuine Form 1040 page prints its own OMB number (1545-0074) — on
    # every 1040 page and on no other form. E-file packages embed the 1099s
    # and 3922s they report (so the corpus may mention "3922" or
    # "consolidated"), and this marker outranks all of them.
    if "1545-0074" in text:
        return FormType.f1040
    if "3922" in text:
        return FormType.f3922
    if "u.s. individual income tax return" in text:
        return FormType.f1040
    # The consolidated statement carries multiple sub-forms; route it to the DIV
    # container reader (which parses DIV/INT/MISC boxes + the 1099-B summary).
    # A single "1099-div" token is enough: Fidelity's individual-account
    # statements are DIV+INT without a 1099-B section, and the pure-INT bank
    # statements never mention 1099-DIV (their branch follows).
    if "consolidated" in text or "1099-div" in text:
        return FormType.f1099_div
    if "1099-nec" in text or "nonemployee compensation" in text:
        return FormType.f1099_nec
    # Navy Federal prints its own 1099-INT layout: a summary strip reading
    # "AMOUNT REPORTED TO IRS: <box1> <box2> <box3> <box4>" and the form's OMB
    # number, but no literal "1099-INT" title that survives KV extraction.
    if "amount reported to irs" in text and ("1545" in text or "1099" in text):
        return FormType.f1099_int
    # OCR splits the form tokens ("1099 INT", "1099-INT", "1099INT") — match
    # spacing-tolerantly.
    if _RE_1099_INT.search(text):
        return FormType.f1099_int
    if _RE_1099_DIV.search(text):
        return FormType.f1099_div
    if _RE_1099_R.search(text):
        return FormType.f1099_r

    # Strong signals: the form's own title / designation.
    if "wage and tax statement" in text or "w-2" in text or "w2" in text:
        return FormType.w2

    # Structural fallback: the signature pair of W-2 boxes.
    has_wages = "wages, tips" in text or "wages tips" in text
    has_fed_wh = "federal income tax withheld" in text
    if has_wages and has_fed_wh:
        return FormType.w2

    # Loosest fallback, deliberately LAST: a bare "1040" + "Department of the
    # Treasury" combination also appears inside bank 1099-INTs, IRS pubs and
    # consolidated statements (they all cite Form 1040). Every specific-form
    # signal above outranks it; a real return has already matched via its
    # OMB number or the return title.
    if "1040" in text and "department of the treasury" in text:
        return FormType.f1040

    return FormType.unknown
