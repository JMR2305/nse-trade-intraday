/**
 * AIValidationV2Page.tsx — AI Validation Centre V2
 *
 * 10-tab page covering the complete validation lifecycle.
 * All API response shapes verified against the Python backend.
 * ADVISORY ONLY — never modifies live parameters or places real orders.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import {
  Play, Pause, RotateCcw, FastForward, Rewind, SkipForward,
  TrendingUp, AlertTriangle, CheckCircle2,
  BarChart3, Brain, Target, Zap, Clock, Activity, Award, Info,
  ChevronDown, ChevronUp, FlaskConical, Search, RefreshCw,
  ArrowUpRight, ArrowDownRight, Minus, ExternalLink, Shield,
} from "lucide-react";
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ─────────────────────────────────────────────────────────────────────────────
// Backend API shapes (verified against Python source)
// ─────────────────────────────────────────────────────────────────────────────

/** Status values returned by the Python backend (uppercase). */
type RunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "ERROR" | string;

/** Row returned by GET /validation-v2/backtest (list) */
interface RunListItem {
  run_id: string;
  status: RunStatus;
  total_decisions: number;
  total_trades: number;
  start_date: string | null;
  end_date: string | null;
  interval: string;
  created_at: string;
  completed_at: string | null;
}

/** _aggregate_trades shape (used inside run detail, optimizer results, model-comparison stats) */
interface AggStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  win_rate_pct: number | null;
  loss_rate_pct: number | null;
  avg_pnl_pct: number | null;
  best_trade_pct: number | null;
  worst_trade_pct: number | null;
  max_drawdown_pct: number | null;
  profit_factor: number | null;
  expectancy_pct: number | null;
  sharpe_ratio: number | null;
  avg_holding_days: number | null;
  avg_confidence: number | null;
  sufficient_data: boolean;
}

/** Row from validation_v2_decisions (decisions_sample) */
interface DecisionRow {
  symbol: string;
  strategy: string;
  bar_date: string;
  bar_close: number | null;
  recommendation: string;
  final_confidence: number;
  reason: string;
  threshold: number | null;
  entry_signal: boolean;
  filter_passed: boolean;
  rr_ratio: number | null;
  detail: Record<string, unknown>;
}

/** Row from validation_v2_trades */
interface TradeRow {
  id?: number;
  run_id?: string;
  symbol: string;
  strategy: string;
  entry_date: string;
  entry_price: number;
  stop_loss: number | null;
  target_price: number | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  pnl_pct: number | null;
  holding_days: number | null;
  mfe_pct: number | null;
  mad_pct: number | null;
  result: string | null;
  confidence: number | null;
}

/** Row from validation_v2_missed */
interface MissedRow {
  symbol: string;
  strategy: string;
  bar_date: string;
  ai_decision: string;
  ai_confidence: number | null;
  actual_move_pct: number;
  potential_profit_pct: number;
  rejection_reason: string;
  improvement_suggestion: string;
  run_id: string;
}

/** Live progress info from a RUNNING run */
interface RunProgress {
  symbols_done: number;
  symbols_total: number;
  current_symbol: string;
}

/** Full run detail from GET /validation-v2/backtest/:runId */
interface RunDetail {
  success?: boolean;
  run_id: string;
  status: RunStatus;
  config: Record<string, unknown>;
  symbols: string[];
  strategies: string[];
  interval: string;
  total_decisions: number;
  total_trades: number;
  stats: AggStats;
  recommendation_distribution: Record<string, number>;
  most_common_rejection: string;
  decisions_sample: DecisionRow[];
  trades: TradeRow[];
  missed_opportunities: MissedRow[];
  progress?: RunProgress;
  symbol_errors?: string[];
  generated_at: string;
}

/** Session timeline event */
interface TimelineEvent {
  time: string;
  type: string;
  label: string;
  bar_date?: string;
  symbol?: string;
  pnl_pct?: number | null;
  exit_reason?: string;
  detail?: string;
  recommendation?: string;
  confidence?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const SYMBOLS = [
  "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
  "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
  "AXISBANK", "KOTAKBANK", "TATAMOTORS", "TITAN", "NESTLEIND",
  "HINDUNILVR", "HCLTECH", "SUNPHARMA", "ITC", "ONGC",
];

const PERIODS = [
  { label: "1 Month",  days: 30  },
  { label: "3 Months", days: 90  },
  { label: "6 Months", days: 180 },
  { label: "1 Year",   days: 365 },
];

const TABS = [
  { id: "overview",      label: "Overview",          icon: BarChart3 },
  { id: "backtest",      label: "Backtest Runner",   icon: FlaskConical },
  { id: "simulation",    label: "Trade Simulation",  icon: Activity },
  { id: "missed",        label: "Missed Opps",       icon: TrendingUp },
  { id: "ai-vs-market",  label: "AI vs Market",      icon: Target },
  { id: "optimizer",     label: "Param Optimizer",   icon: Zap },
  { id: "explainability",label: "Explainability",    icon: Brain },
  { id: "playback",      label: "Session Playback",  icon: Play },
  { id: "performance",   label: "Performance",       icon: Award },
  { id: "model-compare", label: "Model Comparison",  icon: BarChart3 },
];

const REC_COLOR: Record<string, string> = {
  BUY:          "bg-emerald-500/15 border-emerald-600/50 text-emerald-300",
  STRONG_BUY:   "bg-teal-500/15 border-teal-600/50 text-teal-300",
  SELL:         "bg-red-500/15 border-red-600/50 text-red-300",
  AVOID:        "bg-red-500/15 border-red-600/50 text-red-300",
  WATCH:        "bg-amber-500/15 border-amber-600/50 text-amber-300",
  HOLD:         "bg-slate-600/40 border-slate-600/50 text-slate-300",
};

function today() { return new Date().toISOString().split("T")[0]; }
function daysAgo(n: number) {
  const d = new Date(); d.setDate(d.getDate() - n);
  return d.toISOString().split("T")[0];
}
function fmt(n: number | null | undefined, d = 1) {
  return n == null ? "—" : n.toFixed(d);
}
function fmtPct(n: number | null | undefined, signed = true) {
  if (n == null) return "—";
  return `${signed && n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared UI primitives
// ─────────────────────────────────────────────────────────────────────────────

function DecisionBadge({ rec }: { rec: string }) {
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded border ${REC_COLOR[rec] ?? "bg-slate-700/40 border-slate-600 text-slate-300"}`}>
      {rec}
    </span>
  );
}

function ResultBadge({ result }: { result: string | null }) {
  if (!result) return <span className="text-slate-500 text-xs">—</span>;
  const map: Record<string, string> = {
    WIN:       "bg-emerald-500/15 border-emerald-600/50 text-emerald-300",
    LOSS:      "bg-red-500/15 border-red-600/50 text-red-300",
    BREAKEVEN: "bg-amber-500/15 border-amber-600/50 text-amber-300",
  };
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-bold rounded border ${map[result] ?? "bg-slate-700/40 border-slate-600 text-slate-300"}`}>
      {result}
    </span>
  );
}

function StatCard({ label, value, sub, accent = "neutral" }: {
  label: string; value: string; sub?: string;
  accent?: "green" | "red" | "amber" | "teal" | "neutral";
}) {
  const ac = { green: "text-emerald-400", red: "text-red-400", amber: "text-amber-400", teal: "text-teal-400", neutral: "text-white" }[accent];
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">{label}</div>
      <div className={`text-xl font-bold font-mono ${ac}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function AdvisoryBanner({ text }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 bg-amber-900/20 border border-amber-700/40 rounded-xl px-4 py-2.5 text-amber-300 text-xs">
      <Shield size={13} className="flex-shrink-0" />
      {text ?? "Advisory only — research use only. Do not apply configurations or conclusions automatically."}
    </div>
  );
}

