import { useState } from "react";
import type { ExpenseRow } from "../../types";

interface Props {
  data: ExpenseRow[];
  onChange: (rows: ExpenseRow[]) => void;
}

function parseNumeric(raw: string): number {
  const num = parseFloat(raw.replace(/,/g, ""));
  return isNaN(num) ? 0 : num;
}

export default function AdditionalExpenses({ data, onChange }: Props) {
  const [name, setName] = useState("");
  const [amountStr, setAmountStr] = useState("0");
  const [frequency, setFrequency] = useState<"monthly" | "annual">("monthly");

  const add = () => {
    const amount = parseNumeric(amountStr);
    if (!name || amount <= 0) return;
    onChange([...data, { name, amount, frequency }]);
    setName("");
    setAmountStr("0");
  };

  const remove = (i: number) => onChange(data.filter((_, idx) => idx !== i));

  return (
    <fieldset>
      <legend>Additional Expenses</legend>
      {data.map((row, i) => (
        <div key={i} className="log-row">
          <span>{row.name}: ${row.amount.toLocaleString()}/{row.frequency === "monthly" ? "mo" : "yr"}</span>
          <button type="button" onClick={() => remove(i)}>×</button>
        </div>
      ))}
      <div className="log-add">
        <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <input
          type="text"
          inputMode="decimal"
          placeholder="Amount"
          value={amountStr}
          onChange={(e) => setAmountStr(e.target.value.replace(/,/g, "").replace(/^0+(?=\d)/, ""))}
        />
        <select value={frequency} onChange={(e) => setFrequency(e.target.value as "monthly" | "annual")}>
          <option value="monthly">Monthly</option>
          <option value="annual">Annual</option>
        </select>
        <button type="button" onClick={add}>Add</button>
      </div>
    </fieldset>
  );
}
