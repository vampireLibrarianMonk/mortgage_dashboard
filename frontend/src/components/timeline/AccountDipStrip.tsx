import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimelineAccountSeries } from "../../types";

interface Props {
  accounts: TimelineAccountSeries[];
}

const fmtK = (n: number) => `$${(n / 1000).toFixed(1)}k`;
const fmtFull = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const yearTick = (period: string) => (period.endsWith("-01") ? period.slice(0, 4) : "");

// A small palette cycled across accounts.
const COLORS = ["#64b5f6", "#4caf50", "#ff9800", "#e94560", "#ba68c8", "#26c6da"];

/**
 * Account-dip strip: for each funding account, plot its projected balance over
 * the horizon so purchase draws (down payments, pay-in-full) show up as step-downs.
 * Series are seeded from the latest persisted balance snapshot.
 */
export default function AccountDipStrip({ accounts }: Props) {
  if (accounts.length === 0) return null;

  // Merge per-account point arrays into a single row-per-period dataset keyed by
  // account key, so all lines share one X axis.
  const periods = accounts[0]?.points.map((p) => p.period) ?? [];
  const data = periods.map((period, i) => {
    const row: Record<string, string | number> = { period };
    for (const acct of accounts) {
      row[acct.key] = acct.points[i]?.balance ?? 0;
    }
    return row;
  });

  return (
    <div className="chart-body">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 10, right: 12, left: 10, bottom: 0 }}>
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
          {accounts.map((acct, i) => (
            <Line
              key={acct.key}
              type="stepAfter"
              dataKey={acct.key}
              name={acct.label}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={2}
              dot={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
