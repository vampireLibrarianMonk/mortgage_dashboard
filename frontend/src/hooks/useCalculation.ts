import { useReducer, useCallback, useRef, useEffect, useState } from "react";
import type { CalculateRequest, CalculateResponse } from "../types";
import { calculateMortgage } from "../api";

const initialState: CalculateRequest = {
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
    hov_monthly: 0,
  },
  college_savings: {
    contribution_annual_per_child: 0,
    number_of_children: 0,
  },
  additional_expenses: [],
  take_home_pay: [],
  extra_principal: {
    recurring: null,
    escalating: null,
    lump_sums: [],
  },
};

type Action =
  | { type: "SET_FIELD"; section: keyof CalculateRequest; field: string; value: unknown }
  | { type: "SET_SECTION"; section: keyof CalculateRequest; value: unknown }
  | { type: "LOAD"; data: CalculateRequest }
  | { type: "RESET" };

function reducer(state: CalculateRequest, action: Action): CalculateRequest {
  switch (action.type) {
    case "SET_FIELD":
      return {
        ...state,
        [action.section]: {
          ...(state[action.section] as object),
          [action.field]: action.value,
        },
      };
    case "SET_SECTION":
      return { ...state, [action.section]: action.value };
    case "LOAD":
      return action.data;
    case "RESET":
      return initialState;
    default:
      return state;
  }
}

export function useCalculation() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [result, setResult] = useState<CalculateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const calculate = useCallback(async (req: CalculateRequest) => {
    setLoading(true);
    setError(null);
    try {
      const res = await calculateMortgage(req);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Calculation failed");
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounced auto-calculate on state change
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => calculate(state), 500);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [state, calculate]);

  return { state, dispatch, result, loading, error };
}
