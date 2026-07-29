/**
 * StrategyIntelligence.tsx — Phase 5D.3 Strategy Intelligence Dashboard
 *
 * READ-ONLY analytics. Never modifies any trading state.
 * PAPER TRADING / ADVISORY ONLY.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, RadarChart, Radar, PolarGrid, PolarAngleAxis,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell, Legend,
} from "recharts";
import {
  Trophy, Skull, Zap, ShieldCheck, Target, BarChart3,
  Clock, Globe2, Layers, RefreshCw, AlertTriangle, TrendingUp,
  CheckCircle2, XCircle, AlertCircle, Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface StrategyProfile {
  strategy_name: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  profit_factor: number;
  net_pnl: number;
  max_drawdown_pct: number;
  avg_quality_score: number;
  rank_score: number;
  rank: number;
  recommendation: string;
  expectancy: number;
  risk_reward: number;
  avg_holding_seconds: number;
  regime_breakdown: Record<string, { trades: number; win_rate: number; net_pnl: number }>;
  sector_breakdown: Record<string, { trades: number; win_rate: number; net_pnl: number }>;
}

interface LeaderboardRow {
  rank: number;
  strategy_name: string;
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  net_pnl: number;
  max_drawdown_pct: number;
  avg_quality_score: number;
  rank_score: number;
  recommendation: string;
}

interface CriterionRankings {
  highest_net_profit?: { strategy_name: string; net_pnl: number };
  highest_win_rate?: { strategy_name: string; win_rate: number };
  highest_profit_factor?: { strategy_name: string; profit_factor: number };
  lowest_drawdown?: { strategy_name: string; max_drawdown_pct: number };
  best_execution?: { strategy_name: string; avg_quality_score: number };
  highest_rank_score?: { strategy_name: string; rank_score: number };
}

interface SummaryResponse {
  status: string;
  total_strategies: number;
  total_closed_trades: number;
  total_net_pnl: number;
  overall_win_rate: number;
  best_strategy: string | null;
  worst_strategy: string | null;
  leaderboard: LeaderboardRow[];
  criterion_rankings: CriterionRankings;
}

interface RankingsResponse {
  status: string;
  leaderboard: LeaderboardRow[];
  profiles: StrategyProfile[];
  criterion_rankings: CriterionRankings;
}

interface RegimeRow {
  regime: string;
  trades: number;
  win_rate: number;
  net_pnl: number;
  avg_pnl: number;
  best_strategy: string;
}

interface RegimesResponse {
  status: string;
  matrix: Record<string, any>;
  best_per_regime: Record<string, string>;
  summary: RegimeRow[];
}

interface SectorRow { sector: string; trades: number; win_rate: number; net_pnl: number; avg_pnl: number; }
interface SectorsResponse { status: string; best_sector: string; worst_sector: string; summary: SectorRow[]; matrix: Record<string, any>; }

interface SlotStats { trades: number; win_rate: number; net_pnl: number; avg_pnl: number; }
interface TimingResponse {
  status: string;
  slot_matrix: Record<string, SlotStats>;
  day_matrix: Record<string, SlotStats>;
  best_day: string | null;
  worst_day: string | null;
  best_slot: string | null;
  worst_slot: string | null;
}

interface RecommendationRow {
  rank: number;
  strategy_name: string;
  recommendation: string;
  severity: string;
  rationale: string;
  win_rate: number;
  profit_factor: number;
  net_pnl: number;
  max_drawdown_pct: number;
  total_trades: number;
}

interface RecommendationsResponse {
  status: string;
  recommendations: RecommendationRow[];
}

// ── Formatters ────────────────────────────────────────────────────────────────

const fmt   = (v: number, d = 2) => v?.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }) ?? "—";
const fmtRs = (v: number) => `₹${fmt(v)}`;
const fmtPct= (v: number) => `${v >= 0 ? "+" : ""}${fmt(v, 2)}%`;
const fmtHold = (sec: number) => {
  if (!sec || sec <= 0) return "—";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m` : `${Math.floor(sec)}s`;
};

const PALETTE = ["#0ea5e9","#10b981","#f59e0b","#8b5cf6","#ec4899","#f97316","#14b8a6","#6366f1"];

function severityIcon(s: string) {
  if (s === "success") return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
  if (s === "danger")  return <XCircle      className="h-4 w-4 text-red-400" />;
  if (s === "warning") return <AlertCircle  className="h-4 w-4 text-amber-400" />;
  return <Info className="h-4 w-4 text-sky-400" />;
}

function severityBg(s: string) {
  if (s === "success") return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
  if (s === "danger")  return "bg-red-500/10 text-red-400 border-red-500/20";
  if (s === "warning") return "bg-amber-500/10 text-amber-400 border-amber-500/20";
  return "bg-sky-500/10 text-sky-400 border-sky-500/20";
}

// ── Mini components ───────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, icon: Icon, color = "text-foreground" }: {
  label: string; value: string; sub?: string; icon: React.ElementType; color?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Icon className="h-3.5 w-3.5" />{label}
      </div>
      <p className={cn("text-xl font-bold leading-none", color)}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function ChartCard({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-5", className)}>
      <h3 className="text-sm font-semibold mb-4">{title}</h3>
      {children}
    </div>
  );
}

function DisabledBanner({ flag }: { flag?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-4 text-amber-400">
      <AlertTriangle className="h-5 w-5 shrink-0" />
      <div>
        <p className="font-semibold">Strategy Intelligence module is disabled</p>
        <p className="text-sm mt-0.5">Set <code className="bg-amber-500/20 px-1 rounded">{flag ?? "STRATEGY_INTELLIGENCE_ENABLED"}=true</code> to enable analytics.</p>
      </div>
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">{label}</div>;
}

// ── Tab types ─────────────────────────────────────────────────────────────────

type Tab = "overview" | "rankings" | "regimes" | "sectors" | "timing" | "recommendations";

// ── Main page ─────────────────────────────────────────────────────────────────

export default function StrategyIntelligence() {
  const [tab, setTab] = useState<Tab>("overview");

  const { data: summary, isLoading: sumLoading, refetch } = useQuery<SummaryResponse>({
    queryKey: ["strategy-summary"],
    queryFn: () => apiJson("strategy/summary"),
    refetchInterval: 90_000,
  });
  const { data: rankings } = useQuery<RankingsResponse>({
    queryKey: ["strategy-rankings"],
    queryFn: () => apiJson("strategy/rankings"),
    refetchInterval: 90_000,
  });
  const { data: regimes } = useQuery<RegimesResponse>({
    queryKey: ["strategy-regimes"],
    queryFn: () => apiJson("strategy/regimes"),
    refetchInterval: 90_000,
  });
  const { data: sectors } = useQuery<SectorsResponse>({
    queryKey: ["strategy-sectors"],
    queryFn: () => apiJson("strategy/sectors"),
    refetchInterval: 90_000,
  });
  const { data: timing } = useQuery<TimingResponse>({
    queryKey: ["strategy-timing"],
    queryFn: () => apiJson("strategy/timing"),
    refetchInterval: 90_000,
  });
  const { data: recs } = useQuery<RecommendationsResponse>({
    queryKey: ["strategy-recommendations"],
    queryFn: () => apiJson("strategy/recommendations"),
    refetchInterval: 90_000,
  });

  const isDisabled = summary?.status === "DISABLED";
  const isLoading  = sumLoading;

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview",        label: "Overview" },
    { id: "rankings",        label: "Rankings" },
    { id: "regimes",         label: "Regimes" },
    { id: "sectors",         label: "Sectors" },
    { id: "timing",          label: "Timing" },
    { id: "recommendations", label: "Recommendations" },
  ];

  // Chart data
  const profilesForChart = rankings?.profiles?.filter(p => p.total_trades > 0) ?? [];

  const netPnlBar  = profilesForChart.map((p, i) => ({ name: p.strategy_name, pnl: p.net_pnl, fill: PALETTE[i % PALETTE.length] }));
  const winRateBar = profilesForChart.map((p, i) => ({ name: p.strategy_name, win_rate: p.win_rate, fill: PALETTE[i % PALETTE.length] }));
  const pfBar      = profilesForChart.map((p, i) => ({ name: p.strategy_name, pf: Math.min(p.profit_factor, 10), fill: PALETTE[i % PALETTE.length] }));
  const ddBar      = profilesForChart.map((p, i) => ({ name: p.strategy_name, dd: p.max_drawdown_pct, fill: PALETTE[i % PALETTE.length] }));

  const regimeBar  = (regimes?.summary ?? []).map(r => ({ name: r.regime, pnl: r.net_pnl, wr: r.win_rate }));
  const sectorBar  = (sectors?.summary ?? []).map(s => ({ name: s.sector, pnl: s.net_pnl, wr: s.win_rate }));

  const slotEntries = Object.entries(timing?.slot_matrix ?? {});
  const slotBar     = slotEntries.map(([slot, s]) => ({ slot: slot.replace("–", "-"), pnl: s.net_pnl, wr: s.win_rate }));

  const dayOrder = ["Monday","Tuesday","Wednesday","Thursday","Friday"];
  const dayBar   = dayOrder
    .filter(d => (timing?.day_matrix?.[d]?.trades ?? 0) > 0)
    .map(d => ({ day: d.slice(0, 3), pnl: timing!.day_matrix[d].net_pnl, wr: timing!.day_matrix[d].win_rate }));

  const cr = summary?.criterion_rankings ?? {};

  return (
    <div className="p-6 space-y-6 max-w-[1600px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Zap className="h-6 w-6 text-amber-400" />
            Strategy Intelligence
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Read-only · Paper trading only · Advisory only
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground bg-card border border-border px-3 py-1.5 rounded-lg">PAPER / ADVISORY ONLY</span>
          <button onClick={() => refetch()} disabled={isLoading}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg px-3 py-1.5 transition-colors">
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {isDisabled && <DisabledBanner flag={(summary as any)?.feature_flag} />}

      {!isDisabled && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <KpiCard label="Best Strategy" icon={Trophy}
              value={summary?.best_strategy ?? "—"}
              sub={cr.highest_net_profit ? fmtRs(cr.highest_net_profit.net_pnl) : undefined}
              color="text-amber-400" />
            <KpiCard label="Worst Strategy" icon={Skull}
              value={summary?.worst_strategy ?? "—"}
              sub={summary ? `${summary.total_strategies} total` : undefined}
              color="text-red-400" />
            <KpiCard label="Highest Win Rate" icon={Target}
              value={cr.highest_win_rate ? `${fmt(cr.highest_win_rate.win_rate, 1)}%` : "—"}
              sub={cr.highest_win_rate?.strategy_name}
              color="text-emerald-400" />
            <KpiCard label="Highest PF" icon={BarChart3}
              value={cr.highest_profit_factor ? fmt(cr.highest_profit_factor.profit_factor, 2) : "—"}
              sub={cr.highest_profit_factor?.strategy_name}
              color="text-sky-400" />
            <KpiCard label="Lowest Drawdown" icon={ShieldCheck}
              value={cr.lowest_drawdown ? `${fmt(cr.lowest_drawdown.max_drawdown_pct, 1)}%` : "—"}
              sub={cr.lowest_drawdown?.strategy_name}
              color="text-violet-400" />
            <KpiCard label="Best Exec Score" icon={Zap}
              value={cr.best_execution ? fmt(cr.best_execution.avg_quality_score, 1) : "—"}
              sub={cr.best_execution?.strategy_name}
              color="text-teal-400" />
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-border">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={cn("px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
                  tab === t.id
                    ? "border-amber-400 text-amber-400"
                    : "border-transparent text-muted-foreground hover:text-foreground")}>
                {t.label}
              </button>
            ))}
          </div>

          {/* ── Overview tab ── */}
          {tab === "overview" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Net P&L by Strategy">
                  {netPnlBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={netPnlBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} width={54} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [fmtRs(v), "Net P&L"]} />
                        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                          {netPnlBar.map((b, i) => <Cell key={i} fill={b.pnl >= 0 ? PALETTE[i % PALETTE.length] : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No closed trades yet" />}
                </ChartCard>

                <ChartCard title="Win Rate Comparison">
                  {winRateBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={winRateBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `${v}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${fmt(v, 1)}%`, "Win Rate"]} />
                        <Bar dataKey="win_rate" radius={[3, 3, 0, 0]}>
                          {winRateBar.map((b, i) => <Cell key={i} fill={b.win_rate >= 50 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No closed trades yet" />}
                </ChartCard>

                <ChartCard title="Profit Factor Comparison">
                  {pfBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={pfBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [fmt(v, 2), "Profit Factor"]} />
                        <Bar dataKey="pf" radius={[3, 3, 0, 0]}>
                          {pfBar.map((b, i) => <Cell key={i} fill={b.pf >= 1.5 ? "#10b981" : b.pf >= 1 ? "#f59e0b" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No data" />}
                </ChartCard>

                <ChartCard title="Drawdown Comparison">
                  {ddBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={ddBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `${v}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${fmt(v, 2)}%`, "Max Drawdown"]} />
                        <Bar dataKey="dd" radius={[3, 3, 0, 0]}>
                          {ddBar.map((b, i) => <Cell key={i} fill={b.dd < 10 ? "#10b981" : b.dd < 20 ? "#f59e0b" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No data" />}
                </ChartCard>
              </div>
            </div>
          )}

          {/* ── Rankings tab ── */}
          {tab === "rankings" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-card p-5">
                <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                  <Trophy className="h-4 w-4 text-amber-400" /> Strategy Leaderboard
                </h3>
                {rankings?.leaderboard && rankings.leaderboard.length > 0 ? (
                  <div className="overflow-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-muted-foreground border-b border-border">
                          {["Rank","Strategy","Trades","Win %","Profit Factor","Net P&L","Max DD%","Exec Score","Rank Score"].map(h => (
                            <th key={h} className="text-right pb-2 px-2 first:text-left">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rankings.leaderboard.map(r => (
                          <tr key={r.strategy_name} className="border-b border-border/40 hover:bg-muted/20">
                            <td className="py-2 px-2 font-bold text-amber-400">#{r.rank}</td>
                            <td className="py-2 px-2 font-semibold">{r.strategy_name}</td>
                            <td className="py-2 px-2 text-right tabular-nums">{r.total_trades}</td>
                            <td className={cn("py-2 px-2 text-right tabular-nums font-medium",
                              r.win_rate >= 50 ? "text-emerald-400" : "text-red-400")}>
                              {fmt(r.win_rate, 1)}%
                            </td>
                            <td className={cn("py-2 px-2 text-right tabular-nums",
                              r.profit_factor >= 1.5 ? "text-emerald-400" : r.profit_factor >= 1 ? "text-amber-400" : "text-red-400")}>
                              {fmt(r.profit_factor, 2)}
                            </td>
                            <td className={cn("py-2 px-2 text-right tabular-nums font-semibold",
                              r.net_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                              {fmtRs(r.net_pnl)}
                            </td>
                            <td className={cn("py-2 px-2 text-right tabular-nums",
                              r.max_drawdown_pct < 10 ? "text-emerald-400" : r.max_drawdown_pct < 20 ? "text-amber-400" : "text-red-400")}>
                              {fmt(r.max_drawdown_pct, 2)}%
                            </td>
                            <td className="py-2 px-2 text-right tabular-nums">{fmt(r.avg_quality_score, 1)}</td>
                            <td className="py-2 px-2 text-right tabular-nums font-semibold text-sky-400">{fmt(r.rank_score, 1)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <EmptyState label="No strategies with completed trades" />}
              </div>

              {/* Strategy statistics detail */}
              {rankings?.profiles && rankings.profiles.filter(p => p.total_trades > 0).map(p => (
                <div key={p.strategy_name} className="rounded-xl border border-border bg-card p-5">
                  <h3 className="text-sm font-semibold mb-3 flex items-center justify-between">
                    <span>{p.strategy_name}</span>
                    <span className="text-xs text-muted-foreground font-normal">Rank #{p.rank} · Score {fmt(p.rank_score, 1)}</span>
                  </h3>
                  <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-xs">
                    {[
                      ["Trades",    p.total_trades.toString()],
                      ["Win Rate",  `${fmt(p.win_rate, 1)}%`],
                      ["PF",        fmt(p.profit_factor, 2)],
                      ["Net P&L",   fmtRs(p.net_pnl)],
                      ["Max DD",    `${fmt(p.max_drawdown_pct, 2)}%`],
                      ["Expectancy",fmtRs(p.expectancy)],
                      ["R/R",       fmt(p.risk_reward, 2)],
                      ["Hold Avg",  fmtHold(p.avg_holding_seconds)],
                      ["Exec Score",fmt(p.avg_quality_score, 1)],
                    ].map(([l, v]) => (
                      <div key={l} className="flex flex-col gap-0.5">
                        <span className="text-muted-foreground">{l}</span>
                        <span className="font-semibold tabular-nums">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── Regimes tab ── */}
          {tab === "regimes" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="P&L by Market Regime">
                  {regimeBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={regimeBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} width={50} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [fmtRs(v), "Net P&L"]} />
                        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                          {regimeBar.map((r, i) => <Cell key={i} fill={r.pnl >= 0 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No regime data" />}
                </ChartCard>

                <ChartCard title="Win Rate by Regime">
                  {regimeBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={regimeBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `${v}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${fmt(v, 1)}%`, "Win Rate"]} />
                        <Bar dataKey="wr" radius={[3, 3, 0, 0]}>
                          {regimeBar.map((r, i) => <Cell key={i} fill={r.wr >= 50 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No regime data" />}
                </ChartCard>
              </div>

              <div className="rounded-xl border border-border bg-card p-5">
                <h3 className="text-sm font-semibold mb-3">Market Regime Matrix</h3>
                {regimes?.summary && regimes.summary.length > 0 ? (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        {["Regime","Trades","Win %","Net P&L","Avg P&L","Best Strategy"].map(h => (
                          <th key={h} className="text-right pb-2 px-2 first:text-left">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {regimes.summary.map(r => (
                        <tr key={r.regime} className="border-b border-border/40">
                          <td className="py-2 px-2 font-medium">{r.regime}</td>
                          <td className="py-2 px-2 text-right tabular-nums">{r.trades}</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums", r.win_rate >= 50 ? "text-emerald-400" : "text-red-400")}>{fmt(r.win_rate, 1)}%</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums font-semibold", r.net_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtRs(r.net_pnl)}</td>
                          <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">{fmtRs(r.avg_pnl)}</td>
                          <td className="py-2 px-2 text-right text-sky-400">{r.best_strategy}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <EmptyState label="No regime data yet" />}
              </div>
            </div>
          )}

          {/* ── Sectors tab ── */}
          {tab === "sectors" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: "Best Sector",  value: sectors?.best_sector ?? "—",  color: "text-emerald-400", icon: TrendingUp },
                  { label: "Worst Sector", value: sectors?.worst_sector ?? "—", color: "text-red-400",     icon: Skull },
                  { label: "Best Win Rate",value: sectors?.best_sector ?? "—",  color: "text-sky-400",    icon: Target },
                  { label: "Best Return",  value: sectors?.best_sector ?? "—",  color: "text-amber-400",  icon: BarChart3 },
                ].map(({ label, value, color, icon: Icon }) => (
                  <div key={label} className="rounded-xl border border-border bg-card p-4">
                    <div className="flex items-center gap-1.5 text-muted-foreground text-xs mb-1.5"><Icon className="h-3.5 w-3.5" />{label}</div>
                    <p className={cn("text-lg font-bold", color)}>{value}</p>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Sector P&L">
                  {sectorBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={sectorBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} width={46} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [fmtRs(v), "Net P&L"]} />
                        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                          {sectorBar.map((s, i) => <Cell key={i} fill={s.pnl >= 0 ? PALETTE[i % PALETTE.length] : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No sector data" />}
                </ChartCard>

                <ChartCard title="Sector Win Rate">
                  {sectorBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={sectorBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="name" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis domain={[0,100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `${v}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${fmt(v, 1)}%`, "Win Rate"]} />
                        <Bar dataKey="wr" radius={[3, 3, 0, 0]}>
                          {sectorBar.map((s, i) => <Cell key={i} fill={s.wr >= 50 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No sector data" />}
                </ChartCard>
              </div>

              <div className="rounded-xl border border-border bg-card p-5">
                <h3 className="text-sm font-semibold mb-3">Sector Matrix</h3>
                {sectors?.summary && sectors.summary.length > 0 ? (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        {["Sector","Trades","Win %","Net P&L","Avg P&L"].map(h => (
                          <th key={h} className="text-right pb-2 px-2 first:text-left">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sectors.summary.map(s => (
                        <tr key={s.sector} className="border-b border-border/40">
                          <td className="py-2 px-2 font-medium">{s.sector}</td>
                          <td className="py-2 px-2 text-right tabular-nums">{s.trades}</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums", s.win_rate >= 50 ? "text-emerald-400" : "text-red-400")}>{fmt(s.win_rate,1)}%</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums font-semibold", s.net_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtRs(s.net_pnl)}</td>
                          <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">{fmtRs(s.avg_pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <EmptyState label="No sector data yet" />}
              </div>
            </div>
          )}

          {/* ── Timing tab ── */}
          {tab === "timing" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: "Best Day",    value: timing?.best_day  ?? "—", icon: Trophy,  color: "text-emerald-400" },
                  { label: "Worst Day",   value: timing?.worst_day ?? "—", icon: Skull,   color: "text-red-400" },
                  { label: "Best Slot",   value: timing?.best_slot ?? "—", icon: Clock,   color: "text-sky-400" },
                  { label: "Worst Slot",  value: timing?.worst_slot?? "—", icon: AlertTriangle, color: "text-amber-400" },
                ].map(({ label, value, icon: Icon, color }) => (
                  <div key={label} className="rounded-xl border border-border bg-card p-4">
                    <div className="flex items-center gap-1.5 text-muted-foreground text-xs mb-1.5"><Icon className="h-3.5 w-3.5" />{label}</div>
                    <p className={cn("text-base font-bold", color)}>{value}</p>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="P&L by Time Slot">
                  {slotBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={slotBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="slot" tick={{ fontSize: 8, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} width={46} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [fmtRs(v), "Net P&L"]} />
                        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                          {slotBar.map((s, i) => <Cell key={i} fill={s.pnl >= 0 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No timing data" />}
                </ChartCard>

                <ChartCard title="P&L by Day of Week">
                  {dayBar.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={dayBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="day" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                          tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} width={46} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [fmtRs(v), "Net P&L"]} />
                        <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                          {dayBar.map((d, i) => <Cell key={i} fill={d.pnl >= 0 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No timing data" />}
                </ChartCard>
              </div>

              <div className="rounded-xl border border-border bg-card p-5">
                <h3 className="text-sm font-semibold mb-3">Time-of-Day Performance Matrix</h3>
                {slotBar.length > 0 ? (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        {["Time Slot","Trades","Win %","Net P&L","Avg P&L"].map(h => (
                          <th key={h} className="text-right pb-2 px-2 first:text-left">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(timing?.slot_matrix ?? {}).map(([slot, s]) => (
                        <tr key={slot} className="border-b border-border/40">
                          <td className="py-2 px-2 font-medium font-mono text-xs">{slot}</td>
                          <td className="py-2 px-2 text-right tabular-nums">{s.trades}</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums", s.win_rate >= 50 ? "text-emerald-400" : "text-red-400")}>{fmt(s.win_rate,1)}%</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums font-semibold", s.net_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtRs(s.net_pnl)}</td>
                          <td className="py-2 px-2 text-right tabular-nums text-muted-foreground">{fmtRs(s.avg_pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <EmptyState label="No timing data yet" />}
              </div>
            </div>
          )}

          {/* ── Recommendations tab ── */}
          {tab === "recommendations" && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Advisory only — recommendations never automatically change, enable, or disable any strategy.
              </p>
              {recs?.recommendations && recs.recommendations.length > 0 ? (
                recs.recommendations.map(r => (
                  <div key={r.strategy_name}
                    className={cn("rounded-xl border p-4 flex items-start gap-4", severityBg(r.severity))}>
                    <div className="mt-0.5 shrink-0">{severityIcon(r.severity)}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 flex-wrap">
                        <span className="font-semibold text-sm">{r.strategy_name}</span>
                        <span className="text-xs font-bold uppercase tracking-wide">{r.recommendation}</span>
                        {r.rank > 0 && <span className="text-xs text-muted-foreground">Rank #{r.rank}</span>}
                      </div>
                      <p className="text-xs mt-1 opacity-80">{r.rationale}</p>
                      <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
                        <span>Trades: {r.total_trades}</span>
                        <span>Win: {fmt(r.win_rate,1)}%</span>
                        <span>PF: {fmt(r.profit_factor,2)}</span>
                        <span>P&L: {fmtRs(r.net_pnl)}</span>
                        <span>DD: {fmt(r.max_drawdown_pct,1)}%</span>
                      </div>
                    </div>
                  </div>
                ))
              ) : <EmptyState label="No strategies with completed trades" />}
            </div>
          )}
        </>
      )}
    </div>
  );
}
