import { useRef, useState } from "react";
import { taxUploadDocument } from "../../api";

interface Props {
  year: number;
  onUploaded: () => void; // refresh the list after a successful upload
}

/**
 * Upload a tax document (scanned image, digital or flattened PDF). Phase 1 only
 * stores the original immutably and indexes it — no extraction happens yet. The
 * backend validates the file type (PDF/PNG/JPEG) and dedupes by SHA-256.
 */
export default function TaxDocumentUpload({ year, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const uploadFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    setMsg(null);
    let ok = 0;
    let dup = 0;
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      try {
        const res = await taxUploadDocument(year, file);
        if (!res.ok) errors.push(`${file.name}: ${res.error ?? "upload failed"}`);
        else if (res.created === false) dup += 1;
        else ok += 1;
      } catch (e) {
        errors.push(`${file.name}: ${e instanceof Error ? e.message : "error"}`);
      }
    }
    setBusy(false);
    const parts: string[] = [];
    if (ok) parts.push(`${ok} added`);
    if (dup) parts.push(`${dup} already present`);
    if (errors.length) parts.push(`${errors.length} rejected`);
    setMsg(parts.join(", ") + (errors.length ? ` — ${errors[0]}` : ""));
    if (ok || dup) onUploaded();
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div
      className={dragOver ? "tax-dropzone over" : "tax-dropzone"}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        uploadFiles(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
        multiple
        hidden
        onChange={(e) => uploadFiles(e.target.files)}
      />
      <p className="tax-dropzone-main">
        {busy ? "Uploading…" : "Drop tax documents here, or click to choose"}
      </p>
      <p className="tax-dropzone-hint">
        PDF, PNG, or JPEG — scanned images and digital or flattened PDFs
      </p>
      {msg && <p className="tax-dropzone-msg">{msg}</p>}
    </div>
  );
}