function EmptyState({ icon: Icon, title, sub }: { icon: any; title: string; sub?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <Icon size={40} className="text-slate-600 mb-3" />
      <p className="text-slate-400 font-medium">{title}</p>
      {sub && <p className="text-slate-600 text-sm mt-1">{sub}</p>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 0 — Dashboard Overview (Module 11)
// ─────────────────────────────────────────────────────────────────────────────

function OverviewTab({ onNavigate }: { onNavigate: (tab: number) => void }) {
  // GET /validation-v2/backtest → { runs: RunListItem[], count, label }
  const runsQ = useQuery<{ runs: RunListItem[] }>({
    queryKey: ["v2-runs"],
    queryFn:  () => apiJson("validation-v2/backtest"),
    staleTime: 30_000,
  });
  // GET /validation-v2/performance → { stats, period, most_common_rejection, ... }
  const perfQ = useQuery<{ stats: AggStats; most_common_rejection: string; period: string }>({
    queryKey: ["v2-performance", "monthly"],
    queryFn:  () => apiJson("validation-v2/performance?period=monthly"),
    staleTime: 60_000,
  });
  // GET /validation-v2/missed-opportunities → { missed: MissedRow[], count, ... }
  const missedQ = useQuery<{ missed: MissedRow[]; count: number }>({
    queryKey: ["v2-missed"],
    queryFn:  () => apiJson("validation-v2/missed-opportunities"),
    staleTime: 60_000,
  });
  // GET /validation-v2/optimizer/recommendation → { best_config, recommendation, ... }
  const optQ = useQuery<{ best_config?: { sharpe_ratio?: number } & Record<string, unknown>; recommendation?: string }>({
    queryKey: ["v2-opt-rec"],
    queryFn:  () => apiJson("validation-v2/optimizer/recommendation"),
    staleTime: 60_000,
  });

  const runs = runsQ.data?.runs ?? [];
  const perfStats = perfQ.data?.stats;
  const missed = missedQ.data?.missed ?? [];
  const bestCfg = optQ.data?.best_config as any;

  const topMissed = [...missed].sort((a, b) => (b.potential_profit_pct ?? 0) - (a.potential_profit_pct ?? 0))[0];
  const bestSharpe = bestCfg?.sharpe_ratio ?? null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Backtest Runs" value={String(runs.length)} sub="across all sessions" />
        <StatCard label="Overall Win Rate"
          value={perfStats?.win_rate_pct != null ? `${perfStats.win_rate_pct.toFixed(1)}%` : "—"}
          sub="all replay trades"
          accent={perfStats?.win_rate_pct != null ? (perfStats.win_rate_pct >= 55 ? "green" : perfStats.win_rate_pct >= 45 ? "amber" : "red") : "neutral"} />
        <StatCard label="Top Missed Ticker" value={topMissed?.symbol ?? "—"}
          sub={topMissed ? `+${topMissed.potential_profit_pct.toFixed(1)}% potential` : "No missed opps yet"}
          accent="amber" />
        <StatCard label="Best Config Sharpe"
          value={bestSharpe != null ? Number(bestSharpe).toFixed(2) : "—"}
          sub="from optimizer"
          accent={bestSharpe != null ? (Number(bestSharpe) >= 1 ? "green" : Number(bestSharpe) >= 0 ? "amber" : "red") : "neutral"} />
      </div>

      <AdvisoryBanner />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { icon: FlaskConical, title: "Backtest Runner",      sub: "Run multi-symbol backtests with V2 engine",    tab: 1 },
          { icon: Activity,     title: "Trade Simulation",     sub: "Drill into individual trade drill-downs",      tab: 2 },
          { icon: TrendingUp,   title: "Missed Opportunities", sub: "Rejected stocks that moved ≥+2% afterward",   tab: 3 },
          { icon: Target,       title: "AI vs Market",         sub: "Run accuracy vs recommendation distribution",  tab: 4 },
          { icon: Zap,          title: "Parameter Optimizer",  sub: "Grid-search best config ranked by Sharpe",    tab: 5 },
          { icon: Brain,        title: "Agent Explainability", sub: "Per-decision pipeline scorecard",             tab: 6 },
          { icon: Play,         title: "Session Playback",     sub: "Timeline scrubber with play/pause controls",  tab: 7 },
          { icon: Award,        title: "Performance Analytics",sub: "Win rate, drawdown, agent accuracy KPIs",     tab: 8 },
          { icon: BarChart3,    title: "Model Comparison",     sub: "Current vs candidate config verdict",         tab: 9 },
        ].map(({ icon: Icon, title, sub, tab }) => (
          <button key={tab} onClick={() => onNavigate(tab)}
            className="flex items-start gap-3 p-4 bg-slate-800/60 border border-slate-700/50 rounded-xl hover:bg-slate-700/60 hover:border-slate-600 transition-all text-left">
            <div className="mt-0.5 p-2 bg-slate-700/60 rounded-lg flex-shrink-0">
              <Icon size={16} className="text-teal-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">{title}</p>
              <p className="text-xs text-slate-400 mt-0.5">{sub}</p>
            </div>
          </button>
        ))}
      </div>

      {runs.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">Recent Backtest Runs</h3>
            <button onClick={() => onNavigate(1)} className="text-xs text-teal-400 hover:text-teal-300 flex items-center gap-1">
              View all <ExternalLink size={11} />
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-700/50 text-slate-400">
                  {["Run ID", "Status", "Decisions", "Trades", "Interval", "Created"].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 5).map(r => (
                  <tr key={r.run_id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                    <td className="px-3 py-2 text-slate-300">{r.run_id.slice(0, 10)}…</td>
                    <td className="px-3 py-2">
                      <span className={r.status === "COMPLETED" ? "text-emerald-400" : r.status === "RUNNING" ? "text-amber-400 animate-pulse" : "text-red-400"}>
                        {r.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-300">{r.total_decisions}</td>
                    <td className="px-3 py-2 text-emerald-400">{r.total_trades}</td>
                    <td className="px-3 py-2 text-slate-400">{r.interval}</td>
                    <td className="px-3 py-2 text-slate-400">{r.created_at?.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 1 — Backtest Runner (Modules 1+2)
// ─────────────────────────────────────────────────────────────────────────────

function BacktestRunnerTab({ onRunComplete }: { onRunComplete: (run: RunDetail) => void }) {
  const qc = useQueryClient();
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(["RELIANCE", "TCS", "INFY"]);
  const [strategy, setStrategy] = useState("trend_rider");
  const [periodIdx, setPeriodIdx] = useState(1);
  const [interval, setIntervalVal] = useState("1d");
  const [capital, setCapital] = useState(10000);
  const [stopPct, setStopPct] = useState(2.0);
  const [targetPct, setTargetPct] = useState(5.0);
  const [confThresh, setConfThresh] = useState(55);
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // GET /validation-v2/backtest → { runs: RunListItem[], count }
  const runsQ = useQuery<{ runs: RunListItem[] }>({
    queryKey: ["v2-runs"],
    queryFn:  () => apiJson("validation-v2/backtest"),
    staleTime: 10_000,
  });

  // GET /validation-v2/backtest/:runId → RunDetail  (poll while running)
  const currentRunQ = useQuery<RunDetail>({
    queryKey: ["v2-run", runId],
    queryFn:  () => apiJson(`validation-v2/backtest/${runId}`),
    enabled:  !!runId,
    refetchInterval: (q) => {
      const d = q.state.data as RunDetail | undefined;
      return (!d || d.status === "RUNNING" || d.status === "PENDING") ? 3000 : false;
    },
  });
  const currentRun = currentRunQ.data;

  useEffect(() => {
    if (currentRun?.status === "COMPLETED") {
      setRunning(false);
      qc.invalidateQueries({ queryKey: ["v2-runs"] });
      qc.invalidateQueries({ queryKey: ["v2-missed"] });
      onRunComplete(currentRun);
    } else if (currentRun?.status === "ERROR") {
      setRunning(false);
      setError(String((currentRun as any).error ?? "Run failed — check backend logs"));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentRun?.status]);

  const toggleSymbol = (sym: string) =>
    setSelectedSymbols(prev => prev.includes(sym) ? prev.filter(s => s !== sym) : [...prev, sym]);

  const handleRun = async () => {
    if (selectedSymbols.length === 0) return;
    setRunning(true); setError(null);
    const period = PERIODS[periodIdx];
    try {
      const resp = await apiJson<{ run_id: string }>("validation-v2/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbols: selectedSymbols,
          strategies: [strategy],    // backend reads config.get("strategies")
          start_date: daysAgo(period.days),
          end_date: today(),
          interval,
          initial_capital: capital,
          stop_pct: stopPct,
          target_pct: targetPct,
          confidence_threshold: confThresh,
        }),
      }, 180_000);
      setRunId(resp.run_id);
    } catch (e: any) {
      setError(String(e?.message ?? e));
      setRunning(false);
    }
  };

  const runs = runsQ.data?.runs ?? [];

  return (
    <div className="space-y-6">
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <FlaskConical size={15} className="text-teal-400" /> Run Configuration
        </h3>
        <div>
          <label className="text-xs text-slate-400 uppercase tracking-widest mb-2 block">
            Symbols ({selectedSymbols.length} selected)
          </label>
          <div className="flex flex-wrap gap-1.5">
            {SYMBOLS.map(sym => (
              <button key={sym} onClick={() => toggleSymbol(sym)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition-all ${
                  selectedSymbols.includes(sym)
                    ? "bg-teal-500/20 border-teal-500/60 text-teal-300"
                    : "bg-slate-700/40 border-slate-600/50 text-slate-400 hover:border-slate-500"
                }`}>
                {sym}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="flex flex-col gap-1 col-span-2">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Strategy</label>
            <select value={strategy} onChange={e => setStrategy(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500">
              {["trend_rider", "momentum_breakout", "vwap_reversal", "orb_breakout"].map(s => (
                <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Period</label>
            <select value={periodIdx} onChange={e => setPeriodIdx(Number(e.target.value))}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500">
              {PERIODS.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Interval</label>
            <select value={interval} onChange={e => setIntervalVal(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500">
              <option value="1d">Daily</option>
              <option value="1h">Hourly</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Capital (₹)</label>
            <input type="number" value={capital} onChange={e => setCapital(Number(e.target.value))} step={1000}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500" />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Stop %</label>
            <input type="number" value={stopPct} onChange={e => setStopPct(Number(e.target.value))} step={0.5} min={0.5} max={5}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Target %</label>
            <input type="number" value={targetPct} onChange={e => setTargetPct(Number(e.target.value))} step={0.5} min={1} max={20}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Min Confidence</label>
            <input type="number" value={confThresh} onChange={e => setConfThresh(Number(e.target.value))} step={5} min={40} max={90}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500" />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={handleRun} disabled={running || selectedSymbols.length === 0}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-teal-500 hover:bg-teal-400 text-white text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {running ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? "Running…" : "Run Backtest"}
          </button>
          {running && (() => {
            const prog = currentRun?.progress;
            if (prog && prog.symbols_total > 0) {
              const pct = Math.round((prog.symbols_done / prog.symbols_total) * 100);
              const label = prog.current_symbol
                ? `Processing ${prog.current_symbol} (${prog.symbols_done + 1} / ${prog.symbols_total})…`
                : prog.symbols_done >= prog.symbols_total
                  ? "Finalising…"
                  : `Starting symbol ${prog.symbols_done + 1} / ${prog.symbols_total}…`;
              return (
                <span className="flex items-center gap-2 text-xs text-amber-400">
                  <span className="animate-pulse">{label}</span>
                  <span className="font-mono text-slate-500">{pct}%</span>
                </span>
              );
            }
            return <span className="text-xs text-amber-400 animate-pulse">Processing {selectedSymbols.length} symbol{selectedSymbols.length > 1 ? "s" : ""}…</span>;
          })()}
          {error && <span className="text-xs text-red-400 flex items-center gap-1"><AlertTriangle size={12} /> {error}</span>}
        </div>
      </div>

      {currentRun && (currentRun.status === "RUNNING" || currentRun.status === "PENDING") && (
        <BacktestProgressPanel run={currentRun} />
      )}

      {currentRun && currentRun.status === "COMPLETED" && <RunResultsPanel run={currentRun} />}

      {/* Past runs list */}
      {runs.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50">
            <h3 className="text-sm font-semibold text-white">All Backtest Runs</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-700/50 text-slate-400">
                  {["Run ID", "Status", "Decisions", "Trades", "Start", "End", "Interval", "Created"].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-normal uppercase tracking-widest text-[10px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.run_id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                    <td className="px-3 py-2 text-slate-300">{r.run_id.slice(0, 10)}…</td>
                    <td className="px-3 py-2">
                      <span className={r.status === "COMPLETED" ? "text-emerald-400" : r.status === "RUNNING" ? "text-amber-400 animate-pulse" : "text-slate-400"}>
                        {r.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-300">{r.total_decisions}</td>
                    <td className="px-3 py-2 text-emerald-400">{r.total_trades}</td>
                    <td className="px-3 py-2 text-slate-400">{r.start_date?.slice(0, 10) ?? "—"}</td>
                    <td className="px-3 py-2 text-slate-400">{r.end_date?.slice(0, 10) ?? "—"}</td>
                    <td className="px-3 py-2 text-slate-400">{r.interval}</td>
                    <td className="px-3 py-2 text-slate-500">{r.created_at?.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {runs.length === 0 && !running && (
        <EmptyState icon={FlaskConical} title="No backtest runs yet" sub="Select symbols and click Run Backtest to begin" />
      )}
    </div>
  );
}

function BacktestProgressPanel({ run }: { run: RunDetail }) {
  const prog = run.progress;
  const total = prog?.symbols_total ?? run.symbols?.length ?? 0;
  const done = prog?.symbols_done ?? 0;
  const current = prog?.current_symbol ?? "";
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const errors = run.symbol_errors ?? [];

  const label = current
    ? `Processing ${current} (${done + 1} / ${total})…`
    : done >= total && total > 0
      ? "Finalising results…"
      : `Starting (${done} / ${total} done)…`;

  return (
    <div className="bg-slate-800/60 border border-teal-700/40 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2 text-teal-300 text-sm font-semibold">
        <Activity size={14} className="animate-pulse" /> {label}
      </div>

      {/* Progress bar */}
      <div className="relative h-2 bg-slate-700/60 rounded-full overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-teal-500 rounded-full transition-all duration-500"
          style={{ width: `${Math.max(2, pct)}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{done} of {total} symbol{total !== 1 ? "s" : ""} done</span>
        <span className="font-mono">{pct}%</span>
      </div>

      {/* Run ID */}
      <div className="text-xs text-slate-500">
        Run ID: <span className="text-slate-300 font-mono">{run.run_id}</span>
      </div>

      {/* Inline symbol errors */}
      {errors.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-amber-400 font-medium flex items-center gap-1">
            <AlertTriangle size={11} /> {errors.length} symbol{errors.length > 1 ? "s" : ""} had errors (run continues)
          </p>
          <ul className="space-y-0.5">
            {errors.map((e, i) => (
              <li key={i} className="text-xs text-red-400 font-mono bg-red-900/10 border border-red-800/30 rounded px-2 py-1 truncate">
                {e}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RunResultsPanel({ run }: { run: RunDetail }) {
  const s = run.stats;
  return (
    <div className="space-y-4">
      <div className="bg-slate-800/60 border border-emerald-700/30 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold text-white">Run {run.run_id.slice(0, 10)}</div>
          <span className="text-xs text-emerald-400 font-medium">✓ Complete</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
          <StatCard label="Symbols" value={String(run.symbols?.length ?? "—")} />
          <StatCard label="Decisions" value={String(run.total_decisions)} />
          <StatCard label="Trades" value={String(run.total_trades)} accent="teal" />
          <StatCard label="Win Rate" value={s?.win_rate_pct != null ? `${s.win_rate_pct.toFixed(1)}%` : "—"}
            accent={s?.win_rate_pct != null ? (s.win_rate_pct >= 55 ? "green" : s.win_rate_pct >= 45 ? "amber" : "red") : "neutral"} />
          <StatCard label="Avg P&L" value={fmtPct(s?.avg_pnl_pct)}
            accent={s?.avg_pnl_pct != null ? (s.avg_pnl_pct >= 0 ? "green" : "red") : "neutral"} />
          <StatCard label="Sharpe" value={s?.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : "—"}
            accent={s?.sharpe_ratio != null ? (s.sharpe_ratio >= 1 ? "green" : s.sharpe_ratio >= 0 ? "amber" : "red") : "neutral"} />
          <StatCard label="Max DD" value={fmtPct(s?.max_drawdown_pct, false)} accent="red" />
        </div>
        {run.most_common_rejection && (
          <p className="mt-2 text-xs text-slate-500">
            Most common rejection: <span className="text-slate-300">{run.most_common_rejection}</span>
          </p>
        )}
        {run.symbol_errors && run.symbol_errors.length > 0 && (
          <div className="mt-3 space-y-1">
            <p className="text-xs text-amber-400 font-medium flex items-center gap-1">
              <AlertTriangle size={11} /> {run.symbol_errors.length} symbol error{run.symbol_errors.length > 1 ? "s" : ""}
            </p>
            <ul className="space-y-0.5">
              {run.symbol_errors.map((e: string, i: number) => (
                <li key={i} className="text-xs text-red-400 font-mono bg-red-900/10 border border-red-800/30 rounded px-2 py-1 truncate">
                  {e}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Decisions sample table */}
      {run.decisions_sample && run.decisions_sample.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50 text-sm font-semibold text-white">
            Agent Decisions — sample ({run.decisions_sample.length})
          </div>
          <div className="overflow-x-auto max-h-80 overflow-y-auto">
            <table className="w-full text-xs font-mono">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="border-b border-slate-700/50 text-slate-400">
                  {["Symbol", "Strategy", "Date", "Close", "Decision", "Confidence", "R:R", "Filter", "Reason"].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {run.decisions_sample.map((d, i) => (
                  <tr key={i} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                    <td className="px-3 py-2 font-semibold text-white">{d.symbol}</td>
                    <td className="px-3 py-2 text-slate-400">{d.strategy}</td>
                    <td className="px-3 py-2 text-slate-400">{d.bar_date?.slice(0, 10)}</td>
                    <td className="px-3 py-2 text-slate-300">{d.bar_close != null ? `₹${d.bar_close.toFixed(0)}` : "—"}</td>
                    <td className="px-3 py-2"><DecisionBadge rec={d.recommendation} /></td>
                    <td className={`px-3 py-2 ${d.final_confidence >= 75 ? "text-emerald-400" : d.final_confidence >= 55 ? "text-amber-400" : "text-red-400"}`}>
                      {d.final_confidence.toFixed(0)}%
                    </td>
                    <td className="px-3 py-2 text-slate-300">{d.rr_ratio != null ? d.rr_ratio.toFixed(1) : "—"}</td>
                    <td className="px-3 py-2">
                      <span className={d.filter_passed ? "text-emerald-400" : "text-red-400"}>{d.filter_passed ? "✓" : "✗"}</span>
                    </td>
                    <td className="px-3 py-2 text-slate-400 max-w-xs truncate">{d.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 2 — Trade Simulation (Module 3)
// Uses run.trades from GET /validation-v2/backtest/:runId
// ─────────────────────────────────────────────────────────────────────────────

type TradeResultFilter = "ALL" | "WIN" | "LOSS" | "BREAKEVEN";

function TradeSimulationTab({ latestRunId }: { latestRunId: string | null }) {
  const runsQ = useQuery<{ runs: RunListItem[] }>({
    queryKey: ["v2-runs"],
    queryFn:  () => apiJson("validation-v2/backtest"),
    staleTime: 30_000,
  });
  const runs = runsQ.data?.runs ?? [];
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [tradeFilter, setTradeFilter] = useState<TradeResultFilter>("ALL");
  const activeRunId = selectedRunId || latestRunId || runs[0]?.run_id || "";

  // Fetch full run detail for trades
  const runQ = useQuery<RunDetail>({
    queryKey: ["v2-run", activeRunId],
    queryFn:  () => apiJson(`validation-v2/backtest/${activeRunId}`),
    enabled:  !!activeRunId,
    staleTime: 60_000,
  });
  const run = runQ.data;
  const trades = run?.trades ?? [];

  // ── Equity curve — expanded timeline ──────────────────────────────────────
  // Each trade contributes TWO events: ENTRY (equity unchanged) + EXIT
  // (equity updated by PnL). Distinct X positions let us render different
  // marker shapes for each event type:
  //   ENTRY → hollow upward triangle ▲  (colored by result)
  //   EXIT  → filled circle            ●  (colored by result)
  // A START anchor at x=0 initialises the line at ₹10,000.
  type EqEvent = {
    pos: number;           // sequential X position in the chart
    equity: number;        // portfolio value at this event
    event: "START" | "ENTRY" | "EXIT";
    tradeNum: number;
    result: string | null;
    symbol: string;
    entry_price: number | null;
    exit_price: number | null;
    pnl_pct: number | null;
    exit_reason: string | null;
    entry_date: string;
    exit_date: string | null;
  };

  let equity = 10000;
  const eqCurve: EqEvent[] = [
    {
      pos: 0, equity: 10000, event: "START", tradeNum: 0,
      result: null, symbol: "", entry_price: null, exit_price: null,
      pnl_pct: null, exit_reason: null, entry_date: "", exit_date: null,
    },
  ];
  trades.forEach((t, i) => {
    const entryEquity = Math.round(equity);   // portfolio at entry (unchanged)
    equity += equity * (t.pnl_pct ?? 0) / 100;
    const exitEquity = Math.round(equity);    // portfolio at exit (after PnL)
    const meta = {
      tradeNum: i + 1,
      result: t.result ?? null,
      symbol: t.symbol,
      entry_price: t.entry_price,
      exit_price: t.exit_price,
      pnl_pct: t.pnl_pct,
      exit_reason: t.exit_reason,
      entry_date: t.entry_date ?? "",
      exit_date: t.exit_date ?? null,
    };
    eqCurve.push({ pos: (i + 1) * 2 - 1, equity: entryEquity, event: "ENTRY", ...meta });
    eqCurve.push({ pos: (i + 1) * 2,     equity: exitEquity,  event: "EXIT",  ...meta });
  });

  /** Color for a result value */
  const resultCol = (r: string | null) =>
    r === "WIN" ? "#10b981" : r === "LOSS" ? "#ef4444" : "#f59e0b";

  /**
   * Custom dot renderer:
   *   START → nothing
   *   ENTRY → hollow upward-pointing triangle ▲
   *   EXIT  → filled circle ●  (colored by result)
   */
  const TradeDot = (props: any) => {
    const { cx, cy, payload } = props;
    if (!payload || payload.event === "START") return null;
    const col = resultCol(payload.result);
    if (payload.event === "ENTRY") {
      // Hollow upward triangle — visually distinct from the exit circle
      const s = 8; // half-width / height scaling
      return (
        <polygon
          key={`entry-${payload.tradeNum}`}
          points={`${cx},${cy - s} ${cx - s},${cy + s} ${cx + s},${cy + s}`}
          fill="none"
          stroke={col}
          strokeWidth={2}
        />
      );
    }
    // EXIT — filled circle
    return (
      <circle
        key={`exit-${payload.tradeNum}`}
        cx={cx} cy={cy} r={5}
        fill={col} stroke="#0f172a" strokeWidth={1.5}
      />
    );
  };

  /**
   * Tooltip content differs by event type:
   *   ENTRY → entry date + entry price + portfolio at entry
   *   EXIT  → exit date + exit price + exit reason + P&L + portfolio after
   */
  const TradeTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const d: EqEvent = payload[0].payload;
    if (d.event === "START") return null;
    const col = resultCol(d.result);
    const isEntry = d.event === "ENTRY";
    return (
      <div style={{
        background: "#0f172a", border: "1px solid #334155",
        borderRadius: 8, padding: "8px 12px", fontSize: 11, lineHeight: 1.8,
      }}>
        <div style={{ fontWeight: 700, color: col, marginBottom: 2 }}>
          {isEntry ? "▲ Entry" : "● Exit"} — T{d.tradeNum} {d.symbol}
          {d.result ? <span style={{ marginLeft: 6, opacity: 0.8 }}>({d.result})</span> : null}
        </div>
        {isEntry ? (
          <>
            <div style={{ color: "#94a3b8" }}>Date: <span style={{ color: "#e2e8f0" }}>{d.entry_date?.slice(0, 10) || "—"}</span></div>
            {d.entry_price != null && (
              <div>Entry price: <span style={{ color: "#e2e8f0" }}>₹{d.entry_price.toFixed(2)}</span></div>
            )}
            <div style={{ color: "#94a3b8" }}>Portfolio at entry: <span style={{ color: "#e2e8f0" }}>₹{d.equity.toLocaleString()}</span></div>
          </>
        ) : (
          <>
            {d.exit_date && (
              <div style={{ color: "#94a3b8" }}>Exit date: <span style={{ color: "#e2e8f0" }}>{d.exit_date.slice(0, 10)}</span></div>
            )}
            {d.exit_price != null && (
              <div>Exit price: <span style={{ color: "#e2e8f0" }}>₹{d.exit_price.toFixed(2)}</span></div>
            )}
            {d.exit_reason && (
              <div>Exit reason: <span style={{ color: "#94a3b8" }}>{d.exit_reason}</span></div>
            )}
            {d.pnl_pct != null && (
              <div style={{ fontWeight: 700, color: col }}>
                P&amp;L: {d.pnl_pct >= 0 ? "+" : ""}{d.pnl_pct.toFixed(2)}%
              </div>
            )}
            <div style={{ color: "#94a3b8" }}>Portfolio after: <span style={{ color: "#e2e8f0" }}>₹{d.equity.toLocaleString()}</span></div>
          </>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <label className="text-xs text-slate-400 uppercase tracking-widest">Run</label>
        <select value={selectedRunId} onChange={e => setSelectedRunId(e.target.value)}
          className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-teal-500">
          <option value="">{latestRunId ? "Latest run" : "Select a run…"}</option>
          {runs.map(r => (
            <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 10)} ({r.total_trades} trades)</option>
          ))}
        </select>
        {runQ.isFetching && <RefreshCw size={13} className="text-slate-400 animate-spin" />}
      </div>

      {!activeRunId && <EmptyState icon={Activity} title="No run selected" sub="Run a backtest first or select a previous run" />}
      {activeRunId && runQ.isLoading && (
        <div className="flex items-center gap-2 text-slate-400 text-sm"><RefreshCw size={14} className="animate-spin" /> Loading trades…</div>
      )}
      {run && trades.length === 0 && !runQ.isLoading && (
        <EmptyState icon={Target} title="No trades in this run" sub="The run produced no BUY entries with the current thresholds" />
      )}

      {run && trades.length > 0 && (
        <>
          {/* Run stats bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Total Trades" value={String(trades.length)} />
            <StatCard label="Win Rate"
              value={run.stats?.win_rate_pct != null ? `${run.stats.win_rate_pct.toFixed(1)}%` : "—"}
              accent={run.stats?.win_rate_pct != null ? (run.stats.win_rate_pct >= 55 ? "green" : run.stats.win_rate_pct >= 45 ? "amber" : "red") : "neutral"} />
            <StatCard label="Avg P&L" value={fmtPct(run.stats?.avg_pnl_pct)}
              accent={run.stats?.avg_pnl_pct != null ? (run.stats.avg_pnl_pct >= 0 ? "green" : "red") : "neutral"} />
            <StatCard label="Profit Factor" value={run.stats?.profit_factor != null ? run.stats.profit_factor.toFixed(2) : "—"}
              accent={run.stats?.profit_factor != null ? (run.stats.profit_factor >= 1.5 ? "green" : run.stats.profit_factor >= 1 ? "amber" : "red") : "neutral"} />
          </div>

          {/* Equity curve with trade entry/exit markers */}
          {trades.length > 0 && (
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <TrendingUp size={14} className="text-teal-400" /> Equity Curve (₹10,000 start)
                </h3>
                {/* Legend — entry shape + exit shape + result colors */}
                <div className="flex items-center gap-4 text-xs text-slate-400">
                  <span className="flex items-center gap-1.5">
                    <svg width="14" height="12" viewBox="0 0 14 12">
                      <polygon points="7,0 0,12 14,12" fill="none" stroke="#94a3b8" strokeWidth="1.8" />
                    </svg>
                    Entry
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2.5 h-2.5 rounded-full bg-slate-400" />
                    Exit
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500" />
                    WIN
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500" />
                    LOSS
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500" />
                    BE
                  </span>
                </div>
              </div>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={eqCurve} margin={{ top: 10, right: 10, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis
                      dataKey="pos"
                      type="number"
                      domain={[0, trades.length * 2]}
                      tickCount={trades.length + 1}
                      tickFormatter={(pos: number) => {
                        if (pos === 0) return "Start";
                        // Show label only at exit positions (even numbers)
                        if (pos % 2 === 0) return `T${pos / 2}`;
                        return "";
                      }}
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                      domain={["auto", "auto"]}
                      tickFormatter={(v: number) => `₹${(v / 1000).toFixed(1)}k`}
                    />
                    <Tooltip content={<TradeTooltip />} />
                    <Line
                      type="linear"
                      dataKey="equity"
                      stroke="#14b8a6"
                      strokeWidth={2}
                      dot={<TradeDot />}
                      activeDot={{ r: 7, strokeWidth: 2, stroke: "#0f172a" }}
                      isAnimationActive={false}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                ▲ Hover an entry marker to see entry price &amp; portfolio value.
                ● Hover an exit marker to see P&amp;L, exit reason, and portfolio after.
              </p>
            </div>
          )}

          {/* Trade cards — filterable by result */}
          {(() => {
            // Count per bucket (null / unknown → treated as BREAKEVEN for counting)
            const counts: Record<TradeResultFilter, number> = {
              ALL: trades.length,
              WIN: trades.filter(t => t.result === "WIN").length,
              LOSS: trades.filter(t => t.result === "LOSS").length,
              BREAKEVEN: trades.filter(t => t.result !== "WIN" && t.result !== "LOSS").length,
            };
            const visibleTrades = tradeFilter === "ALL"
              ? trades
              : tradeFilter === "BREAKEVEN"
                ? trades.filter(t => t.result !== "WIN" && t.result !== "LOSS")
                : trades.filter(t => t.result === tradeFilter);

            const filterBtns: { key: TradeResultFilter; label: string; active: string; inactive: string }[] = [
              {
                key: "ALL",
                label: "All",
                active: "bg-slate-600 border-slate-500 text-white",
                inactive: "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-slate-600 hover:text-slate-300",
              },
              {
                key: "WIN",
                label: "WIN",
                active: "bg-emerald-500/20 border-emerald-500/60 text-emerald-300",
                inactive: "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-emerald-700/50 hover:text-emerald-400",
              },
              {
                key: "LOSS",
                label: "LOSS",
                active: "bg-red-500/20 border-red-500/60 text-red-300",
                inactive: "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-red-700/50 hover:text-red-400",
              },
              {
                key: "BREAKEVEN",
                label: "BREAKEVEN",
                active: "bg-amber-500/20 border-amber-500/60 text-amber-300",
                inactive: "bg-slate-800/60 border-slate-700/50 text-slate-400 hover:border-amber-700/50 hover:text-amber-400",
              },
            ];

            return (
              <div className="space-y-3">
                {/* Filter toggles */}
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <h3 className="text-sm font-semibold text-white">
                    {visibleTrades.length === trades.length
                      ? `${trades.length} Trades`
                      : `${visibleTrades.length} of ${trades.length} Trades`}
                  </h3>
                  <div className="flex items-center gap-1.5" role="group" aria-label="Filter trades by result">
                    {filterBtns.map(({ key, label, active, inactive }) => (
                      <button
                        key={key}
                        onClick={() => setTradeFilter(key)}
                        aria-pressed={tradeFilter === key}
                        className={`px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all flex items-center gap-1.5 ${
                          tradeFilter === key ? active : inactive
                        }`}
                      >
                        {label}
                        <span className={`text-[10px] font-mono rounded px-1 py-0.5 ${
                          tradeFilter === key
                            ? "bg-white/10"
                            : "bg-slate-700/60 text-slate-500"
                        }`}>
                          {counts[key]}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Trade list */}
                {visibleTrades.length === 0 ? (
                  <div className="py-8 text-center text-slate-500 text-sm">
                    No {tradeFilter.toLowerCase()} trades in this run.
                  </div>
                ) : (
                  visibleTrades.map((t, i) => <TradeCard key={`${t.symbol}-${t.entry_date}-${i}`} trade={t} />)
                )}
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}

function TradeCard({ trade: t }: { trade: TradeRow }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={`bg-slate-800/60 border rounded-xl overflow-hidden ${
      t.result === "WIN" ? "border-emerald-700/40" : t.result === "LOSS" ? "border-red-700/40" : "border-slate-700/50"
    }`}>
      <button className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-700/30 transition-colors"
        onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-3">
          <span className="font-bold text-white">{t.symbol}</span>
          <span className="text-xs text-slate-400">{t.strategy}</span>
          <ResultBadge result={t.result ?? null} />
        </div>
        <div className="flex items-center gap-4 text-xs">
          <span className="text-slate-400">{t.entry_date?.slice(0, 10)}</span>
          {t.pnl_pct != null && (
            <span className={`font-mono font-bold ${t.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
            </span>
          )}
          {expanded ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-4 border-t border-slate-700/50 pt-3 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Entry" value={`₹${t.entry_price.toFixed(2)}`} sub={`Stop: ₹${t.stop_loss?.toFixed(2) ?? "—"}`} />
            <StatCard label="Target" value={`₹${t.target_price?.toFixed(2) ?? "—"}`} />
            <StatCard label="Exit" value={t.exit_price != null ? `₹${t.exit_price.toFixed(2)}` : "—"} sub={`Reason: ${t.exit_reason ?? "open"}`} />
            <StatCard label="Holding Days" value={t.holding_days != null ? String(t.holding_days) : "—"} />
          </div>
          {(t.mfe_pct != null || t.mad_pct != null) && (
            <div className="space-y-2">
              {t.mfe_pct != null && (
                <div>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>MFE (Max Favourable Excursion)</span>
                    <span className="text-emerald-400">+{t.mfe_pct.toFixed(2)}%</span>
                  </div>
                  <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.min(100, t.mfe_pct * 10)}%` }} />
                  </div>
                </div>
              )}
              {t.mad_pct != null && (
                <div>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>MAD (Max Adverse Drawdown)</span>
                    <span className="text-red-400">{t.mad_pct.toFixed(2)}%</span>
                  </div>
                  <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
                    <div className="h-full bg-red-500 rounded-full" style={{ width: `${Math.min(100, Math.abs(t.mad_pct) * 10)}%` }} />
                  </div>
                </div>
              )}
            </div>
          )}
          {t.confidence != null && (
            <div className="text-xs text-slate-400 bg-slate-700/30 rounded-lg px-3 py-2">
              <span className="text-slate-300 font-medium">AI Confidence:</span> {t.confidence.toFixed(0)}%
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 3 — Missed Opportunities (Module 4)
// GET /validation-v2/missed-opportunities → { missed: MissedRow[], count, ... }
// ─────────────────────────────────────────────────────────────────────────────

function MissedOpportunitiesTab() {
  const q = useQuery<{ missed: MissedRow[]; count: number; total_potential_profit_pct: number }>({
    queryKey: ["v2-missed"],
    queryFn:  () => apiJson("validation-v2/missed-opportunities"),
    staleTime: 60_000,
  });

  const opps = [...(q.data?.missed ?? [])].sort((a, b) => (b.potential_profit_pct ?? 0) - (a.potential_profit_pct ?? 0));

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Missed Opportunities</h3>
          <p className="text-xs text-slate-400 mt-0.5">Rejected stocks that moved ≥+2% afterward — sorted by potential profit</p>
        </div>
        {q.isLoading && <RefreshCw size={14} className="text-slate-400 animate-spin" />}
      </div>

      {q.isError && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertTriangle size={14} /> Failed to load missed opportunities
        </div>
      )}

      {opps.length === 0 && !q.isLoading && (
        <EmptyState icon={TrendingUp} title="No missed opportunities found" sub="Run backtests first to collect opportunity data" />
      )}

      {opps.length > 0 && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <StatCard label="Total Missed" value={String(opps.length)} />
            <StatCard label="Avg Potential"
              value={`+${(opps.reduce((s, o) => s + o.potential_profit_pct, 0) / opps.length).toFixed(1)}%`}
              accent="amber" />
            <StatCard label="Max Missed"
              value={`+${opps[0]?.potential_profit_pct?.toFixed(1) ?? "—"}%`}
              sub={opps[0]?.symbol} accent="amber" />
          </div>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-700/50 text-slate-400 bg-slate-900/50">
                    {["Symbol", "Strategy", "Date", "AI Decision", "Actual Move", "Potential Profit", "Rejection Reason", "Suggestion"].map(h => (
                      <th key={h} className="px-3 py-2 text-left font-normal uppercase tracking-widest text-[10px]">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {opps.map((o, i) => (
                    <tr key={i} className={`border-b border-slate-700/30 hover:bg-slate-700/20 ${o.potential_profit_pct >= 3 ? "bg-amber-900/10" : ""}`}>
                      <td className="px-3 py-2.5 font-bold text-white">{o.symbol}</td>
                      <td className="px-3 py-2.5 text-slate-400">{o.strategy}</td>
                      <td className="px-3 py-2.5 text-slate-400">{o.bar_date?.slice(0, 10)}</td>
                      <td className="px-3 py-2.5"><DecisionBadge rec={o.ai_decision} /></td>
                      <td className={`px-3 py-2.5 font-bold ${o.actual_move_pct >= 3 ? "text-amber-300" : "text-emerald-400"}`}>
                        +{o.actual_move_pct?.toFixed(2)}%
                      </td>
                      <td className={`px-3 py-2.5 font-bold ${o.potential_profit_pct >= 3 ? "text-amber-300" : "text-emerald-400"}`}>
                        +{o.potential_profit_pct?.toFixed(2)}%
                      </td>
                      <td className="px-3 py-2.5 text-slate-300 max-w-[200px] truncate">{o.rejection_reason}</td>
                      <td className="px-3 py-2.5">
                        <span className="inline-block px-2 py-0.5 text-xs bg-blue-900/30 border border-blue-700/40 text-blue-300 rounded-full max-w-[200px] truncate">
                          {o.improvement_suggestion}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 4 — AI vs Market (Module 5)
// Shows recommendation distribution + trade outcome breakdown from a run detail
// ─────────────────────────────────────────────────────────────────────────────

function AIvsMarketTab({ latestRunId }: { latestRunId: string | null }) {
  const runsQ = useQuery<{ runs: RunListItem[] }>({
    queryKey: ["v2-runs"],
    queryFn:  () => apiJson("validation-v2/backtest"),
    staleTime: 30_000,
  });
  const runs = runsQ.data?.runs ?? [];
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const activeRunId = selectedRunId || latestRunId || runs[0]?.run_id || "";

  const runQ = useQuery<RunDetail>({
    queryKey: ["v2-run", activeRunId],
    queryFn:  () => apiJson(`validation-v2/backtest/${activeRunId}`),
    enabled:  !!activeRunId,
    staleTime: 60_000,
  });
  const run = runQ.data;

  const dist = run?.recommendation_distribution ?? {};
  const totalDec = run?.total_decisions ?? 0;
  const s = run?.stats;
  const trades = run?.trades ?? [];
  const wins = trades.filter(t => t.result === "WIN").length;
  const losses = trades.filter(t => t.result === "LOSS").length;
  const breakevens = trades.filter(t => t.result === "BREAKEVEN").length;

  // Build bar chart data from recommendation distribution
  const distData = Object.entries(dist).map(([rec, count]) => ({ rec, count }))
    .sort((a, b) => b.count - a.count);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-xs text-slate-400 uppercase tracking-widest">Run</label>
        <select value={selectedRunId} onChange={e => setSelectedRunId(e.target.value)}
          className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
          <option value="">{latestRunId ? "Latest run" : "Select a run…"}</option>
          {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 10)} ({r.total_decisions} decisions)</option>)}
        </select>
        {runQ.isFetching && <RefreshCw size={13} className="text-slate-400 animate-spin" />}
      </div>

      {!activeRunId && <EmptyState icon={Target} title="No run selected" sub="Run a backtest first to see AI vs market analysis" />}
      {activeRunId && runQ.isLoading && <div className="flex items-center gap-2 text-slate-400 text-sm"><RefreshCw size={14} className="animate-spin" /> Loading run…</div>}

      {run && (
        <>
          {/* Decision outcome summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Total Decisions" value={String(totalDec)} />
            <StatCard label="Trades Taken" value={String(trades.length)} sub={`${totalDec > 0 ? ((trades.length / totalDec) * 100).toFixed(0) : "—"}% acted on`} accent="teal" />
            <StatCard label="Win Rate"
              value={s?.win_rate_pct != null ? `${s.win_rate_pct.toFixed(1)}%` : "—"}
              accent={s?.win_rate_pct != null ? (s.win_rate_pct >= 55 ? "green" : s.win_rate_pct >= 45 ? "amber" : "red") : "neutral"} />
            <StatCard label="Expectancy" value={fmtPct(s?.expectancy_pct)}
              accent={s?.expectancy_pct != null ? (s.expectancy_pct > 0 ? "green" : "red") : "neutral"} />
          </div>

          {/* Trade outcome breakdown */}
          {trades.length > 0 && (
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-emerald-900/10 border border-emerald-700/30 rounded-xl p-4">
                <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">WIN</div>
                <div className="text-2xl font-bold text-emerald-400">{wins}</div>
                <div className="text-xs text-slate-500 mt-0.5">{trades.length > 0 ? `${(wins / trades.length * 100).toFixed(1)}%` : "—"} of trades</div>
              </div>
              <div className="bg-red-900/10 border border-red-700/30 rounded-xl p-4">
                <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">LOSS</div>
                <div className="text-2xl font-bold text-red-400">{losses}</div>
                <div className="text-xs text-slate-500 mt-0.5">{trades.length > 0 ? `${(losses / trades.length * 100).toFixed(1)}%` : "—"} of trades</div>
              </div>
              <div className="bg-amber-900/10 border border-amber-700/30 rounded-xl p-4">
                <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">BREAKEVEN</div>
                <div className="text-2xl font-bold text-amber-400">{breakevens}</div>
                <div className="text-xs text-slate-500 mt-0.5">{trades.length > 0 ? `${(breakevens / trades.length * 100).toFixed(1)}%` : "—"} of trades</div>
              </div>
            </div>
          )}

          {/* Recommendation distribution */}
          {distData.length > 0 && (
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-sm font-semibold text-white mb-3">Recommendation Distribution</h3>
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={distData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <YAxis dataKey="rec" type="category" width={80} tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 11 }}
                      formatter={(v: any) => [v, "count"]} />
                    <Bar dataKey="count" fill="#14b8a6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Most common rejection: <span className="text-slate-300">{run.most_common_rejection}</span>
              </p>
            </div>
          )}

          {/* Key accuracy stats */}
          {s && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatCard label="Profit Factor" value={s.profit_factor != null ? s.profit_factor.toFixed(2) : "—"}
                accent={s.profit_factor != null ? (s.profit_factor >= 1.5 ? "green" : s.profit_factor >= 1 ? "amber" : "red") : "neutral"} />
              <StatCard label="Sharpe Ratio" value={s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : "—"}
                accent={s.sharpe_ratio != null ? (s.sharpe_ratio >= 1 ? "green" : s.sharpe_ratio >= 0 ? "amber" : "red") : "neutral"} />
              <StatCard label="Max Drawdown" value={fmtPct(s.max_drawdown_pct, false)} accent="red" />
              <StatCard label="Avg Confidence" value={s.avg_confidence != null ? `${s.avg_confidence.toFixed(0)}%` : "—"} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 5 — Parameter Optimizer (Module 6)
// POST /validation-v2/optimizer/run → { results, best_config, recommendation }
// GET  /validation-v2/optimizer/recommendation → { best_config, recommendation, top_results }
// ─────────────────────────────────────────────────────────────────────────────

interface OptimizerResult {
  config: { confidence_threshold: number; stop_pct: number; target_pct: number; position_size_pct: number; min_rr: number; trailing_stop_pct: number; max_holding_days: number };
  total_trades: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  expectancy_pct: number | null;
  max_drawdown_pct: number | null;
  avg_pnl_pct: number | null;
}

function ParameterOptimizerTab() {
  const [symbols] = useState(["RELIANCE", "TCS", "INFY"]);
  const [grid, setGrid] = useState<Record<string, number[]>>({
    confidence_threshold: [55, 65, 75],
    stop_pct: [1.5, 2.0, 2.5],
    target_pct: [3.0, 4.0, 5.0],
    position_size_pct: [10, 15],
    min_rr: [1.5, 2.0],
  });
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<OptimizerResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  // GET /validation-v2/optimizer/recommendation
  const recQ = useQuery<{ best_config?: OptimizerResult; recommendation?: string; top_results?: OptimizerResult[] }>({
    queryKey: ["v2-opt-rec"],
    queryFn:  () => apiJson("validation-v2/optimizer/recommendation"),
    staleTime: 60_000,
  });
  const rec = recQ.data;

  const handleRun = async () => {
    setRunning(true); setError(null);
    try {
      const res = await apiJson<{ results: OptimizerResult[]; best_config?: OptimizerResult }>(
        "validation-v2/optimizer/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbols,
            // optimizer always tests all strategies — strategy_name is not consumed
            start_date: daysAgo(180), end_date: today(), grid,
          }),
        }, 300_000);
      setResults(res.results ?? []);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setRunning(false);
    }
  };

  const sorted = [...results].sort((a, b) => (b.sharpe_ratio ?? -999) - (a.sharpe_ratio ?? -999));

  const updateGrid = (key: string, val: string) => {
    const nums = val.split(",").map(v => parseFloat(v.trim())).filter(n => !isNaN(n));
    if (nums.length > 0) setGrid(g => ({ ...g, [key]: nums }));
  };

  return (
    <div className="space-y-5">
      <AdvisoryBanner text="Advisory only — optimized parameters are suggestions for human review. Do not apply automatically." />

      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Zap size={14} className="text-amber-400" /> Grid Search Configuration
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {Object.entries(grid).map(([key, vals]) => (
            <div key={key} className="flex flex-col gap-1">
              <label className="text-xs text-slate-400 uppercase tracking-widest">{key.replace(/_/g, " ")}</label>
              <input defaultValue={vals.join(", ")} onChange={e => updateGrid(key, e.target.value)}
                className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-1 focus:ring-amber-500"
                placeholder="comma-separated values" />
              <span className="text-xs text-slate-600">{vals.length} value{vals.length > 1 ? "s" : ""}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <button onClick={handleRun} disabled={running}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-white text-sm font-semibold disabled:opacity-40 transition-colors">
            {running ? <RefreshCw size={14} className="animate-spin" /> : <Zap size={14} />}
            {running ? "Simulating…" : "Simulate (all strategies)"}
          </button>
          {error && <span className="text-xs text-red-400">{error}</span>}
        </div>
        <p className="text-xs text-slate-500">Optimizer tests all available strategies. Results show aggregate across strategies.</p>
      </div>

      {/* Best recommendation from stored run */}
      {rec?.best_config && (
        <div className="bg-teal-900/20 border border-teal-700/40 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-teal-300 mb-2">✓ Best Configuration (Advisory)</h3>
          {rec.recommendation && <p className="text-xs text-slate-400 mb-2">{rec.recommendation}</p>}
          <div className="flex flex-wrap gap-2">
            {Object.entries((rec.best_config as any).config ?? rec.best_config).map(([k, v]) => (
              <span key={k} className="px-2 py-1 text-xs bg-teal-900/40 border border-teal-700/40 text-teal-200 rounded-lg font-mono">
                {k}: {String(v)}
              </span>
            ))}
          </div>
          <div className="mt-2 grid grid-cols-4 gap-2 text-xs">
            <span className="text-slate-400">Sharpe: <span className="text-emerald-400 font-mono">{fmt((rec.best_config as any).sharpe_ratio, 2)}</span></span>
            <span className="text-slate-400">Win%: <span className="text-emerald-400 font-mono">{fmt((rec.best_config as any).win_rate_pct, 1)}%</span></span>
            <span className="text-slate-400">PF: <span className="text-emerald-400 font-mono">{fmt((rec.best_config as any).profit_factor, 2)}</span></span>
            <span className="text-slate-400">Exp: <span className="text-emerald-400 font-mono">{fmtPct((rec.best_config as any).expectancy_pct)}</span></span>
          </div>
        </div>
      )}

      {/* Results table */}
      {sorted.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50 text-sm font-semibold text-white">
            {sorted.length} Configurations — Ranked by Sharpe Ratio
          </div>
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-xs font-mono">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="border-b border-slate-700/50 text-slate-400">
                  {["Rank", "Conf%", "Stop%", "Target%", "Min RR", "Win%", "Sharpe", "PF", "Exp", "Drawdown", "Trades"].map(h => (
                    <th key={h} className="px-3 py-2 text-left font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r, i) => (
                  <tr key={i} className={`border-b border-slate-700/30 hover:bg-slate-700/20 ${i === 0 ? "bg-teal-900/15" : ""}`}>
                    <td className="px-3 py-2">
                      {i === 0 ? <span className="text-teal-400 font-bold">★ 1</span> : <span className="text-slate-500">{i + 1}</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-300">{r.config.confidence_threshold}</td>
                    <td className="px-3 py-2 text-slate-300">{r.config.stop_pct}</td>
                    <td className="px-3 py-2 text-slate-300">{r.config.target_pct}</td>
                    <td className="px-3 py-2 text-slate-300">{r.config.min_rr}</td>
                    <td className={`px-3 py-2 ${(r.win_rate_pct ?? 0) >= 55 ? "text-emerald-400" : (r.win_rate_pct ?? 0) >= 45 ? "text-amber-400" : "text-red-400"}`}>
                      {r.win_rate_pct != null ? `${r.win_rate_pct.toFixed(1)}%` : "—"}
                    </td>
                    <td className={`px-3 py-2 font-bold ${(r.sharpe_ratio ?? 0) >= 1 ? "text-emerald-400" : (r.sharpe_ratio ?? 0) >= 0 ? "text-amber-400" : "text-red-400"}`}>
                      {r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : "—"}
                    </td>
                    <td className={`px-3 py-2 ${(r.profit_factor ?? 0) >= 1.5 ? "text-emerald-400" : (r.profit_factor ?? 0) >= 1 ? "text-amber-400" : "text-red-400"}`}>
                      {r.profit_factor != null ? r.profit_factor.toFixed(2) : "—"}
                    </td>
                    <td className={`px-3 py-2 ${(r.expectancy_pct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {fmtPct(r.expectancy_pct)}
                    </td>
                    <td className="px-3 py-2 text-red-400">{fmtPct(r.max_drawdown_pct, false)}</td>
                    <td className="px-3 py-2 text-slate-300">{r.total_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {results.length === 0 && !running && (
        <EmptyState icon={Zap} title="No optimizer results yet" sub="Configure the grid and click Simulate" />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 6 — Agent Explainability (Module 7)
// Uses decisions_sample from GET /validation-v2/backtest/:runId
// ─────────────────────────────────────────────────────────────────────────────

function AgentExplainabilityTab({ latestRunId }: { latestRunId: string | null }) {
  const runsQ = useQuery<{ runs: RunListItem[] }>({
    queryKey: ["v2-runs"],
    queryFn:  () => apiJson("validation-v2/backtest"),
    staleTime: 30_000,
  });
  const runs = runsQ.data?.runs ?? [];
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const activeRunId = selectedRunId || latestRunId || runs[0]?.run_id || "";

  const runQ = useQuery<RunDetail>({
    queryKey: ["v2-run", activeRunId],
    queryFn:  () => apiJson(`validation-v2/backtest/${activeRunId}`),
    enabled:  !!activeRunId,
    staleTime: 60_000,
  });
  const run = runQ.data;

  const symbols = [...new Set((run?.decisions_sample ?? []).map(d => d.symbol))];
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const sym = selectedSymbol || symbols[0] || "";

  // Find the best decision for the selected symbol (prefer BUY/STRONG_BUY)
  const decision = run?.decisions_sample?.find(d => d.symbol === sym && (d.recommendation === "BUY" || d.recommendation === "STRONG_BUY"))
    ?? run?.decisions_sample?.find(d => d.symbol === sym);

  // Build pipeline cards from known decision fields
  const agentRows = decision ? [
    {
      id: "strategy_agent", label: "Strategy Agent",
      score: decision.final_confidence,
      passed: decision.entry_signal,
      threshold: `entry_signal = true`,
      reason: decision.entry_signal ? "Entry signal confirmed" : "No entry signal on this bar",
      color: "#ef4444",
    },
    {
      id: "risk_agent", label: "Risk Agent / Filter",
      score: decision.rr_ratio,
      passed: decision.filter_passed,
      threshold: `R:R ≥ 1.5 · filter_passed`,
      reason: decision.filter_passed
        ? `R:R ${decision.rr_ratio?.toFixed(1) ?? "—"}:1 — filter passed`
        : `Filter failed — ${decision.reason}`,
      color: "#f59e0b",
    },
    {
      id: "ai_decision_agent", label: "AI Decision Agent",
      score: decision.final_confidence,
      passed: decision.recommendation === "BUY" || decision.recommendation === "STRONG_BUY",
      threshold: `confidence ≥ threshold (${decision.threshold?.toFixed(0) ?? "—"})`,
      reason: `${decision.recommendation}: confidence ${decision.final_confidence.toFixed(0)}% — ${decision.reason}`,
      color: "#6366f1",
    },
  ] : [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-slate-400 uppercase tracking-widest">Run</label>
          <select value={selectedRunId} onChange={e => setSelectedRunId(e.target.value)}
            className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
            <option value="">{latestRunId ? "Latest run" : "Select a run…"}</option>
            {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 10)}</option>)}
          </select>
        </div>
        {symbols.length > 0 && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400 uppercase tracking-widest">Symbol</label>
            <select value={sym} onChange={e => setSelectedSymbol(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
              {symbols.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        )}
        {runQ.isFetching && <RefreshCw size={13} className="text-slate-400 animate-spin mt-5" />}
      </div>

      {!activeRunId && <EmptyState icon={Brain} title="No run selected" sub="Run a backtest to populate the explainability view" />}
      {activeRunId && run && symbols.length === 0 && (
        <EmptyState icon={Info} title="No decisions in this run" sub="Run produced no decision records" />
      )}
      {run && sym && !decision && (
        <EmptyState icon={Search} title={`No decision for ${sym}`} sub="Symbol may not appear in this run's decisions sample" />
      )}

      {decision && (
        <div className="space-y-3">
          {/* Symbol header */}
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold text-white">{sym}</h3>
              <p className="text-xs text-slate-400 mt-0.5">{decision.strategy} · {decision.bar_date?.slice(0, 10)}</p>
            </div>
            <div className="flex items-center gap-2">
              <DecisionBadge rec={decision.recommendation} />
              <span className="text-sm font-mono text-white">{decision.final_confidence.toFixed(0)}%</span>
            </div>
          </div>

          {/* Pipeline vertical */}
          <div className="space-y-2">
            {agentRows.map((row, i) => (
              <div key={row.id} className={`flex gap-3 p-4 rounded-xl border ${row.passed ? "bg-emerald-900/10 border-emerald-700/30" : "bg-red-900/10 border-red-700/30"}`}>
                <div className="flex-shrink-0 flex flex-col items-center">
                  <div className="w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold"
                    style={{ borderColor: row.color, color: row.color }}>
                    {i + 1}
                  </div>
                  {i < agentRows.length - 1 && <div className="w-0.5 flex-1 bg-slate-700 mt-1" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="text-sm font-semibold text-white">{row.label}</span>
                    <span className={`inline-block px-2 py-0.5 text-xs font-bold rounded border ${row.passed ? "bg-emerald-500/15 border-emerald-600/50 text-emerald-300" : "bg-red-500/15 border-red-600/50 text-red-300"}`}>
                      {row.passed ? "PASS" : "FAIL"}
                    </span>
                    {row.score != null && <span className="text-xs text-slate-400 font-mono">Score: {Number(row.score).toFixed(2)}</span>}
                    <span className="text-xs text-slate-500 font-mono ml-auto">Threshold: {row.threshold}</span>
                  </div>
                  <p className="text-xs text-slate-400">{row.reason}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Raw decision context */}
          <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div><span className="text-slate-500">Close:</span> <span className="text-white font-mono">{decision.bar_close != null ? `₹${decision.bar_close.toFixed(2)}` : "—"}</span></div>
            <div><span className="text-slate-500">R:R:</span> <span className="text-white font-mono">{decision.rr_ratio?.toFixed(1) ?? "—"}:1</span></div>
            <div><span className="text-slate-500">Filter:</span> <span className={decision.filter_passed ? "text-emerald-400" : "text-red-400"}>{decision.filter_passed ? "Passed" : "Failed"}</span></div>
            <div><span className="text-slate-500">Entry Signal:</span> <span className={decision.entry_signal ? "text-emerald-400" : "text-red-400"}>{decision.entry_signal ? "Yes" : "No"}</span></div>
            <div className="col-span-4"><span className="text-slate-500">Reason:</span> <span className="text-slate-300">{decision.reason}</span></div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 7 — Session Playback (Module 8)
// GET /validation-v2/session-timeline/:runId → { events, total_events, dates }
// Events use: time (not ts), type (not kind)
// ─────────────────────────────────────────────────────────────────────────────

function SessionPlaybackTab({ latestRunId }: { latestRunId: string | null }) {
  const runsQ = useQuery<{ runs: RunListItem[] }>({
    queryKey: ["v2-runs"],
    queryFn:  () => apiJson("validation-v2/backtest"),
    staleTime: 30_000,
  });
  const runs = runsQ.data?.runs ?? [];
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const runId = selectedRunId || latestRunId || runs[0]?.run_id || "";

  const timelineQ = useQuery<{ events: TimelineEvent[]; total_events: number; run_id: string }>({
    queryKey: ["v2-timeline", runId],
    queryFn:  () => apiJson(`validation-v2/session-timeline/${encodeURIComponent(runId)}`),
    enabled:  !!runId,
    staleTime: 60_000,
  });

  const events = timelineQ.data?.events ?? [];
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPlayback = useCallback(() => {
    setPlaying(false);
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const startPlayback = useCallback(() => {
    if (cursor >= events.length - 1) { setCursor(0); }
    setPlaying(true);
    let idx = cursor;
    timerRef.current = setInterval(() => {
      idx += speed;
      if (idx >= events.length) { stopPlayback(); setCursor(events.length - 1); return; }
      setCursor(Math.round(idx));
    }, 800 / speed);
  }, [cursor, events.length, speed, stopPlayback]);

  useEffect(() => () => { if (timerRef.current) clearInterval(timerRef.current); }, []);
  useEffect(() => { if (playing && cursor >= events.length - 1) stopPlayback(); }, [cursor, events.length]);

  const visibleEvents = events.slice(0, cursor + 1);

  // Color based on event `type` field (not `kind`)
  const typeColor: Record<string, string> = {
    MARKET_OPEN:    "text-teal-400",
    MARKET_CLOSE:   "text-slate-400",
    SCAN_START:     "text-blue-400",
    SCAN_COMPLETE:  "text-blue-300",
    BUY_ENTRY:      "text-emerald-400",
    EXIT_WIN:       "text-emerald-300",
    EXIT_LOSS:      "text-red-400",
    STOP_HIT:       "text-red-400",
    TARGET_HIT:     "text-emerald-400",
    TIME_EXIT:      "text-amber-400",
    WATCH:          "text-amber-400",
    AVOID:          "text-red-300",
    AGENT_DECISION: "text-purple-400",
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <select value={selectedRunId} onChange={e => { setSelectedRunId(e.target.value); setCursor(0); stopPlayback(); }}
          className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none">
          <option value="">{latestRunId ? "Latest run" : "Select a run…"}</option>
          {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 10)} ({r.total_trades} trades)</option>)}
        </select>
        {timelineQ.isLoading && <RefreshCw size={14} className="text-slate-400 animate-spin" />}
      </div>

      {events.length === 0 && !timelineQ.isLoading && runId && (
        <EmptyState icon={Clock} title="No timeline events" sub="Run a backtest to generate session playback data" />
      )}
      {!runId && <EmptyState icon={Play} title="Select a run to begin playback" sub="Session events will appear here" />}

      {events.length > 0 && (
        <>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-400 w-16 flex-shrink-0 font-mono">{cursor + 1} / {events.length}</span>
              <input type="range" min={0} max={events.length - 1} value={cursor}
                onChange={e => { setCursor(Number(e.target.value)); if (playing) stopPlayback(); }}
                className="flex-1 accent-teal-500" />
              <span className="text-xs text-slate-400 w-32 flex-shrink-0 font-mono text-right">
                {events[cursor]?.time?.slice(0, 10) ?? "—"}
              </span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button onClick={() => { setCursor(0); stopPlayback(); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium">
                <Rewind size={13} /> Rewind
              </button>
              <button onClick={playing ? stopPlayback : startPlayback}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-teal-500 hover:bg-teal-400 text-white text-xs font-semibold">
                {playing ? <Pause size={13} /> : <Play size={13} />}
                {playing ? "Pause" : "Play"}
              </button>
              <button onClick={() => setCursor(Math.min(events.length - 1, cursor + 5))}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium">
                <FastForward size={13} /> +5
              </button>
              <button onClick={() => setCursor(Math.min(events.length - 1, cursor + 20))}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium">
                <SkipForward size={13} /> +20
              </button>
              <div className="flex items-center gap-1.5 ml-auto text-xs text-slate-400">
                Speed:
                {[0.5, 1, 2, 5].map(s => (
                  <button key={s} onClick={() => { setSpeed(s); if (playing) stopPlayback(); }}
                    className={`px-2 py-1 rounded ${speed === s ? "bg-teal-600 text-white" : "bg-slate-700 text-slate-300"}`}>
                    {s}×
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700/50 text-sm font-semibold text-white flex items-center gap-2">
              <Activity size={14} className="text-teal-400" /> Session Events — {visibleEvents.length} shown
            </div>
            <div className="max-h-96 overflow-y-auto divide-y divide-slate-700/30">
              {[...visibleEvents].reverse().map((evt, i) => (
                <div key={i} className={`flex gap-3 px-4 py-2.5 hover:bg-slate-700/20 ${i === 0 && playing ? "bg-teal-900/10" : ""}`}>
                  <span className="text-xs font-mono text-slate-500 flex-shrink-0 w-24">{evt.time?.slice(0, 10)}</span>
                  <span className={`text-xs font-semibold flex-shrink-0 w-28 ${typeColor[evt.type] ?? "text-slate-400"}`}>
                    {evt.type?.replace(/_/g, " ")}
                  </span>
                  {evt.symbol && <span className="text-xs font-bold text-white flex-shrink-0 w-16">{evt.symbol}</span>}
                  <span className="text-xs text-slate-400 flex-1 min-w-0 truncate">{evt.label ?? evt.detail}</span>
                  {evt.pnl_pct != null && (
                    <span className={`text-xs font-mono flex-shrink-0 ${evt.pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {fmtPct(evt.pnl_pct)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 8 — Performance Analytics (Module 9)
// GET /validation-v2/performance → { stats: AggStats, period, best_trade, worst_trade,
//   most_common_rejection, recommendation_distribution, all_time_stats }
// ─────────────────────────────────────────────────────────────────────────────

function PerformanceAnalyticsTab() {
  const [period, setPeriod] = useState<"daily" | "weekly" | "monthly">("monthly");

  const q = useQuery<{
    stats: AggStats;
    period: string;
    best_trade: { symbol: string; pnl_pct: number } | null;
    worst_trade: { symbol: string; pnl_pct: number } | null;
    most_common_rejection: string;
    recommendation_distribution: Record<string, number>;
    all_time_stats: AggStats;
  }>({
    queryKey: ["v2-performance", period],
    queryFn:  () => apiJson(`validation-v2/performance?period=${period}`),
    staleTime: 60_000,
  });

  const d = q.data;
  const s = d?.stats;

  // Build equity chart from trade records if available (approximate from stats)
  // No equity_curve in API — skip chart if no data

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-1 bg-slate-800/60 border border-slate-700/50 rounded-xl p-1 w-fit">
        {(["daily", "weekly", "monthly"] as const).map(p => (
          <button key={p} onClick={() => setPeriod(p)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${period === p ? "bg-teal-500 text-white" : "text-slate-400 hover:text-white"}`}>
            {p.charAt(0).toUpperCase() + p.slice(1)}
          </button>
        ))}
      </div>

      {q.isLoading && <div className="flex items-center gap-2 text-slate-400 text-sm"><RefreshCw size={14} className="animate-spin" /> Loading…</div>}
      {!s && !q.isLoading && <EmptyState icon={Award} title="No performance data" sub="Run backtests to generate performance analytics" />}

      {s && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            <StatCard label="Total Trades" value={String(s.total_trades ?? "—")} />
            <StatCard label="Win Rate" value={s.win_rate_pct != null ? `${s.win_rate_pct.toFixed(1)}%` : "—"}
              accent={s.win_rate_pct != null ? (s.win_rate_pct >= 55 ? "green" : s.win_rate_pct >= 45 ? "amber" : "red") : "neutral"} />
            <StatCard label="Loss Rate" value={s.loss_rate_pct != null ? `${s.loss_rate_pct.toFixed(1)}%` : "—"}
              accent={s.loss_rate_pct != null ? (s.loss_rate_pct <= 45 ? "green" : s.loss_rate_pct <= 55 ? "amber" : "red") : "neutral"} />
            <StatCard label="Avg Holding" value={s.avg_holding_days != null ? `${s.avg_holding_days.toFixed(0)}d` : "—"} />
            <StatCard label="Best Trade"
              value={d?.best_trade != null ? fmtPct(d.best_trade.pnl_pct) : fmtPct(s.best_trade_pct)}
              sub={d?.best_trade?.symbol} accent="green" />
            <StatCard label="Worst Trade"
              value={d?.worst_trade != null ? fmtPct(d.worst_trade.pnl_pct) : fmtPct(s.worst_trade_pct)}
              sub={d?.worst_trade?.symbol} accent="red" />
            <StatCard label="Max Drawdown" value={fmtPct(s.max_drawdown_pct, false)} accent="red" />
            <StatCard label="Expectancy" value={fmtPct(s.expectancy_pct)}
              accent={s.expectancy_pct != null ? (s.expectancy_pct > 0 ? "green" : "red") : "neutral"} />
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Profit Factor" value={s.profit_factor != null ? s.profit_factor.toFixed(2) : "—"}
              accent={s.profit_factor != null ? (s.profit_factor >= 1.5 ? "green" : s.profit_factor >= 1 ? "amber" : "red") : "neutral"} />
            <StatCard label="Sharpe Ratio" value={s.sharpe_ratio != null ? s.sharpe_ratio.toFixed(2) : "—"}
              accent={s.sharpe_ratio != null ? (s.sharpe_ratio >= 1 ? "green" : s.sharpe_ratio >= 0 ? "amber" : "red") : "neutral"} />
            <StatCard label="Avg Confidence" value={s.avg_confidence != null ? `${s.avg_confidence.toFixed(0)}%` : "—"} />
            <StatCard label="Most Common Rejection" value={d?.most_common_rejection ?? "—"} sub="top rejection reason" />
          </div>

          {/* All-time totals if different from period */}
          {d?.all_time_stats && d.all_time_stats.total_trades !== s.total_trades && (
            <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
              <h3 className="text-xs text-slate-400 uppercase tracking-widest mb-3">All-Time Stats (vs {period})</h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <StatCard label="Total Trades" value={String(d.all_time_stats.total_trades)} />
                <StatCard label="Win Rate" value={d.all_time_stats.win_rate_pct != null ? `${d.all_time_stats.win_rate_pct.toFixed(1)}%` : "—"}
                  accent={d.all_time_stats.win_rate_pct != null ? (d.all_time_stats.win_rate_pct >= 55 ? "green" : d.all_time_stats.win_rate_pct >= 45 ? "amber" : "red") : "neutral"} />
                <StatCard label="Sharpe" value={d.all_time_stats.sharpe_ratio != null ? d.all_time_stats.sharpe_ratio.toFixed(2) : "—"}
                  accent={d.all_time_stats.sharpe_ratio != null ? (d.all_time_stats.sharpe_ratio >= 1 ? "green" : d.all_time_stats.sharpe_ratio >= 0 ? "amber" : "red") : "neutral"} />
                <StatCard label="Expectancy" value={fmtPct(d.all_time_stats.expectancy_pct)}
                  accent={d.all_time_stats.expectancy_pct != null ? (d.all_time_stats.expectancy_pct > 0 ? "green" : "red") : "neutral"} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab 9 — Model Comparison (Module 10)
// POST /validation-v2/model-comparison →
//   { current_stats, candidate_stats, deltas, verdict, verdict_reason, ... }
// deltas keys: win_rate_pct, sharpe_ratio, profit_factor, expectancy_pct, max_drawdown_pct, avg_pnl_pct
// verdict: "PROMOTE_CANDIDATE" | "KEEP_CURRENT" | "INCONCLUSIVE"
// ─────────────────────────────────────────────────────────────────────────────

const COMPARISON_METRICS = [
  { key: "win_rate_pct",     label: "Win Rate",      fmt: (v: number | null) => v != null ? `${v.toFixed(1)}%` : "—",  higher_better: true  },
  { key: "avg_pnl_pct",      label: "Avg P&L",       fmt: (v: number | null) => fmtPct(v),                              higher_better: true  },
  { key: "max_drawdown_pct", label: "Max Drawdown",  fmt: (v: number | null) => fmtPct(v, false),                       higher_better: false },
  { key: "profit_factor",    label: "Profit Factor", fmt: (v: number | null) => v != null ? v.toFixed(2) : "—",        higher_better: true  },
  { key: "expectancy_pct",   label: "Expectancy",    fmt: (v: number | null) => fmtPct(v),                              higher_better: true  },
  { key: "sharpe_ratio",     label: "Sharpe Ratio",  fmt: (v: number | null) => v != null ? v.toFixed(2) : "—",        higher_better: true  },
];

interface CompareResult {
  current_stats: AggStats;
  candidate_stats: AggStats;
  deltas: Record<string, number | null>;
  verdict: "PROMOTE_CANDIDATE" | "KEEP_CURRENT" | "INCONCLUSIVE";
  verdict_reason: string;
  current_config: Record<string, number>;
  candidate_config: Record<string, number>;
  symbols_tested: number;
}

const DEFAULT_CURRENT = { confidence_threshold: 65, stop_pct: 2.0, target_pct: 4.0, position_size_pct: 10, min_rr: 1.5 };
const DEFAULT_CANDIDATE = { confidence_threshold: 75, stop_pct: 1.5, target_pct: 5.0, position_size_pct: 15, min_rr: 2.0 };

function ModelComparisonTab() {
  const [currentConfig, setCurrentConfig] = useState(DEFAULT_CURRENT);
  const [candidateConfig, setCandidateConfig] = useState(DEFAULT_CANDIDATE);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCompare = async () => {
    setRunning(true); setError(null);
    try {
      const res = await apiJson<CompareResult>("validation-v2/model-comparison", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_config: currentConfig,
          candidate_config: candidateConfig,
          symbols: ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"],
          start_date: daysAgo(180),
          end_date: today(),
        }),
      }, 180_000);
      setResult(res);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setRunning(false);
    }
  };

  const updateConfig = (which: "current" | "candidate", key: string, val: string) => {
    const n = parseFloat(val);
    if (!isNaN(n)) {
      if (which === "current") setCurrentConfig(c => ({ ...c, [key]: n }));
      else setCandidateConfig(c => ({ ...c, [key]: n }));
    }
  };

  const verdictLabel = result?.verdict === "PROMOTE_CANDIDATE"
    ? "Promote Candidate Configuration"
    : result?.verdict === "KEEP_CURRENT"
    ? "Keep Current Configuration"
    : "Inconclusive — Collect More Data";

  const verdictColor = result?.verdict === "PROMOTE_CANDIDATE"
    ? "bg-blue-900/20 border-blue-700/50 text-blue-300"
    : result?.verdict === "KEEP_CURRENT"
    ? "bg-emerald-900/20 border-emerald-700/50 text-emerald-300"
    : "bg-slate-700/40 border-slate-600/50 text-slate-300";

  return (
    <div className="space-y-5">
      <AdvisoryBanner text="Model comparison is advisory only. Version promotion requires manual operator review and must never be applied automatically." />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {(["current", "candidate"] as const).map(which => {
          const cfg = which === "current" ? currentConfig : candidateConfig;
          return (
            <div key={which} className={`bg-slate-800/60 border rounded-xl p-4 space-y-3 ${which === "candidate" ? "border-blue-700/40" : "border-slate-700/50"}`}>
              <h3 className={`text-sm font-semibold ${which === "candidate" ? "text-blue-300" : "text-white"}`}>
                {which === "current" ? "Current Configuration" : "Candidate Configuration"}
                {which === "candidate" && <span className="ml-2 text-xs font-normal text-blue-400">(editable)</span>}
              </h3>
              <div className="grid grid-cols-2 gap-2">
                {Object.entries(cfg).map(([k, v]) => (
                  <div key={k} className="flex flex-col gap-1">
                    <label className="text-xs text-slate-400">{k.replace(/_/g, " ")}</label>
                    {which === "candidate" ? (
                      <input type="number" defaultValue={v} step={0.5}
                        onChange={e => updateConfig(which, k, e.target.value)}
                        className="bg-slate-900 border border-blue-700/40 rounded-lg px-2 py-1.5 text-sm text-white font-mono focus:outline-none focus:ring-1 focus:ring-blue-500" />
                    ) : (
                      <span className="text-sm font-mono text-white">{v}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-3">
        <button onClick={handleCompare} disabled={running}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-blue-500 hover:bg-blue-400 text-white text-sm font-semibold disabled:opacity-40 transition-colors">
          {running ? <RefreshCw size={14} className="animate-spin" /> : <BarChart3 size={14} />}
          {running ? "Comparing…" : "Run Comparison"}
        </button>
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>

      {result && (
        <div className="space-y-4">
          {/* Verdict */}
          <div className={`flex items-center gap-3 p-4 rounded-xl border font-semibold text-sm ${verdictColor}`}>
            {result.verdict === "PROMOTE_CANDIDATE" ? <ArrowUpRight size={18} /> : result.verdict === "KEEP_CURRENT" ? <CheckCircle2 size={18} /> : <Minus size={18} />}
            <div>
              <div>{verdictLabel}</div>
              <div className="text-xs font-normal text-slate-400 mt-0.5">{result.verdict_reason}</div>
              {result.symbols_tested != null && (
                <div className="text-xs font-normal text-slate-500 mt-0.5">{result.symbols_tested} symbol{result.symbols_tested > 1 ? "s" : ""} tested</div>
              )}
            </div>
            <span className="ml-auto text-xs bg-amber-900/30 border border-amber-700/40 text-amber-300 px-3 py-1 rounded-full flex-shrink-0">
              Advisory only
            </span>
          </div>

          {/* Side-by-side metrics */}
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-700/50 bg-slate-900/50">
                    <th className="px-4 py-2 text-left text-slate-400 font-normal">Metric</th>
                    <th className="px-4 py-2 text-center text-slate-300 font-semibold">Current</th>
                    <th className="px-4 py-2 text-center text-blue-300 font-semibold">Candidate</th>
                    <th className="px-4 py-2 text-center text-slate-400 font-normal">Delta</th>
                    <th className="px-4 py-2 text-center text-slate-400 font-normal">Better</th>
                  </tr>
                </thead>
                <tbody>
                  {COMPARISON_METRICS.map(({ key, label, fmt, higher_better }) => {
                    const cur = (result.current_stats as any)[key] as number | null;
                    const cand = (result.candidate_stats as any)[key] as number | null;
                    const delta = result.deltas?.[key] ?? null;
                    const isImprovement = delta != null && ((higher_better && delta > 0) || (!higher_better && delta < 0));
                    return (
                      <tr key={key} className={`border-b border-slate-700/30 hover:bg-slate-700/20 ${isImprovement ? "bg-blue-900/10" : ""}`}>
                        <td className="px-4 py-2.5 text-slate-300">{label}</td>
                        <td className="px-4 py-2.5 text-center text-white">{fmt(cur)}</td>
                        <td className={`px-4 py-2.5 text-center font-semibold ${isImprovement ? "text-blue-300" : "text-slate-300"}`}>
                          {fmt(cand)}
                        </td>
                        <td className={`px-4 py-2.5 text-center ${isImprovement ? "text-emerald-400" : delta != null && delta !== 0 ? "text-red-400" : "text-slate-500"}`}>
                          {delta != null ? (delta > 0 ? "+" : "") + delta.toFixed(2) : "—"}
                        </td>
                        <td className="px-4 py-2.5 text-center">
                          {isImprovement
                            ? <ArrowUpRight size={12} className="text-emerald-400 inline" />
                            : delta != null && delta !== 0
                            ? <ArrowDownRight size={12} className="text-red-400 inline" />
                            : <Minus size={12} className="text-slate-600 inline" />}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {!result && !running && (
        <EmptyState icon={BarChart3} title="No comparison run yet" sub="Edit the candidate config and click Run Comparison" />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────────────────────────────────────

export default function AIValidationV2Page() {
  const [activeTab, setActiveTab] = useState(0);
  const [latestRunId, setLatestRunId] = useState<string | null>(null);

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <div className="p-2 bg-indigo-500/15 rounded-xl">
              <Brain size={22} className="text-indigo-400" />
            </div>
            AI Validation Centre V2
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Production-parity walk-forward validation · Advisory only · Research use only
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs bg-amber-900/20 border border-amber-700/40 px-3 py-1.5 rounded-full text-amber-300">
          <Shield size={12} /> PAPER TRADING · ADVISORY ONLY
        </div>
      </div>

      <DataFreshnessBar variant="historical" datasetLabel="Validation backtest dataset" />

      <div className="flex gap-1 flex-wrap border-b border-slate-700/50 pb-0">
        {TABS.map((tab, i) => {
          const Icon = tab.icon;
          return (
            <button key={tab.id} onClick={() => setActiveTab(i)}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium rounded-t-lg transition-colors border-b-2 -mb-px ${
                activeTab === i
                  ? "border-teal-500 text-teal-300 bg-teal-500/10"
                  : "border-transparent text-slate-400 hover:text-white hover:bg-slate-800/40"
              }`}>
              <Icon size={13} />
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="min-h-[400px]">
        {activeTab === 0 && <OverviewTab onNavigate={setActiveTab} />}
        {activeTab === 1 && <BacktestRunnerTab onRunComplete={(run) => setLatestRunId(run.run_id)} />}
        {activeTab === 2 && <TradeSimulationTab latestRunId={latestRunId} />}
        {activeTab === 3 && <MissedOpportunitiesTab />}
        {activeTab === 4 && <AIvsMarketTab latestRunId={latestRunId} />}
        {activeTab === 5 && <ParameterOptimizerTab />}
        {activeTab === 6 && <AgentExplainabilityTab latestRunId={latestRunId} />}
        {activeTab === 7 && <SessionPlaybackTab latestRunId={latestRunId} />}
        {activeTab === 8 && <PerformanceAnalyticsTab />}
        {activeTab === 9 && <ModelComparisonTab />}
      </div>
    </div>
  );
}
