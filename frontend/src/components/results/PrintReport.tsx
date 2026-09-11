import type { CalculateResponse, CalculateRequest } from "../../types";
import {
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
  Line,
  ComposedChart,
} from "recharts";

interface Props {
  result: CalculateResponse;
  state: CalculateRequest;
}

const fmt = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const fmtK = (n: number) => `$${(n / 1000).toFixed(0)}k`;
const freqLabel = (f: string) => ({ monthly: "Monthly", quarterly: "Quarterly", semi_annual: "Semi-Annual", annual: "Annual" }[f] || f);
const monthName = (m: number) => ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m - 1];

export default function PrintReport({ result, state }: Props) {
  const r = result;
  const hp = state.house_purchase;
  const lt = state.loan_terms;
  const tc = state.tax_and_cost;
  const he = state.household_expenses;
  const ut = state.utilities;
  const ve = state.vehicle_expenses;
  const cs = state.college_savings;
  const ep = state.extra_principal;
  const isExisting = hp.purchase_mode === "existing_mortgage";

  return (
    <div className="print-report">
      {/* ─── HEADER ─── */}
      <div className="report-header">
        <h1>Mortgage & Loan Assumptions Report</h1>
        <p className="report-date">Generated: {new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</p>
      </div>

      {/* ─── EXECUTIVE SUMMARY ─── */}
      <section className="report-section summary-box">
        <h2>Executive Summary</h2>
        <table className="report-table summary-table">
          <tbody>
            <tr><td>Mortgage P&I</td><td>{fmt(r.required_monthly_pi)}</td></tr>
            <tr><td>Lender Payment (P&I + Escrow)</td><td>{fmt(r.required_monthly_payment)}</td></tr>
            <tr><td>Housing Payment (incl. extra principal)</td><td>{fmt(r.planned_mortgage_outflow_monthly)}</td></tr>
            <tr className="separator"><td colSpan={2}></td></tr>
            <tr><td>Total Monthly Obligations</td><td>{fmt(r.planned_monthly_housing_total)}</td></tr>
            <tr><td>Total Take Home Pay</td><td>{fmt(r.take_home_pay_monthly)}</td></tr>
            <tr className={r.monthly_leftover < 0 ? "negative" : "positive"}>
              <td><strong>Monthly Leftover</strong></td>
              <td><strong>{fmt(r.monthly_leftover)}</strong></td>
            </tr>
          </tbody>
        </table>
      </section>

      {/* ─── AMORTIZATION CHART ─── */}
      {r.amortization_schedule.length > 0 && (
        <section className="report-section report-chart">
          <h2>Amortization Schedule</h2>
          <ComposedChart width={700} height={200} data={r.amortization_schedule} margin={{ top: 5, right: 5, left: 5, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#ccc" />
            <XAxis dataKey="year" tick={{ fill: "#333", fontSize: 9 }} />
            <YAxis yAxisId="left" tickFormatter={fmtK} tick={{ fill: "#333", fontSize: 9 }} />
            <YAxis yAxisId="right" orientation="right" tickFormatter={fmtK} tick={{ fill: "#333", fontSize: 9 }} />
            <Legend wrapperStyle={{ fontSize: "9pt" }} />
            <Area yAxisId="left" type="monotone" dataKey="principal" name="Principal" stackId="1" fill="#4caf50" stroke="#4caf50" fillOpacity={0.7} />
            <Area yAxisId="left" type="monotone" dataKey="interest" name="Interest" stackId="1" fill="#e94560" stroke="#e94560" fillOpacity={0.7} />
            <Line yAxisId="right" type="monotone" dataKey="balance" name="Balance" stroke="#1976d2" strokeWidth={2} dot={false} />
          </ComposedChart>
        </section>
      )}

      {/* ─── MORTGAGE DETAILS ─── */}
      <section className="report-section">
        <h2>{isExisting ? "Existing Mortgage Details" : "Purchase & Loan Details"}</h2>
        <table className="report-table">
          <tbody>
            {isExisting ? (
              <>
                <tr><td>Outstanding Balance</td><td>{fmt(hp.outstanding_balance)}</td></tr>
                <tr><td>Assessed Home Value</td><td>{hp.current_home_value > 0 ? fmt(hp.current_home_value) : "—"}</td></tr>
              </>
            ) : (
              <>
                <tr><td>Home Price</td><td>{fmt(hp.home_price)}</td></tr>
                <tr><td>Down Payment</td><td>{hp.down_payment_value}{hp.down_payment_mode === "percent" ? "%" : " (dollars)"} = {fmt(r.down_payment_amount)}</td></tr>
                <tr><td>Closing Costs</td><td>{hp.closing_costs_value}{hp.closing_costs_mode === "percent" ? "%" : " (dollars)"} = {fmt(r.closing_costs_amount)}{hp.closing_costs_financed ? " (financed)" : " (cash)"}</td></tr>
                <tr><td>Earnest Money</td><td>{hp.earnest_money_value}{hp.earnest_money_mode === "percent" ? "%" : " (dollars)"} = {fmt(r.earnest_money_amount)}</td></tr>
                <tr><td>Total Loan Amount</td><td>{fmt(r.loan_amount)}</td></tr>
              </>
            )}
            <tr className="separator"><td colSpan={2}></td></tr>
            <tr><td>Loan Term</td><td>{lt.loan_term_years} years</td></tr>
            <tr><td>Interest Rate</td><td>{lt.annual_interest_rate}%</td></tr>
            <tr><td>Start Date</td><td>{monthName(lt.start_month)} {lt.start_year}</td></tr>
            <tr><td>Standard Payoff Date</td><td>{r.standard_payoff_date}</td></tr>
            <tr className="separator"><td colSpan={2}></td></tr>
            <tr><td>Monthly P&I</td><td>{fmt(r.required_monthly_pi)}</td></tr>
            <tr><td>First-Month Interest</td><td>{fmt(r.first_month_interest)}</td></tr>
            <tr><td>First-Month Principal</td><td>{fmt(r.first_month_principal)}</td></tr>
          </tbody>
        </table>
      </section>

      {/* ─── LIFETIME OUTCOMES ─── */}
      <section className="report-section">
        <h2>Lifetime Mortgage Outcomes</h2>
        <table className="report-table">
          <tbody>
            <tr><td>Total Payments (P&I over life of loan)</td><td>{fmt(r.total_mortgage_payments)}</td></tr>
            <tr><td>Total Interest Paid</td><td>{fmt(r.total_interest)}</td></tr>
            {r.total_interest_with_extra !== null && <tr><td>Total Interest (with extra principal)</td><td>{fmt(r.total_interest_with_extra)}</td></tr>}
          </tbody>
        </table>
      </section>

      {/* ─── EXTRA PRINCIPAL ─── */}
      {(ep.recurring || ep.escalating || ep.lump_sums.length > 0) && (
        <section className="report-section">
          <h2>Extra Principal Strategy</h2>
          <table className="report-table">
            <tbody>
              {ep.recurring && (
                <>
                  <tr><td>Recurring Amount</td><td>{fmt(ep.recurring.amount)} / {freqLabel(ep.recurring.frequency)}</td></tr>
                  <tr><td>Period</td><td>{ep.recurring.start_year} — {ep.recurring.end_year ?? "Until Payoff"}</td></tr>
                  <tr><td>Monthly Equivalent</td><td>{fmt(r.scheduled_extra_principal_monthly)}</td></tr>
                </>
              )}
              {ep.escalating && (
                <>
                  {ep.recurring && <tr className="separator"><td colSpan={2}></td></tr>}
                  <tr><td><strong>Escalating Monthly Payment</strong></td><td></td></tr>
                  <tr><td style={{paddingLeft: "1rem"}}>Starting Amount</td><td>{fmt(ep.escalating.start_amount)} / mo</td></tr>
                  <tr><td style={{paddingLeft: "1rem"}}>Annual Increase</td><td>{fmt(ep.escalating.annual_increase)} / yr</td></tr>
                  <tr><td style={{paddingLeft: "1rem"}}>Period</td><td>{ep.escalating.start_year} — {ep.escalating.end_year ?? "Until Payoff"}</td></tr>
                </>
              )}
              {ep.lump_sums.length > 0 && (
                <>
                  <tr className="separator"><td colSpan={2}></td></tr>
                  <tr><td><strong>Lump Sum Payments</strong></td><td></td></tr>
                  {ep.lump_sums.map((ls, i) => (
                    <tr key={i}><td style={{paddingLeft: "1rem"}}>Year {ls.year}</td><td>{fmt(ls.amount)}</td></tr>
                  ))}
                  <tr><td>Lump Sum Total</td><td>{fmt(r.lump_sum_total)}</td></tr>
                </>
              )}
              <tr className="separator"><td colSpan={2}></td></tr>
              <tr><td>Interest Savings</td><td>{fmt(r.interest_savings)}</td></tr>
              <tr><td>Months Saved</td><td>{r.months_saved} ({(r.months_saved / 12).toFixed(1)} years)</td></tr>
              {r.accelerated_payoff_date && <tr><td>Accelerated Payoff Date</td><td>{r.accelerated_payoff_date}</td></tr>}
            </tbody>
          </table>
        </section>
      )}

      {/* ─── TAX, INSURANCE & HOUSING COSTS ─── */}
      <section className="report-section">
        <h2>Tax, Insurance & Housing Costs</h2>
        <table className="report-table">
          <tbody>
            <tr><td>Property Tax</td><td>{tc.property_tax_value}{tc.property_tax_mode === "percent" ? `% of ${isExisting ? fmt(hp.current_home_value) : fmt(hp.home_price)}` : "/year"}</td></tr>
            <tr><td>Home Insurance</td><td>{fmt(tc.home_insurance_annual)}/year</td></tr>
            <tr><td>PMI</td><td>{tc.pmi_monthly > 0 ? `${fmt(tc.pmi_monthly)}/mo` : "None"}</td></tr>
            <tr><td>HOA</td><td>{tc.hoa_monthly > 0 ? `${fmt(tc.hoa_monthly)}/mo` : "None"}</td></tr>
            <tr><td>Other Home Costs</td><td>{tc.other_home_costs_annual > 0 ? `${fmt(tc.other_home_costs_annual)}/year` : "None"}</td></tr>
            <tr className="separator"><td colSpan={2}></td></tr>
            <tr><td><strong>Monthly Total</strong></td><td><strong>{fmt(r.tax_and_cost_monthly)}</strong></td></tr>
          </tbody>
        </table>
      </section>

      {/* ─── HOUSEHOLD EXPENSES ─── */}
      <section className="report-section">
        <h2>Household Expenses</h2>
        <table className="report-table">
          <tbody>
            <tr><td>Daycare</td><td>{he.daycare_weekly > 0 ? `${fmt(he.daycare_weekly)}/week` : "—"}</td></tr>
            <tr><td>Groceries</td><td>{he.groceries_weekly > 0 ? `${fmt(he.groceries_weekly)}/week` : "—"}</td></tr>
            <tr><td>Property Expenses</td><td>{he.property_expenses_monthly > 0 ? `${fmt(he.property_expenses_monthly)}/mo` : "—"}</td></tr>
            <tr className="separator"><td colSpan={2}></td></tr>
            <tr><td><strong>Monthly Total</strong></td><td><strong>{fmt(r.household_monthly)}</strong></td></tr>
          </tbody>
        </table>
      </section>

      {/* ─── UTILITIES ─── */}
      <section className="report-section">
        <h2>Utilities</h2>
        <table className="report-table">
          <tbody>
            <tr><td>Cable / Internet</td><td>{ut.cable_internet_monthly > 0 ? `${fmt(ut.cable_internet_monthly)}/mo` : "—"}</td></tr>
            <tr><td>Cellular</td><td>{ut.cellular_monthly > 0 ? `${fmt(ut.cellular_monthly)}/mo` : "—"}</td></tr>
            <tr><td>Electricity</td><td>{ut.electricity_monthly > 0 ? `${fmt(ut.electricity_monthly)}/mo` : "—"}</td></tr>
            <tr><td>Gas</td><td>{ut.gas_monthly > 0 ? `${fmt(ut.gas_monthly)}/mo` : "—"}</td></tr>
            <tr><td>Consolidated Water</td><td>{ut.water_monthly > 0 ? `${fmt(ut.water_monthly)}/mo` : "—"}</td></tr>
            <tr className="separator"><td colSpan={2}></td></tr>
            <tr><td><strong>Monthly Total</strong></td><td><strong>{fmt(r.utilities_monthly)}</strong></td></tr>
          </tbody>
        </table>
      </section>

      {/* ─── VEHICLE EXPENSES ─── */}
      <section className="report-section">
        <h2>Vehicle Expenses</h2>
        <table className="report-table">
          <tbody>
            <tr><td>Car Tax</td><td>{ve.car_tax_annual > 0 ? `${fmt(ve.car_tax_annual)}/year` : "—"}</td></tr>
            <tr><td>Gasoline</td><td>{ve.gasoline_weekly > 0 ? `${fmt(ve.gasoline_weekly)}/week` : "—"}</td></tr>
            <tr><td>Car Maintenance</td><td>{ve.car_maintenance_annual > 0 ? `${fmt(ve.car_maintenance_annual)}/year` : "—"}</td></tr>
            <tr><td>Car Insurance</td><td>{ve.car_insurance_monthly > 0 ? `${fmt(ve.car_insurance_monthly)}/mo` : "—"}</td></tr>
            <tr><td>HOV / Tolls</td><td>{ve.hov_monthly > 0 ? `${fmt(ve.hov_monthly)}/mo` : "—"}</td></tr>
            <tr className="separator"><td colSpan={2}></td></tr>
            <tr><td><strong>Monthly Total</strong></td><td><strong>{fmt(r.vehicle_monthly)}</strong></td></tr>
          </tbody>
        </table>
      </section>

      {/* ─── COLLEGE SAVINGS ─── */}
      {cs.number_of_children > 0 && (
        <section className="report-section">
          <h2>College Savings (529)</h2>
          <table className="report-table">
            <tbody>
              <tr><td>Annual Contribution per Child</td><td>{fmt(cs.contribution_annual_per_child)}</td></tr>
              <tr><td>Number of Children</td><td>{cs.number_of_children}</td></tr>
              <tr className="separator"><td colSpan={2}></td></tr>
              <tr><td><strong>Monthly Total</strong></td><td><strong>{fmt(r.college_monthly)}</strong></td></tr>
            </tbody>
          </table>
        </section>
      )}

      {/* ─── ADDITIONAL EXPENSES ─── */}
      {state.additional_expenses.length > 0 && (
        <section className="report-section">
          <h2>Additional Recurring Expenses</h2>
          <table className="report-table">
            <tbody>
              {state.additional_expenses.map((row, i) => (
                <tr key={i}><td>{row.name}</td><td>{fmt(row.amount)}/{row.frequency === "monthly" ? "mo" : "year"}</td></tr>
              ))}
              <tr className="separator"><td colSpan={2}></td></tr>
              <tr><td><strong>Monthly Total</strong></td><td><strong>{fmt(r.additional_expenses_monthly)}</strong></td></tr>
            </tbody>
          </table>
        </section>
      )}

      {/* ─── INCOME SOURCES ─── */}
      {state.take_home_pay.length > 0 && (
        <section className="report-section">
          <h2>Take Home Income</h2>
          <table className="report-table">
            <tbody>
              {state.take_home_pay.map((row, i) => (
                <tr key={i}><td>{row.name}</td><td>{fmt(row.amount)}/{row.frequency === "monthly" ? "mo" : "year"}</td></tr>
              ))}
              <tr className="separator"><td colSpan={2}></td></tr>
              <tr><td><strong>Monthly Total</strong></td><td><strong>{fmt(r.take_home_pay_monthly)}</strong></td></tr>
            </tbody>
          </table>
        </section>
      )}

      {/* ─── CASH TO CLOSE (new purchase only) ─── */}
      {!isExisting && (
        <section className="report-section">
          <h2>Estimated Cash to Close</h2>
          <table className="report-table">
            <tbody>
              <tr><td>Prepaids & Escrow (Low est.)</td><td>{fmt(r.prepaids_escrow_low)}</td></tr>
              <tr><td>Prepaids & Escrow (High est.)</td><td>{fmt(r.prepaids_escrow_high)}</td></tr>
              <tr className="separator"><td colSpan={2}></td></tr>
              <tr><td>Cash to Close (Low)</td><td>{fmt(r.cash_to_close_low)}</td></tr>
              <tr><td>Cash to Close (High)</td><td>{fmt(r.cash_to_close_high)}</td></tr>
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
