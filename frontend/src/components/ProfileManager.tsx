import { useState, useEffect, useCallback } from "react";
import type { CalculateRequest } from "../types";
import { saveProfile, listProfiles, loadProfile, deleteProfile, type ProfileSummary } from "../api";

const defaults: CalculateRequest = {
  house_purchase: {
    purchase_mode: "new_purchase",
    home_price: 0,
    down_payment_value: 0,
    down_payment_mode: "percent",
    closing_costs_value: 0,
    closing_costs_mode: "percent",
    closing_costs_financed: true,
    earnest_money_value: 0,
    earnest_money_mode: "percent",
    outstanding_balance: 0,
    current_home_value: 0,
    assessment_lookup_url: "",
  },
  loan_terms: {
    loan_term_years: 30,
    annual_interest_rate: 0,
    start_month: 1,
    start_year: 2026,
  },
  tax_and_cost: {
    property_tax_value: 0,
    property_tax_mode: "percent",
    home_insurance_annual: 0,
    pmi_monthly: 0,
    hoa_monthly: 0,
    other_home_costs_annual: 0,
  },
  household_expenses: {
    groceries_weekly: 0,
    property_expenses_monthly: 0,
  },
  utilities: {
    cable_internet_monthly: 0,
    cellular_monthly: 0,
    electricity_monthly: 0,
    gas_monthly: 0,
    water_monthly: 0,
  },
  vehicle_expenses: {
    car_tax_annual: 0,
    gasoline_weekly: 0,
    car_maintenance_annual: 0,
    car_insurance_monthly: 0,
  },
  child_care: {
    contribution_annual_per_child: 0,
    number_of_children: 0,
    food_monthly: 0,
    daycare_weekly: 0,
    babysitter_monthly: 0,
    toiletries_monthly: 0,
    hov_monthly: 0,
  },
  pet_care: {
    food_monthly: 0,
    vet_annual: 0,
    grooming_monthly: 0,
  },
  additional_expenses: [],
  discretionary: [
    { name: "Eating Out", amount: 0, frequency: "monthly", classification: "D" },
    { name: "Movies", amount: 0, frequency: "monthly", classification: "D" },
    { name: "Vacations", amount: 0, frequency: "annual", classification: "D" },
  ],
  take_home_pay: [],
  extra_principal: {
    recurring: null,
    escalating: null,
    lump_sums: [],
  },
  classifications: {},
};

/**
 * Translate pre-restructure profiles into the current shape before the generic
 * merge runs. Older profiles stored `college_savings` and a `daycare_weekly`
 * field inside `household_expenses`; both now live under `child_care`. We map
 * the known values across and let the generic merge fill the rest from defaults.
 */
function normalizeLegacyShape(data: Record<string, unknown>): Record<string, unknown> {
  const out = { ...data };
  const legacyCollege = data.college_savings as Record<string, unknown> | undefined;
  const legacyHousehold = data.household_expenses as Record<string, unknown> | undefined;
  const legacyVehicle = data.vehicle_expenses as Record<string, unknown> | undefined;
  const existingChild = data.child_care as Record<string, unknown> | undefined;

  // HOV moved from vehicle_expenses into child_care. Pull the legacy value
  // (from either an existing child_care block or the old vehicle block).
  const legacyHov = Number(existingChild?.hov_monthly ?? legacyVehicle?.hov_monthly ?? 0);

  // Build/repair the child_care block from whatever the profile has.
  // Pre-restructure profiles had college_savings + household_expenses.daycare_weekly;
  // pre-HOV-move profiles had vehicle_expenses.hov_monthly. Either way, land the
  // values under child_care with sensible defaults for anything absent.
  const needsChild =
    existingChild === undefined ||
    legacyCollege !== undefined ||
    legacyHousehold?.daycare_weekly !== undefined ||
    legacyVehicle?.hov_monthly !== undefined;

  if (needsChild) {
    out.child_care = {
      contribution_annual_per_child: Number(existingChild?.contribution_annual_per_child ?? legacyCollege?.contribution_annual_per_child ?? 0),
      number_of_children: Number(existingChild?.number_of_children ?? legacyCollege?.number_of_children ?? 0),
      food_monthly: Number(existingChild?.food_monthly ?? 0),
      daycare_weekly: Number(existingChild?.daycare_weekly ?? legacyHousehold?.daycare_weekly ?? 0),
      babysitter_monthly: Number(existingChild?.babysitter_monthly ?? 0),
      toiletries_monthly: Number(existingChild?.toiletries_monthly ?? 0),
      hov_monthly: legacyHov,
    };
  }

  // Strip a stray hov_monthly from vehicle_expenses so it does not linger.
  if (legacyVehicle && "hov_monthly" in legacyVehicle) {
    const v = { ...legacyVehicle };
    delete v.hov_monthly;
    out.vehicle_expenses = v;
  }

  // Ensure list rows carry a classification (older profiles predate the flag).
  const withClass = (rows: unknown, fallback: "M" | "D") =>
    Array.isArray(rows)
      ? rows.map((r) => ({ ...(r as object), classification: (r as Record<string, unknown>).classification ?? fallback }))
      : rows;
  if (data.additional_expenses !== undefined) out.additional_expenses = withClass(data.additional_expenses, "M");
  if (data.discretionary !== undefined) out.discretionary = withClass(data.discretionary, "D");

  return out;
}

