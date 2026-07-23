from datetime import date
from models import (
    CalculateRequest,
    CalculateResponse,
    InputMode,
    ExtraPrincipalFrequency,
    PurchaseMode,
)


def _resolve_value(value: float, mode: InputMode, base: float) -> float:
    if mode == InputMode.percent:
        return base * (value / 100.0)
    return value


def _monthly_payment(principal: float, monthly_rate: float, num_payments: int) -> float:
    if monthly_rate == 0:
        return principal / num_payments
    return principal * (monthly_rate * (1 + monthly_rate) ** num_payments) / (
        (1 + monthly_rate) ** num_payments - 1
    )


def _weekly_to_monthly(weekly: float) -> float:
    return weekly * 52 / 12


def _annual_to_monthly(annual: float) -> float:
    return annual / 12


def _extra_principal_monthly_equivalent(req: CalculateRequest) -> float:
    ep = req.extra_principal
    if ep.recurring is None:
        return 0.0
    amount = ep.recurring.amount
    if ep.recurring.frequency == ExtraPrincipalFrequency.monthly:
        return amount
    elif ep.recurring.frequency == ExtraPrincipalFrequency.quarterly:
        return amount / 3
    elif ep.recurring.frequency == ExtraPrincipalFrequency.semi_annual:
        return amount / 6
    else:  # annual
        return amount / 12


def _payments_per_year(freq: ExtraPrincipalFrequency) -> int:
    return {"monthly": 12, "quarterly": 4, "semi_annual": 2, "annual": 1}[freq.value]


def _simulate_amortization(
    principal: float,
    monthly_rate: float,
    num_payments: int,
    required_payment: float,
    req: CalculateRequest,
    start_month: int,
    start_year: int,
) -> tuple[str, float, int]:
    """Returns (payoff_date, total_interest, total_payments_count)."""
    balance = principal
    total_interest = 0.0
    month_idx = 0
    ep = req.extra_principal

    while balance > 0 and month_idx < num_payments * 2:
        current_month = ((start_month - 1 + month_idx) % 12) + 1
        current_year = start_year + (start_month - 1 + month_idx) // 12

        interest = balance * monthly_rate
        total_interest += interest
        principal_portion = min(required_payment - interest, balance)
        balance -= principal_portion

        # Recurring extra principal
        if ep.recurring and ep.recurring.start_year <= current_year:
            # end_year=None means "until payoff"
            if ep.recurring.end_year is None or current_year <= ep.recurring.end_year:
                freq = ep.recurring.frequency
                apply = False
                if freq == ExtraPrincipalFrequency.monthly:
                    apply = True
                elif freq == ExtraPrincipalFrequency.quarterly:
                    apply = month_idx % 3 == 0
                elif freq == ExtraPrincipalFrequency.semi_annual:
                    apply = month_idx % 6 == 0
                elif freq == ExtraPrincipalFrequency.annual:
                    apply = current_month == start_month
                if apply:
                    extra = min(ep.recurring.amount, balance)
                    balance -= extra

        # Lump sums (applied in January of the specified year)
        for ls in ep.lump_sums:
            if current_year == ls.year and current_month == 1:
                lump = min(ls.amount, balance)
                balance -= lump

        month_idx += 1
        if balance <= 0.01:
            balance = 0
            break

    payoff_month = ((start_month - 1 + month_idx - 1) % 12) + 1
    payoff_year = start_year + (start_month - 1 + month_idx - 1) // 12
    payoff_date = f"{payoff_year}-{payoff_month:02d}"
    return payoff_date, total_interest, month_idx


