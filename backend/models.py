from enum import Enum

from pydantic import BaseModel, Field


class InputMode(str, Enum):
    percent = "percent"
    dollars = "dollars"


class PurchaseMode(str, Enum):
    new_purchase = "new_purchase"
    existing_mortgage = "existing_mortgage"


class HousePurchase(BaseModel):
    purchase_mode: PurchaseMode = PurchaseMode.new_purchase
    # New purchase fields
    home_price: float = Field(ge=0, default=0)
    down_payment_value: float = Field(ge=0, default=20)
    down_payment_mode: InputMode = InputMode.percent
    closing_costs_value: float = Field(ge=0, default=3)
    closing_costs_mode: InputMode = InputMode.percent
    closing_costs_financed: bool = True
    earnest_money_value: float = Field(ge=0, default=0)
    earnest_money_mode: InputMode = InputMode.percent
    # Existing mortgage field
    outstanding_balance: float = Field(ge=0, default=300000)
    current_home_value: float = Field(ge=0, default=0)
    assessment_lookup_url: str = ""


class LoanTerms(BaseModel):
    loan_term_years: int = Field(gt=0, le=50)
    annual_interest_rate: float = Field(ge=0, le=100)
    start_month: int = Field(ge=1, le=12)
    start_year: int = Field(ge=2000, le=2100)


class TaxAndCost(BaseModel):
    property_tax_value: float = Field(ge=0, default=0)
    property_tax_mode: InputMode = InputMode.percent
    home_insurance_annual: float = Field(ge=0, default=0)
    pmi_monthly: float = Field(ge=0, default=0)
    hoa_monthly: float = Field(ge=0, default=0)
    other_home_costs_annual: float = Field(ge=0, default=0)


class HouseholdExpenses(BaseModel):
    groceries_weekly: float = Field(ge=0, default=0)
    property_expenses_monthly: float = Field(ge=0, default=0)


class Utilities(BaseModel):
    cable_internet_monthly: float = Field(ge=0, default=0)
    cellular_monthly: float = Field(ge=0, default=0)
    electricity_monthly: float = Field(ge=0, default=0)
    gas_monthly: float = Field(ge=0, default=0)
    water_monthly: float = Field(ge=0, default=0)


class VehicleExpenses(BaseModel):
    car_tax_annual: float = Field(ge=0, default=0)
    gasoline_weekly: float = Field(ge=0, default=0)
    car_maintenance_annual: float = Field(ge=0, default=0)
    car_insurance_monthly: float = Field(ge=0, default=0)


class ChildCare(BaseModel):
    # College savings keeps the per-child model: contribution x number_of_children.
    contribution_annual_per_child: float = Field(ge=0, default=0)
    number_of_children: int = Field(ge=0, default=0)
    food_monthly: float = Field(ge=0, default=0)
    daycare_weekly: float = Field(ge=0, default=0)  # billed weekly
    babysitter_monthly: float = Field(ge=0, default=0)
    toiletries_monthly: float = Field(ge=0, default=0)  # diapers, etc.
    hov_monthly: float = Field(ge=0, default=0)  # HOV/toll lanes, primarily for the children


class PetCare(BaseModel):
    food_monthly: float = Field(ge=0, default=0)
    vet_annual: float = Field(ge=0, default=0)
    grooming_monthly: float = Field(ge=0, default=0)


class ExpenseRow(BaseModel):
    name: str
    amount: float = Field(ge=0)
    frequency: str = Field(pattern="^(monthly|annual)$")
    classification: str = Field(pattern="^[MD]$", default="M")  # M=mandatory, D=discretionary


class DiscretionaryRow(BaseModel):
    name: str
    amount: float = Field(ge=0)
    frequency: str = Field(pattern="^(weekly|monthly|annual)$")
    classification: str = Field(pattern="^[MD]$", default="D")


class IncomeRow(BaseModel):
    name: str
    amount: float = Field(gt=0)
    frequency: str = Field(pattern="^(monthly|annual)$")


class ExtraPrincipalFrequency(str, Enum):
    monthly = "monthly"
    quarterly = "quarterly"
    semi_annual = "semi_annual"
    annual = "annual"


