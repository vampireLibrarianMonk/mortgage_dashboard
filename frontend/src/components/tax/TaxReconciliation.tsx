import { useCallback, useEffect, useState } from "react";
import { taxReconcile } from "../../api";
import type {
  HouseholdReconciliation,
  PersonReconciliation,
  ReconcileLine,
  ReconcileVerdict,
} from "../../types";

interface Props {
  year: number;
}

const fmtMoney = (n: number | null): string =>
  n === null || n === undefined
    ? "—"
    : n.toLocaleString(undefined, { style: "currency", currency: "USD" });

const VERDICT_LABEL: Record<ReconcileVerdict, string> = {
  match: "match",
  explainable_delta: "explainable",
  mismatch: "check",
  w2_only: "W-2 only",
  paystub_only: "paystub only",
  missing: "no data",
};

function VerdictBadge({ verdict }: { verdict: ReconcileVerdict }) {
  return (
    <span className={`recon-verdict recon-verdict-${verdict}`}>
      {VERDICT_LABEL[verdict]}
    </span>
  );
}

function LineRow({ line }: { line: ReconcileLine }) {
  return (
    <div className="recon-row" title={line.note}>
      <span className="recon-label">{line.label}</span>
      <span className="recon-num">{fmtMoney(line.w2_value)}</span>
      <span className="recon-num">{fmtMoney(line.paystub_value)}</span>
      <span className="recon-num recon-delta">
        {line.delta === null ? "" : fmtMoney(line.delta)}
      </span>
      <VerdictBadge verdict={line.verdict} />
    </div>
  );
}

function PersonCard({ person }: { person: PersonReconciliation }) {
  return (
    <div className="recon-person">
      <div className="recon-person-head">
        <span className="recon-person-name">{person.person}</span>
        {person.employer && <span className="recon-person-emp">{person.employer}</span>}
      </div>
      <p className="recon-person-summary">{person.summary}</p>
      <div className="recon-table">
        <div className="recon-row recon-head" aria-hidden="true">
          <span>Line</span>
          <span className="recon-num">W-2</span>
          <span className="recon-num">Paystub</span>
          <span className="recon-num">Δ</span>
          <span>Check</span>
        </div>
        {person.lines.map((ln) => (
          <LineRow key={ln.key} line={ln} />
        ))}
      </div>
    </div>
  );
}

function HouseholdPanel({ h }: { h: HouseholdReconciliation }) {
  const t = h.totals;
  return (
    <div className="recon-household">
      <h4>Household W-2 totals — {h.tax_year}</h4>
      <div className="recon-tiles">
        <div className="recon-tile">
          <span className="recon-tile-label">Total wages (Box 1)</span>
          <span className="recon-tile-value">{fmtMoney(t.total_wages)}</span>
        </div>
        <div className="recon-tile">
          <span className="recon-tile-label">Federal withheld</span>
          <span className="recon-tile-value">{fmtMoney(t.total_fed_withheld)}</span>
        </div>
        <div className="recon-tile">
          <span className="recon-tile-label">Virginia withheld</span>
          <span className="recon-tile-value">{fmtMoney(t.total_state_withheld)}</span>
        </div>
      </div>
      {t.people_missing_w2.length > 0 && (
        <p className="recon-missing">
          Not included (W-2 unreadable or missing): {t.people_missing_w2.join(", ")}.
        </p>
      )}
      <p className="recon-disclaimer">
        These are the raw inputs a filing would start from — wages earned and tax
        already withheld. The actual federal and Virginia tax owed or refunded is
        not computed yet; that needs the filing engine (a later phase).
      </p>
    </div>
  );
}

/**
 * Household reconciliation: cross-checks each person's W-2 against the full-year
 * totals rebuilt from their paystubs, and rolls the W-2 figures into a household
 * total. Honest about asymmetry — a person with only a W-2 (no paystubs) shows
 * "W-2 only" lines; a person whose W-2 didn't read shows paystub-derived values.
 */
export default function TaxReconciliation({ year }: Props) {
  const [data, setData] = useState<HouseholdReconciliation | null>(null);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ran, setRan] = useState(false);

  const run = useCallback(() => {
    setLoading(true);
    setError("");
    taxReconcile(year)
      .then((res) => {
        setData(res.reconciliation);
        setNote(res.note ?? "");
        setRan(true);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "reconciliation failed"))
      .finally(() => setLoading(false));
  }, [year]);

  // Reset when the year changes so stale numbers never linger.
  useEffect(() => {
    setData(null);
    setNote("");
    setRan(false);
    setError("");
  }, [year]);

  return (
    <div className="recon">
      <div className="recon-actions">
        <button type="button" className="recon-run" disabled={loading} onClick={run}>
          {loading ? "Reconciling…" : "Run reconciliation"}
        </button>
        <span className="recon-hint">
          Cross-checks extracted W-2s against paystub-rebuilt year totals.
        </span>
      </div>

      {error && <p className="recon-error">{error}</p>}
      {ran && !data && !error && (
        <p className="tax-empty">{note || "No extracted W-2 or paystub documents yet."}</p>
      )}

      {data && (
        <>
          <p className="recon-summary">{data.summary}</p>
          <HouseholdPanel h={data} />
          <div className="recon-people">
            {data.people.map((p) => (
              <PersonCard key={p.person} person={p} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
