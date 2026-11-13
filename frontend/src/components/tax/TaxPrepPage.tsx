import { useCallback, useEffect, useState } from "react";
import { taxDeleteDocument, taxGetSummary, taxListDocuments } from "../../api";
import type { TaxDocument, TaxYearSummary } from "../../types";
import ExtractedFacts from "./ExtractedFacts";
import TaxDocumentList from "./TaxDocumentList";
import TaxDocumentUpload from "./TaxDocumentUpload";
import TaxDocumentViewer from "./TaxDocumentViewer";
import TaxReconciliation from "./TaxReconciliation";

interface Props {
  year: number;
  onYearChange: (year: number) => void;
}

// Years from 2023 through next year, newest first — the chip row scrolls
// horizontally once the chips no longer fit.
const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from(
  { length: Math.max(0, CURRENT_YEAR + 1 - 2023 + 1) },
  (_, i) => CURRENT_YEAR + 1 - i,
);

const fmt = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const pct = (n: number | null | undefined) =>
  n == null ? "—" : `${(n * 100).toFixed(1)}%`;

/**
 * Tax Planning & Research. The tax picture per year, built purely from the
 * documents on file: salary per person (W-2), investments (1099-INT/DIV/B),
 * side income (1099-NEC), and the as-filed return figures as the ground truth.
 * Every number is traceable to a document; nothing is computed or estimated.
 */
