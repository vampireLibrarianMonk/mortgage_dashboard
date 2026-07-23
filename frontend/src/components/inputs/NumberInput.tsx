import { useState, useEffect } from "react";

interface Props {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: string;
  suffix?: string;
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

export default function NumberInput({ label, value, onChange, min = 0, max, suffix }: Props) {
  const [display, setDisplay] = useState(String(value));

  // Sync display when value changes externally (e.g. profile load)
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
    </div>
  );
}
