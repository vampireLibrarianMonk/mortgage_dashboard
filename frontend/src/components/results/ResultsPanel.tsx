import AmortizationChart from "./AmortizationChart";
import type { CalculateResponse, PurchaseMode, DiscretionaryRow } from "../../types";

interface Props {
  result: CalculateResponse;
  purchaseMode: PurchaseMode;
  discretionary: DiscretionaryRow[];
}

const fmt = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });

const FREQ_LABEL: Record<DiscretionaryRow["frequency"], string> = {
  weekly: "wk",
  monthly: "mo",
  annual: "yr",
};

/** Convert a discretionary row to its monthly-equivalent cost. */
function rowMonthly(row: DiscretionaryRow): number {
  if (row.frequency === "weekly") return (row.amount * 52) / 12;
  if (row.frequency === "annual") return row.amount / 12;
  return row.amount;
}

export default function ResultsPanel({ result, purchaseMode, discretionary }: Props) {
  const r = result;
  const isExisting = purchaseMode === "existing_mortgage";

  // Rows with a real budget, ranked largest monthly cost first for quick cuts.
  const discretionaryRanked = discretionary
    .filter((row) => row.amount > 0)
    .map((row) => ({ ...row, monthly: rowMonthly(row) }))
    .sort((a, b) => b.monthly - a.monthly);

  return (
    <div className="results-panel">
      <div className="banner">
        <div className="banner-item">
          <span className="banner-label">Take Home Pay</span>
          <span className="banner-value">{fmt(r.take_home_pay_monthly)}</span>
        </div>
        <div className="banner-item">
          <span className="banner-label">Total Outflow</span>
          <span className="banner-value">{fmt(r.planned_monthly_housing_total)}</span>
        </div>
        <div className="banner-item">
          <span className="banner-label">Discretionary</span>
          <span className="banner-value">{fmt(r.discretionary_monthly)}</span>
        </div>
        <div className="banner-item">
          <span className={`banner-value ${r.monthly_leftover < 0 ? "negative" : "positive"}`}>
            <span className="banner-label">Leftover</span>
            {fmt(r.monthly_leftover)}
          </span>
        </div>
      </div>

      <AmortizationChart schedule={r.amortization_schedule} />

      <section>
        <h3>Monthly Summary</h3>
        <dl>
          <dt>Planned Monthly Housing Total</dt><dd>{fmt(r.planned_monthly_housing_total)}</dd>
          <dt>Take Home Pay</dt><dd>{fmt(r.take_home_pay_monthly)}</dd>
          <dt>Monthly Leftover</dt><dd>{fmt(r.monthly_leftover)}</dd>
        </dl>
      </section>

      {discretionaryRanked.length > 0 && (
        <section className="discretionary-summary">
          <h3>Discretionary Summary</h3>
          <p className="section-hint">Ranked by monthly cost — start cutting from the top.</p>
          <dl>
            {discretionaryRanked.map((row, i) => (
              <div className="discretionary-line" key={i}>
                <dt>
                  {row.name} <span className="freq-note">({fmt(row.amount)}/{FREQ_LABEL[row.frequency]})</span>
                </dt>
                <dd>{fmt(row.monthly)}/mo</dd>
              </div>
            ))}
          </dl>
          <dl className="discretionary-total">
            <dt>Total Discretionary</dt><dd>{fmt(r.discretionary_monthly)}/mo</dd>
          </dl>
        </section>
      )}

      {isExisting ? (
        <section>
          <h3>Existing Mortgage</h3>
          <dl>
            <dt>Outstanding Balance</dt><dd>{fmt(r.loan_amount)}</dd>
            <dt>P&amp;I Monthly</dt><dd>{fmt(r.required_monthly_pi)}</dd>
            <dt>Required Monthly (w/ escrow)</dt><dd>{fmt(r.required_monthly_payment)}</dd>
            <dt>Planned Mortgage Outflow</dt><dd>{fmt(r.planned_mortgage_outflow_monthly)}</dd>
            <dt>First-Month Interest</dt><dd>{fmt(r.first_month_interest)}</dd>
            <dt>First-Month Principal</dt><dd>{fmt(r.first_month_principal)}</dd>
          </dl>
        </section>
      ) : (
        <section>
          <h3>Purchase &amp; Loan</h3>
          <dl>
            <dt>House Price</dt><dd>{fmt(r.down_payment_amount + r.loan_amount - r.closing_costs_amount)}</dd>
            <dt>Down Payment</dt><dd>{fmt(r.down_payment_amount)}</dd>
            <dt>Closing Costs</dt><dd>{fmt(r.closing_costs_amount)}</dd>
            <dt>Earnest Money Credit</dt><dd>{fmt(r.earnest_money_amount)}</dd>
            <dt>Total Loan Amount</dt><dd>{fmt(r.loan_amount)}</dd>
            <dt>P&amp;I Monthly</dt><dd>{fmt(r.required_monthly_pi)}</dd>
            <dt>Required Monthly (w/ escrow)</dt><dd>{fmt(r.required_monthly_payment)}</dd>
            <dt>Planned Mortgage Outflow</dt><dd>{fmt(r.planned_mortgage_outflow_monthly)}</dd>
            <dt>First-Month Interest</dt><dd>{fmt(r.first_month_interest)}</dd>
            <dt>First-Month Principal</dt><dd>{fmt(r.first_month_principal)}</dd>
          </dl>
        </section>
      )}

      <section>
        <h3>Lifetime Mortgage Outcomes</h3>
        <dl>
          <dt>Total Mortgage Payments (P&amp;I)</dt><dd>{fmt(r.total_mortgage_payments)}</dd>
          <dt>Total Interest</dt><dd>{fmt(r.total_interest)}</dd>
          <dt>Payoff Date</dt><dd>{r.standard_payoff_date}</dd>
          <dt>Tax &amp; Cost Monthly</dt><dd>{fmt(r.tax_and_cost_monthly)}</dd>
          <dt>Household Monthly</dt><dd>{fmt(r.household_monthly)}</dd>
          <dt>Utilities Monthly</dt><dd>{fmt(r.utilities_monthly)}</dd>
          <dt>Vehicle Monthly</dt><dd>{fmt(r.vehicle_monthly)}</dd>
          <dt>College Monthly</dt><dd>{fmt(r.college_monthly)}</dd>
          <dt>Discretionary Monthly</dt><dd>{fmt(r.discretionary_monthly)}</dd>
          <dt>Additional Expenses Monthly</dt><dd>{fmt(r.additional_expenses_monthly)}</dd>
        </dl>
      </section>

      {(r.months_saved > 0 || r.lump_sum_total > 0) && (
        <section>
          <h3>Extra Principal Effects</h3>
          <dl>
            <dt>Scheduled Extra (monthly equiv.)</dt><dd>{fmt(r.scheduled_extra_principal_monthly)}</dd>
            <dt>Lump Sum Total</dt><dd>{fmt(r.lump_sum_total)}</dd>
            <dt>Interest Savings</dt><dd>{fmt(r.interest_savings)}</dd>
            <dt>Months Saved</dt><dd>{r.months_saved}</dd>
            {r.accelerated_payoff_date && <><dt>New Payoff Date</dt><dd>{r.accelerated_payoff_date}</dd></>}
          </dl>
        </section>
      )}

      {!isExisting && (
        <section>
          <h3>Cash to Close</h3>
          <dl>
            <dt>Prepaids &amp; Escrow (Low)</dt><dd>{fmt(r.prepaids_escrow_low)}</dd>
            <dt>Cash to Close (Low)</dt><dd>{fmt(r.cash_to_close_low)}</dd>
            <dt>Prepaids &amp; Escrow (High)</dt><dd>{fmt(r.prepaids_escrow_high)}</dd>
            <dt>Cash to Close (High)</dt><dd>{fmt(r.cash_to_close_high)}</dd>
          </dl>
        </section>
      )}
    </div>
  );
}
