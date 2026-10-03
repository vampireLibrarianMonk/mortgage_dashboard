# Mortgage Dashboard — Tax Prep Module Architecture

## Objective

Extend the existing `mortgage_dashboard` repository with a first-class **Tax Prep** tab that supports:

- Digital tax PDF ingestion
- OCR fallback for scanned PDFs
- Structured extraction of tax facts
- Human review and verification
- Reconciliation against existing dashboard financial data
- Federal and Virginia tax calculations
- Local-first processing
- Optional AWS Textract and Bedrock escalation
- Full provenance from every calculated tax value back to the source document and page

The intended navigation becomes:

```text
Dashboard | Console | Banks | Timeline | Tax Prep
```

The design should reuse the repository's existing ingestion philosophy:

```text
ingest -> extract -> normalize -> validate -> human review -> commit
```

The system should **not** rely on an LLM as the authoritative tax calculator.

---

# 1. High-Level Architecture

```text
                           TAX PREP TAB
                                |
              +-----------------+-----------------+
              |                                   |
       Document ingestion                    Existing data
              |                                   |
    +---------+----------+              +---------+---------+
    |         |          |              |         |         |
 AcroForm   PDF text    OCR           Plaid    Mortgage   Budget
    |         |          |              |         |         |
    +---------+----------+              +---------+---------+
              |                                   |
              +---------------+-------------------+
                              |
                          TAX FACTS
                              |
                    +---------+---------+
                    |                   |
               Reconciliation        Tax Rules
                    |                   |
                    +---------+---------+
                              |
                       Tax Worksheet
                              |
             +----------------+----------------+
             |                |                |
         Review UI       AI Assistant      CPA Export
                              |
                           Optional
                       Local / Bedrock
```

---

# 2. Frontend Navigation

Add a fifth top-level page:

```text
Tax Prep
```

Suggested route:

```text
/tax
```

Update the frontend page type:

```ts
type Page =
  | "dashboard"
  | "console"
  | "banks"
  | "timeline"
  | "tax";
```

Add:

```ts
tax: "/tax"
```

The existing SPA architecture can then render a new:

```text
TaxPrepPage
```

Suggested frontend structure:

```text
frontend/src/components/tax/
  TaxPrepPage.tsx
  TaxDocumentUpload.tsx
  TaxDocumentList.tsx
  TaxDocumentViewer.tsx
  ExtractedFacts.tsx
  TaxSummary.tsx
  TaxReviewQueue.tsx
  TaxReconciliation.tsx
  TaxQuestions.tsx
```

---

# 3. Backend Structure

Suggested backend module:

```text
backend/
  tax/
    __init__.py
    routes.py
    models.py
    service.py

    documents.py
    storage.py

    extraction/
      pdf.py
      ocr.py
      classifier.py

    forms/
      base.py
      w2.py
      form_1099_int.py
      form_1099_div.py
      form_1099_b.py
      form_1099_nec.py
      form_1099_misc.py
      form_1098.py
      form_1099_r.py
      form_5498.py
      ssa_1099.py
      k1.py

    rules/
      federal/
        2026.json
      virginia/
        2026.json

    reconciliation/
      banking.py
      mortgage.py
      investments.py

    tests/
```

---

# 4. Tax Prep Main Page

The Tax Prep tab should provide six major functions.

| Area | Purpose |
|---|---|
| Documents | Upload W-2s, 1099s, 1098s, brokerage statements, daycare statements, receipts, etc. |
| Extracted Facts | Show each extracted field, form box, source page, and confidence |
| Reconciliation | Compare tax documents against bank, Plaid, mortgage, and dashboard data |
| Tax Worksheet | Consolidate income, withholding, deductions, credits, basis, gains, and losses |
| Review / Questions | Surface missing forms, conflicts, OCR uncertainty, and human-judgment items |
| Tax Package | Export a clean package for CPA, TurboTax, FreeTaxUSA, or manual filing |

---

# 5. Document Extraction Strategy

Use this extraction order:

```text
1. PDF AcroForm fields
2. Native PDF text and coordinates
3. OCR fallback
```

This provides the highest-confidence extraction method first.

---

# 6. AcroForm Extraction

Some tax PDFs contain real PDF form fields.

Use `pypdf` to inspect:

```python
fields = PdfReader(...).get_fields()
```

or:

```python
get_form_text_fields()
```

This should be the first extraction attempt because it may expose exact form values without OCR.

---

# 7. Positional PDF Extraction

Add:

```text
PyMuPDF
pypdf
```

PyMuPDF should be used to retain text position information.

Example normalized token:

