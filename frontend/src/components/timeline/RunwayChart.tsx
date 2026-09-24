import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { NegativeWindow, TimelineProjectionPoint } from "../../types";

interface Props {
  projection: TimelineProjectionPoint[];
  firstNegative: string | null;
  negativeWindows?: NegativeWindow[];
}

// Compact shortfall label, e.g. -$18.4k
const fmtShort = (n: number) => {
  const abs = Math.abs(n);
  const s = abs >= 1000 ? `$${(abs / 1000).toFixed(1)}k` : `$${abs.toFixed(0)}`;
  return `-${s}`;
};

const fmtK = (n: number) => `$${(n / 1000).toFixed(1)}k`;
const fmtFull = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

// Show only a year label on the axis (period is "YYYY-MM") to avoid clutter.
const yearTick = (period: string) => (period.endsWith("-01") ? period.slice(0, 4) : "");

/**
 * The runway chart: two monthly-leftover lines — raw (solid, before adjustments)
 * and adjusted (dashed, after +save/−spend) — with a zero reference line and a
 * marker at the first month the adjusted runway goes negative.
 */
export default function RunwayChart({ projection, firstNegative, negativeWindows = [] }: Props) {
  if (projection.length === 0) return null;

  return (
    <div className="chart-body">
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={projection} margin={{ top: 28, right: 12, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#0f3460" />
          <XAxis
            dataKey="period"
            tickFormatter={yearTick}
            interval={0}
            tick={{ fill: "#a0a0b0", fontSize: 11 }}
          />
          <YAxis tickFormatter={fmtK} tick={{ fill: "#a0a0b0", fontSize: 11 }} />
          <Tooltip
            contentStyle={{ background: "#16213e", border: "1px solid #0f3460", color: "#eaeaea" }}
            formatter={(value: number) => fmtFull(value)}
            labelFormatter={(label) => `Month ${label}`}
          />
          <Legend wrapperStyle={{ color: "#eaeaea" }} />
          <ReferenceLine y={0} stroke="#e94560" strokeWidth={1.5} />

          {/* Shade each negative stretch and label its total shortfall at the
              midpoint. Falls back to a single "goes negative" marker if the
              backend didn't provide windows. */}
          {negativeWindows.length > 0
            ? negativeWindows.map((w) => (
                <ReferenceArea
                  key={w.start}
                  x1={w.start}
                  x2={w.end}
                  fill="#ff9800"
                  fillOpacity={0.12}
                  stroke="#ff9800"
                  strokeOpacity={0.4}
                  strokeDasharray="4 3"
                  label={{
                    value: `${fmtShort(w.shortfall)} over ${w.months} mo (incl.)`,
                    fill: "#ff9800",
                    fontSize: 10,
                    position: "insideTop",
                  }}
                />
              ))
            : firstNegative && (
                <ReferenceLine
                  x={firstNegative}
                  stroke="#ff9800"
                  strokeDasharray="4 3"
                  label={{
                    value: "goes negative",
                    fill: "#ff9800",
                    fontSize: 10,
                    position: "insideTop",
                    dy: -14,
                  }}
                />
              )}
          <Line
            type="monotone"
            dataKey="runway_raw"
            name="Runway (raw)"
            stroke="#64b5f6"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="runway_adjusted"
            name="Runway (adjusted)"
            stroke="#4caf50"
            strokeWidth={2}
            strokeDasharray="6 4"
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
