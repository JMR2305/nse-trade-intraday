/**
 * PerformanceAnalytics.tsx — Phase 10.1: institutional-grade analytics page.
 * Sections: performance summary, risk analytics, charts (equity/daily P&L/
 * monthly/drawdown/cumulative/win-loss), strategy & sector tables, best/worst
 * trades, AI performance, historical trades (sort + filter), benchmark
 * comparison, exports.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  BarChart3, RefreshCw, Loader2, Download, AlertTriangle,
  TrendingUp, TrendingDown, Trophy, ThumbsDown, Bot, Gauge as GaugeIcon,
  ArrowUpDown, Scale, FileJson, FileSpreadsheet, Camera,
} from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area, BarChart, Bar,
  PieChart, Pie, Cell, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
  ReferenceLine,
} from "recharts";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";

/* eslint-disable @typescript-eslint/no-explicit-any */

const CHART_TOOLTIP = { background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 };

const pnlColor = (v: number | null | undefined) =>
  (v ?? 0) > 0 ? "text-emerald-400" : (v ?? 0) < 0 ? "text-red-400" : "text-zinc-300";

const fmtINR = (v: number | null | undefined) =>
  v == null ? "—" : `₹${Math.round(v).toLocaleString("en-IN")}`;

const fmtPct = (v: number | null | undefined, sign = true) =>
  v == null ? "—" : `${sign && v > 0 ? "+" : ""}${v}%`;

function KpiCard({ title, value, sub, tooltip, tone }: {
  title: string; value: React.ReactNode; sub?: React.ReactNode; tooltip: string; tone?: string;
}) {
  return (
    <div className="group relative rounded-lg border border-zinc-800 bg-zinc-900/60 p-3.5" title={tooltip}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{title}</div>
      <div className={cn("mt-1 text-lg font-bold", tone ?? "text-zinc-100")}>{value}</div>
      {sub && <div className="mt-0.5 text-[10px] text-zinc-500">{sub}</div>}
    </div>
  );
}

