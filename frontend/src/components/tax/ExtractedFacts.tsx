import { useCallback, useEffect, useState } from "react";
import {
  type ExtractionProvider,
  taxExtract,
  taxFacts,
  taxVerifyFact,
} from "../../api";
import type { TaxDocument, TaxFact } from "../../types";

interface Props {
  year: number;
  doc: TaxDocument | null;
  // Called after extraction/verification changes a document's stage so the
  // parent can refresh the document list pills.
  onChanged?: () => void;
}

const CONFIDENCE_OK = 0.9;

const fmtConfidence = (c: number) => `${Math.round(c * 100)}%`;

// Render a fact's value for display. Booleans (Box 13) become Yes/No; PII is
// already masked by the backend.
const fmtValue = (v: TaxFact["value"]): string => {
  if (v === true) return "Yes";
  if (v === false) return "No";
  if (v === null || v === undefined) return "—";
  return String(v);
};

/**
 * Per-document extracted facts with a review workflow. Each row shows the box
 * label, its value, a confidence badge (green ≥90%, amber below — the backend's
 * needs_review threshold), and the source page. A reviewer can accept a value
 * as-is or correct it; corrections keep the original (the backend preserves
 * extracted_value and records an audit trail).
 *
 * Extraction is explicit and honest about cost: "Local" is offline/free but
 * reads almost nothing from a scan; "AWS Textract" (opt-in) reads the boxes.
 */
export default function ExtractedFacts({ year, doc, onChanged }: Props) {
  const [facts, setFacts] = useState<TaxFact[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const docId = doc?.id ?? null;

  const refresh = useCallback(() => {
    if (!docId) {
      setFacts([]);
      return;
    }
    setLoading(true);
    taxFacts(year, docId)
      .then(setFacts)
      .catch(() => setFacts([]))
      .finally(() => setLoading(false));
  }, [year, docId]);

  useEffect(() => {
    setNote("");
    setError("");
    setEditing(null);
    refresh();
  }, [refresh]);

  const runExtract = async (provider: ExtractionProvider) => {
    if (!docId) return;
    setBusy(true);
    setError("");
    setNote("");
    try {
      const res = await taxExtract(year, docId, provider);
      if (!res.ok) {
        setError(res.error ?? "extraction failed");
      } else {
        setNote(res.note ?? "");
        setFacts(res.facts ?? []);
      }
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "extraction failed");
    } finally {
      setBusy(false);
    }
  };

  const accept = async (f: TaxFact) => {
    if (!docId) return;
    setBusy(true);
    try {
      await taxVerifyFact(year, docId, f.field_code, null);
      refresh();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (f: TaxFact) => {
    setEditing(f.field_code);
    setDraft(fmtValue(f.value));
  };

  const saveEdit = async (f: TaxFact) => {
    if (!docId) return;
    setBusy(true);
    try {
      await taxVerifyFact(year, docId, f.field_code, draft);
      setEditing(null);
      refresh();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };

  if (!doc) {
    return (
      <div className="tax-facts tax-facts-empty">
        <p>Select a document to extract and review its facts.</p>
      </div>
    );
  }

  return (
    <div className="tax-facts">
      <div className="tax-facts-actions">
        <button
          type="button"
          className="tax-extract-btn"
          disabled={busy}
          onClick={() => runExtract("local")}
          title="Offline, free — reads digital text/form fields only (little on scans)"
        >
          Extract (Local)
        </button>
        <button
          type="button"
          className="tax-extract-btn tax-extract-aws"
          disabled={busy}
          onClick={() => runExtract("aws")}
          title="Opt-in cloud — AWS Textract reads scanned boxes with confidence + position"
        >
          Extract with AWS Textract
        </button>
        {busy && <span className="tax-facts-busy">working…</span>}
      </div>

      <p className="tax-facts-hint">
        Scanned documents need AWS Textract to read their boxes. Local extraction
        is free and offline but only sees a digital text layer or fillable form
        fields — a scan has neither, so it will find nothing.
      </p>

      {note && <p className="tax-facts-note">{note}</p>}
      {error && <p className="tax-facts-error">{error}</p>}

      {loading ? (
        <p className="section-hint">Loading…</p>
      ) : facts.length === 0 ? (
        <p className="tax-empty">No facts yet. Run extraction above.</p>
      ) : (
        <div className="tax-facts-table">
          <div className="tax-fact-row tax-fact-head" aria-hidden="true">
            <span>Field</span>
            <span>Value</span>
            <span>Confidence</span>
            <span>Source</span>
            <span>Status</span>
            <span></span>
          </div>
          {facts.map((f) => {
            const low = f.confidence < CONFIDENCE_OK;
            const isEditing = editing === f.field_code;
            return (
              <div key={f.field_code} className="tax-fact-row">
                <span className="tax-fact-label" title={f.field_code}>
                  {f.field_label}
                </span>
                <span className="tax-fact-value">
                  {isEditing ? (
                    <input
                      className="tax-fact-input"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      autoFocus
                    />
                  ) : (
                    fmtValue(f.value)
                  )}
                </span>
                <span
                  className={low ? "tax-conf tax-conf-low" : "tax-conf tax-conf-ok"}
                  title={low ? "Below 90% — review suggested" : "High confidence"}
                >
                  {fmtConfidence(f.confidence)}
                </span>
                <span className="tax-fact-source">
                  {f.extraction_method} · p.{f.page}
                </span>
                <span className={`tax-fact-status tax-fact-status-${f.status}`}>
                  {f.status.replace("_", " ")}
                </span>
                <span className="tax-fact-ops">
                  {isEditing ? (
                    <>
                      <button
                        type="button"
                        className="tax-fact-op"
                        disabled={busy}
                        onClick={() => saveEdit(f)}
                      >
                        save
                      </button>
                      <button
                        type="button"
                        className="tax-fact-op tax-fact-op-cancel"
                        onClick={() => setEditing(null)}
                      >
                        cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="tax-fact-op"
                        disabled={busy}
                        onClick={() => accept(f)}
                        title="Accept the extracted value"
                      >
                        ✓
                      </button>
                      <button
                        type="button"
                        className="tax-fact-op"
                        disabled={busy}
                        onClick={() => startEdit(f)}
                        title="Correct the value"
                      >
                        ✎
                      </button>
                    </>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
