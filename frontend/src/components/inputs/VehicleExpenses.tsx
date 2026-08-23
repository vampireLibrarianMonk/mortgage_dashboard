import type { VehicleExpenses } from "../../types";
import NumberInput from "./NumberInput";

interface Props {
  data: VehicleExpenses;
  onChange: (field: string, value: unknown) => void;
}

export default function VehicleExpensesSection({ data, onChange }: Props) {
  return (
    <fieldset>
      <legend>Vehicle Expenses</legend>
      <NumberInput label="Car Tax (annual)" value={data.car_tax_annual} onChange={(v) => onChange("car_tax_annual", v)} suffix="$/yr" />
      <NumberInput label="Gasoline (weekly)" value={data.gasoline_weekly} onChange={(v) => onChange("gasoline_weekly", v)} suffix="$/wk" />
      <NumberInput label="Car Maintenance (annual)" value={data.car_maintenance_annual} onChange={(v) => onChange("car_maintenance_annual", v)} suffix="$/yr" />
      <NumberInput label="Car Insurance (monthly)" value={data.car_insurance_monthly} onChange={(v) => onChange("car_insurance_monthly", v)} suffix="$/mo" />
      <NumberInput label="HOV / Tolls (monthly)" value={data.hov_monthly} onChange={(v) => onChange("hov_monthly", v)} suffix="$/mo" />
    </fieldset>
  );
}
