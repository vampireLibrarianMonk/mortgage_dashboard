import type { Classification } from "../../types";

interface Props {
  value: Classification;
  onChange: (v: Classification) => void;
}

/**
 * Compact Mandatory/Discretionary toggle. Click to flip between M and D.
 * Rendered inline next to an expense input.
 */
export default function MDToggle({ value, onChange }: Props) {
  return (
    <button
      type="button"
      className={`md-toggle md-${value.toLowerCase()}`}
      title={value === "M" ? "Mandatory (click to mark Discretionary)" : "Discretionary (click to mark Mandatory)"}
      aria-label={value === "M" ? "Mandatory" : "Discretionary"}
      onClick={() => onChange(value === "M" ? "D" : "M")}
    >
      {value}
    </button>
  );
}
