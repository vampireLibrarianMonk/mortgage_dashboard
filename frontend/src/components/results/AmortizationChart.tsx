import { useState, useCallback } from "react";
import {
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from "recharts";
import type { AmortizationPoint } from "../../types";

interface Props {
  schedule: AmortizationPoint[];
}

const fmtK = (n: number) => `$${(n / 1000).toFixed(0)}k`;
const fmtFull = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export default function AmortizationChart({ schedule }: Props) {
  const [collapsed, setCollapsed] = useState(true);

  const openInWindow = useCallback(() => {
    const win = window.open("", "amortization", "width=900,height=550,menubar=no,toolbar=no");
    if (!win) return;

    const data = JSON.stringify(schedule);
    win.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Amortization Schedule</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
        <style>
          body { margin: 0; padding: 1rem; background: #1a1a2e; color: #eaeaea; font-family: system-ui; }
          canvas { width: 100% !important; height: 450px !important; }
          h2 { font-size: 1.1rem; margin-bottom: 0.5rem; color: #e94560; }
        </style>
      </head>
      <body>
        <h2>Amortization Schedule</h2>
        <canvas id="chart"></canvas>
        <script>
          const data = ${data};
          new Chart(document.getElementById('chart'), {
            type: 'bar',
            data: {
              labels: data.map(d => d.year),
              datasets: [
                { label: 'Principal', data: data.map(d => d.principal), backgroundColor: '#4caf50', stack: 'payment' },
                { label: 'Interest', data: data.map(d => d.interest), backgroundColor: '#e94560', stack: 'payment' },
              ]
            },
            options: {
              responsive: true,
              scales: {
                x: { title: { display: true, text: 'Year', color: '#a0a0b0' }, ticks: { color: '#a0a0b0' } },
                y: { title: { display: true, text: 'Annual Amount ($)', color: '#a0a0b0' }, ticks: { color: '#a0a0b0' }, stacked: true },
              },
              plugins: { legend: { labels: { color: '#eaeaea' } } }
            }
          });
        </script>
      </body>
      </html>
    `);
    win.document.close();
  }, [schedule]);

  if (schedule.length === 0) return null;

  return (
    <div className="chart-container">
      <div className="chart-header">
        <button
          type="button"
          className="chart-toggle"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? "▶" : "▼"} Amortization Chart
        </button>
        <button type="button" className="chart-popout" onClick={openInWindow} title="Open in new window">
          ⧉
        </button>
      </div>
      {!collapsed && (
        <div className="chart-body">
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={schedule} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#0f3460" />
              <XAxis dataKey="year" tick={{ fill: "#a0a0b0", fontSize: 11 }} />
              <YAxis yAxisId="left" tickFormatter={fmtK} tick={{ fill: "#a0a0b0", fontSize: 11 }} />
              <YAxis yAxisId="right" orientation="right" tickFormatter={fmtK} tick={{ fill: "#a0a0b0", fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: "#16213e", border: "1px solid #0f3460", color: "#eaeaea" }}
                formatter={(value: number) => fmtFull(value)}
                labelFormatter={(label) => `Year ${label}`}
              />
              <Legend wrapperStyle={{ color: "#eaeaea" }} />
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="principal"
                name="Principal"
                stackId="1"
                fill="#4caf50"
                stroke="#4caf50"
                fillOpacity={0.7}
              />
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="interest"
                name="Interest"
                stackId="1"
                fill="#e94560"
                stroke="#e94560"
                fillOpacity={0.7}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="balance"
                name="Balance"
                stroke="#64b5f6"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