def _generate_amortization_schedule(
    principal: float,
    monthly_rate: float,
    num_payments: int,
    required_payment: float,
    req: CalculateRequest,
    start_month: int,
    start_year: int,
) -> list[dict]:
    """Generate yearly amortization schedule for charting."""
    if principal <= 0 or required_payment <= 0:
        return []

    schedule = []
    balance = principal
    cumulative_interest = 0.0
    cumulative_principal = 0.0
    month_idx = 0
    ep = req.extra_principal

    # Track yearly aggregates
    year_interest = 0.0
    year_principal = 0.0

    while balance > 0 and month_idx < num_payments * 2:
        current_month = ((start_month - 1 + month_idx) % 12) + 1
        current_year = start_year + (start_month - 1 + month_idx) // 12

        interest = balance * monthly_rate
        principal_portion = min(required_payment - interest, balance)
        extra_applied = 0.0

        balance -= principal_portion

        # Recurring extra principal
        if ep.recurring and ep.recurring.start_year <= current_year:
            if ep.recurring.end_year is None or current_year <= ep.recurring.end_year:
                freq = ep.recurring.frequency
                apply = False
                if freq == ExtraPrincipalFrequency.monthly:
                    apply = True
                elif freq == ExtraPrincipalFrequency.quarterly:
                    apply = month_idx % 3 == 0
                elif freq == ExtraPrincipalFrequency.semi_annual:
                    apply = month_idx % 6 == 0
                elif freq == ExtraPrincipalFrequency.annual:
                    apply = current_month == start_month
                if apply:
                    extra = min(ep.recurring.amount, balance)
                    balance -= extra
                    extra_applied += extra

        # Lump sums
        for ls in ep.lump_sums:
            if current_year == ls.year and current_month == 1:
                lump = min(ls.amount, balance)
                balance -= lump
                extra_applied += lump

        cumulative_interest += interest
        cumulative_principal += principal_portion + extra_applied
        year_interest += interest
        year_principal += principal_portion + extra_applied

        month_idx += 1

        # Emit a data point at year boundaries or loan end
        is_year_end = month_idx < num_payments * 2 and ((start_month - 1 + month_idx) % 12) + 1 == start_month
        is_loan_end = balance <= 0.01

        if is_year_end or is_loan_end:
            schedule.append({
                "year": current_year,
                "principal": round(year_principal, 0),
                "interest": round(year_interest, 0),
                "balance": round(max(balance, 0), 0),
                "cumulative_interest": round(cumulative_interest, 0),
                "cumulative_principal": round(cumulative_principal, 0),
            })
            year_interest = 0.0
            year_principal = 0.0

        if is_loan_end:
            balance = 0
            break

    return schedule