export default function TaxPrepPage({ year, onYearChange }: Props) {
  const [docs, setDocs] = useState<TaxDocument[]>([]);
  const [summaries, setSummaries] = useState<TaxYearSummary[]>([]);
  const [selected, setSelected] = useState<TaxDocument | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    Promise.all([taxGetSummary(YEARS), taxListDocuments(year)])
      .then(([sums, list]) => {
        setSummaries(sums);
        setDocs(list);
        setSelected((cur) => (cur ? (list.find((d) => d.id === cur.id) ?? cur) : cur));
      })
      .catch(() => {
        setSummaries([]);
        setDocs([]);
      })
      .finally(() => setLoading(false));
  }, [year]);

  useEffect(() => {
    setSelected(null);
    refresh();
  }, [refresh]);

  const summary = summaries.find((s) => s.year === year);

  // States whose W-2 withholding we paid — used to surface states with no
  // as-filed return on file (e.g. VA withholding in a year whose only filed
  // state return was Illinois).
  const filedStateNames = (summary?.as_filed.states ?? []).map((s) => s.name);
  const withheldByState: { state: string; total: number }[] = [];
  if (summary) {
    const by = new Map<string, number>();
    for (const p of summary.salary.people) {
      if (p.state && p.state_withholding != null) {
        by.set(p.state, (by.get(p.state) ?? 0) + p.state_withholding);
      }
    }
    for (const [state, total] of by) withheldByState.push({ state, total });
  }
  const stateName = (code: string | null) =>
    code === "VA" ? "Virginia" : code === "IL" ? "Illinois" : (code ?? "");
  const unfiledStates = withheldByState.filter(
    (s) => !filedStateNames.includes(stateName(s.state)),
  );

  const handleDelete = async (doc: TaxDocument) => {
    await taxDeleteDocument(year, doc.id);
    if (selected?.id === doc.id) setSelected(null);
    refresh();
  };

  return (
    <div className="tax-prep">
      <div className="tax-head">
        <div className="tax-head-top">
          <h2>Tax Picture {year}</h2>
          <label className="tax-year-pick">
            Tax year
            <select value={year} onChange={(e) => onYearChange(Number(e.target.value))}>
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="section-hint">
          Salary, investments, and the as-filed results — every figure traceable
          to a document on file. What is owed is shown from the filed return;
          nothing here is an estimate or advice.
        </p>
      </div>

      <div className="tax-year-chips">
        {YEARS.map((y) => {
          const s = summaries.find((x) => x.year === y);
          const combined = s?.as_filed.combined ?? null;
          const line = combined && combined.net_owed != null
            ? combined.net_owed >= 0
              ? `Owe ${fmt(combined.net_owed)}`
              : `Refund ${fmt(-combined.net_owed)}`
            : s && s.salary.total_wages > 0
              ? `Wages ${fmt(s.salary.total_wages)}`
              : "No documents";
          return (
            <button
              key={y}
              type="button"
              className={y === year ? "tax-chip tax-chip-active" : "tax-chip"}
              onClick={() => onYearChange(y)}
            >
              <span className="tax-chip-year">{y}</span>
              <span className="tax-chip-line">{line}</span>
            </button>
          );
        })}
      </div>

      {summary?.as_filed.federal ? (
        <section className="tax-summary-cards">
          <div className="tax-card tax-card-federal">
            <span className="tax-pic-label">Federal — as filed</span>
            <div className="tax-kv"><span>Adjusted gross income</span><span>{fmt(summary.as_filed.federal.agi)}</span></div>
            <div className="tax-kv"><span>Taxable income</span><span>{fmt(summary.as_filed.federal.taxable_income)}</span></div>
            <div className="tax-kv"><span>Total tax</span><span>{fmt(summary.as_filed.federal.total_tax)}</span></div>
            <div className="tax-kv"><span>Payments/credits</span><span>{fmt(summary.as_filed.federal.total_payments)}</span></div>
            {summary.as_filed.federal.balance_due != null && (
              <div className="tax-kv tax-kv-due"><span>Balance due</span><span>{fmt(summary.as_filed.federal.balance_due)}</span></div>
            )}
            {summary.as_filed.derived && (
              <div className="tax-kv"><span>Effective rate</span><span>{pct(summary.as_filed.derived.effective_rate)}</span></div>
            )}
            {summary.as_filed.derived?.withholding_coverage != null && (
              <div className="tax-kv"><span>Withholding coverage</span><span>{pct(summary.as_filed.derived.withholding_coverage)}</span></div>
            )}
          </div>
          {summary.as_filed.states.map((st) => (
            <div className="tax-card tax-card-state" key={st.name ?? st.document_id}>
              <span className="tax-pic-label">{st.name} — as filed</span>
              <div className="tax-kv"><span>Taxable income</span><span>{fmt(st.taxable_income)}</span></div>
              <div className="tax-kv"><span>Total tax</span><span>{fmt(st.total_tax)}</span></div>
              <div className="tax-kv"><span>Payments/credits</span><span>{fmt(st.payments)}</span></div>
              {st.refund != null && (
                <div className="tax-kv"><span>Refund</span><span>{fmt(st.refund)}</span></div>
              )}
              {st.balance_due != null && (
                <div className="tax-kv tax-kv-due"><span>Payment due</span><span>{fmt(st.balance_due)}</span></div>
              )}
            </div>
          ))}
          {summary.as_filed.states.length === 0 && (
            <div className="tax-card tax-pic-pending">
              <span className="tax-pic-label">State</span>
              <span className="tax-pic-note">no state return on file for {year}</span>
            </div>
          )}
        </section>
      ) : (
        <section className="tax-picture-placeholder">
          <div className="tax-pic-tile tax-pic-pending">
            <span className="tax-pic-label">Federal</span>
            <span className="tax-pic-value">—</span>
            <span className="tax-pic-note">no return on file for {year}</span>
          </div>
          <div className="tax-pic-tile tax-pic-pending">
            <span className="tax-pic-label">State</span>
            <span className="tax-pic-value">—</span>
            <span className="tax-pic-note">no return on file for {year}</span>
          </div>
        </section>
      )}

      {unfiledStates.map((s) => (
        <section className="tax-summary-cards" key={s.state}>
          <div className="tax-card tax-card-state">
            <span className="tax-pic-label">
              {stateName(s.state)} — withholding paid, return not on file
            </span>
            <div className="tax-kv">
              <span>State withholding paid (per W-2)</span>
              <span>{fmt(s.total)}</span>
            </div>
          </div>
        </section>
      ))}

      <section className="tax-section">
        <h3>Salary</h3>
        {summary && summary.salary.people.length > 0 ? (
          <div className="tax-salary-table">
            {summary.salary.people.map((p) => (
              <div className="tax-kv-row" key={p.document_id}>
                <span className="tax-kv-person">{p.person ?? "—"} · {p.employer ?? "W-2"}</span>
                <span className="tax-col"><span className="tax-col-label">Wages</span><span className="tax-col-value">{fmt(p.wages)}</span></span>
                <span className="tax-col"><span className="tax-col-label">Fed WH</span><span className="tax-col-value">{fmt(p.fed_withholding)}</span></span>
                <span className="tax-col"><span className="tax-col-label">{p.state ? `${p.state} WH` : "State WH"}</span><span className="tax-col-value">{fmt(p.state_withholding)}</span></span>
              </div>
            ))}
            <div className="tax-kv-row tax-total-row">
              <span className="tax-kv-person">Household total</span>
              <span className="tax-col"><span className="tax-col-label">Wages</span><span className="tax-col-value">{fmt(summary.salary.total_wages)}</span></span>
              <span className="tax-col"><span className="tax-col-label">Fed WH</span><span className="tax-col-value">{fmt(summary.salary.total_fed_withholding)}</span></span>
              <span className="tax-col"><span className="tax-col-label">State WH</span><span className="tax-col-value">{fmt(summary.salary.total_state_withholding)}</span></span>
            </div>
            <p className="section-hint">
              $/hour combined and per person appears once a final-of-year paystub
              (with hours) is on file for each person.
            </p>
          </div>
        ) : (
          <p className="section-hint">No W-2 documents extracted for {year} yet.</p>
        )}
      </section>

      {summary && summary.investments.statements.length > 0 && (
        <section className="tax-section">
          <h3>Investments</h3>
          {summary.investments.statements.map((st) => (
            <div className="tax-kv-block" key={st.document_id}>
              <div className="tax-kv"><span>Payer</span><span>{st.payer ?? "—"}</span></div>
              {st.interest != null && <div className="tax-kv"><span>Interest income</span><span>{fmt(st.interest)}</span></div>}
              {st.dividends_ordinary != null && <div className="tax-kv"><span>Ordinary dividends</span><span>{fmt(st.dividends_ordinary)}</span></div>}
              {st.dividends_qualified != null && <div className="tax-kv"><span>Qualified dividends</span><span>{fmt(st.dividends_qualified)}</span></div>}
              {st.dividends_199a != null && <div className="tax-kv"><span>§199A dividends</span><span>{fmt(st.dividends_199a)}</span></div>}
              {st.nondividend_distributions != null && <div className="tax-kv"><span>Nondividend distributions (return of capital)</span><span>{fmt(st.nondividend_distributions)}</span></div>}
              {st.st_realized_gain != null && <div className="tax-kv"><span>Short-term realized gain</span><span>{fmt(st.st_realized_gain)}</span></div>}
              {st.st_realized_loss != null && <div className="tax-kv"><span>Short-term realized loss</span><span>{fmt(st.st_realized_loss)}</span></div>}
              {st.lt_realized_gain != null && <div className="tax-kv"><span>Long-term realized gain</span><span>{fmt(st.lt_realized_gain)}</span></div>}
              {st.lt_realized_loss != null && <div className="tax-kv"><span>Long-term realized loss</span><span>{fmt(st.lt_realized_loss)}</span></div>}
            </div>
          ))}
          <p className="section-hint">
            Interest total {fmt(summary.investments.total_interest)} · Net realized
            gain/loss {fmt(summary.investments.net_realized_gain_loss)}
          </p>
        </section>
      )}

      {summary && summary.side_income.entries.length > 0 && (
        <section className="tax-section">
          <h3>Side income (Schedule C input)</h3>
          {summary.side_income.entries.map((e) => (
            <div className="tax-kv" key={e.document_id}>
              <span>{e.payer ?? "1099-NEC"} · {e.person ?? "—"}</span>
              <span>{fmt(e.amount)}</span>
            </div>
          ))}
        </section>
      )}

      {summary && summary.informational.length > 0 && (
        <section className="tax-section">
          <h3>Informational (no income unless traded/used)</h3>
          {summary.informational.map((i) => (
            <div className="tax-kv" key={i.document_id}>
              <span>{i.form_type}</span>
              <span>{i.label ?? "—"}</span>
            </div>
          ))}
        </section>
      )}

      <section className="tax-section">
        <h3>Documents</h3>
        <TaxDocumentUpload year={year} onUploaded={refresh} />
        {loading ? (
          <p className="section-hint">Loading…</p>
        ) : (
          <TaxDocumentList
            documents={docs}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
            onDelete={handleDelete}
          />
        )}
      </section>

      <section className="tax-section">
        <h3>Household reconciliation</h3>
        <TaxReconciliation year={year} />
      </section>

      <section className="tax-section">
        <h3>Extracted facts</h3>
        <ExtractedFacts year={year} doc={selected} onChanged={refresh} />
      </section>

      <section className="tax-section">
        <h3>Original</h3>
        <TaxDocumentViewer year={year} doc={selected} />
      </section>
    </div>
  );
}
