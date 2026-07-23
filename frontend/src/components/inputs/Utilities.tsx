import type { Utilities } from "../../types";
import NumberInput from "./NumberInput";

interface Props {
  data: Utilities;
  onChange: (field: string, value: unknown) => void;
}

export default function UtilitiesSection({ data, onChange }: Props) {
  return (
    <fieldset>
      <legend>Utilities</legend>
      <NumberInput label="Cable / Internet" value={data.cable_internet_monthly} onChange={(v) => onChange("cable_internet_monthly", v)} suffix="$/mo" />
      <NumberInput label="Cellular" value={data.cellular_monthly} onChange={(v) => onChange("cellular_monthly", v)} suffix="$/mo" />
      <NumberInput label="Electricity" value={data.electricity_monthly} onChange={(v) => onChange("electricity_monthly", v)} suffix="$/mo" />
      <NumberInput label="Gas" value={data.gas_monthly} onChange={(v) => onChange("gas_monthly", v)} suffix="$/mo" />
      <NumberInput label="Consolidated Water" value={data.water_monthly} onChange={(v) => onChange("water_monthly", v)} suffix="$/mo" />
    </fieldset>
  );
}
