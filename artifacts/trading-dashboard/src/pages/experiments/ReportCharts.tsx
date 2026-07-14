/**
 * ReportCharts.tsx — reusable charts for the Phase 4.4 Research Report.
 *
 * Research only. Charts render exclusively from the stored backend report
 * payload — no frontend recalculation, no fabricated data. When source data
 * is missing the chart shows a consistent "Not available" state.
 */
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine, Cell,
} from "recharts";

/* eslint-disable @typescript-eslint/no-explicit-any */

const AXIS = { fontSize: 9, fontFamily: "monospace", fill: "#71717a" };
const GRID = "#27272a";
const TOOLTIP_STYLE = {
  backgroundColor: "#18181b", border: "1px solid #3f3f46", borderRadius: 4,
  fontSize: 10, fontFamily: "monospace",
};

export function ChartCard({ title, available, reason, children }: {
  title: string; available: boolean; reason?: string; children?: React.ReactNode;
}) {
  return (
    <div className="border border-zinc-800 rounded-md p-2 min-w-0 overflow-hidden report-chart-card">
      <p className="text-[10px] font-mono text-zinc-400 mb-1">{title}</p>
      {available ? (
        <div className="w-full h-[190px]">{children}</div>
      ) : (
        <div className="w-full h-[80px] flex items-center justify-center border border-dashed border-zinc-800 rounded">
          <p className="text-[10px] font-mono text-zinc-500 text-center px-3">
            Not available for this experiment{reason ? ` — ${reason}` : "."}
          </p>
        </div>
      )}
    </div>
  );
}

export function EquityCurveChart({ data }: { data?: any[] }) {
  const ok = Array.isArray(data) && data.length > 1;
  return (
    <ChartCard title="Equity Curve (₹, net of costs)" available={ok} reason="no equity curve was recorded in the stored results">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={AXIS} minTickGap={40} />
          <YAxis tick={AXIS} width={44} domain={["auto", "auto"]} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 9, fontFamily: "monospace" }} />
          <Line type="monotone" dataKey="full_model" name="Strategy" stroke="#8b5cf6" dot={false} strokeWidth={1.5} isAnimationActive={false} />
          {ok && data![0]?.nifty != null && (
            <Line type="monotone" dataKey="nifty" name="NIFTY 50" stroke="#71717a" dot={false} strokeWidth={1} strokeDasharray="4 3" isAnimationActive={false} />
          )}
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function DrawdownChart({ data }: { data?: any[] }) {
  const ok = Array.isArray(data) && data.length > 1;
  return (
    <ChartCard title="Drawdown (%)" available={ok} reason="no drawdown curve was recorded in the stored results">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={AXIS} minTickGap={40} />
          <YAxis tick={AXIS} width={36} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Area type="monotone" dataKey="drawdown_pct" name="Drawdown %" stroke="#ef4444" fill="#ef444433" isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

/** Generic grouped bar over breakdown rows: net P&L or trade counts. */
export function ContributionChart({ title, rows, dataKey = "net_pnl", name = "Net P&L ₹", reason }: {
  title: string; rows?: any[]; dataKey?: string; name?: string; reason?: string;
}) {
  const data = (rows ?? []).filter(r => r && r.group != null && typeof r[dataKey] === "number" && isFinite(r[dataKey]));
  const ok = data.length > 0;
  return (
    <ChartCard title={title} available={ok} reason={reason ?? "no breakdown rows were recorded"}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="group" tick={AXIS} interval={0} angle={data.length > 6 ? -30 : 0} height={data.length > 6 ? 46 : 24} textAnchor={data.length > 6 ? "end" : "middle"} />
          <YAxis tick={AXIS} width={44} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <ReferenceLine y={0} stroke="#52525b" />
          <Bar dataKey={dataKey} name={name} isAnimationActive={false}>
            {data.map((r, i) => (
              <Cell key={i} fill={Number(r[dataKey]) >= 0 ? "#10b981" : "#ef4444"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function WinLossChart({ rows }: { rows?: any[] }) {
  const data = (rows ?? [])
    .filter(r => r && r.group != null && (typeof r.wins === "number" || typeof r.losses === "number"));
  const ok = data.length > 0;
  return (
    <ChartCard title="Winners vs Losers by strategy" available={ok} reason="no per-strategy win/loss counts were recorded">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="group" tick={AXIS} interval={0} angle={data.length > 4 ? -30 : 0} height={data.length > 4 ? 46 : 24} textAnchor={data.length > 4 ? "end" : "middle"} />
          <YAxis tick={AXIS} width={30} allowDecimals={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 9, fontFamily: "monospace" }} />
          <Bar dataKey="wins" name="Wins" fill="#10b981" isAnimationActive={false} />
          <Bar dataKey="losses" name="Losses" fill="#ef4444" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function CalibrationChart({ buckets }: { buckets?: any[] }) {
  const data = (buckets ?? [])
    .filter(b => b && typeof b.predicted_win_prob === "number" && typeof b.actual_win_rate === "number")
    .map(b => ({ ...b, ideal: b.predicted_win_prob }));
  const ok = data.length > 1;
  return (
    <ChartCard title="Calibration — predicted vs actual win rate" available={ok}
      reason="fewer than two reliability buckets have both predicted and actual values">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="range" tick={AXIS} />
          <YAxis tick={AXIS} width={32} domain={[0, 1]} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={{ fontSize: 9, fontFamily: "monospace" }} />
          <Line type="monotone" dataKey="ideal" name="Perfect calibration" stroke="#71717a" strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="predicted_win_prob" name="Predicted" stroke="#38bdf8" dot={{ r: 2 }} isAnimationActive={false} />
          <Line type="monotone" dataKey="actual_win_rate" name="Actual" stroke="#8b5cf6" dot={{ r: 2 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
