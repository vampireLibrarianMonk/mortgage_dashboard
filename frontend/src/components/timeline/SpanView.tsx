import type { Timeline, TimelineSettings } from "../../types";

interface Props {
  timelines: Timeline[];
  settings: TimelineSettings;
}

// "YYYY-MM" -> absolute month index; null/invalid -> null.
function ymToIndex(ym: string | null): number | null {
  if (!ym) return null;
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  if (!m) return null;
  return Number(m[1]) * 12 + (Number(m[2]) - 1);
}

/**
 * Span view: a compact Gantt-style strip showing each timeline's active window
 * (start → end) laid out across the plan horizon. Ongoing timelines (no end)
 * run to the horizon edge. Purely a visual aid — the numbers come from the
 * runway chart below.
 */
export default function SpanView({ timelines, settings }: Props) {
  if (timelines.length === 0) return null;

  // Horizon axis: from the earliest timeline start (or now) across horizon_years.
  const starts = timelines
    .map((t) => ymToIndex(t.start))
    .filter((n): n is number => n != null);
  if (starts.length === 0) return null;

  const now = new Date();
  const nowIdx = now.getFullYear() * 12 + now.getMonth();
  const axisStart = Math.min(nowIdx, ...starts);
  const axisEnd = axisStart + Math.max(1, settings.horizon_years) * 12;
  const span = axisEnd - axisStart || 1;

  const pct = (idx: number) => ((idx - axisStart) / span) * 100;

  // Year gridlines across the axis.
  const firstYear = Math.ceil(axisStart / 12);
  const lastYear = Math.floor(axisEnd / 12);
  const yearMarks: { year: number; left: number }[] = [];
  for (let y = firstYear; y <= lastYear; y++) {
    yearMarks.push({ year: y, left: pct(y * 12) });
  }

  return (
    <div className="tl-spanview">
      <div className="tl-span-axis">
        {yearMarks.map((m) => (
          <span key={m.year} className="tl-span-year" style={{ left: `${m.left}%` }}>
            {m.year}
          </span>
        ))}
      </div>
      {timelines.map((t, i) => {
        const s = ymToIndex(t.start) ?? axisStart;
        const e = ymToIndex(t.end) ?? axisEnd; // ongoing -> horizon edge
        const left = Math.max(0, pct(s));
        const right = Math.min(100, pct(Math.max(e, s + 1)));
        const width = Math.max(1.5, right - left);
        const isPurchase = t.purchase != null;
        return (
          <div key={i} className="tl-span-row">
            <span className="tl-span-label" title={t.label || "(unnamed)"}>
              {t.label || "(unnamed)"}
            </span>
            <div className="tl-span-track">
              <div
                className={isPurchase ? "tl-span-bar purchase" : "tl-span-bar"}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={`${t.start} → ${t.end ?? "ongoing"}`}
              >
                {isPurchase && <span className="tl-span-dot" title="purchase event" />}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
