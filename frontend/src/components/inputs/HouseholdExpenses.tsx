import type { HouseholdExpenses } from "../../types";
import type { MakeMD } from "../../App";
import NumberInput from "./NumberInput";

interface Props {
  data: HouseholdExpenses;
  onChange: (field: string, value: unknown) => void;
  makeMD: MakeMD;
}

export default function HouseholdExpensesSection({ data, onChange, makeMD }: Props) {
  return (
    <fieldset>
      <legend>Household Expenses</legend>
      <NumberInput label="Groceries (weekly)" value={data.groceries_weekly} onChange={(v) => onChange("groceries_weekly", v)} suffix="$/wk" {...makeMD("household.groceries_weekly", "M")} />
      <NumberInput label="Property Expenses (monthly)" value={data.property_expenses_monthly} onChange={(v) => onChange("property_expenses_monthly", v)} suffix="$/mo" {...makeMD("household.property_expenses_monthly", "M")} />
    </fieldset>
  );
}
