import { useState, useEffect } from "react";
import type { InputMode } from "../../types";

interface Props {
  label: string;
  value: number;
  mode: InputMode;
  onValueChange: (v: number) => void;
  onModeChange: (m: InputMode) => void;
}

function parseNumeric(raw: string): number {
  const cleaned = raw.replace(/,/g, "");
  const num = parseFloat(cleaned);
  return isNaN(num) ? 0 : num;
}

function formatDisplay(raw: string): string {
  let cleaned = raw.replace(/,/g, "");
  if (cleaned.length > 1 && cleaned.startsWith("0") && cleaned[1] !== ".") {
    cleaned = cleaned.replace(/^0+/, "") || "0";
  }
  return cleaned;
}

export default function DualModeInput({ label, value, mode, onValueChange, onModeChange }: Props) {
  const [display, setDisplay] = useState(String(value));

  useEffect(() => {
    const current = parseNumeric(display);
    if (current !== value) {
      setDisplay(String(value));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const handleChange = (raw: string) => {
    const formatted = formatDisplay(raw);
    setDisplay(formatted);
    const num = parseNumeric(formatted);
    if (num < 0) return;
    onValueChange(num);
  };

  return (
    <div className="field-row">
      <label>{label}</label>
      <input
        type="text"
        inputMode="decimal"
        value={display}
        onChange={(e) => handleChange(e.target.value)}
        onBlur={() => setDisplay(String(value))}
      />
      <select value={mode} onChange={(e) => onModeChange(e.target.value as InputMode)}>
        <option value="percent">%</option>
        <option value="dollars">$</option>
      </select>
    </div>
  );
}
