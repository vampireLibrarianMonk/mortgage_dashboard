import { useEffect, useState } from "react";
import { plaidActuals, type PlaidActuals, type ActualsCategoryTotals } from "../../api";
import type { CalculateResponse } from "../../types";

interface Props {
  result: CalculateResponse;
}

const CATS: (keyof ActualsCategoryTotals)[] = [
  "Mortgage", "Household", "Utilities", "Vehicle", "ChildCare", "PetCare", "Discretionary",
];

const fmt = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

/**
 * Budget vs Actual, sourced from the standalone pipeline's aggregates-only JSON
 * (per-month + yearly category totals). The monthly budget targets come from the
 * currently loaded profile's computed category monthlies, so variance reflects
 * whatever profile is active. No transactions or balances are shown here.
 */
const monthLabel = (mk: string) => {
  const [y, m] = mk.split("-");
  const name = new Date(Number(y), Number(m) - 1, 1).toLocaleString("en-US", { month: "long" });
  return `${name} ${y}`;
};

export default function BudgetVsActual({ result }: Props) {
  const [actuals, setActuals] = useState<PlaidActuals | null>(null);
  const [error, setError] = useState<string | null>(null);
  // "" = YTD (all months); otherwise a month key like "2026-09".
  const [period, setPeriod] = useState<string>("");

  useEffect(() => {
    plaidActuals().then(setActuals).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Map the app's computed monthly totals to the pipeline's category names.
  // Mortgage here = planned mortgage outflow (P&I + escrow + extra principal).
  const budget: ActualsCategoryTotals = {
    Mortgage: result.planned_mortgage_outflow_monthly,
    Household: result.household_monthly,
    Utilities: result.utilities_monthly,
    Vehicle: result.vehicle_monthly,
    ChildCare: result.child_care_monthly,
    PetCare: result.pet_care_monthly,
    Discretionary: result.discretionary_total_monthly,
  };

  if (error) return null; // stay quiet if the endpoint isn't reachable
  if (!actuals) return null;
  if (!actuals.available || actuals.years.length === 0) {
    return (
      <section>
        <h3>Budget vs Actual</h3>
        <p className="section-hint">
          No bank actuals yet. Run the transaction pipeline to populate this.
        </p>
      </section>
    );
  }

  // The selected period: a single month, or YTD (all months summed). The budget
  // target scales by how many months the period covers (monthly target x N).
  const selectedMonth = period ? actuals.months.find((m) => m.month === period) : null;
  const isYtd = !period;
  const periodMonthCount = isYtd ? (actuals.months.length || 1) : 1;
  const catActual = (c: keyof ActualsCategoryTotals): number => {
    if (selectedMonth) return selectedMonth.categories[c] ?? 0;
    // YTD: sum every month (years[] only covers a single year; summing months is
    // correct across any span of available history).
    return actuals.months.reduce((s, m) => s + (m.categories[c] ?? 0), 0);
  };
  const unbudgeted = selectedMonth
    ? selectedMonth.unbudgeted_outflow
    : actuals.months.reduce((s, m) => s + m.unbudgeted_outflow, 0);
  const budgetLabel = isYtd ? "Budget (YTD)" : "Budget";
  const actualLabel = isYtd ? "Actual (YTD)" : "Actual";
  const heading = isYtd
    ? `YTD — ${periodMonthCount} month${periodMonthCount === 1 ? "" : "s"}`
    : monthLabel(period);

  return (
    <section className="bva">
      <div className="bva-title">
        <h3>Budget vs Actual — {heading}</h3>
        <label className="bva-period">
          Period{" "}
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="">Year to date (all months)</option>
            {actuals.months.map((m) => (
              <option key={m.month} value={m.month}>{monthLabel(m.month)}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="section-hint">
        Actuals from linked banks (aggregated), compared against the loaded profile's budget.
        Positive variance = over budget.
      </p>
      <dl className="bva-grid">
        <div className="bva-head">
          <dt>Category</dt>
          <dd>{budgetLabel}</dd>
          <dd>{actualLabel}</dd>
          <dd>Variance</dd>
        </div>
        {CATS.map((c) => {
          const periodBudget = budget[c] * periodMonthCount;
          const periodActual = catActual(c);
          const variance = periodActual - periodBudget;
          return (
            <div className="bva-row" key={c}>
              <dt>{c}</dt>
              <dd>{fmt(periodBudget)}</dd>
              <dd>{fmt(periodActual)}</dd>
              <dd className={variance > 0 ? "negative" : "positive"}>
                {variance > 0 ? "+" : ""}{fmt(variance)}
              </dd>
            </div>
          );
        })}
      </dl>
      {unbudgeted > 0 && (
        <p className="section-hint">
          Plus {fmt(unbudgeted)} of unbudgeted outflow (transfers, card payments, misc)
          with no budget line to compare against.
        </p>
      )}
      <p className="section-hint">
        {isYtd
          ? `Covering ${periodMonthCount} month${periodMonthCount === 1 ? "" : "s"} of available bank history.`
          : "Single-month view. Switch the period selector for other months or year-to-date."}
      </p>
    </section>
  );
}
