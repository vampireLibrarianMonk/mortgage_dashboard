import type { ChildCare } from "../../types";
import type { MakeMD } from "../../App";
import NumberInput from "./NumberInput";

interface Props {
  data: ChildCare;
  onChange: (field: string, value: unknown) => void;
  makeMD: MakeMD;
}

export default function ChildCareSection({ data, onChange, makeMD }: Props) {
  return (
    <fieldset>
      <legend>Child Care</legend>
      <NumberInput label="529 Contribution (annual/child)" value={data.contribution_annual_per_child} onChange={(v) => onChange("contribution_annual_per_child", v)} suffix="$/yr" {...makeMD("child_care.college", "D")} />
      <NumberInput label="Number of Children" value={data.number_of_children} onChange={(v) => onChange("number_of_children", Math.max(0, Math.round(v)))} step="1" />
      <NumberInput label="Food (monthly)" value={data.food_monthly} onChange={(v) => onChange("food_monthly", v)} suffix="$/mo" {...makeMD("child_care.food_monthly", "M")} />
      <NumberInput label="Daycare (weekly)" value={data.daycare_weekly} onChange={(v) => onChange("daycare_weekly", v)} suffix="$/wk" {...makeMD("child_care.daycare_weekly", "M")} />
      <NumberInput label="Babysitter (monthly)" value={data.babysitter_monthly} onChange={(v) => onChange("babysitter_monthly", v)} suffix="$/mo" {...makeMD("child_care.babysitter_monthly", "D")} />
      <NumberInput label="Toiletries (monthly)" value={data.toiletries_monthly} onChange={(v) => onChange("toiletries_monthly", v)} suffix="$/mo" {...makeMD("child_care.toiletries_monthly", "M")} />
      <NumberInput label="HOV / Tolls (monthly)" value={data.hov_monthly} onChange={(v) => onChange("hov_monthly", v)} suffix="$/mo" {...makeMD("child_care.hov_monthly", "D")} />
    </fieldset>
  );
}
