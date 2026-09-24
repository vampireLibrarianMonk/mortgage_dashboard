import type { Adjustment, Purchase, Timeline } from "../../types";

// Budget categories mirror the backend actuals categories, plus a catch-all.
export const TIMELINE_CATEGORIES = [
  "Mortgage",
  "Household",
  "Utilities",
  "Vehicle",
  "ChildCare",
  "PetCare",
  "Discretionary",
  "Generic",
] as const;

// Current month as "YYYY-MM" for sensible new-row defaults.
export function currentYearMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function newTimeline(): Timeline {
  return {
    label: "",
    category: "Generic",
    start: currentYearMonth(),
    end: null,
    base: 0,
    unit: "month",
    escalation_value: 0,
    escalation_unit: "percent",
    purchase: null,
  };
}

export function newPurchase(): Purchase {
  return {
    amount: 0,
    method: "pay_in_full",
    down_payment: 0,
    apr: 0,
    term_months: 12,
    account: null,
  };
}

export function newAdjustment(): Adjustment {
  return { label: "", amount: 0, unit: "month" };
}
