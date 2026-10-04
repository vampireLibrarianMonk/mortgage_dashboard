import { useCallback, useEffect, useState } from "react";
import { taxDeleteDocument, taxListDocuments } from "../../api";
import type { TaxDocument } from "../../types";
import ExtractedFacts from "./ExtractedFacts";
import TaxDocumentList from "./TaxDocumentList";
import TaxDocumentUpload from "./TaxDocumentUpload";
import TaxDocumentViewer from "./TaxDocumentViewer";

interface Props {
  year: number;
  onYearChange: (year: number) => void;
}

// A small, sensible range of recent tax years to pick from.
const YEARS = [2026, 2025, 2024, 2023];

/**
 * Tax Prep. Upload tax documents (scanned images, digital or flattened PDFs),
 * stored immutably with SHA-256 identity, view the originals, and — Phase 2 —
 * extract and review a W-2's boxes into provenance-carrying facts (local or AWS
 * Textract, PII masked). The federal/Virginia tax picture and the AI assistant
 * are later phases (see new_spec/tax_prep_tab_design.md) and are shown here as
 * honest placeholders — no tax owed is computed yet.
 */
export default function TaxPrepPage({ year, onYearChange }: Props) {
  const [docs, setDocs] = useState<TaxDocument[]>([]);
  const [selected, setSelected] = useState<TaxDocument | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    taxListDocuments(year)
      .then((list) => {
        setDocs(list);
        // Keep the selected document's metadata (stage/form_type) in sync after
        // an extraction or verification changed it.
        setSelected((cur) => (cur ? (list.find((d) => d.id === cur.id) ?? cur) : cur));
      })
      .catch(() => setDocs([]))
      .finally(() => setLoading(false));
  }, [year]);

  useEffect(() => {
    setSelected(null);
    refresh();
  }, [refresh]);

  const handleDelete = async (doc: TaxDocument) => {
    await taxDeleteDocument(year, doc.id);
    if (selected?.id === doc.id) setSelected(null);
    refresh();
  };

  return (
    <div className="tax-prep">
      <div className="tax-head">
        <div className="tax-head-top">
          <h2>Tax Picture {year}</h2>
          <label className="tax-year-pick">
            Tax year
            <select value={year} onChange={(e) => onYearChange(Number(e.target.value))}>
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="section-hint">
          Upload your household's tax documents and keep the originals in one place.
          Documents are stored immutably; a W-2 can be read into reviewable facts
          (box values with confidence and source, PII masked). Showing what you owe
          federally and in Virginia comes in a later phase — no tax is computed yet.
        </p>
      </div>

      {/* Honest placeholder for the eventual federal/VA answer — no numbers yet. */}
      <section className="tax-picture-placeholder">
        <div className="tax-pic-tile tax-pic-pending">
          <span className="tax-pic-label">Federal</span>
          <span className="tax-pic-value">—</span>
          <span className="tax-pic-note">computed in a later phase</span>
        </div>
        <div className="tax-pic-tile tax-pic-pending">
          <span className="tax-pic-label">Virginia</span>
          <span className="tax-pic-value">—</span>
          <span className="tax-pic-note">computed in a later phase</span>
        </div>
      </section>

      <section className="tax-section">
        <h3>Documents</h3>
        <TaxDocumentUpload year={year} onUploaded={refresh} />
        {loading ? (
          <p className="section-hint">Loading…</p>
        ) : (
          <TaxDocumentList
            documents={docs}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            onDelete={handleDelete}
          />
        )}
      </section>

      <section className="tax-section">
        <h3>Extracted facts</h3>
        <ExtractedFacts year={year} doc={selected} onChanged={refresh} />
      </section>

      <section className="tax-section">
        <h3>Original</h3>
        <TaxDocumentViewer year={year} doc={selected} />
      </section>
    </div>
  );
}
