import type { TaxAndCost } from "../../types";
import type { MakeMD } from "../../App";
import DualModeInput from "./DualModeInput";
import NumberInput from "./NumberInput";

interface Props {
  data: TaxAndCost;
  onChange: (field: string, value: unknown) => void;
  makeMD: MakeMD;
}

export default function TaxAndCostSection({ data, onChange, makeMD }: Props) {
  return (
    <fieldset>
      <legend>Annual Tax &amp; Cost</legend>
      <DualModeInput
        label="Property Tax"
        value={data.property_tax_value}
        mode={data.property_tax_mode}
        onValueChange={(v) => onChange("property_tax_value", v)}
        onModeChange={(m) => onChange("property_tax_mode", m)}
      />
      <NumberInput label="Home Insurance (annual)" value={data.home_insurance_annual} onChange={(v) => onChange("home_insurance_annual", v)} suffix="$/yr" />
      <NumberInput label="PMI (monthly)" value={data.pmi_monthly} onChange={(v) => onChange("pmi_monthly", v)} suffix="$/mo" />
      <NumberInput label="HOA (monthly)" value={data.hoa_monthly} onChange={(v) => onChange("hoa_monthly", v)} suffix="$/mo" />
      <NumberInput label="Other Home Costs (annual)" value={data.other_home_costs_annual} onChange={(v) => onChange("other_home_costs_annual", v)} suffix="$/yr" {...makeMD("tax_and_cost.other_home_costs_annual", "M")} />
    </fieldset>
  );
}
