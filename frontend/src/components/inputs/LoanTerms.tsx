import type { LoanTerms } from "../../types";
import NumberInput from "./NumberInput";

interface Props {
  data: LoanTerms;
  onChange: (field: string, value: unknown) => void;
}

export default function LoanTermsSection({ data, onChange }: Props) {
  return (
    <fieldset>
      <legend>Loan Terms</legend>
      <NumberInput label="Loan Term" value={data.loan_term_years} onChange={(v) => onChange("loan_term_years", v)} suffix="years" />
      <NumberInput label="Interest Rate" value={data.annual_interest_rate} onChange={(v) => onChange("annual_interest_rate", v)} suffix="%" />
      <div className="field-row">
        <label>Start Month</label>
        <select value={data.start_month} onChange={(e) => onChange("start_month", parseInt(e.target.value))}>
          {Array.from({ length: 12 }, (_, i) => (
            <option key={i + 1} value={i + 1}>
              {new Date(2000, i).toLocaleString("default", { month: "long" })}
            </option>
          ))}
        </select>
      </div>
      <NumberInput label="Start Year" value={data.start_year} onChange={(v) => onChange("start_year", v)} step="1" />
    </fieldset>
  );
}
