from models import (
    CalculateRequest,
    CalculateResponse,
    ExtraPrincipalFrequency,
    InputMode,
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


def _escalating_monthly_amount(req: CalculateRequest, current_year: int) -> float:
    """Monthly escalating extra-principal amount active in current_year (0 if inactive)."""
    esc = req.extra_principal.escalating
    if esc is None:
        return 0.0
    if current_year < esc.start_year:
        return 0.0
    if esc.end_year is not None and current_year > esc.end_year:
        return 0.0
    years_elapsed = current_year - esc.start_year
    return esc.start_amount + esc.annual_increase * years_elapsed


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

        # Escalating monthly extra principal
        esc_amount = _escalating_monthly_amount(req, current_year)
        if esc_amount > 0 and balance > 0:
            esc_pay = min(esc_amount, balance)
            balance -= esc_pay

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

        # Escalating monthly extra principal
        esc_amount = _escalating_monthly_amount(req, current_year)
        if esc_amount > 0 and balance > 0:
            esc_pay = min(esc_amount, balance)
            balance -= esc_pay
            extra_applied += esc_pay

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


# --- Timeline Builder projection (see new_spec/timeline_builder.md) -----------

def _ym_to_index(ym: str) -> int:
    """'YYYY-MM' -> absolute month index (year*12 + (month-1)). Robust to a bare
    'YYYY' (treated as January)."""
    parts = str(ym).split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
    return year * 12 + (month - 1)


def _index_to_ym(idx: int) -> str:
    return f"{idx // 12:04d}-{(idx % 12) + 1:02d}"


def _loan_monthly_payment(principal: float, apr_pct: float, term_months: int) -> float:
    """Standard amortized monthly payment for a financed purchase."""
    if term_months <= 0 or principal <= 0:
        return 0.0
    r = (apr_pct / 100.0) / 12.0
    if r == 0:
        return principal / term_months
    return principal * r / (1 - (1 + r) ** (-term_months))


def _timeline_monthly_cost(tl, month_idx: int) -> tuple[float, float]:
    """(recurring_cost, one_time) a single timeline contributes at `month_idx`.

    recurring: the escalated per-month cost while active (start..end inclusive),
    plus any payment-plan monthly within its term. one_time: a full purchase or a
    down payment landing exactly on the start month.
    """
    start = _ym_to_index(tl.start)
    end = _ym_to_index(tl.end) if tl.end else None
    if month_idx < start or (end is not None and month_idx > end):
        # Even outside the recurring span, a payment-plan can run past `end` and a
        # one-time still only fires at start (handled below). Recurring is 0 here,
        # but payment-plan months may still apply — fall through for the purchase.
        recurring_active = False
    else:
        recurring_active = True

    recurring = 0.0
    one_time = 0.0

    # Base recurring cost, normalized to monthly, escalated by whole years elapsed.
    if recurring_active and tl.base:
        years_elapsed = (month_idx - start) // 12
        base = float(tl.base)
        if tl.escalation_value:
            if str(getattr(tl.escalation_unit, "value", tl.escalation_unit)) == "percent":
                base *= (1 + float(tl.escalation_value) / 100.0) ** years_elapsed
            else:  # dollar
                base += float(tl.escalation_value) * years_elapsed
        recurring += base / 12.0 if str(getattr(tl.unit, "value", tl.unit)) == "year" else base

    # Purchase funding.
    p = tl.purchase
    if p is not None:
        method = str(getattr(p.method, "value", p.method))
        if method == "pay_in_full":
            if month_idx == start:
                one_time += float(p.amount)
        elif method == "payment_plan":
            if month_idx == start and p.down_payment:
                one_time += float(p.down_payment)
            financed = max(0.0, float(p.amount) - float(p.down_payment))
            mp = _loan_monthly_payment(financed, float(p.apr), int(p.term_months))
            if mp and start <= month_idx < start + int(p.term_months):
                recurring += mp
        # already_paid: contributes nothing.

    return round(recurring, 2), round(one_time, 2)


def _adjustment_monthly(plan) -> float:
    """Net of all adjustments normalized to monthly (+ = money freed / saved)."""
    total = 0.0
    for a in plan.adjustments:
        amt = float(a.amount)
        total += amt / 12.0 if str(getattr(a.unit, "value", a.unit)) == "year" else amt
    return total


def _timeline_projection(req: CalculateRequest, monthly_leftover: float,
                         balances: dict | None = None) -> tuple[list[dict], dict, list[dict]]:
    """Build the runway projection from req.timeline_plan.

    Returns (projection_points, summary, accounts). Monthly resolution over the
    horizon starting at the loan's start month. `balances` maps an account key
    ("<bank>:<mask>" or "other") to {"balance","as_of"} for the account-dip lines;
    when absent, account lines start at 0 (still show the draw-downs).
    """
    plan = req.timeline_plan
    if not plan or (not plan.timelines and not plan.adjustments):
        return [], {}, []

    settings = plan.settings
    start_idx = req.loan_terms.start_year * 12 + (req.loan_terms.start_month - 1)
    horizon_months = int(settings.horizon_years) * 12

    starting_leftover = (round(monthly_leftover, 2) if settings.carry_over_leftover
                         else float(settings.starting_leftover))
    adj_monthly = _adjustment_monthly(plan)

    # Account draw-downs: per funded account, the one-time draws by month index.
    balances = balances or {}
    acct_draws: dict[str, dict] = {}   # key -> {month_idx: draw_amount}
    for tl in plan.timelines:
        p = tl.purchase
        if p is None or p.account is None:
            continue
        method = str(getattr(p.method, "value", p.method))
        s = _ym_to_index(tl.start)
        draw = 0.0
        if method == "pay_in_full":
            draw = float(p.amount)
        elif method == "payment_plan":
            draw = float(p.down_payment)
        if draw > 0:
            acct_draws.setdefault(p.account, {}).setdefault(s, 0.0)
            acct_draws[p.account][s] += draw

    projection: list[dict] = []
    first_negative = None
    for m in range(horizon_months + 1):
        idx = start_idx + m
        cost = 0.0
        one_time = 0.0
        for tl in plan.timelines:
            rec, ot = _timeline_monthly_cost(tl, idx)
            cost += rec
            one_time += ot
        runway_raw = round(starting_leftover - cost - one_time, 2)
        runway_adjusted = round(runway_raw + adj_monthly, 2)
        if first_negative is None and runway_adjusted < 0:
            first_negative = _index_to_ym(idx)
        projection.append({
            "period": _index_to_ym(idx),
            "year": idx // 12,
            "timeline_cost": round(cost, 2),
            "adjustment": round(adj_monthly, 2),
            "one_time": round(one_time, 2),
            "runway_raw": runway_raw,
            "runway_adjusted": runway_adjusted,
        })

    # Account-dip series: start at latest snapshot balance (or 0), step down on draws.
    accounts: list[dict] = []
    for key, draws in acct_draws.items():
        snap = balances.get(key) or {}
        bal = float(snap.get("balance", 0.0) or 0.0)
        as_of = snap.get("as_of")
        pts = []
        for m in range(horizon_months + 1):
            idx = start_idx + m
            if idx in draws:
                bal -= draws[idx]
            pts.append({"period": _index_to_ym(idx), "balance": round(bal, 2)})
        accounts.append({"key": key, "label": key, "as_of": as_of, "points": pts})

    summary = {
        "first_negative_period": first_negative,
        "starting_leftover": round(starting_leftover, 2),
        "horizon_years": int(settings.horizon_years),
        "net_adjustment_monthly": round(adj_monthly, 2),
    }
    return projection, summary, accounts


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
    has_extra = (
        req.extra_principal.recurring is not None
        or req.extra_principal.escalating is not None
        or len(req.extra_principal.lump_sums) > 0
    )
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
    # Recurring flat portion + the escalating payment's starting monthly amount
    extra_monthly = _extra_principal_monthly_equivalent(req)
    if req.extra_principal.escalating is not None:
        extra_monthly += req.extra_principal.escalating.start_amount
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
        _weekly_to_monthly(he.groceries_weekly)
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

    # Vehicle monthly (HOV moved to child care)
    ve = req.vehicle_expenses
    vehicle_monthly = (
        _annual_to_monthly(ve.car_tax_annual)
        + _weekly_to_monthly(ve.gasoline_weekly)
        + _annual_to_monthly(ve.car_maintenance_annual)
        + ve.car_insurance_monthly
    )

    # Child care monthly (college savings per child + food + daycare + babysitter + toiletries + HOV)
    cc = req.child_care
    child_care_monthly = (
        _annual_to_monthly(cc.contribution_annual_per_child * cc.number_of_children)
        + cc.food_monthly
        + _weekly_to_monthly(cc.daycare_weekly)
        + cc.babysitter_monthly
        + cc.toiletries_monthly
        + cc.hov_monthly
    )

    # Pet care monthly (food + vet annual + grooming)
    pc = req.pet_care
    pet_care_monthly = (
        pc.food_monthly
        + _annual_to_monthly(pc.vet_annual)
        + pc.grooming_monthly
    )

    # Additional expenses monthly
    additional_monthly = sum(
        row.amount if row.frequency == "monthly" else _annual_to_monthly(row.amount)
        for row in req.additional_expenses
    )

    # Discretionary (entertainment) monthly — supports weekly/monthly/annual
    def _discretionary_row_monthly(row) -> float:
        if row.frequency == "weekly":
            return _weekly_to_monthly(row.amount)
        if row.frequency == "annual":
            return _annual_to_monthly(row.amount)
        return row.amount  # monthly
    discretionary_monthly = sum(_discretionary_row_monthly(row) for row in req.discretionary)

    # --- Mandatory vs Discretionary rollup (per line, across all sections) ---
    # Each fixed line has a canonical key and a built-in default class. The
    # request's `classifications` map overrides any key. List rows carry their
    # own classification field. The mortgage payment (P&I + escrow) is always
    # mandatory and is added to the mandatory bucket directly below.
    overrides = req.classifications

    # (key, monthly_value, default_class)
    fixed_lines: list[tuple[str, float, str]] = [
        # Household — mandatory
        ("household.groceries_weekly", _weekly_to_monthly(he.groceries_weekly), "M"),
        ("household.property_expenses_monthly", he.property_expenses_monthly, "M"),
        # Utilities — all mandatory
        ("utilities.cable_internet_monthly", ut.cable_internet_monthly, "M"),
        ("utilities.cellular_monthly", ut.cellular_monthly, "M"),
        ("utilities.electricity_monthly", ut.electricity_monthly, "M"),
        ("utilities.gas_monthly", ut.gas_monthly, "M"),
        ("utilities.water_monthly", ut.water_monthly, "M"),
        # Vehicle — mandatory
        ("vehicle.car_tax_annual", _annual_to_monthly(ve.car_tax_annual), "M"),
        ("vehicle.gasoline_weekly", _weekly_to_monthly(ve.gasoline_weekly), "M"),
        ("vehicle.car_maintenance_annual", _annual_to_monthly(ve.car_maintenance_annual), "M"),
        ("vehicle.car_insurance_monthly", ve.car_insurance_monthly, "M"),
        # Child care — daycare/food/toiletries mandatory; college/babysitter/HOV discretionary
        ("child_care.college", _annual_to_monthly(cc.contribution_annual_per_child * cc.number_of_children), "D"),
        ("child_care.food_monthly", cc.food_monthly, "M"),
        ("child_care.daycare_weekly", _weekly_to_monthly(cc.daycare_weekly), "M"),
        ("child_care.babysitter_monthly", cc.babysitter_monthly, "D"),
        ("child_care.toiletries_monthly", cc.toiletries_monthly, "M"),
        ("child_care.hov_monthly", cc.hov_monthly, "D"),
        # Pet care — food/vet mandatory; grooming discretionary
        ("pet_care.food_monthly", pc.food_monthly, "M"),
        ("pet_care.vet_annual", _annual_to_monthly(pc.vet_annual), "M"),
        ("pet_care.grooming_monthly", pc.grooming_monthly, "D"),
        # Tax & cost — mandatory (other home costs; escrow handled with the mortgage below)
        ("tax_and_cost.other_home_costs_annual", _annual_to_monthly(tc.other_home_costs_annual), "M"),
    ]

    mandatory_monthly = 0.0
    discretionary_total_monthly = 0.0
    for key, value, default_class in fixed_lines:
        cls = overrides.get(key, default_class)
        if cls == "D":
            discretionary_total_monthly += value
        else:
            mandatory_monthly += value

    # List rows carry their own classification.
    for row in req.additional_expenses:
        v = row.amount if row.frequency == "monthly" else _annual_to_monthly(row.amount)
        if row.classification == "D":
            discretionary_total_monthly += v
        else:
            mandatory_monthly += v
    for row in req.discretionary:
        v = _discretionary_row_monthly(row)
        if row.classification == "D":
            discretionary_total_monthly += v
        else:
            mandatory_monthly += v

    # Required monthly with escrow (what the lender bills)
    # Escrow = property tax + insurance + PMI + HOA
    escrow_monthly = property_tax_monthly + _annual_to_monthly(tc.home_insurance_annual) + tc.pmi_monthly + tc.hoa_monthly
    required_monthly_with_escrow = required_monthly + escrow_monthly

    # Planned mortgage outflow = required with escrow + extra principal
    planned_mortgage_outflow = required_monthly_with_escrow + extra_monthly

    # The mortgage payment plus escrow and any scheduled extra principal is always
    # mandatory. (Escrow is not in fixed_lines above; other_home_costs is.)
    mandatory_monthly += planned_mortgage_outflow

    # Planned monthly housing total (all categories)
    planned_monthly_housing_total = (
        planned_mortgage_outflow
        + _annual_to_monthly(tc.other_home_costs_annual)
        + household_monthly
        + utilities_monthly
        + vehicle_monthly
        + child_care_monthly
        + pet_care_monthly
        + additional_monthly
        + discretionary_monthly
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
        child_care_monthly=round(child_care_monthly, 2),
        pet_care_monthly=round(pet_care_monthly, 2),
        additional_expenses_monthly=round(additional_monthly, 2),
        discretionary_monthly=round(discretionary_monthly, 2),
        # Derive mandatory as the remainder so the M/D split always reconciles
        # exactly with the rounded housing total (avoids 1-cent rounding drift).
        discretionary_total_monthly=round(discretionary_total_monthly, 2),
        mandatory_monthly=round(round(planned_monthly_housing_total, 2) - round(discretionary_total_monthly, 2), 2),
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
        **_timeline_response_fields(req, monthly_leftover),
    )


def _timeline_response_fields(req: CalculateRequest, monthly_leftover: float) -> dict:
    """Compute the Timeline Builder projection and package it as the response
    fields. Balances (for account-dip lines) are looked up from the balance
    snapshot store when available; absent snapshots just start those lines at 0."""
    try:
        import balances_store
        balances = balances_store.load_balances()
    except Exception:
        balances = {}
    projection, summary, accounts = _timeline_projection(req, monthly_leftover, balances)
    return {
        "timeline_projection": projection,
        "timeline_summary": summary,
        "timeline_accounts": accounts,
    }
