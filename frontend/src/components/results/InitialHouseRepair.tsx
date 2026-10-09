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

// "2026-04-17" -> "Apr 17, 2026" (no timezone shift: parse the parts directly).
const fmtDate = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
};

const EMPTY: IHR = { total: 0, by_year: {}, items: [], count: 0 };

/**
 * Initial House Repair — a running total of the one-time, move-in capital repairs
 * (roof, HVAC, plumbing, electrical, fireplace, etc.) for the active property.
 * Excluded from the budget-vs-actual reconciliation; this card is its own
 * per-property ledger. The headline total stays visible when collapsed and grows
 * as older records are backfilled. The card is ALWAYS shown (even at $0) so a
 * newly saved property has a blank move-in ledger ready to fill.
 */
export default function InitialHouseRepair({ profileId }: Props) {
  const [ihr, setIhr] = useState<IHR | null>(null);
  const [collapsed, setCollapsed] = useState(false);

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
    <section className="ihr-card">
      <header
        className="ihr-card-head"
        onClick={() => !empty && setCollapsed(!collapsed)}
        role={empty ? undefined : "button"}
        tabIndex={empty ? undefined : 0}
      >
        <div className="ihr-head-left">
          {!empty && <span className="ihr-caret">{collapsed ? "▸" : "▾"}</span>}
          <div className="ihr-head-titles">
            <span className="ihr-title">Initial House Repair</span>
            <span className="ihr-subtitle">
              {empty
                ? "No move-in repairs recorded yet for this property"
                : `${ihr.count} one-time repair${ihr.count === 1 ? "" : "s"} · excluded from budget`}
            </span>
          </div>
        </div>
        <span className="ihr-grand">{fmt(ihr.total)}</span>
      </header>

      {empty && (
        <p className="ihr-empty-hint">
          One-time repairs (roof, HVAC, electrical, etc.) tagged to this property
          will total here, kept separate from your monthly budget.
        </p>
      )}

      {!empty && !collapsed && (
        <>
          <ul className="ihr-list">
            {ihr.items.map((it, i) => (
              <li className="ihr-item" key={`${it.date}-${i}`}>
                <div className="ihr-item-main">
                  <span className="ihr-vendor">{it.vendor}</span>
                  {it.work && <span className="ihr-work">{it.work}</span>}
                </div>
                <div className="ihr-item-meta">
                  <span className="ihr-date">{fmtDate(it.date)}</span>
                  {it.source && <span className="ihr-source">{it.source}</span>}
                </div>
                <span className="ihr-amount">{fmt(it.amount)}</span>
              </li>
            ))}
          </ul>
          <footer className="ihr-foot">
            {years.length > 1 && (
              <span className="ihr-byyear">
                {years.map((y) => `${y}: ${fmt(ihr.by_year[y])}`).join("   ")}
              </span>
            )}
            <span className="ihr-foot-total">
              <span className="ihr-foot-label">Total</span>
              <span className="ihr-amount">{fmt(ihr.total)}</span>
            </span>
          </footer>
        </>
      )}
    </section>
  );
}
