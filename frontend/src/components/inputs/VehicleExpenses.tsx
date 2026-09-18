import type { VehicleExpenses } from "../../types";
import type { MakeMD } from "../../App";
import NumberInput from "./NumberInput";

interface Props {
  data: VehicleExpenses;
  onChange: (field: string, value: unknown) => void;
  makeMD: MakeMD;
}

export default function VehicleExpensesSection({ data, onChange, makeMD }: Props) {
  return (
    <fieldset>
      <legend>Vehicle Expenses</legend>
      <NumberInput label="Car Tax (annual)" value={data.car_tax_annual} onChange={(v) => onChange("car_tax_annual", v)} suffix="$/yr" {...makeMD("vehicle.car_tax_annual", "M")} />
      <NumberInput label="Gasoline (weekly)" value={data.gasoline_weekly} onChange={(v) => onChange("gasoline_weekly", v)} suffix="$/wk" {...makeMD("vehicle.gasoline_weekly", "M")} />
      <NumberInput label="Car Maintenance (annual)" value={data.car_maintenance_annual} onChange={(v) => onChange("car_maintenance_annual", v)} suffix="$/yr" {...makeMD("vehicle.car_maintenance_annual", "M")} />
      <NumberInput label="Car Insurance (monthly)" value={data.car_insurance_monthly} onChange={(v) => onChange("car_insurance_monthly", v)} suffix="$/mo" {...makeMD("vehicle.car_insurance_monthly", "M")} />
    </fieldset>
  );
}
