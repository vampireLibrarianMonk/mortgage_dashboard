import type { HousePurchase } from "../../types";
import DualModeInput from "./DualModeInput";
import NumberInput from "./NumberInput";

interface Props {
  data: HousePurchase;
  onChange: (field: string, value: unknown) => void;
}

export default function HousePurchaseSection({ data, onChange }: Props) {
  const isNew = data.purchase_mode === "new_purchase";

  return (
    <fieldset>
      <legend>House Purchase Essentials</legend>
      <div className="tab-bar">
        <button
          className={`tab ${isNew ? "tab-active" : ""}`}
          onClick={() => onChange("purchase_mode", "new_purchase")}
          type="button"
        >
          New Purchase
        </button>
        <button
          className={`tab ${!isNew ? "tab-active" : ""}`}
          onClick={() => onChange("purchase_mode", "existing_mortgage")}
          type="button"
        >
          Existing Mortgage
        </button>
      </div>

      {isNew ? (
        <div className="tab-content">
          <NumberInput label="Home Price" value={data.home_price} onChange={(v) => onChange("home_price", v)} suffix="$" />
          <DualModeInput
            label="Down Payment"
            value={data.down_payment_value}
            mode={data.down_payment_mode}
            onValueChange={(v) => onChange("down_payment_value", v)}
            onModeChange={(m) => onChange("down_payment_mode", m)}
          />
          <DualModeInput
            label="Closing Costs"
            value={data.closing_costs_value}
            mode={data.closing_costs_mode}
            onValueChange={(v) => onChange("closing_costs_value", v)}
            onModeChange={(m) => onChange("closing_costs_mode", m)}
          />
          <div className="field-row">
            <label>Finance Closing Costs</label>
            <input
              type="checkbox"
              checked={data.closing_costs_financed}
              onChange={(e) => onChange("closing_costs_financed", e.target.checked)}
            />
          </div>
          <DualModeInput
            label="Earnest Money"
            value={data.earnest_money_value}
            mode={data.earnest_money_mode}
            onValueChange={(v) => onChange("earnest_money_value", v)}
            onModeChange={(m) => onChange("earnest_money_mode", m)}
          />
        </div>
      ) : (
        <div className="tab-content">
          <NumberInput
            label="Outstanding Balance"
            value={data.outstanding_balance}
            onChange={(v) => onChange("outstanding_balance", v)}
            suffix="$"
          />
          <NumberInput
            label="Assessed Home Value (for tax)"
            value={data.current_home_value}
            onChange={(v) => onChange("current_home_value", v)}
            suffix="$"
          />
          <div className="field-row">
            <label>Assessment Lookup URL</label>
            <input
              type="text"
              placeholder="Paste your county assessment link"
              value={data.assessment_lookup_url}
              onChange={(e) => onChange("assessment_lookup_url", e.target.value)}
              className="link-field"
            />
          </div>
          {data.assessment_lookup_url && (
            <div className="field-row">
              <a
                href={data.assessment_lookup_url}
                target="_blank"
                rel="noopener noreferrer"
                className="help-link"
              >
                Open assessment lookup →
              </a>
            </div>
          )}
        </div>
      )}
    </fieldset>
  );
}
