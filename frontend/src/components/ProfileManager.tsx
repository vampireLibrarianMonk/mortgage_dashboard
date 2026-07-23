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
    daycare_weekly: 0,
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
  college_savings: {
    contribution_annual_per_child: 0,
    number_of_children: 0,
  },
  additional_expenses: [],
  take_home_pay: [],
  extra_principal: {
    recurring: null,
    lump_sums: [],
  },
};

/** Deep merge loaded profile data with defaults to handle schema migrations */
function migrateProfile(data: Record<string, unknown>): CalculateRequest {
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