class RecurringExtraPrincipal(BaseModel):
    # ge=0 (not gt=0): while the user edits the amount it can pass through 0/empty,
    # and a 0 amount should simply contribute nothing rather than 422-ing the whole
    # /calculate request (which froze the results). The engine guards with
    # min(amount, balance), so 0 is a safe no-op.
    amount: float = Field(ge=0, default=0)
    frequency: ExtraPrincipalFrequency = ExtraPrincipalFrequency.monthly
    start_year: int
    end_year: int | None = None  # None means "until payoff"


class LumpSumPayment(BaseModel):
    year: int
    amount: float = Field(gt=0)


class EscalatingExtraPrincipal(BaseModel):
    """A monthly extra-principal payment that increases by a fixed amount once per year."""
    # ge=0 (not gt=0): same reasoning as RecurringExtraPrincipal.amount — a 0/empty
    # intermediate while editing must not invalidate the whole request; the engine
    # treats 0 as no payment.
    start_amount: float = Field(ge=0, default=0)  # initial monthly extra payment
    annual_increase: float = Field(ge=0, default=0)  # added to the monthly amount each anniversary year
    start_year: int
    end_year: int | None = None  # None means "until payoff"


class ExtraPrincipal(BaseModel):
    recurring: RecurringExtraPrincipal | None = None
    escalating: EscalatingExtraPrincipal | None = None
    lump_sums: list[LumpSumPayment] = []


# --- Timeline Builder (see new_spec/timeline_builder.md) ----------------------
# A generic, forward-looking planner. Timelines are labeled recurring costs (some
# of which are purchases with a funding method); adjustments are flat offsets that
# apply across the whole horizon (+ = money saved/freed, - = new expense). The
# projection is a monthly-leftover "runway" over `horizon_years`. It is decoupled
# from the live budget except for the single opt-in starting-leftover number.

class AmountUnit(str, Enum):
    month = "month"
    year = "year"


class EscalationUnit(str, Enum):
    percent = "percent"  # base *= (1 + value/100) each start-anniversary year
    dollar = "dollar"    # base += value each start-anniversary year


class PurchaseMethod(str, Enum):
    pay_in_full = "pay_in_full"      # full amount draws the account on start
    payment_plan = "payment_plan"    # down draws account; financed -> monthly for term
    already_paid = "already_paid"    # excluded from the projection (recorded only)


class Purchase(BaseModel):
    amount: float = Field(ge=0, default=0)
    method: PurchaseMethod = PurchaseMethod.pay_in_full
    down_payment: float = Field(ge=0, default=0)     # payment_plan only
    apr: float = Field(ge=0, default=0)              # annual %, financed remainder
    term_months: int = Field(ge=0, default=0)        # payment_plan only
    account: str | None = None                       # earmark: "<bank>:<mask>" or "other"


class Timeline(BaseModel):
    label: str = ""
    category: str = "Generic"          # a budget category name or "Generic"
    start: str                         # "YYYY-MM"
    end: str | None = None             # "YYYY-MM"; None = ongoing (to horizon)
    # Signed recurring amount at `unit` cadence. Positive = a cost (reduces the
    # runway); negative = income/savings (bolsters the runway). Applied only
    # within [start, end], so a negative base is a time-boxed budget boost.
    base: float = Field(default=0)
    unit: AmountUnit = AmountUnit.month
    escalation_value: float = Field(ge=0, default=0)  # per-year increase; 0 = flat
    escalation_unit: EscalationUnit = EscalationUnit.percent
    purchase: Purchase | None = None   # present when this timeline is a purchase


class Adjustment(BaseModel):
    label: str = ""
    amount: float = 0                  # + = saved/freed, - = new expense
    unit: AmountUnit = AmountUnit.month


class TimelineSettings(BaseModel):
    starting_leftover: float = 0       # runway start line
    carry_over_leftover: bool = False  # if true, filled from Dashboard monthly_leftover
    horizon_years: int = Field(ge=1, le=50, default=10)


