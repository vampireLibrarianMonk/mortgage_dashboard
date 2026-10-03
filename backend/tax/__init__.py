"""Tax Prep module (Phase 1: document foundation).

Local-first ingestion of tax documents (scanned images, digital + flattened
PDFs) with SHA-256 identity, immutable originals, and an encrypted metadata
index. Extraction, reconciliation, calculation, and AI assistance are later
phases — see new_spec/tax_prep_tab_design.md. Phase 1 adds NO extraction/OCR/
calc/AI; it establishes the document store and the tab.
"""