function GaugeBar({ label, value, max, unit, tone, tooltip }: {
  label: string; value: number | null; max: number; unit?: string; tone: string; tooltip: string;
}) {
  const pct = value == null ? 0 : Math.min(Math.abs(value) / max * 100, 100);
  return (
    <div title={tooltip}>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-zinc-400">{label}</span>
        <span className={cn("font-bold", tone)}>{value == null ? "—" : `${value}${unit ?? ""}`}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
        <div className={cn("h-full rounded-full transition-all",
          tone.includes("emerald") ? "bg-emerald-500" : tone.includes("red") ? "bg-red-500" : tone.includes("amber") ? "bg-amber-500" : "bg-sky-500")}
          style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function SectionCard({ title, icon, children, right }: {
  title: string; icon: React.ReactNode; children: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardHeader className="px-5 pb-2 pt-4">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-zinc-300">
            {icon}{title}
          </h2>
          {right}
        </div>
      </CardHeader>
      <CardContent className="px-5 pb-5">{children}</CardContent>
    </Card>
  );
}

export default function PerformanceAnalytics() {
  const { toast } = useToast();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<string>("date");
  const [sortDesc, setSortDesc] = useState(true);
  const [outcomeFilter, setOutcomeFilter] = useState<string>("ALL");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/analytics/performance`);
      const d = JSON.parse(await r.text());
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      setData(d);
    } catch (e: any) {
      setError(e.message ?? "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const doExport = async (kind: "json" | "csv" | "snapshot") => {
    try {
      const resp = await fetch(`${API_BASE}/analytics/export?kind=${kind}`);
      if (!resp.ok) throw new Error(`Export failed (HTTP ${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = kind === "csv" ? "phase10_trades.csv" : kind === "snapshot" ? "phase10_snapshot.json" : "phase10_analytics.json";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: "Export downloaded" });
    } catch (e: any) {
      toast({ title: "Export failed", description: e.message, variant: "destructive" });
    }
  };

  const trades = useMemo(() => {
    let list: any[] = data?.historical_trades ?? [];
    if (outcomeFilter !== "ALL") list = list.filter(t => t.outcome === outcomeFilter);
    const sorted = [...list].sort((a, b) => {
      const av = a[sortKey] ?? 0, bv = b[sortKey] ?? 0;
      if (av < bv) return sortDesc ? 1 : -1;
      if (av > bv) return sortDesc ? -1 : 1;
      return 0;
    });
    return sorted;
  }, [data, sortKey, sortDesc, outcomeFilter]);

  if (loading && !data) return (
    <div className="space-y-4 font-mono">
      <Skeleton className="h-10 w-72 bg-zinc-800" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {Array.from({ length: 10 }).map((_, i) => <Skeleton key={i} className="h-20 bg-zinc-800" />)}
      </div>
      <Skeleton className="h-64 w-full bg-zinc-800" />
      <Skeleton className="h-64 w-full bg-zinc-800" />
    </div>
  );

  if (error) return (
    <div className="rounded-lg border border-red-800 bg-red-950/30 p-6 font-mono text-sm text-red-300">
      <AlertTriangle className="mr-2 inline h-4 w-4" />{error}
      <Button size="sm" variant="outline" className="ml-4" onClick={load}>Retry</Button>
    </div>
  );

  const s = data.summary ?? {};
  const risk = data.risk ?? {};
  const charts = data.charts ?? {};
  const ai = data.ai_performance ?? {};
  const bw = data.best_worst ?? {};
  const suff = data.data_sufficiency ?? {};
  const winLossData = [
    { name: "Wins", value: charts.win_loss?.wins ?? 0 },
    { name: "Losses", value: charts.win_loss?.losses ?? 0 },
  ];
  const hasWL = winLossData.some(d => d.value > 0);

  const sortBtn = (key: string, label: string) => (
    <button className="flex items-center gap-1 hover:text-zinc-200"
      onClick={() => { if (sortKey === key) setSortDesc(v => !v); else { setSortKey(key); setSortDesc(true); } }}>
      {label}<ArrowUpDown className={cn("h-3 w-3", sortKey === key ? "text-primary" : "opacity-40")} />
    </button>
  );

  return (
    <div className="space-y-6 font-mono">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="mb-1 flex items-center gap-3">
            <BarChart3 className="h-5 w-5 text-primary" />
            <h1 className="text-xl font-bold text-foreground">Performance Analytics</h1>
            <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
              PAPER / LIVE DATA VALIDATION
            </Badge>
          </div>
          <p className="text-xs text-zinc-500">
            {suff.closed_trades ?? 0} closed trades analyzed · {suff.note}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={load} className="gap-2 text-xs">
            <RefreshCw className="h-3.5 w-3.5" />Refresh
          </Button>
          <Button size="sm" variant="outline" onClick={() => doExport("json")} className="gap-2 text-xs">
            <FileJson className="h-3.5 w-3.5" />JSON Report
          </Button>
          <Button size="sm" variant="outline" onClick={() => doExport("csv")} className="gap-2 text-xs">
            <FileSpreadsheet className="h-3.5 w-3.5" />CSV
          </Button>
          <Button size="sm" variant="outline" onClick={() => doExport("snapshot")} className="gap-2 text-xs">
            <Camera className="h-3.5 w-3.5" />Snapshot
          </Button>
        </div>
      </div>

      <DataFreshnessBar
        variant="historical"
        datasetLabel="Trade performance history"
        lastUpdated={data.generated_at}
        sampleSize={`${suff.closed_trades ?? 0} trades`}
      />

      {/* ── Section 1: Performance Summary ─────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <KpiCard title="Total Return" tooltip="Portfolio value vs ₹5,000 starting capital, incl. open positions"
          value={fmtPct(s.total_return_pct)} tone={pnlColor(s.total_return_pct)}
          sub={fmtINR(s.total_return_amount)} />
        <KpiCard title="Today's Return" tooltip="Realized P&L from trades closed today"
          value={fmtINR(s.today_return)} tone={pnlColor(s.today_return)} />
        <KpiCard title="Weekly Return" tooltip="Realized P&L over the last 7 days"
          value={fmtINR(s.weekly_return)} tone={pnlColor(s.weekly_return)} />
        <KpiCard title="Monthly Return" tooltip="Realized P&L over the last 30 days"
          value={fmtINR(s.monthly_return)} tone={pnlColor(s.monthly_return)} />
        <KpiCard title="Total Trades" tooltip="Number of closed (realized) trades"
          value={s.total_trades ?? 0} sub={`${s.wins ?? 0}W / ${s.losses ?? 0}L`} />
        <KpiCard title="Win Rate" tooltip="Winning trades as a % of all closed trades"
          value={fmtPct(s.win_rate_pct, false)} tone={(s.win_rate_pct ?? 0) >= 50 ? "text-emerald-400" : "text-amber-400"} />
        <KpiCard title="Profit Factor" tooltip="Gross profit ÷ gross loss (>1 is profitable)"
          value={s.profit_factor ?? "—"} tone={(s.profit_factor ?? 0) >= 1 ? "text-emerald-400" : "text-red-400"} />
        <KpiCard title="Avg Winner" tooltip="Average profit on winning trades"
          value={fmtINR(s.avg_winner)} tone="text-emerald-400" />
        <KpiCard title="Avg Loser" tooltip="Average loss on losing trades"
          value={fmtINR(s.avg_loser)} tone="text-red-400" />
        <KpiCard title="Expectancy" tooltip="Expected ₹ P&L per trade = winrate×avgWin − lossrate×avgLoss"
          value={fmtINR(s.expectancy)} tone={pnlColor(s.expectancy)} />
      </div>

      {/* ── Section 2: Risk Analytics ──────────────────────────────────────── */}
      <SectionCard title="Risk Analytics" icon={<GaugeIcon className="h-4 w-4 text-primary" />}
        right={risk.estimated && (
          <Badge variant="outline" className="text-[9px] text-amber-500/80 border-amber-800" data-testid="badge-risk-estimated">
            Estimated — limited evidence ({risk.observations ?? 0} observations)
          </Badge>
        )}>
        <div className="grid grid-cols-2 gap-x-8 gap-y-4 md:grid-cols-4">
          <GaugeBar label="Max Drawdown" value={risk.max_drawdown_pct} max={20} unit="%" tone="text-red-400"
            tooltip="Largest peak-to-trough equity decline" />
          <GaugeBar label="Current Drawdown" value={risk.current_drawdown_pct} max={20} unit="%" tone="text-amber-400"
            tooltip="Distance from the most recent equity peak" />
          <GaugeBar label="Sharpe Ratio" value={risk.sharpe} max={3} tone={(risk.sharpe ?? 0) >= 1 ? "text-emerald-400" : "text-amber-400"}
            tooltip="Risk-adjusted return (annualized); >1 is good" />
          <GaugeBar label="Sortino Ratio" value={risk.sortino} max={3} tone={(risk.sortino ?? 0) >= 1 ? "text-emerald-400" : "text-amber-400"}
            tooltip="Downside-risk-adjusted return; >1 is good" />
          <GaugeBar label="Calmar Ratio" value={risk.calmar} max={5} tone={(risk.calmar ?? 0) >= 1 ? "text-emerald-400" : "text-amber-400"}
            tooltip="Total return ÷ max drawdown" />
          <GaugeBar label="Volatility (ann.)" value={risk.volatility_pct} max={40} unit="%" tone="text-sky-400"
            tooltip="Annualized standard deviation of returns" />
          {(risk.observations ?? 0) >= 10 ? (
            <GaugeBar label="Beta vs NIFTY" value={risk.beta} max={2} tone="text-sky-400"
              tooltip="Sensitivity to NIFTY moves (estimated from available data)" />
          ) : (
            <div data-testid="beta-insufficient">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">Beta vs NIFTY</div>
              <div className="mt-1 text-xs text-zinc-600">N/A — insufficient history</div>
            </div>
          )}
          <GaugeBar label="Risk Score" value={risk.risk_score} max={100}
            tone={risk.risk_level === "LOW" ? "text-emerald-400" : risk.risk_level === "MEDIUM" ? "text-amber-400" : "text-red-400"}
            tooltip={`Composite 0–100 (drawdown, volatility, VIX, exposure) — ${risk.risk_level}`} />
        </div>
        {risk.monitor && (
          <div className="mt-5 border-t border-zinc-800 pt-4">
            <div className="mb-3 text-[10px] uppercase tracking-wider text-zinc-500">
              Risk Monitor — live paper portfolio
            </div>
            <div className="grid grid-cols-2 gap-x-8 gap-y-4 md:grid-cols-4" data-testid="risk-monitor">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Largest Winner</div>
                <div className="mt-1 font-mono text-sm text-emerald-400">
                  {risk.monitor.largest_winning_trade
                    ? `${risk.monitor.largest_winning_trade.symbol} ${fmtINR(risk.monitor.largest_winning_trade.pnl)}`
                    : "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Largest Loser</div>
                <div className="mt-1 font-mono text-sm text-red-400">
                  {risk.monitor.largest_losing_trade
                    ? `${risk.monitor.largest_losing_trade.symbol} ${fmtINR(risk.monitor.largest_losing_trade.pnl)}`
                    : "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Max Consecutive Wins</div>
                <div className="mt-1 font-mono text-sm text-emerald-400">{risk.monitor.max_consecutive_wins ?? 0}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Max Consecutive Losses</div>
                <div className="mt-1 font-mono text-sm text-red-400">{risk.monitor.max_consecutive_losses ?? 0}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Daily Drawdown</div>
                <div className="mt-1 font-mono text-sm text-amber-400">{fmtPct(risk.monitor.daily_drawdown_pct, false)}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Weekly Drawdown</div>
                <div className="mt-1 font-mono text-sm text-amber-400">{fmtPct(risk.monitor.weekly_drawdown_pct, false)}</div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-zinc-500">Monthly Drawdown</div>
                <div className="mt-1 font-mono text-sm text-amber-400">{fmtPct(risk.monitor.monthly_drawdown_pct, false)}</div>
              </div>
            </div>
          </div>
        )}
      </SectionCard>

      {/* ── Section 3: Performance Charts ──────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SectionCard title="Equity Curve" icon={<TrendingUp className="h-4 w-4 text-primary" />}>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={charts.equity_curve ?? []}>
                <defs>
                  <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#71717a" }} />
                <YAxis domain={["auto", "auto"]} tick={{ fontSize: 9, fill: "#71717a" }} />
                <Tooltip contentStyle={CHART_TOOLTIP} />
                <ReferenceLine y={data.initial_capital} stroke="#52525b" strokeDasharray="4 4" />
                <Area type="monotone" dataKey="equity" name="Equity (₹)" stroke="#38bdf8" strokeWidth={2} fill="url(#eqFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Daily P&L" icon={<BarChart3 className="h-4 w-4 text-primary" />}>
          {(charts.daily_pnl ?? []).length === 0 ? (
            <div className="flex h-56 items-center justify-center text-xs text-zinc-500">No realized trades yet — bars appear as trades close.</div>
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={charts.daily_pnl}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#71717a" }} />
                  <YAxis tick={{ fontSize: 9, fill: "#71717a" }} />
                  <Tooltip contentStyle={CHART_TOOLTIP} />
                  <ReferenceLine y={0} stroke="#52525b" />
                  <Bar dataKey="pnl" name="P&L (₹)">
                    {(charts.daily_pnl ?? []).map((d: any, i: number) => (
                      <Cell key={i} fill={d.pnl >= 0 ? "#34d399" : "#f87171"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Monthly Returns" icon={<BarChart3 className="h-4 w-4 text-primary" />}>
          {(charts.monthly_returns ?? []).length === 0 ? (
            <div className="flex h-56 items-center justify-center text-xs text-zinc-500">No monthly history yet.</div>
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={charts.monthly_returns}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="month" tick={{ fontSize: 9, fill: "#71717a" }} />
                  <YAxis tick={{ fontSize: 9, fill: "#71717a" }} />
                  <Tooltip contentStyle={CHART_TOOLTIP} />
                  <ReferenceLine y={0} stroke="#52525b" />
                  <Bar dataKey="return_pct" name="Return %">
                    {(charts.monthly_returns ?? []).map((d: any, i: number) => (
                      <Cell key={i} fill={d.return_pct >= 0 ? "#34d399" : "#f87171"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Drawdown Curve" icon={<TrendingDown className="h-4 w-4 text-primary" />}>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={charts.drawdown ?? []}>
                <defs>
                  <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#f87171" stopOpacity={0} />
                    <stop offset="100%" stopColor="#f87171" stopOpacity={0.35} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#71717a" }} />
                <YAxis tick={{ fontSize: 9, fill: "#71717a" }} />
                <Tooltip contentStyle={CHART_TOOLTIP} />
                <Area type="monotone" dataKey="drawdown_pct" name="Drawdown %" stroke="#f87171" strokeWidth={2} fill="url(#ddFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title="Cumulative Profit" icon={<TrendingUp className="h-4 w-4 text-primary" />}>
          {(charts.cumulative_profit ?? []).length === 0 ? (
            <div className="flex h-56 items-center justify-center text-xs text-zinc-500">No realized profit history yet.</div>
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={charts.cumulative_profit}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#71717a" }} />
                  <YAxis tick={{ fontSize: 9, fill: "#71717a" }} />
                  <Tooltip contentStyle={CHART_TOOLTIP} />
                  <ReferenceLine y={0} stroke="#52525b" />
                  <Line type="monotone" dataKey="cumulative_profit" name="Cumulative ₹" stroke="#a78bfa" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Win vs Loss" icon={<Scale className="h-4 w-4 text-primary" />}>
          {!hasWL ? (
            <div className="flex h-56 items-center justify-center text-xs text-zinc-500">No closed trades yet.</div>
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={winLossData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={4}>
                    <Cell fill="#34d399" />
                    <Cell fill="#f87171" />
                  </Pie>
                  <Tooltip contentStyle={CHART_TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </SectionCard>
      </div>

      {/* ── Section 4 & 5: Strategy + Sector Performance ───────────────────── */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <SectionCard title="Strategy Performance" icon={<BarChart3 className="h-4 w-4 text-primary" />}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500">
                  {["Strategy","Trades","Wins","Losses","Win Rate","Avg Return","PF","Total Profit"].map(h => (
                    <th key={h} className="py-2 pr-3 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(data.strategy_performance ?? []).map((row: any) => (
                  <tr key={row.strategy} className={cn("border-b border-zinc-800/50", row.trades === 0 && "opacity-40")}>
                    <td className="py-1.5 pr-3 font-bold text-zinc-200">{row.strategy}</td>
                    <td className="py-1.5 pr-3">{row.trades}</td>
                    <td className="py-1.5 pr-3 text-emerald-400">{row.wins}</td>
                    <td className="py-1.5 pr-3 text-red-400">{row.losses}</td>
                    <td className="py-1.5 pr-3">{row.trades ? `${row.win_rate_pct}%` : "No trades yet"}</td>
                    <td className={cn("py-1.5 pr-3", pnlColor(row.avg_return_pct))}>{row.trades ? fmtPct(row.avg_return_pct) : "—"}</td>
                    <td className="py-1.5 pr-3">{row.trades ? row.profit_factor : "—"}</td>
                    <td className={cn("py-1.5 pr-3", pnlColor(row.total_profit))}>{row.trades ? fmtINR(row.total_profit) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title="Sector Performance" icon={<BarChart3 className="h-4 w-4 text-primary" />}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500">
                  {["Sector","Trades","Win Rate","Avg Return","Total Profit"].map(h => (
                    <th key={h} className="py-2 pr-3 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(data.sector_performance ?? []).map((row: any) => (
                  <tr key={row.sector} className={cn("border-b border-zinc-800/50", row.trades === 0 && "opacity-40")}>
                    <td className="py-1.5 pr-3 font-bold text-zinc-200">{row.sector}</td>
                    <td className="py-1.5 pr-3">{row.trades}</td>
                    <td className="py-1.5 pr-3">{row.trades ? `${row.win_rate_pct}%` : "No trades yet"}</td>
                    <td className={cn("py-1.5 pr-3", pnlColor(row.avg_return_pct))}>{row.trades ? fmtPct(row.avg_return_pct) : "—"}</td>
                    <td className={cn("py-1.5 pr-3", pnlColor(row.total_profit))}>{row.trades ? fmtINR(row.total_profit) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      </div>

      {/* ── Section 6: Best & Worst Trades ─────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="border-emerald-900/40 bg-emerald-950/10">
          <CardHeader className="px-5 pb-2 pt-4">
            <h2 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-emerald-400">
              <Trophy className="h-4 w-4" />Best Trade
            </h2>
          </CardHeader>
          <CardContent className="px-5 pb-5 text-xs">
            {!bw.best ? (
              <div className="py-6 text-center text-zinc-500">No winning trades yet.</div>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                <div><div className="text-[10px] text-zinc-500">Stock</div><div className="text-sm font-bold text-zinc-100">{bw.best.symbol}</div></div>
                <div><div className="text-[10px] text-zinc-500">Entry → Exit</div><div className="font-bold text-zinc-200">₹{bw.best.entry} → ₹{bw.best.exit}</div></div>
                <div><div className="text-[10px] text-zinc-500">Holding</div><div className="font-bold text-zinc-200">{bw.best.holding_days} days</div></div>
                <div><div className="text-[10px] text-zinc-500">Return</div><div className="font-bold text-emerald-400">{fmtPct(bw.best.return_pct)}</div></div>
                <div><div className="text-[10px] text-zinc-500">Profit</div><div className="font-bold text-emerald-400">{fmtINR(bw.best.pnl)}</div></div>
                <div><div className="text-[10px] text-zinc-500">Strategy</div><div className="font-bold text-zinc-200">{bw.best.strategy}</div></div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="border-red-900/40 bg-red-950/10">
          <CardHeader className="px-5 pb-2 pt-4">
            <h2 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-red-400">
              <ThumbsDown className="h-4 w-4" />Worst Trade
            </h2>
          </CardHeader>
          <CardContent className="px-5 pb-5 text-xs">
            {!bw.worst ? (
              <div className="py-6 text-center text-zinc-500">No losing trades — nothing to show (yet).</div>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                <div><div className="text-[10px] text-zinc-500">Stock</div><div className="text-sm font-bold text-zinc-100">{bw.worst.symbol}</div></div>
                <div><div className="text-[10px] text-zinc-500">Loss %</div><div className="font-bold text-red-400">{fmtPct(bw.worst.return_pct)}</div></div>
                <div><div className="text-[10px] text-zinc-500">Loss Amount</div><div className="font-bold text-red-400">{fmtINR(bw.worst.pnl)}</div></div>
                <div><div className="text-[10px] text-zinc-500">Holding</div><div className="font-bold text-zinc-200">{bw.worst.holding_days} days</div></div>
                <div className="col-span-2"><div className="text-[10px] text-zinc-500">Reason</div><div className="text-zinc-300">{bw.worst.reason || bw.worst.exit_type}</div></div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Section 7: AI Performance ──────────────────────────────────────── */}
      <SectionCard title="AI Performance" icon={<Bot className="h-4 w-4 text-primary" />}
        right={ai.estimated && (
          <Badge variant="outline" className="text-[9px] text-amber-500/80 border-amber-800" data-testid="badge-ai-estimated">
            Estimated — limited evidence ({ai.closed_trades_used ?? 0} closed trades)
          </Badge>
        )}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {[
            ["Prediction Accuracy", ai.prediction_accuracy_pct, "%", "Closed trades that ended profitable"],
            ["Confidence Accuracy", ai.confidence_accuracy_pct, "%", "How often confidence ≥50 matched the outcome"],
            ["Avg Confidence", ai.avg_confidence, "", "Average calibrated confidence in latest scan"],
            ["Avg Opportunity Score", ai.avg_opportunity_score, "", "Average opportunity score in latest scan"],
            ["Buy Signal Accuracy", ai.buy_signal_accuracy_pct, "%", "Buy signals that produced winning trades"],
            ["Sell Signal Accuracy", ai.sell_signal_accuracy_pct, "%", "Signal/target exits that locked in profit"],
            ["Exit Signal Accuracy", ai.exit_signal_accuracy_pct, "%", "Exits that ended profitable"],
            ["Avg Holding Period", ai.avg_holding_days, " days", "Average days from entry to exit"],
            ["Trade Quality Score", ai.trade_quality_score, "", "Gate-pass quality from latest confidence snapshot"],
            ["Learning Score", ai.learning_score, "", "Blend of prediction accuracy and trade quality"],
          ].map(([label, v, unit, tip]) => (
            <div key={label as string} title={tip as string}
              className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3.5">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
              <div className="mt-1 text-lg font-bold text-primary">{v == null ? "—" : `${v}${unit}`}</div>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* ── Section 8: Historical Performance ──────────────────────────────── */}
      <SectionCard title="Historical Performance" icon={<BarChart3 className="h-4 w-4 text-primary" />}
        right={
          <div className="flex gap-1.5">
            {["ALL", "WIN", "LOSS"].map(f => (
              <button key={f} onClick={() => setOutcomeFilter(f)}
                className={cn("rounded border px-2 py-0.5 text-[10px]",
                  outcomeFilter === f ? "border-primary/60 bg-primary/10 text-primary" : "border-zinc-700 text-zinc-400")}>
                {f}
              </button>
            ))}
          </div>
        }>
        {trades.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-500">No trades match this filter.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zinc-800 text-zinc-500">
                  <th className="py-2 pr-3 text-left font-medium">{sortBtn("date", "Date")}</th>
                  <th className="py-2 pr-3 text-left font-medium">{sortBtn("symbol", "Stock")}</th>
                  <th className="py-2 pr-3 text-left font-medium">Strategy</th>
                  <th className="py-2 pr-3 text-left font-medium">Entry</th>
                  <th className="py-2 pr-3 text-left font-medium">Exit</th>
                  <th className="py-2 pr-3 text-left font-medium">{sortBtn("return_pct", "Return %")}</th>
                  <th className="py-2 pr-3 text-left font-medium">{sortBtn("holding_days", "Duration")}</th>
                  <th className="py-2 pr-3 text-left font-medium">{sortBtn("confidence", "Confidence")}</th>
                  <th className="py-2 pr-3 text-left font-medium">{sortBtn("opportunity_score", "Opp. Score")}</th>
                  <th className="py-2 pr-3 text-left font-medium">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t: any) => (
                  <tr key={t.trade_id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                    <td className="py-1.5 pr-3 text-zinc-400">{t.date}</td>
                    <td className="py-1.5 pr-3 font-bold text-zinc-100">{t.symbol}</td>
                    <td className="py-1.5 pr-3 text-zinc-400">{t.strategy}</td>
                    <td className="py-1.5 pr-3">₹{t.entry}</td>
                    <td className="py-1.5 pr-3">₹{t.exit}</td>
                    <td className={cn("py-1.5 pr-3 font-bold", pnlColor(t.return_pct))}>{fmtPct(t.return_pct)}</td>
                    <td className="py-1.5 pr-3">{t.holding_days}d</td>
                    <td className="py-1.5 pr-3">{t.confidence ?? "—"}</td>
                    <td className="py-1.5 pr-3">{t.opportunity_score ?? "—"}</td>
                    <td className="py-1.5 pr-3">
                      <Badge variant="outline" className={cn("text-[9px]",
                        t.outcome === "WIN" ? "border-emerald-700 text-emerald-400" :
                        t.outcome === "LOSS" ? "border-red-700 text-red-400" : "border-zinc-600 text-zinc-400")}>
                        {t.outcome}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {/* ── Section 9: Benchmark Comparison ────────────────────────────────── */}
      <SectionCard title="Benchmark Comparison" icon={<Scale className="h-4 w-4 text-primary" />}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-zinc-800 text-zinc-500">
                {["Benchmark","Benchmark Return","Portfolio Return","Outperformance","Alpha","Beta",""].map((h, i) => (
                  <th key={i} className="py-2 pr-3 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data.benchmarks ?? []).map((b: any) => (
                <tr key={b.benchmark} className="border-b border-zinc-800/50">
                  <td className="py-2 pr-3 font-bold text-zinc-200">{b.benchmark}</td>
                  <td className={cn("py-2 pr-3", pnlColor(b.benchmark_return_pct))}>{fmtPct(b.benchmark_return_pct)}</td>
                  <td className={cn("py-2 pr-3", pnlColor(b.portfolio_return_pct))}>{fmtPct(b.portfolio_return_pct)}</td>
                  <td className={cn("py-2 pr-3 font-bold", pnlColor(b.outperformance_pct))}>{fmtPct(b.outperformance_pct)}</td>
                  <td className={cn("py-2 pr-3", pnlColor(b.alpha))}>{b.alpha}</td>
                  <td className="py-2 pr-3">{b.beta}</td>
                  <td className="py-2 pr-3">
                    {b.estimated && <span className="text-[9px] text-zinc-600">est.</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[10px] text-zinc-600">
          Benchmark returns use the latest cached market context (daily change). Comparisons become period-accurate as more history accumulates.
        </p>
      </SectionCard>

      <Phase14LearningSection />

      <div className="text-center text-[10px] text-zinc-600">
        {data.label} · Generated {data.generated_at} · Paper trading research — not investment advice
      </div>
    </div>
  );
}

// ── Phase 14 learning impact section ──────────────────────────────────────────

function Phase14LearningSection() {
  const [ver, setVer] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/phase14/verification`)
      .then((r) => r.json())
      .then((d) => { if (alive) setVer(d?.verification ?? null); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!ver) return null;
  return (
    <SectionCard title="Adaptive Learning Impact (Phase 14 · research only)"
      icon={<Bot className="h-4 w-4 text-primary" />}>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <KpiCard title="Learning Trades" value={String(ver.completed_learning_rows)}
          sub={ver.evaluation_reliability} tooltip="Completed paper trades used for learning" />
        <KpiCard title="Calibrator" value={ver.active_calibrator ?? "identity"}
          sub={ver.calibrator_method} tooltip="Active confidence calibrator version" />
        <KpiCard title="Active Adjustments" value={String(ver.adjustment_sources_active)}
          sub={`max ${ver.max_adjustment_observed}`} tooltip="Evidence-based adjustment sources currently non-zero" />
        <KpiCard title="Champion Model" value={ver.current_champion ?? "—"}
          sub="model registry" tooltip="Current champion decision model" />
        <KpiCard title="Drift" value={ver.drift_status}
          sub={ver.learning_frozen?.frozen ? "learning FROZEN" : "learning active"}
          tone={ver.drift_status === "CRITICAL" ? "text-red-400" : ver.drift_status === "WARNING" ? "text-yellow-400" : "text-emerald-400"}
          tooltip="Drift monitor severity" />
      </div>
      <p className="mt-3 text-[10px] text-zinc-600">
        Adaptive learning uses completed historical and paper trades. Findings may be unreliable with limited samples.
        No model, rule, or strategy is promoted automatically. Human approval is required.
      </p>
    </SectionCard>
  );
}
