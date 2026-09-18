import { useState } from "react";
import type { Classification } from "../../types";
import MDToggle from "./MDToggle";

interface Props {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: string;
  suffix?: string;
  // When provided, renders an inline Mandatory/Discretionary toggle.
  classification?: Classification;
  onClassificationChange?: (v: Classification) => void;
}

function parseNumeric(raw: string): number {
  // Strip commas, then parse
  const cleaned = raw.replace(/,/g, "");
  const num = parseFloat(cleaned);
  return isNaN(num) ? 0 : num;
}

function formatDisplay(raw: string): string {
  // Remove commas (allow user to paste them, we just strip)
  let cleaned = raw.replace(/,/g, "");
  // Remove leading zeros except for "0." decimal case
  if (cleaned.length > 1 && cleaned.startsWith("0") && cleaned[1] !== ".") {
    cleaned = cleaned.replace(/^0+/, "") || "0";
  }
  return cleaned;
}

export default function NumberInput({ label, value, onChange, min = 0, max, suffix, classification, onClassificationChange }: Props) {
  const [display, setDisplay] = useState(String(value));
  // Track the last `value` prop we synced from so we can detect an external
  // change (e.g. a profile load) and refresh the editable display string.
  const [lastValue, setLastValue] = useState(value);

  // Adjust state during render instead of in an effect: when the incoming prop
  // differs from what we last saw AND from what the user is currently editing,
  // reset the display to the new value. This is React's recommended pattern for
  // syncing state to a prop, and avoids a setState-in-effect round trip.
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
    if (min !== undefined && num < min) return;
    if (max !== undefined && num > max) return;
    onChange(num);
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
      {suffix && <span className="suffix">{suffix}</span>}
      {classification && onClassificationChange && (
        <MDToggle value={classification} onChange={onClassificationChange} />
      )}
    </div>
  );
}