```python
ExtractedToken(
    text="132,541.15",
    page=1,
    bbox=(x0, y0, x1, y1),
    source="native_pdf",
    confidence=1.0,
)
```

The system should understand:

```text
Box 1 -> 132,541.15
Box 2 -> 24,281.00
```

rather than simply extracting disconnected strings.

Source coordinates allow the user to click a tax fact and highlight the original value in the PDF viewer.

---

# 8. OCR Fallback

For scanned PDFs, use:

```text
OCRmyPDF + Tesseract
```

Recommended flow:

```text
PDF
 |
usable native text?
 +-- YES -> native extraction
 |
 +-- NO
      |
   OCRmyPDF
      |
 searchable PDF
      |
 PyMuPDF extraction
```

A useful OCRmyPDF mode is:

```bash
ocrmypdf --mode skip input.pdf output.pdf
```

This leaves pages with usable text alone and OCRs pages that require recognition.

For Windows development, consider isolating OCR dependencies in either:

```text
WSL
```

or:

```text
Docker
```

while keeping the rest of the dashboard native.

---

# 9. Normalized TaxFact Model

Use one normalized representation for extracted values.

Example:

```python
class TaxFact(BaseModel):
    tax_year: int

    document_id: str
    form_type: str

    payer_name: str | None
    payer_tin_masked: str | None

    taxpayer_name: str | None

    field_code: str
    field_label: str

    value: str | float | int | None

    page: int
    bbox: tuple[float, float, float, float] | None

    extraction_method: str
    confidence: float

    status: Literal[
        "extracted",
        "verified",
        "corrected",
        "rejected"
    ]
```

Example stored fact:

```text
Form: W-2
Field: box_1_wages
Value: $143,211.42

Source:
my_bah_w2_2026.pdf

Page:
1

Method:
native_pdf

Confidence:
0.99
```

If the user corrects an extracted value, never destroy the original.

Store both:

```text
extracted_value
verified_value
corrected_by
corrected_at
```

This preserves a full audit trail.

---

# 10. Form Reader Plugin System

Reuse the existing importer architecture.

Define:

```python
class TaxDocumentReader:
    form_type: str

    def matches(self, document):
        ...

    def extract(self, document):
        ...
```

Initial readers:

```text
W2Reader
Form1099INTReader
Form1099DIVReader
Form1099BReader
Form1099RReader
Form1098Reader
SSA1099Reader
```

Readers should classify documents based on content, not filenames.

Example:

```text
"Wage and Tax Statement"
"Form W-2"
```

should identify a W-2 even if the uploaded file is named:

```text
Document123.pdf
```

---

# 11. Field-Level Confidence

Confidence should be tracked per field, not just per document.

Example UI:

```text
W-2 — Employer

OK  Employer EIN          XX-XXXXXXX
OK  Box 1 wages           $143,221.10
OK  Box 2 fed withholding $24,611.55
OK  Box 3 SS wages        $143,221.10
!!  Box 12 DD             $19,442.12
OK  VA wages              $143,221.10
OK  VA withholding        $7,982.14
```

Suggested rule:

```text
confidence < 0.90
```

goes into:

```text
Review Required
```

---

# 12. Reuse Existing Financial Data

The Tax Prep module should connect with existing dashboard data.

Potential sources include:

```text
Plaid transactions
Bank balances
Expense categories
Mortgage data
Property tax
Child care
Income
Investment cash flows
Order-level itemization
```

Tax documents remain authoritative where appropriate, while dashboard data acts as a consistency check.

---

# 13. Mortgage Reconciliation

Example:

```text
Form 1098 mortgage interest = $38,411
```

The dashboard can compare:

```text
Dashboard property-tax estimate   $9,232
Bank payments found               $9,228
Tax documentation                 $9,228
                                  -------
Status                            MATCH
```

This can surface discrepancies before filing.

---

# 14. Dependent Care Reconciliation

Example:

```text
Daycare transactions:
AUMC CDC
January through December
Total = $21,743
```

Tax provider statement:

```text
Provider statement = $21,740
```

Result:

```text
Difference: $3
```

The system should flag meaningful differences for review.

---

# 15. Investment Reconciliation

Support:

```text
1099-B
1099-DIV
1099-INT
1099-R
```

Normalize fields such as:

```text
Ordinary dividends
Qualified dividends
Capital gain distributions
Interest income
Federal withholding

Proceeds
Cost basis
Short-term gain/loss
Long-term gain/loss
Wash sale adjustments
```

Do not reconstruct brokerage tax basis from Plaid transactions.

