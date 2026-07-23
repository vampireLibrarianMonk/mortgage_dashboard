import type { HouseholdExpenses } from "../../types";
import NumberInput from "./NumberInput";

interface Props {
  data: HouseholdExpenses;
  onChange: (field: string, value: unknown) => void;
}

export default function HouseholdExpensesSection({ data, onChange }: Props) {
  return (
    <fieldset>
      <legend>Household Expenses</legend>
      <NumberInput label="Daycare (weekly)" value={data.daycare_weekly} onChange={(v) => onChange("daycare_weekly", v)} suffix="$/wk" />
      <NumberInput label="Groceries (weekly)" value={data.groceries_weekly} onChange={(v) => onChange("groceries_weekly", v)} suffix="$/wk" />
      <NumberInput label="Property Expenses (monthly)" value={data.property_expenses_monthly} onChange={(v) => onChange("property_expenses_monthly", v)} suffix="$/mo" />
    </fieldset>
  );
}
