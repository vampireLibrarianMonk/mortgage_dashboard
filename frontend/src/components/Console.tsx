import { useEffect, useRef, useState } from "react";
import {
  runConsole,
  previewStatement,
  commitStatement,
  type ImportPreview,
} from "../api";

interface Line {
  kind: "input" | "output" | "error";
  text: string;
}

function fmt(n: number): string {
  return `$${n.toFixed(2)}`;
}

// Render an import preview into console scrollback lines.
function previewLines(pv: ImportPreview): Line[] {
  const out: Line[] = [];
  for (const f of pv.files) {
    if (f.error) out.push({ kind: "error", text: `  ${f.filename}: ${f.error}` });
    else out.push({ kind: "output", text: `  ${f.filename}: ${f.count} transaction(s) via ${f.reader}` });
  }
  for (const p of pv.problems) out.push({ kind: "error", text: `  ! ${p}` });
  out.push({ kind: "output", text: "" });
  out.push({ kind: "output", text: `would import ${pv.import_count} transaction(s) on/after ${pv.data_start}:` });
  for (const r of pv.to_import) {
    const tag = r.category === "Ignore" ? "  [offset->Ignore]" : "";
    out.push({ kind: "output", text: `  ${r.date}  ${fmt(r.amount).padStart(11)}  ${r.name.slice(0, 44)}${tag}` });
  }
  if (pv.pre_start_count > 0)
    out.push({ kind: "output", text: `excluding ${pv.pre_start_count} transaction(s) before data start ${pv.data_start} (partial history)` });
  if (pv.reconciled.length > 0) {
    out.push({ kind: "output", text: `reconciling ${pv.reconciled.length} opaque 'PAYPAL PURCHASE' bank row(s) -> Ignore:` });
    for (const m of pv.reconciled)
      out.push({ kind: "output", text: `  ${m.date}  ${fmt(m.amount).padStart(11)}  ${m.name.slice(0, 40)}` });
  }
  return out;
}

const BANNER: Line[] = [
  { kind: "output", text: "mortgage-dashboard console" },
  { kind: "output", text: "user-driven bank sync + categorization. type 'help' for commands." },
  { kind: "output", text: "" },
];

export default function Console() {
  const [lines, setLines] = useState<Line[]>(BANNER);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  // A statement file the user picked, held until they confirm the import.
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function pushLines(newLines: Line[]) {
    setLines((prev) => [...prev, ...newLines]);
  }

  // Step 1: user picked a file -> preview it (writes nothing on the server).
  async function onFilePicked(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file later
    if (!file) return;
    pushLines([{ kind: "input", text: `$ import ${file.name}` }]);
    setBusy(true);
    try {
      const res = await previewStatement(file);
      if (!res.ok || !res.preview) {
        pushLines([{ kind: "error", text: `error: ${res.error ?? "preview failed"}` }]);
        setPendingFile(null);
        return;
      }
      pushLines(previewLines(res.preview));
      if (res.preview.import_count > 0) {
        setPendingFile(file);
        pushLines([{ kind: "output", text: "" }, { kind: "output", text: "review above, then confirm the import below." }]);
      } else {
        setPendingFile(null);
        pushLines([{ kind: "output", text: "nothing to import." }]);
      }
    } catch (err) {
      pushLines([{ kind: "error", text: `error: ${err instanceof Error ? err.message : String(err)}` }]);
      setPendingFile(null);
    } finally {
      setBusy(false);
      setTimeout(focusInput, 0);
    }
  }

  // Step 2: user confirmed -> commit the same file.
  async function confirmImport() {
    if (!pendingFile) return;
    pushLines([{ kind: "input", text: `$ import ${pendingFile.name} --commit` }]);
    setBusy(true);
    try {
      const res = await commitStatement(pendingFile);
      if (!res.ok) {
        pushLines([{ kind: "error", text: `error: ${res.error ?? "commit failed"}` }]);
        return;
      }
      pushLines((res.summary ?? []).map((text) => ({ kind: "output" as const, text: `  ${text}` })));
      pushLines([{ kind: "output", text: "done. run `summary` to refresh Budget vs Actual, `undo` to revert." }]);
    } catch (err) {
      pushLines([{ kind: "error", text: `error: ${err instanceof Error ? err.message : String(err)}` }]);
    } finally {
      setPendingFile(null);
      setBusy(false);
      setTimeout(focusInput, 0);
    }
  }

  function cancelImport() {
    setPendingFile(null);
    pushLines([{ kind: "output", text: "import cancelled." }]);
  }

  // Keep the view pinned to the newest output.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, busy]);

  function focusInput() {
    inputRef.current?.focus();
  }

  async function submit(raw: string) {
    const command = raw.trim();
    // Always echo the prompt line, even for blank input.
    setLines((prev) => [...prev, { kind: "input", text: `$ ${command}` }]);
    if (!command) return;

    // clear resets the scrollback locally without hitting the backend.
    if (command === "clear" || command === "cls") {
      setLines([]);
      return;
    }

    setHistory((prev) => [...prev, command]);
    setHistoryIndex(null);
    setBusy(true);
    try {
      const output = await runConsole(command);
      setLines((prev) => [
        ...prev,
        ...output.map((text) => ({ kind: "output" as const, text })),
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setLines((prev) => [...prev, { kind: "error", text: `error: ${msg}` }]);
    } finally {
      setBusy(false);
      // Re-focus after the async round-trip so the user can keep typing.
      setTimeout(focusInput, 0);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (busy) return;
      const current = input;
      setInput("");
      void submit(current);
      return;
    }

    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (history.length === 0) return;
      const next = historyIndex === null ? history.length - 1 : Math.max(0, historyIndex - 1);
      setHistoryIndex(next);
      setInput(history[next]);
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (history.length === 0 || historyIndex === null) return;
      const next = historyIndex + 1;
      if (next >= history.length) {
        setHistoryIndex(null);
        setInput("");
      } else {
        setHistoryIndex(next);
        setInput(history[next]);
      }
      return;
    }
  }

  return (
    <div className="console" onClick={focusInput}>
      <div className="console-scrollback" ref={scrollRef}>
        {lines.map((line, i) => (
          <div key={i} className={`console-line console-${line.kind}`}>
            {line.text === "" ? "\u00a0" : line.text}
          </div>
        ))}
        {busy && <div className="console-line console-output">working...</div>}
      </div>

      {pendingFile ? (
        <div className="console-confirmbar" onClick={(e) => e.stopPropagation()}>
          <span className="console-confirm-label">Import {pendingFile.name}?</span>
          <button className="console-btn console-btn-primary" disabled={busy} onClick={confirmImport}>
            Confirm import
          </button>
          <button className="console-btn" disabled={busy} onClick={cancelImport}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="console-toolbar" onClick={(e) => e.stopPropagation()}>
          <button
            className="console-btn"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            title="Upload a PayPal statement .zip or .pdf to preview and import"
          >
            Import statement...
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".zip,.pdf,.csv"
            style={{ display: "none" }}
            onChange={onFilePicked}
          />
        </div>
      )}

      <div className="console-inputline">
        <span className="console-prompt">$</span>
        <input
          ref={inputRef}
          className="console-input"
          type="text"
          value={input}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          autoComplete="off"
          disabled={busy}
          placeholder={busy ? "" : "type a command, 'help' for the list"}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
      </div>
    </div>
  );
}
