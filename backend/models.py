from pydantic import BaseModel, Field
from enum import Enum


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
    daycare_weekly: float = Field(ge=0, default=0)
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


class CollegeSavings(BaseModel):
    contribution_annual_per_child: float = Field(ge=0, default=0)
    number_of_children: int = Field(ge=0, default=0)


class ExpenseRow(BaseModel):
    name: str
    amount: float = Field(ge=0)
    frequency: str = Field(pattern="^(monthly|annual)$")


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
    amount: float = Field(gt=0)
    frequency: ExtraPrincipalFrequency = ExtraPrincipalFrequency.monthly
    start_year: int
    end_year: int | None = None  # None means "until payoff"


class LumpSumPayment(BaseModel):
    year: int
    amount: float = Field(gt=0)


class ExtraPrincipal(BaseModel):
    recurring: RecurringExtraPrincipal | None = None
    lump_sums: list[LumpSumPayment] = []


class CalculateRequest(BaseModel):
    house_purchase: HousePurchase
    loan_terms: LoanTerms
    tax_and_cost: TaxAndCost = TaxAndCost()
    household_expenses: HouseholdExpenses = HouseholdExpenses()
    utilities: Utilities = Utilities()
    vehicle_expenses: VehicleExpenses = VehicleExpenses()
    college_savings: CollegeSavings = CollegeSavings()
    additional_expenses: list[ExpenseRow] = []
    take_home_pay: list[IncomeRow] = []
    extra_principal: ExtraPrincipal = ExtraPrincipal()


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
    college_monthly: float
    additional_expenses_monthly: float

    # Affordability
    planned_monthly_housing_total: float
    take_home_pay_monthly: float
    monthly_leftover: float

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