Use official brokerage tax documents as the authoritative source.

---

# 16. Rules Engine

Keep tax calculations separate from document extraction.

```text
Document extraction
        |
        v
TaxFacts
        |
        v
Tax Rules Engine
```

Suggested files:

```text
tax/rules/federal/2026.json
tax/rules/virginia/2026.json
```

Example contents:

```json
{
  "tax_year": 2026,
  "filing_status": {},
  "standard_deduction": {},
  "brackets": [],
  "child_tax_credit": {},
  "dependent_care": {},
  "capital_gains": {}
}
```

The rules engine should be deterministic and thoroughly tested.

---

# 17. LLM Role

Do not make the LLM the source of truth.

Preferred architecture:

```text
TaxFacts
+
Tax Calculation
+
Tax Rules
+
Supporting Documents
        |
        v
AI Tax Assistant
```

The assistant can explain:

```text
Why did my projected refund drop?

Which documents are still missing?

Why are qualified dividends treated differently?

Show all documentation related to dependent-care expenses.

Why is Box 12 Code DD not treated as taxable wages?
```

The LLM should interpret structured facts, not independently calculate the return.

---

# 18. Local LLM Option

A local model may be added later through a tool such as:

```text
Ollama
```

Potential use cases:

```text
Summarization
Natural-language search
Tax worksheet explanations
Missing-document reasoning
Document classification support
```

The architecture should remain:

```text
LLM = interpretation layer
```

not:

```text
LLM = source of truth
```

---

# 19. Optional AWS Textract

AWS should be optional rather than the default.

Example setting:

```text
Extraction Mode

(*) Local only
( ) Local + AWS fallback
```

If local OCR performs poorly:

```text
OCR confidence: 71%

[Retry locally]
[Send this document to AWS Textract]
```

Create an extraction abstraction:

```python
class ExtractionProvider:
    def extract(...):
        ...

class LocalExtractionProvider:
    ...

class TextractExtractionProvider:
    ...
```

All downstream processing should remain identical regardless of extraction provider.

Textract is especially useful for:

```text
Forms
Key-value pairs
Tables
Queries
Bounding boxes
Confidence scores
Difficult scanned PDFs
```

---

# 20. Optional Bedrock

Cloud AI should be introduced only after the local tax data model is stable.

Preferred flow:

```text
PDF
 |
Local extraction
 |
TaxFacts
 |
Redact SSNs / account numbers
 |
Bedrock
```

Use structured JSON output where possible.

Bedrock should operate primarily on normalized facts rather than raw highly-sensitive tax PDFs.

---

# 21. Local Storage

Suggested structure:

```text
data/
  tax/
    2026/
      documents/
        original/
        searchable/
      extraction/
      exports/
      tax.db
```

Example:

```text
data/tax/2026/documents/original/
    00291ab0.pdf

data/tax/2026/documents/searchable/
    00291ab0_ocr.pdf
```

Store metadata:

```text
SHA-256
Original filename
Tax year
Document type
Upload timestamp
OCR status
Parser version
```

SHA-256 should be used to detect duplicate document uploads.

---

# 22. PII Protection

Never display or log complete values such as:

```text
123-45-6789
```

Normal UI should show:

```text
***-**-6789
```

Sensitive values must not appear in:

```text
console_history.log
server logs
Git commits
exceptions
pytest fixtures
debug dumps
```

Add sensitive storage locations to `.gitignore`.

Examples:

```gitignore
data/tax/
tax_documents/
*.tax.db
```

---

# 23. Tax Prep Dashboard Concept

Example:

```text
-------------------------------------------------------------
                     TAX PREP — 2026
-------------------------------------------------------------

Documents              Income                 Withholding
   12 / 15             $XXX,XXX               $XX,XXX

Federal readiness       Virginia readiness
     87%                    91%

-------------------------------------------------------------

DOCUMENTS

OK W-2 — Employer 1
OK W-2 — Employer 2
OK 1099-DIV — Brokerage
OK 1099-INT — Bank
OK 1098 — Mortgage
!! 1099-B — Needs review
-- Daycare statement — Missing

[ Add documents ]

-------------------------------------------------------------

NEEDS REVIEW

!! 1099-B Box 1e cost basis
   OCR confidence 74%

!! Mortgage interest
   Dashboard estimate differs from Form 1098 by $413

!! Dependent care
   $21,400 bank transactions
   $20,900 provider statement
   Difference: $500
```

---

# 24. API Design

Suggested endpoints:

