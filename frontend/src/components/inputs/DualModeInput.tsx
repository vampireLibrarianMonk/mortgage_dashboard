import { useState } from "react";
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
  // Track the last synced `value` prop to detect external changes (profile load).
  const [lastValue, setLastValue] = useState(value);

  // Adjust state during render (React's recommended prop-sync pattern) rather
  // than in an effect, so the display refreshes when `value` changes externally
  // without a setState-in-effect round trip or an extra render.
  if (value !== lastValue) {
    setLastValue(value);
    if (parseNumeric(display) !== value) {
      setDisplay(String(value));
    }
  }

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
