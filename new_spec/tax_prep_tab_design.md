# Tax Prep Tab — Design & Alpha-Loop Decisions

Status: **design complete, pre-implementation.** This is the decision companion to
`new_spec/mortgage_dashboard_tax_prep_architecture.md`. That doc is the full
architecture; **this doc records the alpha-looped decisions** — grounded in the
household's *real* scanned documents, the available AWS services, and the
`document_aggregator` reference UX — and defines the **simple output** the user
asked for. Where this doc and the architecture doc disagree, **this doc wins**
(it reflects what the real corpus actually requires).

> Deliver target (user's words): *"a tax picture capturing the household
> population (husband, wife, kids)… showing what they owe in their federal and
> state taxes"* — simple, elegant, informative, with every number traceable to a
> source document. Not a filing engine, not a chatbot.

---

## 0. The one empirical finding that reshaped the design

Before designing, the four real 2025 documents were inspected
(`Tax_Documents/2025/`: both W-2s, the 1099-INT, the 1099-NEC):

- **All four have ZERO native PDF text and NO AcroForm fields.**
- Each page is a **single high-resolution JPEG** (≈2525×3269, DCTDecode) — i.e.
  scanned or photographed paper.

**Consequence:** the architecture doc's extraction order (AcroForm → native text
→ *OCR fallback*) is **inverted** for this household. OCR/vision is **not a
fallback — it is the primary path.** Any design that treats OCR as an edge case
would fail on the real corpus. This single fact drives the extraction decision
below. (The AcroForm/native-text path is still tried first — it's a cheap win on
the rare digital PDF — but it will usually miss, and that's expected.)

---

## 1. Scope — the simple output

The tab's hero deliverable is **one glanceable screen**, "**Tax Picture <year>**",
that answers two questions:

1. **What do we owe (or get back) — federal and Virginia?**
2. **How complete and trustworthy is that answer right now?**

Everything else (document management, field-level review, the full worksheet,
the AI assistant) is **progressive disclosure** beneath that answer. The screen
is modeled on the existing Dashboard/Timeline summary aesthetic and the
architecture doc's §23 "Tax Prep Dashboard Concept."

**Out of scope (v1):** e-filing, form generation (1040/760 PDFs), multi-year
comparison, non-VA states, itemized-vs-standard optimization beyond a simple
pick, audit defense. The output is a **planning estimate**, labeled as such
everywhere.

---

## 2. The household this must model (from the real corpus)

Married filing jointly, two earners plus side income and dependents:

| Person | Documents | Tax meaning |
|---|---|---|
| Patrick | W-2 (Booz Allen) | wages, fed + VA withholding |
| Sara | W-2 (Inova) **and** 1099-NEC (Fay Nutrition) | wages **+ self-employment** → Schedule C + SE tax |
| Interest | 1099-INT (Navy Federal) | interest income |
| Kids (dependents) | childcare records | Child Tax Credit + dependent-care credit |
| Informational | 1095-C (coverage), Form 3922 (ESPP) | no $ unless ESPP shares were sold |

So the engine must handle: **W-2 wages ×2, a Schedule C with self-employment
tax, 1099-INT, the standard deduction (MFJ), CTC, the dependent-care credit, and
Virginia state** on top. This is the concrete end-to-end the design is validated
against — not a toy W-2-only case.

---

## 3. Extraction architecture (alpha-loop result)

Three strategies were weighed against the real (scanned) corpus and the goals
(simple, provenance-first, local-first *preferred*):

| Strategy | Verdict |
|---|---|
| **A. Local OCR** (OCRmyPDF + Tesseract + PyMuPDF bbox) | Free, offline, private. But Tesseract reads *text*, not *"Box 1 = X"* — key/value association on form layouts is weak and needs heavy per-form positional templates. Windows dependency friction (the architecture doc itself says isolate in WSL/Docker). **Viable but brittle + high dev cost** for box-accurate extraction. |
| **B. AWS Textract** `AnalyzeDocument` (FORMS + TABLES) | Purpose-built for scanned forms: returns key/value pairs, tables, **bounding boxes, and per-field confidence** — exactly the provenance the design requires — directly from the JPEG-in-PDF. Cost ≈ $0.05–0.065/page; a household return is ~10–20 pages/year = **pennies.** **Best fit** for box-accurate, confidence-scored extraction on genuinely scanned docs. |
| **C. Bedrock multimodal** (Claude / Nova vision → JSON) | Flexible, no templates, but **non-deterministic and can hallucinate numbers** → violates the "LLM is never the source of truth" principle. **Disallowed** as the extractor of authoritative values. Allowed only as an assist/cross-check surfaced for human verification, never silently. |

### Chosen: a provider **ladder** behind one interface

An `ExtractionProvider` abstraction (architecture doc §19) so everything
downstream (TaxFact normalize → validate → calculate) is **identical regardless
of provider**:

```
per document / page:
  1. LOCAL DIGITAL   try AcroForm fields, then PyMuPDF native text + bbox
                     (cheap win when a PDF is actually digital; usually misses here)
  2. LOCAL OCR       OCRmyPDF + Tesseract → searchable text + a confidence signal
                     (always available, offline; weak at box/KV mapping)
  3. AWS TEXTRACT    AnalyzeDocument FORMS/TABLES → KV + tables + bbox + confidence
                     (the recommended extractor for scanned tax forms;
                      populates TaxFact provenance directly)
```

- **Explicit, user-visible toggle** (architecture doc §19): `( ) Local only
  (•) Local + AWS`. Default local; AWS is opt-in and clearly indicated per
  document.
- **Honest expectation to document in the UI:** because the real corpus is
  scanned, *pure-local gets you searchable text but weak box mapping* — accurate,
  box-level extraction effectively leans on Textract. This is stated plainly, not
  hidden, so the user chooses with eyes open. (If they add digital PDFs later,
  path 1 handles them for free.)
- Textract's bbox + confidence **are** the provenance and the review signal — no
  extra work to get the "click a number → highlight the box" requirement.

### LLM (Bedrock) role — interpretation only

Same stance taken for the Timeline/Reports graphics alpha-loop: **the model never
produces an authoritative number.** Bedrock consumes **verified TaxFacts +
deterministic calc output** (redacted — see §7) to:

- write the plain-language "what to watch for" summary,
- detect missing/expected documents,
- explain a specific number or difference on request.

It is a **side panel**, introduced in a late phase, never the headline figure.

---

## 4. Deterministic tax engine (separate from extraction)

Per the architecture doc §16, calculation is **deterministic code over
year-versioned rules**, fully unit-tested, completely separate from extraction:

```
tax/rules/federal/<year>.json     brackets, std deduction, CTC, dependent-care,
                                  SE-tax params, capital-gains
tax/rules/virginia/<year>.json    VA brackets, deductions, VA child/dependent-care
```

Engine inputs = verified TaxFacts (§5). Engine output = the worksheet + the two
hero numbers. **No LLM in this path, ever.** The engine must handle the real
household's shape (W-2 ×2, Schedule C + SE tax, 1099-INT, std deduction, CTC,
dependent-care credit, VA). Rules are data, versioned by tax year, so a new year
is a new JSON, not a code change.