def calculate(req: CalculateRequest) -> CalculateResponse:
    hp = req.house_purchase
    lt = req.loan_terms
    tc = req.tax_and_cost

    # Determine loan amount based on purchase mode
    if hp.purchase_mode == PurchaseMode.existing_mortgage:
        # Existing mortgage: user provides outstanding balance directly
        down_payment_amount = 0.0
        closing_costs_amount = 0.0
        earnest_money_amount = 0.0
        loan_amount = hp.outstanding_balance
    else:
        # New purchase: calculate from home price
        down_payment_amount = _resolve_value(hp.down_payment_value, hp.down_payment_mode, hp.home_price)
        closing_costs_amount = _resolve_value(hp.closing_costs_value, hp.closing_costs_mode, hp.home_price)
        earnest_money_amount = _resolve_value(hp.earnest_money_value, hp.earnest_money_mode, hp.home_price)
        loan_amount = hp.home_price - down_payment_amount
        if hp.closing_costs_financed:
            loan_amount += closing_costs_amount

    # Monthly payment
    monthly_rate = (lt.annual_interest_rate / 100.0) / 12
    num_payments = lt.loan_term_years * 12
    required_monthly = _monthly_payment(loan_amount, monthly_rate, num_payments)

    # First month breakdown
    first_month_interest = loan_amount * monthly_rate
    first_month_principal = required_monthly - first_month_interest

    # Standard amortization (no extra principal)
    standard_total_interest = required_monthly * num_payments - loan_amount
    standard_payoff_month = ((lt.start_month - 1 + num_payments - 1) % 12) + 1
    standard_payoff_year = lt.start_year + (lt.start_month - 1 + num_payments - 1) // 12
    standard_payoff_date = f"{standard_payoff_year}-{standard_payoff_month:02d}"

    # Accelerated amortization
    has_extra = req.extra_principal.recurring is not None or len(req.extra_principal.lump_sums) > 0
    if has_extra:
        accel_payoff_date, accel_interest, accel_months = _simulate_amortization(
            loan_amount, monthly_rate, num_payments, required_monthly, req, lt.start_month, lt.start_year
        )
        months_saved = num_payments - accel_months
        interest_savings = standard_total_interest - accel_interest
    else:
        accel_payoff_date = None
        accel_interest = standard_total_interest
        accel_months = num_payments
        months_saved = 0
        interest_savings = 0

    # Extra principal monthly equivalent
    extra_monthly = _extra_principal_monthly_equivalent(req)
    lump_sum_total = sum(ls.amount for ls in req.extra_principal.lump_sums)

    # Tax & cost monthly
    # Use current_home_value for property tax base in existing mortgage mode
    tax_base = hp.current_home_value if hp.purchase_mode == PurchaseMode.existing_mortgage else hp.home_price
    property_tax_monthly = _resolve_value(tc.property_tax_value, tc.property_tax_mode, tax_base) / 12 if tc.property_tax_mode == InputMode.percent else tc.property_tax_value / 12
    tax_and_cost_monthly = (
        property_tax_monthly
        + _annual_to_monthly(tc.home_insurance_annual)
        + tc.pmi_monthly
        + tc.hoa_monthly
        + _annual_to_monthly(tc.other_home_costs_annual)
    )

    # Household monthly
    he = req.household_expenses
    household_monthly = (
        _weekly_to_monthly(he.daycare_weekly)
        + _weekly_to_monthly(he.groceries_weekly)
        + he.property_expenses_monthly
    )

    # Utilities monthly
    ut = req.utilities
    utilities_monthly = (
        ut.cable_internet_monthly
        + ut.cellular_monthly
        + ut.electricity_monthly
        + ut.gas_monthly
        + ut.water_monthly
    )

    # Vehicle monthly
    ve = req.vehicle_expenses
    vehicle_monthly = (
        _annual_to_monthly(ve.car_tax_annual)
        + _weekly_to_monthly(ve.gasoline_weekly)
        + _annual_to_monthly(ve.car_maintenance_annual)
        + ve.car_insurance_monthly
    )

    # College monthly
    cs = req.college_savings
    college_monthly = _annual_to_monthly(cs.contribution_annual_per_child * cs.number_of_children)

    # Additional expenses monthly
    additional_monthly = sum(
        row.amount if row.frequency == "monthly" else _annual_to_monthly(row.amount)
        for row in req.additional_expenses
    )

    # Required monthly with escrow (what the lender bills)
    # Escrow = property tax + insurance + PMI + HOA
    escrow_monthly = property_tax_monthly + _annual_to_monthly(tc.home_insurance_annual) + tc.pmi_monthly + tc.hoa_monthly
    required_monthly_with_escrow = required_monthly + escrow_monthly

    # Planned mortgage outflow = required with escrow + extra principal
    planned_mortgage_outflow = required_monthly_with_escrow + extra_monthly

    # Planned monthly housing total (all categories)
    planned_monthly_housing_total = (
        planned_mortgage_outflow
        + _annual_to_monthly(tc.other_home_costs_annual)
        + household_monthly
        + utilities_monthly
        + vehicle_monthly
        + college_monthly
        + additional_monthly
    )

    # Take home pay monthly
    take_home_monthly = sum(
        row.amount if row.frequency == "monthly" else _annual_to_monthly(row.amount)
        for row in req.take_home_pay
    )

    monthly_leftover = take_home_monthly - planned_monthly_housing_total

    # Cash to close (only relevant for new purchase)
    if hp.purchase_mode == PurchaseMode.existing_mortgage:
        prepaids_low = 0.0
        prepaids_high = 0.0
        cash_to_close_low = 0.0
        cash_to_close_high = 0.0
    else:
        prepaids_low = hp.home_price * 0.02
        prepaids_high = hp.home_price * 0.04
        cash_closing_costs = 0 if hp.closing_costs_financed else closing_costs_amount
        cash_to_close_low = down_payment_amount + cash_closing_costs + prepaids_low - earnest_money_amount
        cash_to_close_high = down_payment_amount + cash_closing_costs + prepaids_high - earnest_money_amount

    return CalculateResponse(
        down_payment_amount=round(down_payment_amount, 2),
        closing_costs_amount=round(closing_costs_amount, 2),
        earnest_money_amount=round(earnest_money_amount, 2),
        loan_amount=round(loan_amount, 2),
        required_monthly_pi=round(required_monthly, 2),
        required_monthly_payment=round(required_monthly_with_escrow, 2),
        first_month_interest=round(first_month_interest, 2),
        first_month_principal=round(first_month_principal, 2),
        planned_mortgage_outflow_monthly=round(planned_mortgage_outflow, 2),
        standard_payoff_date=standard_payoff_date,
        accelerated_payoff_date=accel_payoff_date,
        months_saved=months_saved,
        total_mortgage_payments=round(required_monthly * num_payments, 2),
        total_interest=round(standard_total_interest, 2),
        total_interest_with_extra=round(accel_interest, 2) if has_extra else None,
        interest_savings=round(interest_savings, 2),
        tax_and_cost_monthly=round(tax_and_cost_monthly, 2),
        household_monthly=round(household_monthly, 2),
        utilities_monthly=round(utilities_monthly, 2),
        vehicle_monthly=round(vehicle_monthly, 2),
        college_monthly=round(college_monthly, 2),
        additional_expenses_monthly=round(additional_monthly, 2),
        planned_monthly_housing_total=round(planned_monthly_housing_total, 2),
        take_home_pay_monthly=round(take_home_monthly, 2),
        monthly_leftover=round(monthly_leftover, 2),
        prepaids_escrow_low=round(prepaids_low, 2),
        prepaids_escrow_high=round(prepaids_high, 2),
        cash_to_close_low=round(cash_to_close_low, 2),
        cash_to_close_high=round(cash_to_close_high, 2),
        scheduled_extra_principal_monthly=round(extra_monthly, 2),
        lump_sum_total=round(lump_sum_total, 2),
        amortization_schedule=_generate_amortization_schedule(
            loan_amount, monthly_rate, num_payments, required_monthly, req, lt.start_month, lt.start_year
        ),
    )