class TimelinePlan(BaseModel):
    """The whole Timeline Builder state (persists on the profile)."""
    settings: TimelineSettings = TimelineSettings()
    timelines: list[Timeline] = []
    adjustments: list[Adjustment] = []


class TimelineScenario(BaseModel):
    """A named timeline plan the user tabs between. The active scenario's plan is
    mirrored into CalculateRequest.timeline_plan, which the projection reads."""
    name: str = "Base"
    plan: TimelinePlan = TimelinePlan()


class CalculateRequest(BaseModel):
    house_purchase: HousePurchase
    loan_terms: LoanTerms
    tax_and_cost: TaxAndCost = TaxAndCost()
    household_expenses: HouseholdExpenses = HouseholdExpenses()
    utilities: Utilities = Utilities()
    vehicle_expenses: VehicleExpenses = VehicleExpenses()
    child_care: ChildCare = ChildCare()
    pet_care: PetCare = PetCare()
    additional_expenses: list[ExpenseRow] = []
    discretionary: list[DiscretionaryRow] = []
    take_home_pay: list[IncomeRow] = []
    extra_principal: ExtraPrincipal = ExtraPrincipal()
    # Per-line Mandatory/Discretionary overrides, keyed by canonical line key
    # (e.g. "vehicle.car_insurance_monthly", "child_care.hov_monthly"). Values
    # are "M" or "D". Missing keys fall back to the built-in defaults in
    # calculations.py. List rows carry their own classification field instead.
    classifications: dict[str, str] = {}
    # Timeline Builder state (optional; drives the forward-looking runway projection).
    # timeline_plan is the ACTIVE scenario's plan — the projection reads it directly.
    timeline_plan: TimelinePlan = TimelinePlan()
    # Named scenarios the user tabs between (per-profile). timeline_plan mirrors
    # timeline_scenarios[active_scenario].plan; these persist but don't affect the
    # projection (which uses timeline_plan). Optional for back-compat.
    timeline_scenarios: list[TimelineScenario] = []
    active_scenario: int = 0


class CalculateResponse(BaseModel):
    # Purchase & Loan
    down_payment_amount: float
    closing_costs_amount: float
    earnest_money_amount: float
    loan_amount: float
    required_monthly_pi: float  # P&I only
    required_monthly_payment: float  # P&I + escrow (tax, insurance, PMI, HOA)
    first_month_interest: float
    first_month_principal: float

    # Planned outflow
    planned_mortgage_outflow_monthly: float

    # Payoff
    standard_payoff_date: str
    accelerated_payoff_date: str | None = None
    months_saved: int = 0

    # Lifetime
    total_mortgage_payments: float
    total_interest: float
    total_interest_with_extra: float | None = None
    interest_savings: float = 0

    # Monthly category totals
    tax_and_cost_monthly: float
    household_monthly: float
    utilities_monthly: float
    vehicle_monthly: float
    child_care_monthly: float
    pet_care_monthly: float
    additional_expenses_monthly: float
    discretionary_monthly: float

    # Affordability
    planned_monthly_housing_total: float
    take_home_pay_monthly: float
    monthly_leftover: float

    # Mandatory vs Discretionary split (per-line, across all sections)
    mandatory_monthly: float = 0
    discretionary_total_monthly: float = 0

    # Cash to close
    prepaids_escrow_low: float
    prepaids_escrow_high: float
    cash_to_close_low: float
    cash_to_close_high: float

    # Extra principal detail
    scheduled_extra_principal_monthly: float = 0
    lump_sum_total: float = 0

    # Amortization schedule (for chart)
    amortization_schedule: list[dict] = []

    # Timeline Builder projection (for the Timeline tab). Same delivery convention
    # as amortization_schedule: a list of per-period points the frontend charts.
    # Each point: {period "YYYY-MM", year, timeline_cost, adjustment, runway_raw,
    # runway_adjusted, one_time}. Plus a small summary the UI reads for warnings.
    timeline_projection: list[dict] = []
    timeline_summary: dict = {}
    # Per funded account: {"key","label","points":[{period,balance}], "as_of"}.
    timeline_accounts: list[dict] = []
