import { useEffect, useRef, useState } from "react";
import { runConsole } from "../api";

interface Line {
  kind: "input" | "output" | "error";
  text: string;
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

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
