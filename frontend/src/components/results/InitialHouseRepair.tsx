import { useEffect, useState } from "react";
import { plaidActuals, type InitialHouseRepair as IHR } from "../../api";

const fmt = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

/**
 * Initial House Repair — a running total of the one-time, move-in capital repairs
 * (roof, HVAC, plumbing, electrical, fireplace, etc.). These are deliberately
 * EXCLUDED from the budget-vs-actual reconciliation (they are not recurring
 * spend); this card is their own ledger. The headline grand total stays visible
 * even when collapsed, and it grows as older emails/checks/bank records are
 * backfilled into the "Initial House Repair" category.
 */
export default function InitialHouseRepair() {
  const [ihr, setIhr] = useState<IHR | null>(null);
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    plaidActuals()
      .then((a) => setIhr(a.initial_house_repair ?? null))
      .catch(() => setIhr(null));
  }, []);

  // Nothing recorded yet (or the actuals JSON predates this feature): stay quiet.
  if (!ihr || ihr.count === 0) return null;

  const years = Object.keys(ihr.by_year).sort();

  return (
    <div className="chart-container ihr">
      <div className="chart-header">
        <button
          type="button"
          className="chart-toggle"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? "▶" : "▼"} Initial House Repair
        </button>
        <span className="ihr-total" title="Running total of one-time move-in repairs">
          {fmt(ihr.total)}
        </span>
      </div>

      <p className="section-hint ihr-note">
        One-time move-in repairs ({ihr.count} item{ihr.count === 1 ? "" : "s"}),
        excluded from the budget. This total grows as older records are added.
      </p>

      {!collapsed && (
        <div className="chart-body">
          <dl className="ihr-grid">
            <div className="ihr-head">
              <dt>Date</dt>
              <dd>Item</dd>
              <dd>Amount</dd>
            </div>
            {ihr.items.map((it, i) => (
              <div className="ihr-row" key={`${it.date}-${i}`}>
                <dt>{it.date}</dt>
                <dd title={it.name}>{it.label || it.name}</dd>
                <dd className="ihr-amt">{fmt(it.amount)}</dd>
              </div>
            ))}
            <div className="ihr-row ihr-footer">
              <dt></dt>
              <dd>Total</dd>
              <dd className="ihr-amt">{fmt(ihr.total)}</dd>
            </div>
          </dl>
          {years.length > 1 && (
            <p className="section-hint">
              By year: {years.map((y) => `${y} ${fmt(ihr.by_year[y])}`).join("  ·  ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
