"""Form readers: map normalized extraction output to TaxFacts per form type.

Phase 2 ships the W-2 reader. Readers classify/map by content (not filename) and
preserve provenance (page, bbox, confidence, extraction method) on every fact.
"""
