import { useEffect, useState } from "react";
import { plaidActuals, type InitialHouseRepair as IHR } from "../../api";

interface Props {
  // The active profile (property) id. When set, the ledger is scoped to that
  // property; when a property has no repairs yet, an empty skeleton is shown so
  // there's always a place to fill for the next property.
  profileId?: string | null;
}

const fmt = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

const EMPTY: IHR = { total: 0, by_year: {}, items: [], count: 0 };

/**
 * Initial House Repair — a running total of the one-time, move-in capital repairs
 * (roof, HVAC, plumbing, electrical, fireplace, etc.) for the active property.
 * These are deliberately EXCLUDED from the budget-vs-actual reconciliation (they
 * are not recurring spend); this card is their own per-property ledger. The
 * headline total stays visible even when collapsed and grows as older
 * emails/checks/bank records are backfilled. The card is ALWAYS shown (even at
 * $0) so a newly saved property has a blank move-in ledger ready to fill.
 */
export default function InitialHouseRepair({ profileId }: Props) {
  const [ihr, setIhr] = useState<IHR | null>(null);
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    let cancelled = false;
    plaidActuals(profileId)
      .then((a) => { if (!cancelled) setIhr(a.initial_house_repair ?? EMPTY); })
      .catch(() => { if (!cancelled) setIhr(EMPTY); });
    return () => { cancelled = true; };
  }, [profileId]);

  // Until the first fetch resolves, render nothing (avoids a flash of $0).
  if (ihr === null) return null;

  const empty = ihr.count === 0;
  const years = Object.keys(ihr.by_year).sort();

  return (
    <div className="chart-container ihr">
      <div className="chart-header">
        <button
          type="button"
          className="chart-toggle"
          onClick={() => setCollapsed(!collapsed)}
          disabled={empty}
        >
          {empty ? "" : collapsed ? "▶ " : "▼ "}Initial House Repair
        </button>
        <span className="ihr-total" title="Running total of one-time move-in repairs">
          {fmt(ihr.total)}
        </span>
      </div>

      {empty ? (
        <p className="section-hint ihr-note">
          No move-in repairs recorded yet for this property. One-time repairs
          (roof, HVAC, electrical, etc.) tagged to this profile will total here,
          excluded from the budget.
        </p>
      ) : (
        <>
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
        </>
      )}
    </div>
  );
}
