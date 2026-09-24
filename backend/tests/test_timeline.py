"""Tests for the Timeline Builder projection engine (calculations._timeline_*).

Covers escalation (%/$), unit normalization, adjustments (+save/-spend), purchase
funding methods (pay_in_full / payment_plan / already_paid), one-time spikes,
first-negative detection, and the account-dip series seeded from a balance snapshot.

Isolation: isolated_store (conftest) covers txn_store; we redirect
balances_store.BALANCES_PATH to tmp so seeding a balance is disposable.
"""

import pytest

import balances_store as bs
from calculations import calculate
from models import (
    Adjustment,
    CalculateRequest,
    HousePurchase,
    LoanTerms,
    Purchase,
    Timeline,
    TimelinePlan,
    TimelineSettings,
)


@pytest.fixture(autouse=True)
def isolated_balances(isolated_store, monkeypatch):
    monkeypatch.setattr(bs, "BALANCES_PATH", isolated_store.DATA_DIR / "balances.json.enc")


def _req(timelines=None, adjustments=None, *, starting_leftover=3000.0,
         carry_over=False, horizon_years=3, start_year=2026, start_month=1):
    """A minimal CalculateRequest with a timeline plan. Loan is present but its
    numbers don't matter to the timeline projection except start_year/start_month
    (the projection's time origin)."""
    return CalculateRequest(
        house_purchase=HousePurchase(home_price=400000, down_payment_value=20),
        loan_terms=LoanTerms(annual_interest_rate=6.0, loan_term_years=30,
                             start_month=start_month, start_year=start_year),
        timeline_plan=TimelinePlan(
            settings=TimelineSettings(starting_leftover=starting_leftover,
                                      carry_over_leftover=carry_over,
                                      horizon_years=horizon_years),
            timelines=timelines or [],
            adjustments=adjustments or [],
        ),
    )


def _point(resp, period):
    return next(p for p in resp.timeline_projection if p["period"] == period)


# --- basics --------------------------------------------------------------------

def test_empty_plan_yields_no_projection():
    resp = calculate(_req())
    assert resp.timeline_projection == []
    assert resp.timeline_summary == {}
    assert resp.timeline_accounts == []


def test_projection_spans_horizon_from_loan_start():
    resp = calculate(_req([Timeline(label="x", start="2026-01", end=None, base=100)]))
    # horizon 3y -> 37 monthly points, first is the loan start month.
    assert len(resp.timeline_projection) == 37
    assert resp.timeline_projection[0]["period"] == "2026-01"
    assert resp.timeline_projection[-1]["period"] == "2029-01"


# --- recurring cost + unit normalization --------------------------------------

def test_flat_monthly_cost_reduces_runway_while_active():
    tl = Timeline(label="daycare", start="2027-01", end="2027-12", base=1000, unit="month")
    resp = calculate(_req([tl], starting_leftover=3000))
    assert _point(resp, "2026-06")["timeline_cost"] == 0.0       # before start
    assert _point(resp, "2027-06")["timeline_cost"] == 1000.0    # active
    assert _point(resp, "2027-06")["runway_raw"] == 2000.0
    assert _point(resp, "2028-06")["timeline_cost"] == 0.0       # after end


def test_year_unit_normalizes_to_monthly():
    tl = Timeline(label="annual", start="2026-01", end=None, base=1200, unit="year")
    resp = calculate(_req([tl]))
    assert _point(resp, "2026-06")["timeline_cost"] == 100.0     # 1200/yr -> 100/mo


def test_negative_base_bolsters_runway_within_window():
    """A negative base is income/savings: it ADDS to the runway while active, and
    that boost stops at the end month (runway steps back down)."""
    tl = Timeline(label="side income", start="2027-01", end="2027-12",
                  base=-300, unit="month")
    resp = calculate(_req([tl], starting_leftover=2000))
    assert _point(resp, "2026-06")["timeline_cost"] == 0.0        # before start
    assert _point(resp, "2027-06")["timeline_cost"] == -300.0     # active (signed)
    assert _point(resp, "2027-06")["runway_raw"] == 2300.0        # 2000 - (-300)
    assert _point(resp, "2028-06")["timeline_cost"] == 0.0        # after end
    assert _point(resp, "2028-06")["runway_raw"] == 2000.0        # boost gone


