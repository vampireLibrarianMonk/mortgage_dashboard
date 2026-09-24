import { useCallback, useEffect, useState } from "react";
import { balancesRefresh, balancesSnapshot } from "../../api";
import type { BalanceSnapshotAccount } from "../../api";
import type { CalculateResponse, TimelinePlan } from "../../types";
import AccountDipStrip from "./AccountDipStrip";
import AdjustmentRows from "./AdjustmentRows";
import RunwayChart from "./RunwayChart";
import SpanView from "./SpanView";
import TimelineRows from "./TimelineRows";

interface Props {
  plan: TimelinePlan;
  onChange: (plan: TimelinePlan) => void;
  result: CalculateResponse | null;
  address: string;
  onSave: (address: string) => Promise<void>;
}

const fmt = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

/**
 * Timeline Builder — a generic forward-looking planner. Place labeled cost
 * "timelines" (with start/end + escalation + optional purchase funding) and flat
 * "adjustments" (+save / -spend), and see the projected monthly-leftover runway.
 *
 * Editing the plan updates state.timeline_plan, which auto-recalculates
 * (useCalculation debounce) and refreshes result.timeline_projection.
 */
export default function TimelinePage({ plan, onChange, result, address, onSave }: Props) {
  const settings = plan.settings;
  const setSettings = (patch: Partial<typeof settings>) =>
    onChange({ ...plan, settings: { ...settings, ...patch } });

  // Save-to-profile control. The profile address is chosen only on the Dashboard;
  // here we simply save to whatever address is currently selected there. No inline
  // address entry — the Dashboard is the single point of edit for the selection.
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const savedAddress = address.trim();

  const handleSave = async () => {
    if (!savedAddress) return;
    setSaveStatus("saving");
    try {
      await onSave(savedAddress);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2500);
    } catch {
      setSaveStatus("error");
    }
  };

  const projection = result?.timeline_projection ?? [];
  const summary = result?.timeline_summary ?? {};
  const firstNeg = summary.first_negative_period ?? null;
  const negativeWindows = summary.negative_windows ?? [];
  const accountSeries = result?.timeline_accounts ?? [];

  // Funding-account balances (persisted snapshots; ⟳ triggers a live refresh).
  const [accounts, setAccounts] = useState<BalanceSnapshotAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    balancesSnapshot()
      .then((a) => {
        if (!cancelled) setAccounts(a);
      })
      .catch(() => {
        /* snapshot is best-effort; funding still works with manual accounts */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshAccounts = useCallback(() => {
    setAccountsLoading(true);
    balancesRefresh()
      .then(setAccounts)
      .catch(() => {
        /* leave the last-known snapshot in place on failure */
      })
      .finally(() => setAccountsLoading(false));
  }, []);

  return (
    <div className="timeline-builder">
      <div className="tl-head">
        <div className="tl-head-top">
          <h2>Timeline Builder</h2>
          <div className="tl-save">
            {savedAddress ? (
              <span className="tl-save-target" title="Profile is selected on the Dashboard">
                {savedAddress}
              </span>
            ) : (
              <span className="tl-save-none">No profile selected — choose one on the Dashboard</span>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={!savedAddress || saveStatus === "saving"}
              title={savedAddress ? `Save to "${savedAddress}"` : "Select a profile on the Dashboard first"}
            >
              {saveStatus === "saving" ? "Saving…" : "Save to profile"}
            </button>
            {saveStatus === "saved" && <span className="tl-save-ok">✔ saved</span>}
            {saveStatus === "error" && <span className="tl-save-err">save failed</span>}
          </div>
        </div>
        <p className="section-hint">
          Plan future costs and purchases on a shared time axis and see how they
          draw down your monthly leftover. This is a forward-looking estimate
          (best-guess capital allocation), separate from your Dashboard budget.
          Saving writes the whole profile (budget + timeline) to this address.
        </p>
      </div>

      <section className="tl-settings">
        <label>
          Starting monthly leftover
          <input
            type="number"
            value={settings.starting_leftover}
            disabled={settings.carry_over_leftover}
            onChange={(e) => setSettings({ starting_leftover: Number(e.target.value) })}
          />
        </label>
        <label className="tl-checkbox">
          <input
            type="checkbox"
            checked={settings.carry_over_leftover}
            onChange={(e) => setSettings({ carry_over_leftover: e.target.checked })}
          />
          carry over from Dashboard{" "}
          {settings.carry_over_leftover && result && (
            <span className="tl-muted">({fmt(result.monthly_leftover)}/mo)</span>
          )}
        </label>
        <label>
          Horizon (years)
          <input
            type="number"
            min={1}
            max={50}
            value={settings.horizon_years}
            onChange={(e) => setSettings({ horizon_years: Number(e.target.value) })}
          />
        </label>
      </section>

      <TimelineRows
        timelines={plan.timelines}
        onChange={(timelines) => onChange({ ...plan, timelines })}
        accounts={accounts}
        accountsLoading={accountsLoading}
        onRefreshAccounts={refreshAccounts}
      />

      <AdjustmentRows
        adjustments={plan.adjustments}
        onChange={(adjustments) => onChange({ ...plan, adjustments })}
      />

      <section className="tl-summary">
        <p className="section-hint">
          {plan.timelines.length} timeline(s), {plan.adjustments.length} adjustment(s).
          {" "}Projection points: {projection.length}.
        </p>
        {firstNeg ? (
          <div className="tl-warn">
            <p>
              ⚠ leftover goes negative — add adjustments or reduce timelines (or
              adjust the budget on the Dashboard to cover it).
            </p>
            <ul className="tl-neg-windows">
              {negativeWindows.map((w) => (
                <li key={w.start}>
                  <span
                    className="tl-neg-span"
                    title={`Negative every month from ${w.start} through ${w.end}, both endpoints included`}
                  >
                    {w.start} – {w.end} (incl.)
                  </span>
                  <span
                    className="tl-neg-months"
                    title="Count of negative months, inclusive of the first and last month"
                  >
                    {w.months} mo (incl.)
                  </span>
                  <span className="tl-neg-short">{fmt(w.shortfall)} shortfall</span>
                  <span className="tl-neg-deep">
                    deepest {fmt(w.deepest)} ({w.deepest_period})
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : projection.length > 0 ? (
          <p className="tl-ok">✔ leftover stays non-negative across the horizon.</p>
        ) : (
          <p className="section-hint">Add a timeline to see the projected runway.</p>
        )}
      </section>

      {plan.timelines.length > 0 && (
        <section className="tl-viz">
          <h3>Span view</h3>
          <p className="section-hint">
            Each bar shows when a timeline is active across the horizon. Bars with a
            dot include a purchase event.
          </p>
          <SpanView timelines={plan.timelines} settings={settings} />
        </section>
      )}

      {projection.length > 0 && (
        <section className="tl-viz">
          <h3>Runway</h3>
          <p className="section-hint">
            Solid line is the raw monthly leftover; dashed line adds your
            adjustments. The red line is zero.
          </p>
          <RunwayChart
            projection={projection}
            firstNegative={firstNeg}
            negativeWindows={negativeWindows}
          />
        </section>
      )}

      {accountSeries.length > 0 && (
        <section className="tl-viz">
          <h3>Account balances</h3>
          <p className="section-hint">
            Projected balance of each funding account, stepping down on purchase
            draws (seeded from the latest synced balance).
          </p>
          <AccountDipStrip accounts={accountSeries} />
        </section>
      )}
    </div>
  );
}
