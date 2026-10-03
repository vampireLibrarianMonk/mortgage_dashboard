import { taxDocumentRawUrl } from "../../api";
import type { TaxDocument } from "../../types";

interface Props {
  year: number;
  doc: TaxDocument | null;
}

/**
 * Renders the selected document's original bytes inline — a PDF in an iframe,
 * an image in an <img>. Phase 1 has no extraction overlay; later phases will add
 * bounding-box highlights for provenance.
 */
export default function TaxDocumentViewer({ year, doc }: Props) {
  if (!doc) {
    return (
      <div className="tax-viewer tax-viewer-empty">
        <p>Select a document to view the original.</p>
      </div>
    );
  }

  const url = taxDocumentRawUrl(year, doc.id);

  return (
    <div className="tax-viewer">
      <div className="tax-viewer-head">
        <span className="tax-viewer-title">{doc.original_filename}</span>
        <a href={url} target="_blank" rel="noreferrer" className="tax-viewer-open">
          open in new tab ↗
        </a>
      </div>
      {doc.kind === "pdf" ? (
        <iframe className="tax-viewer-frame" title={doc.original_filename} src={url} />
      ) : (
        <img className="tax-viewer-img" alt={doc.original_filename} src={url} />
      )}
    </div>
  );
}
