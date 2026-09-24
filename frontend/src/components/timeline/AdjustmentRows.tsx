import type { Adjustment, AmountUnit } from "../../types";
import { newAdjustment } from "./constants";

interface Props {
  adjustments: Adjustment[];
  onChange: (adjustments: Adjustment[]) => void;
}

/**
 * Flat adjustments that span the whole horizon: a positive amount is money
 * saved/freed each period (+save), a negative amount is a new recurring
 * expense (-spend). No dates, no escalation — just a steady net shift applied
 * to the "adjusted" runway line.
 */
export default function AdjustmentRows({ adjustments, onChange }: Props) {
  const update = (i: number, patch: Partial<Adjustment>) =>
    onChange(adjustments.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  const remove = (i: number) => onChange(adjustments.filter((_, idx) => idx !== i));
  const add = () => onChange([...adjustments, newAdjustment()]);

  return (
    <fieldset className="tl-adjustments">
      <legend>Adjustments (steady +save / −spend)</legend>
      <p className="section-hint">
        A steady monthly or yearly shift applied to the adjusted runway line.
        Enter a positive amount to add savings, a negative amount for a new cost.
      </p>
      {adjustments.length === 0 && (
        <p className="tl-empty">No adjustments yet.</p>
      )}
      {adjustments.map((row, i) => (
        <div key={i} className="tl-adj-row">
          <input
            className="tl-adj-label"
            placeholder="Label (e.g. raise, subscription)"
            value={row.label}
            onChange={(e) => update(i, { label: e.target.value })}
          />
          <input
            className="tl-adj-amount"
            type="number"
            placeholder="Amount"
            value={row.amount}
            onChange={(e) => update(i, { amount: Number(e.target.value) })}
          />
          <span className={row.amount >= 0 ? "tl-sign tl-save" : "tl-sign tl-spend"}>
            {row.amount >= 0 ? "+save" : "−spend"}
          </span>
          <select
            value={row.unit}
            onChange={(e) => update(i, { unit: e.target.value as AmountUnit })}
          >
            <option value="month">/mo</option>
            <option value="year">/yr</option>
          </select>
          <button type="button" className="tl-remove" onClick={() => remove(i)}>
            ×
          </button>
        </div>
      ))}
      <button type="button" className="tl-add" onClick={add}>
        + Add adjustment
      </button>
    </fieldset>
  );
}
