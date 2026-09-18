from calculations import calculate
from models import (
    CalculateRequest,
    ExtraPrincipal,
    ExtraPrincipalFrequency,
    HousePurchase,
    IncomeRow,
    InputMode,
    LoanTerms,
    LumpSumPayment,
    RecurringExtraPrincipal,
)


def _basic_request(**overrides) -> CalculateRequest:
    defaults = dict(
        house_purchase=HousePurchase(
            home_price=400000,
            down_payment_value=20,
            down_payment_mode=InputMode.percent,
            closing_costs_value=3,
            closing_costs_mode=InputMode.percent,
            closing_costs_financed=True,
            earnest_money_value=1,
            earnest_money_mode=InputMode.percent,
        ),
        loan_terms=LoanTerms(
            loan_term_years=30,
            annual_interest_rate=6.5,
            start_month=1,
            start_year=2026,
        ),
        take_home_pay=[
            IncomeRow(name="Salary", amount=8000, frequency="monthly"),
        ],
    )
    defaults.update(overrides)
    return CalculateRequest(**defaults)


class TestPurchaseCalculations:
    def test_down_payment_percent(self):
        r = calculate(_basic_request())
        assert r.down_payment_amount == 80000.0

    def test_down_payment_dollars(self):
        req = _basic_request(
            house_purchase=HousePurchase(
                home_price=400000,
                down_payment_value=50000,
                down_payment_mode=InputMode.dollars,
                closing_costs_value=0,
                closing_costs_mode=InputMode.dollars,
                closing_costs_financed=False,
                earnest_money_value=0,
                earnest_money_mode=InputMode.dollars,
            )
        )
        r = calculate(req)
        assert r.down_payment_amount == 50000.0
        assert r.loan_amount == 350000.0

    def test_loan_amount_with_financed_closing(self):
        r = calculate(_basic_request())
        # 400000 - 80000 (down) + 12000 (3% closing financed)
        assert r.loan_amount == 332000.0

    def test_loan_amount_without_financed_closing(self):
        req = _basic_request(
            house_purchase=HousePurchase(
                home_price=400000,
                down_payment_value=20,
                down_payment_mode=InputMode.percent,
                closing_costs_value=3,
                closing_costs_mode=InputMode.percent,
                closing_costs_financed=False,
                earnest_money_value=0,
                earnest_money_mode=InputMode.percent,
            )
        )
        r = calculate(req)
        assert r.loan_amount == 320000.0


class TestMonthlyPayment:
    def test_standard_30yr(self):
        r = calculate(_basic_request())
        # 332000 @ 6.5% / 30yr ≈ $2098.94
        assert 2090 < r.required_monthly_payment < 2110

    def test_zero_interest(self):
        req = _basic_request(
            loan_terms=LoanTerms(
                loan_term_years=30,
                annual_interest_rate=0,
                start_month=1,
                start_year=2026,
            )
        )
        r = calculate(req)
        expected = 332000 / 360
        assert abs(r.required_monthly_payment - expected) < 0.01

    def test_first_month_breakdown(self):
        r = calculate(_basic_request())
        assert abs(r.first_month_interest + r.first_month_principal - r.required_monthly_payment) < 0.01


class TestExtraPrincipal:
    def test_monthly_extra_saves_months(self):
        req = _basic_request(
            extra_principal=ExtraPrincipal(
                recurring=RecurringExtraPrincipal(
                    amount=500,
                    frequency=ExtraPrincipalFrequency.monthly,
                    start_year=2026,
                    end_year=2056,
                )
            )
        )
        r = calculate(req)
        assert r.months_saved > 0
        assert r.interest_savings > 0
        assert r.accelerated_payoff_date is not None

    def test_lump_sum_reduces_interest(self):
        req = _basic_request(
            extra_principal=ExtraPrincipal(
                lump_sums=[LumpSumPayment(year=2028, amount=50000)]
            )
        )
        r = calculate(req)
        assert r.interest_savings > 0
        assert r.lump_sum_total == 50000

    def test_no_extra_principal(self):
        r = calculate(_basic_request())
        assert r.months_saved == 0
        assert r.interest_savings == 0
        assert r.accelerated_payoff_date is None


class TestAffordability:
    def test_monthly_leftover(self):
        r = calculate(_basic_request())
        assert abs(r.monthly_leftover - (r.take_home_pay_monthly - r.planned_monthly_housing_total)) < 0.02

    def test_take_home_annual_conversion(self):
        req = _basic_request(
            take_home_pay=[IncomeRow(name="Salary", amount=96000, frequency="annual")]
        )
        r = calculate(req)
        assert r.take_home_pay_monthly == 8000.0


class TestCashToClose:
    def test_with_financed_closing(self):
        r = calculate(_basic_request())
        # down + prepaids - earnest (closing financed so not included)
        assert r.cash_to_close_low == 80000 + 400000 * 0.02 - 4000
        assert r.cash_to_close_high == 80000 + 400000 * 0.04 - 4000

    def test_without_financed_closing(self):
        req = _basic_request(
            house_purchase=HousePurchase(
                home_price=400000,
                down_payment_value=20,
                down_payment_mode=InputMode.percent,
                closing_costs_value=3,
                closing_costs_mode=InputMode.percent,
                closing_costs_financed=False,
                earnest_money_value=1,
                earnest_money_mode=InputMode.percent,
            )
        )
        r = calculate(req)
        # down + closing + prepaids - earnest
        assert r.cash_to_close_low == 80000 + 12000 + 8000 - 4000