---

## 5. TaxFact + provenance model

Adopt the architecture doc's §9 `TaxFact` verbatim in spirit — every extracted
value carries: `document_id, form_type, field_code, field_label, value, page,
bbox, extraction_method, confidence, status (extracted|verified|corrected|
rejected)`. On correction, **never destroy the original**: keep
`extracted_value` + `verified_value` + `corrected_by` + `corrected_at` +
`parser_version` (full audit trail).

**Provenance interaction (core requirement):** every number on the hero tiles and
in the worksheet is a **button**. Click → expands its **contribution breakdown**
(e.g. *Federal withholding = W-2 Patrick Box 2 + W-2 Sara Box 2 + 1099-NEC
backup wh*). Click a contribution → opens the **source PDF on the right page with
the bbox highlighted**. Textract supplies the bbox + confidence that make this
possible.

Status/aggregation rules borrowed from `document_aggregator` ("assembly, not
generation"): never invent a value; when two documents disagree, mark a
**conflict** and preserve all candidates (don't auto-resolve); when something is
required but unsupported by any doc, mark **needs_review** (don't fabricate).

---

## 6. The Tax Picture screen (UX, top → bottom)

Chosen over a worksheet-first layout (too intimidating, buries the answer) and a
chatbot-first layout (violates "simple output," makes AI feel authoritative).
Card-first dashboard, progressive disclosure. Matches the mortgage app's own
design tokens (`--border/--accent/--muted/--panel`), borrowing the *interaction*
idioms (not the CSS) from `document_aggregator` (`StageTrack`, `OverallBadge`,
click-through provenance).

1. **Household strip** — filing status (MFJ) + people as chips: Patrick (W-2),
   Sara (W-2 + self-employment), kids (dependents → CTC / dependent-care). Each
   chip ties to the docs/income attributed to that person. Humanizes the
   "household population."

2. **The answer — two hero tiles:** **Federal** owe/refund and **Virginia**
   owe/refund. Large signed number (owe = red, refund = green), each labeled
   **ESTIMATE** with a one-line plain read. This is the whole point of the tab.

3. **Readiness bar** — Federal readiness % and VA readiness % (how much of the
   expected picture is captured **and verified**). A number built from 40% of the
   docs should *say* 40% — trust before precision.

4. **Documents list** — each known/expected document with a `StageTrack`-style
   pipeline (`ingested → classified → extracted → verified`), form type, whose it
   is, and confidence. **Expected-but-missing** docs appear explicitly (e.g.
   *"Dependent-care statement — expected, not uploaded"*). `[ Add documents ]`
   dropzone (reuses the existing importer preview→commit idiom).

5. **Watch for / Needs review** — the human-judgment list, and the user's second
   explicit ask (*"what they need to watch for tax-wise"*): low-confidence fields
   (< 0.90), document-vs-dashboard mismatches (Form 1098 interest vs mortgage
   data; daycare bank total vs provider statement), missing forms, and flags like
   *"Sara has 1099-NEC → self-employment tax applies; estimated payments?"*

6. **Worksheet (collapsible)** — income / withholding / deductions / credits with
   full per-number provenance (§5). Tucked beneath the simple answer for those
   who want the detail.

**AI assistant** (optional, late phase) is a **side panel** that explains and
answers, always citing underlying facts — never the source of the headline
number.

---

## 7. AWS recommendations (concrete, for this account)

Verified on account **809784555426** (`us-east-1`, user `asus-tester`): Bedrock
is enabled and Textract is reachable. Everything cloud is **opt-in, feature-
flagged off by default, and redacted before send.**

| Need | Service / model | Notes |
|---|---|---|
| Scanned-form extraction | **Textract `AnalyzeDocument`** (FORMS + TABLES); `AnalyzeExpense` for receipts | KV + tables + **bbox + confidence** = provenance for free. ~pennies per return. The practical default for *this* scanned corpus. |
| Narrative assistant (default) | **Bedrock `anthropic.claude-haiku-4-5-20251001-v1:0`** | Cheap/fast; good enough for "what to watch for," missing-doc reasoning, explain-this-number. |
| Narrative assistant (rich) | **`anthropic.claude-sonnet-4-5-20250929-v1:0`** | For deeper explanations when asked. |
| Optional document search | **`amazon.titan-embed-text-v2:0`** | Local hybrid search is fine first; Titan v2 if cloud search is wanted. |

- **Invoke via boto3 in-app**, not the AWS CLI (CLI arg-quoting is unreliable on
  PowerShell; proven during this analysis — not a blocker, just use the SDK).
- **Redaction before any cloud send:** SSNs, account numbers, and TINs are masked
  (`***-**-6789`) *before* a TaxFact or image leaves the machine for Bedrock. For
  Textract, send the document image but treat the returned text as sensitive and
  mask on storage/display/log.
- **Graceful degradation:** AWS off → the tab still runs (local OCR text), and the
  UI says *"local text only — box-level mapping limited; enable AWS for accurate
  form extraction."* Bedrock off → template sentences instead of generated prose.
  Nothing breaks when cloud is absent.

---

## 8. Reconciliation against existing dashboard data

The tab cross-checks tax documents against data already in the app (architecture
doc §13–15), surfacing differences in "Watch for":

- **Form 1098 mortgage interest** vs the mortgage data / bank payments.
- **Dependent-care** (provider statement) vs **Plaid** daycare transactions
  (the app already categorizes AUMC CDC childcare).
- **1099-INT / investment** docs are **authoritative** — the dashboard is only a
  consistency check; never reconstruct brokerage basis from Plaid.

Tax documents win where authoritative; the dashboard is the sanity check that
catches a fat-fingered box or a missing form *before* filing.

---

## 9. Security, storage, honesty

- **Immutable originals**, SHA-256 identity (dedupe), originals never altered;
  OCR-enhanced copies stored separately (architecture doc §21).
- **Encrypted at rest**, reusing the app's existing Fernet-encrypted store
  pattern (`txn_store`). Tax data paths **gitignored** (`data/tax/`, `*.tax.db`).
- **PII never logged** — not in `console_history.log`, server logs, exceptions,
  commits, or test fixtures. Display masked.
- **Everything is an ESTIMATE** — persistent disclaimer; this is planning, not
  tax advice or a filed return.
- **No silent AI** — the LLM never overwrites or invents a fact; low-confidence
  and conflicting values always surface for human review.
- **a11y gate** — carry the `document_aggregator` axe-core + keyboard/focus audit
  over to the new tab's UI states.
- **Honest "surfaced vs API-only"** — document which endpoints the UI actually
  exercises vs. which are backend-only, so nothing looks more finished than it is.

---

## 10. Build order (reordered for the OCR-primary reality)

Mirrors the architecture doc's phases, **resequenced** because the real corpus is
scanned (so OCR/Textract must come early, not at phase 4/9):

1. **Tab + document foundation.** Add the `tax` page + `/tax` route (extend
   `Page`, `PAGE_PATHS`, `pageFromPath` — the pattern already used for the other
   tabs). Upload with SHA-256 identity, immutable original storage, the generic
   document viewer, and the `TaxDocument` / `TaxFact` models. No calc, no AI.
2. **Extraction ladder + provider abstraction.** Local digital (AcroForm /
   PyMuPDF) → local OCR (OCRmyPDF/Tesseract, Dockerized) → **Textract**
   (opt-in toggle). Populate TaxFacts with bbox + confidence. *(Early, because the
   docs are scans — this is where the architecture doc's "AWS at phase 9" is
   wrong for this corpus.)*
3. **W-2 excellent first.** Classify + extract W-2 (content-based, not filename),
   all federal + VA boxes, confidence per field, source coordinates, human verify,
   regression tests — against the **real** scanned W-2s (Patrick, Sara).
4. **Core forms.** 1099-INT, 1099-NEC (→ Schedule C), then 1098/1099-DIV as they
   appear. Content classification.
5. **Deterministic engine v1.** Federal + Virginia for the real household shape
   (W-2 ×2, Schedule C + SE tax, 1099-INT, std deduction, CTC, dependent-care).
   Year-versioned JSON rules. Heavy unit tests. → lights up the two hero tiles.
6. **The Tax Picture screen** (§6) with provenance click-through and readiness.
7. **Reconciliation** against mortgage + Plaid (§8) → the "Watch for" list.
8. **AI assistant side panel** (Bedrock, redacted, cite-the-facts) + optional
   doc search.
9. **Export** a clean CPA/filing package (facts + worksheet + provenance).

Each phase: `tsc` + backend tests + pre-commit green, same discipline as the rest
of the repo.

---

## 11. What changed vs. the architecture doc (summary)

- **OCR is primary, not a fallback** — the real corpus is image-only scans.
- **Textract is the practical default extractor** for scanned forms (still opt-in,
  still local-first by preference) — pulled early, not phase 9.
- **The output is deliberately simple**: a two-tile federal/VA "Tax Picture" with
  a household strip and readiness, worksheet behind progressive disclosure.
- Everything else (TaxFact provenance, deterministic engine, LLM-as-interpreter,
  PII rules, immutable originals, phased W-2-first) is **kept and endorsed.**