```text
POST   /tax/documents/preview
POST   /tax/documents
GET    /tax/documents
GET    /tax/documents/{id}
DELETE /tax/documents/{id}

POST   /tax/documents/{id}/extract
POST   /tax/documents/{id}/verify

GET    /tax/{year}/facts
GET    /tax/{year}/summary
GET    /tax/{year}/review
GET    /tax/{year}/reconciliation

POST   /tax/{year}/calculate

GET    /tax/{year}/export
```

Follow the existing pattern:

```text
preview
   |
review
   |
commit
```

---

# 25. Frontend Proxy Changes

Ensure the Vite development proxy supports:

```text
/tax
```

Example:

```ts
'/tax': `http://localhost:${BACKEND_PORT}`,
```

While touching this configuration, also inspect the existing `/console` proxy behavior to make sure development routing is intentional and reliable.

---

# 26. Provenance Requirement

Every important number in the tax worksheet should be clickable.

Example:

```text
Federal withholding: $31,442
```

Expands to:

```text
$18,221 — W-2 Employer A, Box 2
$10,441 — W-2 Employer B, Box 2
 $2,780 — 1099-R, Box 4
--------
$31,442
```

Clicking an individual contribution should open the source PDF on the correct page and highlight the extracted box.

This provenance system should be considered a core requirement.

---

# 27. Recommended Kiro Implementation Sequence

## Phase 1 — Document Foundation

Implement:

```text
Add /tax tab.

Implement local PDF upload.

Store original document using SHA-256 identity.

Extract:
1. AcroForm fields
2. native PDF text
3. positional text with PyMuPDF

Create TaxDocument and TaxFact models.

Add generic document viewer.

Add extracted-field viewer.

Do not add:
- tax calculations
- LLM
- AWS
```

---

## Phase 2 — W-2

Make one form type excellent before expanding.

Implement:

```text
W-2 classification
W-2 parser
Important federal boxes
State boxes
Confidence tracking
Source coordinates
Human verification
Unit tests
Regression tests
```

---

## Phase 3 — Core Forms

Add:

```text
1099-INT
1099-DIV
1098
```

---

## Phase 4 — OCR

Add:

```text
OCRmyPDF
Tesseract
Mixed digital/scanned-page handling
Confidence tracking
```

---

## Phase 5 — Additional Forms

Add:

```text
1099-B
1099-R
SSA-1099
Dependent-care statements
```

---

## Phase 6 — Dashboard Reconciliation

Integrate:

```text
Plaid
Mortgage data
Transaction categories
Child-care expenses
Investment-related transactions
```

---

## Phase 7 — Tax Calculation Engine

Implement deterministic:

```text
Federal calculation
Virginia calculation
Filing status
Dependents
Standard/itemized deduction logic
Credits
Capital gains
Withholding
Estimated refund/balance due
```

Rules should be versioned by tax year.

---

## Phase 8 — AI Assistant

Add:

```text
Natural-language Q&A
Tax worksheet explanation
Missing-document detection
Review assistance
Tax-planning explanations
```

The AI should consume structured data and cite underlying facts.

---

## Phase 9 — AWS Fallback

Add optional:

```text
Textract
Bedrock
```

Only use cloud services when explicitly enabled or when the user manually requests escalation.

---

# 28. Key Architectural Principles

The implementation should preserve the following principles.

## Local First

Default to:

```text
local PDF parsing
local OCR
local database
local rules engine
```

AWS should be optional.

## Deterministic Calculation

Tax calculations must use deterministic code and versioned tax rules.

## Human Verification

Low-confidence values should always be surfaced for review.

## Provenance

Every tax fact should retain:

```text
document
page
bounding box
extraction method
confidence
verification state
```

## No Silent AI Decisions

An LLM should never silently overwrite or invent tax facts.

## Preserve Originals

Never alter the originally uploaded file.

Store OCR-enhanced copies separately.

## Auditability

Corrections should preserve:

```text
original extracted value
verified value
person/process making correction
timestamp
parser version
```

---

# 29. Definition of "Ultimate Tax Prep Assistance"

The goal should not simply be:

```text
Upload PDF -> Chatbot
```

The target should be:

```text
Upload documents
        |
Automatic classification
        |
High-confidence local extraction
        |
OCR fallback
        |
Normalized tax facts
        |
Human verification
        |
Cross-check against financial data
        |
Deterministic tax calculations
        |
Missing-document detection
        |
Explainable AI assistance
        |
CPA / filing package export
```

The key differentiator is **traceability**.

Every conclusion should be explainable, every important number should be traceable to its source, and the tax assistant should sit on top of verified structured financial data rather than attempting to infer an entire tax return from raw PDFs.
