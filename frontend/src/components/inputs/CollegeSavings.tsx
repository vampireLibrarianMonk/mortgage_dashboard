import type { CollegeSavings } from "../../types";
import NumberInput from "./NumberInput";

interface Props {
  data: CollegeSavings;
  onChange: (field: string, value: unknown) => void;
}

export default function CollegeSavingsSection({ data, onChange }: Props) {
  return (
    <fieldset>
      <legend>Kids College Savings</legend>
      <NumberInput label="529 Contribution (annual/child)" value={data.contribution_annual_per_child} onChange={(v) => onChange("contribution_annual_per_child", v)} suffix="$/yr" />
      <NumberInput label="Number of Children" value={data.number_of_children} onChange={(v) => onChange("number_of_children", Math.max(0, Math.round(v)))} step="1" />
    </fieldset>
  );
}
