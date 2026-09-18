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
export default function BudgetVsActual({ result }: Props) {
  const [actuals, setActuals] = useState<PlaidActuals | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const year = actuals.years[actuals.years.length - 1];
  const monthsCount = actuals.months.length || 1;

  return (
    <section className="bva">
      <h3>Budget vs Actual — {year.year}</h3>
      <p className="section-hint">
        Actuals from linked banks (aggregated), compared against the loaded profile's budget.
        Positive variance = over budget.
      </p>
      <dl className="bva-grid">
        <div className="bva-head">
          <dt>Category</dt>
          <dd>Budget (YTD)</dd>
          <dd>Actual (YTD)</dd>
          <dd>Variance</dd>
        </div>
        {CATS.map((c) => {
          const ytdBudget = budget[c] * monthsCount;
          const ytdActual = year.categories[c] ?? 0;
          const variance = ytdActual - ytdBudget;
          return (
            <div className="bva-row" key={c}>
              <dt>{c}</dt>
              <dd>{fmt(ytdBudget)}</dd>
              <dd>{fmt(ytdActual)}</dd>
              <dd className={variance > 0 ? "negative" : "positive"}>
                {variance > 0 ? "+" : ""}{fmt(variance)}
              </dd>
            </div>
          );
        })}
      </dl>
      {year.unbudgeted_outflow > 0 && (
        <p className="section-hint">
          Plus {fmt(year.unbudgeted_outflow)} of unbudgeted outflow (transfers, card payments, misc)
          with no budget line to compare against.
        </p>
      )}
      <p className="section-hint">
        Covering {monthsCount} month{monthsCount === 1 ? "" : "s"} of available bank history.
      </p>
    </section>
  );
}