/** Deep merge loaded profile data with defaults to handle schema migrations */
function migrateProfile(raw: Record<string, unknown>): CalculateRequest {
  const data = normalizeLegacyShape(raw);
  const result = { ...defaults };
  for (const key of Object.keys(defaults) as (keyof CalculateRequest)[]) {
    if (data[key] !== undefined) {
      if (Array.isArray(defaults[key])) {
        (result as Record<string, unknown>)[key] = data[key];
      } else if (typeof defaults[key] === "object" && defaults[key] !== null) {
        (result as Record<string, unknown>)[key] = { ...(defaults[key] as object), ...(data[key] as object) };
      } else {
        (result as Record<string, unknown>)[key] = data[key];
      }
    }
  }
  return result;
}

interface Props {
  currentState: CalculateRequest;
  onLoad: (data: CalculateRequest) => void;
  onAddressChange: (address: string) => void;
}

export default function ProfileManager({ currentState, onLoad, onAddressChange }: Props) {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [address, setAddressRaw] = useState("");
  const setAddress = (value: string) => {
    setAddressRaw(value);
    onAddressChange(value);
  };
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showList, setShowList] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const list = await listProfiles();
      setProfiles(list);
    } catch {
      // API may not be running yet
    }
  }, []);

  // Load the saved-profiles list once on mount. `refresh` setStates only after
  // an awaited API call (async callback), not synchronously in the effect body,
  // so it does not cause cascading renders; the rule can't see through the await.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { refresh(); }, [refresh]);

  const handleSave = async () => {
    if (!address.trim()) return;
    const profile = await saveProfile(address.trim(), currentState);
    setActiveId(profile.id);
    await refresh();
  };

  const handleLoad = async (id: string) => {
    const profile = await loadProfile(id);
    setAddress(profile.address);
    setActiveId(id);
    onLoad(migrateProfile(profile.data as unknown as Record<string, unknown>));
    setShowList(false);
  };

  const handleDelete = async (id: string) => {
    await deleteProfile(id);
    if (activeId === id) {
      setActiveId(null);
      setAddress("");
    }
    await refresh();
  };

  return (
    <div className="profile-bar">
      <div className="profile-input-row">
        <input
          type="text"
          placeholder="Street address (e.g. 123 Main St)"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          className="profile-address"
        />
        <button type="button" onClick={handleSave} disabled={!address.trim()}>
          Save
        </button>
        <button type="button" onClick={() => setShowList(!showList)}>
          {showList ? "Hide" : "Load"} ({profiles.length})
        </button>
      </div>
      {showList && profiles.length > 0 && (
        <div className="profile-list">
          {profiles.map((p) => (
            <div key={p.id} className={`profile-item ${p.id === activeId ? "profile-active" : ""}`}>
              <button type="button" className="profile-name" onClick={() => handleLoad(p.id)}>
                {p.address}
              </button>
              <span className="profile-date">{new Date(p.updated_at).toLocaleDateString()}</span>
              <button type="button" className="profile-delete" onClick={() => handleDelete(p.id)}>×</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
