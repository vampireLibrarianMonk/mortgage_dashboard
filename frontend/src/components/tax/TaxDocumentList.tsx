import type { TaxDocument } from "../../types";

interface Props {
  documents: TaxDocument[];
  selectedId: string | null;
  onSelect: (doc: TaxDocument) => void;
  onDelete: (doc: TaxDocument) => void;
}

const fmtSize = (n: number) => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
};

const fmtDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
};

/**
 * The uploaded documents for a tax year. Each row shows a pipeline stage pill
 * (Phase 1 only ever reaches "ingested"), the detected form type ("unknown"
 * until a later phase's classifier runs), and basic file metadata.
 */
export default function TaxDocumentList({ documents, selectedId, onSelect, onDelete }: Props) {
  if (documents.length === 0) {
    return <p className="tax-empty">No documents yet. Upload W-2s, 1099s, 1098s, etc. above.</p>;
  }

  return (
    <div className="tax-doc-list">
      <div className="tax-doc-row tax-doc-head" aria-hidden="true">
        <span>Document</span>
        <span>Form</span>
        <span>Stage</span>
        <span>Kind</span>
        <span>Size</span>
        <span>Uploaded</span>
        <span></span>
      </div>
      {documents.map((d) => (
        <div
          key={d.id}
          className={d.id === selectedId ? "tax-doc-row selected" : "tax-doc-row"}
          onClick={() => onSelect(d)}
          title="Click to view the original"
        >
          <span className="tax-doc-name">{d.original_filename}</span>
          <span className={d.form_type === "unknown" ? "tax-form tax-form-unknown" : "tax-form"}>
            {d.form_type}
          </span>
          <span className={`tax-stage tax-stage-${d.stage}`}>{d.stage}</span>
          <span className="tax-doc-kind">{d.kind.toUpperCase()}</span>
          <span className="tax-doc-size">{fmtSize(d.size_bytes)}</span>
          <span className="tax-doc-date">{fmtDate(d.uploaded_at)}</span>
          <button
            type="button"
            className="tax-doc-del"
            title="Remove this document"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(d);
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