def test_negative_windows_group_contiguous_deficits():
    """Two separate dips (a cost that turns the runway negative, recovers, then a
    second cost) produce two grouped windows with correct shortfall totals."""
    tls = [
        # Dip 1: 2027-01..2027-03, cost 1500 vs 1000 leftover -> -500/mo x3.
        Timeline(label="dip1", start="2027-01", end="2027-03", base=1500, unit="month"),
        # Dip 2: 2028-01..2028-02, cost 1200 -> -200/mo x2.
        Timeline(label="dip2", start="2028-01", end="2028-02", base=1200, unit="month"),
    ]
    resp = calculate(_req(tls, starting_leftover=1000, horizon_years=3))
    windows = resp.timeline_summary["negative_windows"]
    assert len(windows) == 2

    w1, w2 = windows
    assert (w1["start"], w1["end"], w1["months"]) == ("2027-01", "2027-03", 3)
    assert w1["shortfall"] == -1500.0     # 3 x -500
    assert w1["deepest"] == -500.0

    assert (w2["start"], w2["end"], w2["months"]) == ("2028-01", "2028-02", 2)
    assert w2["shortfall"] == -400.0      # 2 x -200


def test_no_negative_windows_when_solvent():
    tl = Timeline(label="ok", start="2026-01", end=None, base=100, unit="month")
    resp = calculate(_req([tl], starting_leftover=3000))
    assert resp.timeline_summary["negative_windows"] == []


def test_negative_base_percent_escalation_grows_the_boost():
    """Percent escalation on a negative base scales its magnitude, so the boost
    gets larger over time."""
    tl = Timeline(label="raise", start="2026-01", end=None, base=-1000, unit="month",
                  escalation_value=10, escalation_unit="percent")
    resp = calculate(_req([tl], horizon_years=3))
    assert _point(resp, "2026-06")["timeline_cost"] == -1000.0
    assert _point(resp, "2027-06")["timeline_cost"] == -1100.0    # bigger boost


# --- escalation ----------------------------------------------------------------

def test_percent_escalation_compounds_yearly():
    tl = Timeline(label="esc", start="2026-01", end=None, base=1000, unit="month",
                  escalation_value=10, escalation_unit="percent")
    resp = calculate(_req([tl], horizon_years=3))
    assert _point(resp, "2026-06")["timeline_cost"] == 1000.0      # year 0
    assert _point(resp, "2027-06")["timeline_cost"] == 1100.0      # +10%
    assert _point(resp, "2028-06")["timeline_cost"] == 1210.0      # compounding


def test_dollar_escalation_adds_yearly():
    tl = Timeline(label="esc", start="2026-01", end=None, base=1000, unit="month",
                  escalation_value=50, escalation_unit="dollar")
    resp = calculate(_req([tl], horizon_years=3))
    assert _point(resp, "2026-06")["timeline_cost"] == 1000.0
    assert _point(resp, "2027-06")["timeline_cost"] == 1050.0
    assert _point(resp, "2028-06")["timeline_cost"] == 1100.0


# --- adjustments (+save / -spend) ---------------------------------------------

def test_adjustments_net_and_lift_adjusted_runway():
    adjs = [Adjustment(label="drop ezpass", amount=40, unit="month"),
            Adjustment(label="stop stock", amount=1200, unit="year"),   # -> +100/mo
            Adjustment(label="new gym", amount=-60, unit="month")]
    resp = calculate(_req([], adjustments=adjs, starting_leftover=1000))
    # net = 40 + 100 - 60 = 80/mo
    assert resp.timeline_summary["net_adjustment_monthly"] == 80.0
    p = _point(resp, "2026-06")
    assert p["runway_raw"] == 1000.0
    assert p["runway_adjusted"] == 1080.0


# --- purchase funding methods --------------------------------------------------

