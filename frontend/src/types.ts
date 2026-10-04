export type InputMode = "percent" | "dollars";
export type ExtraPrincipalFrequency = "monthly" | "quarterly" | "semi_annual" | "annual";

// Mandatory or Discretionary flag applied per line item.
export type Classification = "M" | "D";

export type PurchaseMode = "new_purchase" | "existing_mortgage";

export interface HousePurchase {
  purchase_mode: PurchaseMode;
  // New purchase fields
  home_price: number;
  down_payment_value: number;
  down_payment_mode: InputMode;
  closing_costs_value: number;
  closing_costs_mode: InputMode;
  closing_costs_financed: boolean;
  earnest_money_value: number;
  earnest_money_mode: InputMode;
  // Existing mortgage fields
  outstanding_balance: number;
  current_home_value: number;
  assessment_lookup_url: string;
}

export interface LoanTerms {
  loan_term_years: number;
  annual_interest_rate: number;
  start_month: number;
  start_year: number;
}

export interface TaxAndCost {
  property_tax_value: number;
  property_tax_mode: InputMode;
  home_insurance_annual: number;
  pmi_monthly: number;
  hoa_monthly: number;
  other_home_costs_annual: number;
}

export interface HouseholdExpenses {
  groceries_weekly: number;
  property_expenses_monthly: number;
}

export interface Utilities {
  cable_internet_monthly: number;
  cellular_monthly: number;
  electricity_monthly: number;
  gas_monthly: number;
  water_monthly: number;
}

export interface VehicleExpenses {
  car_tax_annual: number;
  gasoline_weekly: number;
  car_maintenance_annual: number;
  car_insurance_monthly: number;
}

export interface ChildCare {
  contribution_annual_per_child: number;
  number_of_children: number;
  food_monthly: number;
  daycare_weekly: number;
  babysitter_monthly: number;
  toiletries_monthly: number;
  hov_monthly: number;
}

export interface PetCare {
  food_monthly: number;
  vet_annual: number;
  grooming_monthly: number;
}

export interface ExpenseRow {
  name: string;
  amount: number;
  frequency: "monthly" | "annual";
  classification: Classification;
}

export interface IncomeRow {
  name: string;
  amount: number;
  frequency: "monthly" | "annual";
}

export interface DiscretionaryRow {
  name: string;
  amount: number;
  frequency: "weekly" | "monthly" | "annual";
  classification: Classification;
}

export interface RecurringExtraPrincipal {
  amount: number;
  frequency: ExtraPrincipalFrequency;
  start_year: number;
  end_year: number | null; // null means "until payoff"
}

export interface LumpSumPayment {
  year: number;
  amount: number;
}

export interface EscalatingExtraPrincipal {
  start_amount: number; // initial monthly extra payment
  annual_increase: number; // added to the monthly amount each anniversary year
  start_year: number;
  end_year: number | null; // null means "until payoff"
}

export interface ExtraPrincipal {
  recurring: RecurringExtraPrincipal | null;
  escalating: EscalatingExtraPrincipal | null;
  lump_sums: LumpSumPayment[];
}

// --- Timeline Builder (see new_spec/timeline_builder.md) ---

export type AmountUnit = "month" | "year";
export type EscalationUnit = "percent" | "dollar";
export type PurchaseMethod = "pay_in_full" | "payment_plan" | "already_paid";

export interface Purchase {
  amount: number;
  method: PurchaseMethod;
  down_payment: number;
  apr: number;
  term_months: number;
  account: string | null; // "<bank>:<mask>" or "other"
}

export interface Timeline {
  label: string;
  category: string; // budget category or "Generic"
  start: string; // "YYYY-MM"
  end: string | null; // null = ongoing
  base: number;
  unit: AmountUnit;
  escalation_value: number;
  escalation_unit: EscalationUnit;
  purchase: Purchase | null;
}

export interface Adjustment {
  label: string;
  amount: number; // + = saved/freed, - = new expense
  unit: AmountUnit;
}

export interface TimelineSettings {
  starting_leftover: number;
  carry_over_leftover: boolean;
  horizon_years: number;
}

export interface TimelinePlan {
  settings: TimelineSettings;
  timelines: Timeline[];
  adjustments: Adjustment[];
}

// A named timeline plan ("scenario") the user can switch between via tabs. Each
// saved profile/address carries its own set. The active scenario's plan is
// mirrored into CalculateRequest.timeline_plan so the backend projection (which
// reads timeline_plan) is unchanged.
export interface TimelineScenario {
  name: string;
  plan: TimelinePlan;
}

export interface TimelineProjectionPoint {
  period: string; // "YYYY-MM"
  year: number;
  timeline_cost: number;
  adjustment: number;
  runway_raw: number;
  runway_adjusted: number;
  one_time: number;
}

export interface TimelineAccountSeries {
  key: string;
  label: string;
  as_of: string | null;
  points: { period: string; balance: number }[];
}

// A contiguous stretch of months where the adjusted runway is negative.
export interface NegativeWindow {
  start: string; // "YYYY-MM"
  end: string; // "YYYY-MM"
  months: number;
  shortfall: number; // total deficit over the stretch (<= 0)
  deepest: number; // worst single month
  deepest_period: string;
  mid_period: string; // middle month (for centered chart labels)
}

