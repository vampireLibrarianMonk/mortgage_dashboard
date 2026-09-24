import { useState } from "react";
import type { BalanceSnapshotAccount } from "../../api";
import type {
  AmountUnit,
  EscalationUnit,
  Purchase,
  PurchaseMethod,
  Timeline,
} from "../../types";
import { TIMELINE_CATEGORIES, newPurchase, newTimeline } from "./constants";

interface Props {
  timelines: Timeline[];
  onChange: (timelines: Timeline[]) => void;
  accounts: BalanceSnapshotAccount[];
  accountsLoading: boolean;
  onRefreshAccounts: () => void;
}

const fmtBal = (n: number | null) =>
  n == null
    ? "—"
    : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function accountLabel(a: BalanceSnapshotAccount): string {
  const bank = a.bank ?? "bank";
  const mask = a.mask ?? "----";
  const name = a.name ? ` ${a.name}` : "";
  return `${bank} ••${mask}${name} — ${fmtBal(a.balance)}`;
}

/**
 * The timelines builder table. Each row is a labeled recurring cost with a
 * start/end span, base amount + unit, yearly escalation, and an optional
 * purchase-funding panel (⚙) that turns the row into a one-time or financed
 * purchase drawn from a chosen account.
 */
export default function TimelineRows({
  timelines,
  onChange,
  accounts,
  accountsLoading,
  onRefreshAccounts,
}: Props) {
  const [openFunding, setOpenFunding] = useState<number | null>(null);

  const update = (i: number, patch: Partial<Timeline>) =>
    onChange(timelines.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  const remove = (i: number) => {
    onChange(timelines.filter((_, idx) => idx !== i));
    if (openFunding === i) setOpenFunding(null);
  };
  const add = () => onChange([...timelines, newTimeline()]);

  const updatePurchase = (i: number, patch: Partial<Purchase>) => {
    const row = timelines[i];
    const base = row.purchase ?? newPurchase();
    update(i, { purchase: { ...base, ...patch } });
  };

  const toggleFundingRow = (i: number) => {
    const row = timelines[i];
    if (!row.purchase) update(i, { purchase: newPurchase() });
    setOpenFunding(openFunding === i ? null : i);
  };

  return (
    <fieldset className="tl-timelines">
      <legend>Timelines</legend>
      <p className="section-hint">
        Each row is a labeled cost on the time axis. Set the <strong>end</strong>{" "}
        month to when the cost stops (e.g. daycare ending Oct 2029) — leave it blank
        (ongoing) for a cost with no end. Escalation applies every year from the start.
      </p>

      {timelines.length === 0 && <p className="tl-empty">No timelines yet.</p>}

      {timelines.map((row, i) => (
        <div key={i} className="tl-row-wrap">
          <div className="tl-row">
            <input
              className="tl-label"
              placeholder="Label (e.g. Childcare, New SUV)"
              value={row.label}
              onChange={(e) => update(i, { label: e.target.value })}
            />
            <select
              className="tl-cat"
              value={row.category}
              onChange={(e) => update(i, { category: e.target.value })}
            >
              {TIMELINE_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <label className="tl-month">
              start
              <input
                type="month"
                value={row.start}
                onChange={(e) => update(i, { start: e.target.value })}
              />
            </label>
            <label className="tl-month">
              <span className="tl-month-cap">
                end
                {row.end ? (
                  <button
                    type="button"
                    className="tl-end-clear"
                    title="Clear end (make ongoing)"
                    onClick={() => update(i, { end: null })}
                  >
                    ongoing ×
                  </button>
                ) : (
                  <span className="tl-end-ongoing" title="No end date set — this cost runs to the horizon">
                    ongoing
                  </span>
                )}
              </span>
              <input
                type="month"
                value={row.end ?? ""}
                min={row.start || undefined}
                onChange={(e) => update(i, { end: e.target.value || null })}
              />
            </label>
            <input
              className="tl-base"
              type="number"
              placeholder="Base"
              value={row.base}
              onChange={(e) => update(i, { base: Number(e.target.value) })}
            />
            <select
              className="tl-unit"
              value={row.unit}
              onChange={(e) => update(i, { unit: e.target.value as AmountUnit })}
            >
              <option value="month">/mo</option>
              <option value="year">/yr</option>
            </select>
            <span className="tl-esc-label">esc</span>
            <input
              className="tl-esc"
              type="number"
              placeholder="0"
              value={row.escalation_value}
              onChange={(e) => update(i, { escalation_value: Number(e.target.value) })}
            />
            <select
              className="tl-esc-unit"
              value={row.escalation_unit}
              onChange={(e) => update(i, { escalation_unit: e.target.value as EscalationUnit })}
            >
              <option value="percent">%/yr</option>
              <option value="dollar">$/yr</option>
            </select>
            <button
              type="button"
              className={row.purchase ? "tl-funding-btn active" : "tl-funding-btn"}
              title="Purchase funding"
              onClick={() => toggleFundingRow(i)}
            >
              ⚙ Funding
            </button>
            <button type="button" className="tl-remove" onClick={() => remove(i)}>
              ×
            </button>
          </div>

          {openFunding === i && row.purchase && (
            <FundingPanel
              purchase={row.purchase}
              onChange={(patch) => updatePurchase(i, patch)}
              onClear={() => {
                update(i, { purchase: null });
                setOpenFunding(null);
              }}
              accounts={accounts}
              accountsLoading={accountsLoading}
              onRefreshAccounts={onRefreshAccounts}
            />
          )}
        </div>
      ))}

      <button type="button" className="tl-add" onClick={add}>
        + Add timeline
      </button>
    </fieldset>
  );
}

interface FundingProps {
  purchase: Purchase;
  onChange: (patch: Partial<Purchase>) => void;
  onClear: () => void;
  accounts: BalanceSnapshotAccount[];
  accountsLoading: boolean;
  onRefreshAccounts: () => void;
}

function FundingPanel({
  purchase,
  onChange,
  onClear,
  accounts,
  accountsLoading,
  onRefreshAccounts,
}: FundingProps) {
  const methods: { value: PurchaseMethod; label: string }[] = [
    { value: "pay_in_full", label: "Pay in full" },
    { value: "payment_plan", label: "Payment plan" },
    { value: "already_paid", label: "Already paid" },
  ];

  return (
    <div className="tl-funding-panel">
      <div className="tl-funding-head">
        <strong>Purchase funding</strong>
        <button type="button" className="tl-funding-clear" onClick={onClear}>
          remove funding
        </button>
      </div>

      <div className="tl-funding-grid">
        <label>
          Purchase amount
          <input
            type="number"
            value={purchase.amount}
            onChange={(e) => onChange({ amount: Number(e.target.value) })}
          />
        </label>

        <div className="tl-methods">
          {methods.map((m) => (
            <label key={m.value} className="tl-radio">
              <input
                type="radio"
                name={`method-${purchase.account ?? ""}-${purchase.amount}`}
                checked={purchase.method === m.value}
                onChange={() => onChange({ method: m.value })}
              />
              {m.label}
            </label>
          ))}
        </div>

        {purchase.method === "payment_plan" && (
          <>
            <label>
              Down payment
              <input
                type="number"
                value={purchase.down_payment}
                onChange={(e) => onChange({ down_payment: Number(e.target.value) })}
              />
            </label>
            <label>
              APR %
              <input
                type="number"
                value={purchase.apr}
                onChange={(e) => onChange({ apr: Number(e.target.value) })}
              />
            </label>
            <label>
              Term (months)
              <input
                type="number"
                value={purchase.term_months}
                onChange={(e) => onChange({ term_months: Number(e.target.value) })}
              />
            </label>
          </>
        )}

        {purchase.method !== "already_paid" && (
          <label className="tl-account">
            Draw from account
            <div className="tl-account-row">
              <select
                value={purchase.account ?? ""}
                onChange={(e) => onChange({ account: e.target.value || null })}
              >
                <option value="">(don't track an account)</option>
                {accounts.map((a) => (
                  <option key={a.key} value={a.key}>
                    {accountLabel(a)}
                  </option>
                ))}
                <option value="other">Other / manual</option>
              </select>
              <button
                type="button"
                className="tl-refresh"
                title="Refresh balances from banks"
                disabled={accountsLoading}
                onClick={onRefreshAccounts}
              >
                {accountsLoading ? "…" : "⟳"}
              </button>
            </div>
          </label>
        )}
      </div>
    </div>
  );
}