def test_pay_in_full_is_one_time_on_start_month():
    tl = Timeline(label="tv", start="2027-03", end=None, base=0,
                  purchase=Purchase(amount=2000, method="pay_in_full", account="usaa:0000"))
    resp = calculate(_req([tl]))
    assert _point(resp, "2027-03")["one_time"] == 2000.0
    assert _point(resp, "2027-04")["one_time"] == 0.0
    assert _point(resp, "2027-03")["timeline_cost"] == 0.0  # full price is one-time, not recurring


def test_payment_plan_down_one_time_plus_financed_monthly_within_term():
    tl = Timeline(label="suv", start="2027-01", end=None, base=0,
                  purchase=Purchase(amount=38000, method="payment_plan", down_payment=5000,
                                    apr=0, term_months=10, account="usaa:0000"))
    resp = calculate(_req([tl], horizon_years=4))
    # 0% APR, financed 33000 over 10 months -> 3300/mo
    assert _point(resp, "2027-01")["one_time"] == 5000.0           # down payment
    assert _point(resp, "2027-01")["timeline_cost"] == 3300.0      # financed monthly
    assert _point(resp, "2027-10")["timeline_cost"] == 3300.0      # last month of term
    assert _point(resp, "2027-11")["timeline_cost"] == 0.0         # term over


def test_already_paid_excluded_from_projection():
    tl = Timeline(label="paid", start="2027-01", end=None, base=0,
                  purchase=Purchase(amount=9999, method="already_paid", account="usaa:0000"))
    resp = calculate(_req([tl]))
    assert _point(resp, "2027-01")["one_time"] == 0.0
    assert _point(resp, "2027-01")["timeline_cost"] == 0.0


# --- first-negative detection --------------------------------------------------

def test_first_negative_period_detected_on_adjusted_line():
    tl = Timeline(label="big", start="2027-05", end=None, base=5000, unit="month")
    resp = calculate(_req([tl], starting_leftover=3000))
    assert resp.timeline_summary["first_negative_period"] == "2027-05"


def test_no_negative_when_runway_stays_positive():
    tl = Timeline(label="small", start="2027-01", end=None, base=100, unit="month")
    resp = calculate(_req([tl], starting_leftover=3000))
    assert resp.timeline_summary["first_negative_period"] is None


# --- account-dip series (seeded from balance snapshot) -------------------------

def test_account_series_seeds_from_snapshot_and_draws_down():
    bs.upsert_balance("usaa", "0000", 12431.00, "2026-09-24T14:37:00")
    tl = Timeline(label="suv", start="2028-01", end=None, base=0,
                  purchase=Purchase(amount=38000, method="payment_plan", down_payment=5000,
                                    apr=6.0, term_months=60, account="usaa:0000"))
    resp = calculate(_req([tl], horizon_years=4))
    acct = next(a for a in resp.timeline_accounts if a["key"] == "usaa:0000")
    assert acct["as_of"] == "2026-09-24T14:37:00"
    assert acct["points"][0]["balance"] == 12431.00              # seeded start
    assert min(p["balance"] for p in acct["points"]) == 7431.00  # after 5000 down


def test_account_series_starts_at_zero_without_snapshot():
    tl = Timeline(label="suv", start="2028-01", end=None, base=0,
                  purchase=Purchase(amount=10000, method="pay_in_full", account="chase:2038"))
    resp = calculate(_req([tl], horizon_years=4))
    acct = next(a for a in resp.timeline_accounts if a["key"] == "chase:2038")
    assert acct["points"][0]["balance"] == 0.0
    assert min(p["balance"] for p in acct["points"]) == -10000.0  # full price drawn


# --- carry-over leftover -------------------------------------------------------

def test_carry_over_uses_dashboard_monthly_leftover():
    # With no income and no expenses beyond the mortgage, monthly_leftover is
    # negative; carry_over should seed the runway from it (not from the typed 3000).
    req = _req([Timeline(label="x", start="2026-06", end=None, base=100)],
               carry_over=True, starting_leftover=3000)
    resp = calculate(req)
    assert resp.timeline_summary["starting_leftover"] == resp.monthly_leftover