export interface CalculateRequest {
  house_purchase: HousePurchase;
  loan_terms: LoanTerms;
  tax_and_cost: TaxAndCost;
  household_expenses: HouseholdExpenses;
  utilities: Utilities;
  vehicle_expenses: VehicleExpenses;
  child_care: ChildCare;
  pet_care: PetCare;
  additional_expenses: ExpenseRow[];
  discretionary: DiscretionaryRow[];
  take_home_pay: IncomeRow[];
  extra_principal: ExtraPrincipal;
  // Per-line M/D overrides for fixed-field sections, keyed by canonical line
  // key (e.g. "vehicle.car_insurance_monthly"). Missing keys use backend defaults.
  classifications: Record<string, Classification>;
  // The active scenario's plan, mirrored here so the backend projection reads it
  // unchanged. Edits go through timeline_scenarios[active_scenario].plan and are
  // mirrored to this field.
  timeline_plan: TimelinePlan;
  // Named scenarios the user switches between (tabs). active_scenario indexes it.
  // Optional for back-compat; old profiles are migrated to a single "Base" scenario.
  timeline_scenarios?: TimelineScenario[];
  active_scenario?: number;
}

export interface CalculateResponse {
  down_payment_amount: number;
  closing_costs_amount: number;
  earnest_money_amount: number;
  loan_amount: number;
  required_monthly_pi: number;
  required_monthly_payment: number;
  first_month_interest: number;
  first_month_principal: number;
  planned_mortgage_outflow_monthly: number;
  standard_payoff_date: string;
  accelerated_payoff_date: string | null;
  months_saved: number;
  total_mortgage_payments: number;
  total_interest: number;
  total_interest_with_extra: number | null;
  interest_savings: number;
  tax_and_cost_monthly: number;
  household_monthly: number;
  utilities_monthly: number;
  vehicle_monthly: number;
  child_care_monthly: number;
  pet_care_monthly: number;
  additional_expenses_monthly: number;
  discretionary_monthly: number;
  mandatory_monthly: number;
  discretionary_total_monthly: number;
  planned_monthly_housing_total: number;
  take_home_pay_monthly: number;
  monthly_leftover: number;
  prepaids_escrow_low: number;
  prepaids_escrow_high: number;
  cash_to_close_low: number;
  cash_to_close_high: number;
  scheduled_extra_principal_monthly: number;
  lump_sum_total: number;
  amortization_schedule: AmortizationPoint[];
  timeline_projection: TimelineProjectionPoint[];
  timeline_summary: {
    first_negative_period?: string | null;
    starting_leftover?: number;
    horizon_years?: number;
    net_adjustment_monthly?: number;
    negative_windows?: NegativeWindow[];
  };
  timeline_accounts: TimelineAccountSeries[];
}

export interface AmortizationPoint {
  year: number;
  principal: number;
  interest: number;
  balance: number;
  cumulative_interest: number;
  cumulative_principal: number;
}

// --- Tax Prep (see new_spec/tax_prep_tab_design.md) ---
// Phase 1 is the document foundation only — no extraction/calc/AI yet.

export type DocKind = "pdf" | "png" | "jpeg";

export type DocStage = "ingested" | "classified" | "extracted" | "verified" | "error";

export type TaxFormType =
  | "unknown"
  | "W-2"
  | "1099-INT"
  | "1099-DIV"
  | "1099-B"
  | "1099-NEC"
  | "1099-MISC"
  | "1099-R"
  | "1098"
  | "1095-C"
  | "3922"
  | "SSA-1099"
  | "K-1"
  | "other";

export interface TaxDocument {
  id: string; // SHA-256 of the original bytes
  tax_year: number;
  original_filename: string;
  kind: DocKind;
  size_bytes: number;
  uploaded_at: string; // iso8601
  stage: DocStage;
  form_type: TaxFormType;
  taxpayer: string | null;
  page_count: number | null;
  note: string;
}

// --- Phase 2: extraction + review ---

export type ExtractionMethod =
  | "acroform"
  | "native_pdf"
  | "local_ocr"
  | "textract"
  | "manual";

export type FactStatus =
  | "extracted"
  | "verified"
  | "corrected"
  | "rejected"
  | "needs_review"
  | "conflict";

// A single extracted value from a document, with provenance. PII (SSN/EIN) is
// already masked by the backend at creation — the frontend never sees raw values.
export interface TaxFact {
  tax_year: number;
  document_id: string;
  form_type: TaxFormType;
  payer_name: string | null;
  payer_tin_masked: string | null;
  taxpayer_name: string | null;
  field_code: string;
  field_label: string;
  value: boolean | string | number | null;
  page: number;
  bbox: [number, number, number, number] | null;
  extraction_method: ExtractionMethod;
  confidence: number; // 0-1
  status: FactStatus;
  extracted_value: boolean | string | number | null;
  verified_value: boolean | string | number | null;
  corrected_by: string | null;
  corrected_at: string | null;
  parser_version: string | null;
}

// --- Phase 3: W-2 ↔ paystub reconciliation ---

export type ReconcileVerdict =
  | "match"
  | "explainable_delta"
  | "mismatch"
  | "w2_only"
  | "paystub_only"
  | "missing";

export interface ReconcileLine {
  key: string;
  label: string;
  w2_value: number | null;
  paystub_value: number | null;
  delta: number | null; // paystub - w2 when both present
  verdict: ReconcileVerdict;
  note: string;
}

export interface PersonReconciliation {
  person: string;
  employer: string | null;
  tax_year: number;
  has_w2: boolean;
  has_paystubs: boolean;
  paystubs_complete: boolean;
  lines: ReconcileLine[];
  summary: string;
}

export interface HouseholdTotals {
  tax_year: number;
  total_wages: number;
  total_fed_withheld: number;
  total_ss_tax: number;
  total_medicare_tax: number;
  total_state_withheld: number;
  people_counted: string[];
  people_missing_w2: string[];
}

export interface HouseholdReconciliation {
  tax_year: number;
  people: PersonReconciliation[];
  totals: HouseholdTotals;
  summary: string;
}
