import type { PetCare } from "../../types";
import type { MakeMD } from "../../App";
import NumberInput from "./NumberInput";

interface Props {
  data: PetCare;
  onChange: (field: string, value: unknown) => void;
  makeMD: MakeMD;
}

export default function PetCareSection({ data, onChange, makeMD }: Props) {
  return (
    <fieldset>
      <legend>Pet Care</legend>
      <NumberInput label="Food (monthly)" value={data.food_monthly} onChange={(v) => onChange("food_monthly", v)} suffix="$/mo" {...makeMD("pet_care.food_monthly", "M")} />
      <NumberInput label="Vet (annual)" value={data.vet_annual} onChange={(v) => onChange("vet_annual", v)} suffix="$/yr" {...makeMD("pet_care.vet_annual", "M")} />
      <NumberInput label="Grooming (monthly)" value={data.grooming_monthly} onChange={(v) => onChange("grooming_monthly", v)} suffix="$/mo" {...makeMD("pet_care.grooming_monthly", "D")} />
    </fieldset>
  );
}
