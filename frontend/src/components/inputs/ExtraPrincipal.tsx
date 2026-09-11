import { useState } from "react";
import type { ExtraPrincipal, ExtraPrincipalFrequency, LumpSumPayment, EscalatingExtraPrincipal } from "../../types";
import NumberInput from "./NumberInput";

interface Props {
  data: ExtraPrincipal;
  onChange: (value: ExtraPrincipal) => void;
}

export default function ExtraPrincipalSection({ data, onChange }: Props) {
  const [lumpYear, setLumpYear] = useState("2028");
  const [lumpAmount, setLumpAmount] = useState("0");

  const setRecurring = (field: string, value: unknown) => {
    const current = data.recurring ?? { amount: 0, frequency: "monthly" as ExtraPrincipalFrequency, start_year: 2026, end_year: null };
    onChange({ ...data, recurring: { ...current, [field]: value } });
  };

  const toggleRecurring = (enabled: boolean) => {
    onChange({
      ...data,
      recurring: enabled ? { amount: 500, frequency: "monthly", start_year: 2026, end_year: null } : null,
    });
  };

  const untilPayoff = data.recurring?.end_year === null;

  const toggleUntilPayoff = (checked: boolean) => {
    if (checked) {
      setRecurring("end_year", null);
    } else {
      setRecurring("end_year", 2056);
    }
  };

  // --- Escalating monthly extra principal ---
  const setEscalating = (field: string, value: unknown) => {
    const current: EscalatingExtraPrincipal =
      data.escalating ?? { start_amount: 0, annual_increase: 0, start_year: 2026, end_year: null };
    onChange({ ...data, escalating: { ...current, [field]: value } });
  };

  const toggleEscalating = (enabled: boolean) => {
    onChange({
      ...data,
      escalating: enabled
        ? { start_amount: 500, annual_increase: 100, start_year: 2026, end_year: null }
        : null,
    });
  };

  const escUntilPayoff = data.escalating?.end_year === null;

  const toggleEscUntilPayoff = (checked: boolean) => {
    if (checked) {
      setEscalating("end_year", null);
    } else {
      setEscalating("end_year", 2056);
    }
  };

  const parseNumeric = (raw: string): number => {
    const num = parseFloat(raw.replace(/,/g, ""));
    return isNaN(num) ? 0 : num;
  };

  const cleanInput = (raw: string): string => {
    return raw.replace(/,/g, "").replace(/^0+(?=\d)/, "");
  };

  const addLumpSum = () => {
    const amount = parseNumeric(lumpAmount);
    const year = parseInt(lumpYear) || 2028;
    if (amount <= 0) return;
    const ls: LumpSumPayment = { year, amount };
    onChange({ ...data, lump_sums: [...data.lump_sums, ls] });
    setLumpAmount("0");
  };

  const removeLumpSum = (i: number) => {
    onChange({ ...data, lump_sums: data.lump_sums.filter((_, idx) => idx !== i) });
  };

  return (
    <fieldset>
      <legend>Extra Principal Payments</legend>
      <div className="field-row">
        <label>Enable Recurring</label>
        <input type="checkbox" checked={data.recurring !== null} onChange={(e) => toggleRecurring(e.target.checked)} />
      </div>
      {data.recurring && (
        <>
          <NumberInput label="Amount" value={data.recurring.amount} onChange={(v) => setRecurring("amount", v)} suffix="$" />
          <div className="field-row">
            <label>Frequency</label>
            <select value={data.recurring.frequency} onChange={(e) => setRecurring("frequency", e.target.value)}>
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="semi_annual">Semi-Annual</option>
              <option value="annual">Annual</option>
            </select>
          </div>
          <NumberInput label="Start Year" value={data.recurring.start_year} onChange={(v) => setRecurring("start_year", v)} step="1" />
          <div className="field-row">
            <label>Until Payoff</label>
            <input type="checkbox" checked={untilPayoff} onChange={(e) => toggleUntilPayoff(e.target.checked)} />
          </div>
          {!untilPayoff && (
            <NumberInput label="End Year" value={data.recurring.end_year ?? 2056} onChange={(v) => setRecurring("end_year", v)} step="1" />
          )}
        </>
      )}
      <h4>Escalating Monthly Payment</h4>
      <div className="field-row">
        <label>Enable Escalating</label>
        <input type="checkbox" checked={data.escalating !== null} onChange={(e) => toggleEscalating(e.target.checked)} />
      </div>
      {data.escalating && (
        <>
          <NumberInput label="Starting Amount (monthly)" value={data.escalating.start_amount} onChange={(v) => setEscalating("start_amount", v)} suffix="$/mo" />
          <NumberInput label="Annual Increase" value={data.escalating.annual_increase} onChange={(v) => setEscalating("annual_increase", v)} suffix="$/yr" />
          <NumberInput label="Start Year" value={data.escalating.start_year} onChange={(v) => setEscalating("start_year", v)} step="1" />
          <div className="field-row">
            <label>Until Payoff</label>
            <input type="checkbox" checked={escUntilPayoff} onChange={(e) => toggleEscUntilPayoff(e.target.checked)} />
          </div>
          {!escUntilPayoff && (
            <NumberInput label="End Year" value={data.escalating.end_year ?? 2056} onChange={(v) => setEscalating("end_year", v)} step="1" />
          )}
        </>
      )}
      <h4>Lump Sum Payments</h4>
      {data.lump_sums.map((ls, i) => (
        <div key={i} className="log-row">
          <span>{ls.year}: ${ls.amount.toLocaleString()}</span>
          <button type="button" onClick={() => removeLumpSum(i)}>×</button>
        </div>
      ))}
      <div className="log-add">
        <input type="text" inputMode="numeric" placeholder="Year" value={lumpYear} onChange={(e) => setLumpYear(cleanInput(e.target.value))} />
        <input type="text" inputMode="decimal" placeholder="Amount" value={lumpAmount} onChange={(e) => setLumpAmount(cleanInput(e.target.value))} />
        <button type="button" onClick={addLumpSum}>Add</button>
      </div>
    </fieldset>
  );
}
