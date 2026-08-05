/**
 * AIPaperTraderPage — 🤖 AI Paper Trader
 * Primary operational screen during market hours.
 * 12 sections: Market Status · Portfolio · AI Status · Holdings ·
 * Activity Feed · Recommendation Queue · Closed Trades · AI Performance ·
 * Charts · Date History · Replay · Capital Reset
 *
 * PAPER TRADING ONLY — No live broker orders. Advisory display only.
 */
import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  TrendingUp, TrendingDown, Activity, Brain, RefreshCw,
  ChevronLeft, ChevronRight, PlayCircle, PauseCircle, SkipBack, SkipForward,
  Target, Clock, BookOpen, Search, Zap, Bell, Monitor,
  BarChart2, Wallet, Layers, Trophy, Info,
  CalendarDays, RotateCcw, PieChart,
  Power, CheckCircle2, XCircle, AlertTriangle, Bot, Cpu, Shield, RefreshCcw,
  GitBranch, ArrowDown, ChevronDown,
} from "lucide-react";
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  PieChart as RechartsPie, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Actual shape returned by /live-data/health-v2 */
interface HealthV2 {
  market?: {
    state?: string;       // "OPEN" | "PRE_OPEN" | "CLOSED" | "HOLIDAY" …
    is_open?: boolean;
    now_ist?: string;
    holiday_today?: string | null;
    label?: string;
    session?: {
      pre_open?: string; open?: string; close?: string; post_close?: string;
    };
    next_transition?: { state?: string; at?: string };
  };
  quote_provider?: string;
  scan_id?: string;
  snapshot_ts?: string;
}

/**
 * Shape from /market-intelligence/overview
 * `regime` is a nested object from analyse_regime(); `volatility` is a nested
 * object from volatility_analyser. There is no top-level nifty_price or
 * agent_health — those live inside `regime`.
 */
interface MarketOverview {
  regime?: {
    regime?: string;        // "SIDEWAYS" | "BULL" | "BEAR" | "HIGH_VOL" | …
    sub_regime?: string;
    nifty_price?: number;
    nifty_change_pct?: number;
    nifty_trend?: string;
    banknifty_price?: number;
    banknifty_change_pct?: number;
    banknifty_trend?: string;
    vix_value?: number;
    vix_status?: string;
  };
  volatility?: {
    vix_value?: number;
    vix_status?: string;
  };
  summary?: {
    trend?: string;
    outlook?: string;
    health_score?: number;
  };
  scanned_at?: string;
}
interface Portfolio {
  starting_capital: number; cash: number; invested_amount: number;
  buying_power: number; current_value: number;
  realised_pnl: number; unrealised_pnl: number; total_pnl: number;
  portfolio_return: number; daily_pnl: number; daily_return: number;
  drawdown_pct: number; open_positions: number;
  capital_mode: string; capital_mode_label: string;
  paper_only: boolean; advisory_only: boolean; as_of: string;
}
interface OpenPosition {
  stock: string; buy_time: string; buy_price: number; current_price: number;
  quantity: number; current_value: number; current_pnl: number;
  current_pnl_pct: number; ai_confidence: number;
  expected_return_entry: number; expected_return_current: number;
  target: number; stop_loss: number; strategy: string;
  market_regime: string; risk_level: string; holding_label: string;
}
interface ClosedPosition {
  symbol: string; buy_time: string; sell_time: string;
  entry_price: number; exit_price: number; quantity: number;
  pnl: number; pnl_pct: number; holding_label: string;
  exit_reason: string; ai_confidence: number; strategy: string;
  lesson_learned: string;
}
interface TimelineEvent {
  ts: string; type: string; label: string; detail?: string;
  symbol?: string; price?: number; pnl?: number;
  strategy?: string; category: string;
}
interface Recommendation {
  symbol: string; action: string; confidence: number; risk_level: string;
  expected_return: number; estimated_holding: string;
  entry: number; stop_loss: number; target: number;
  reasoning: string; strategy: string;
}
interface RecsData { items: Recommendation[]; count: number; }
interface AIPerf {
  trades_analysed: number; trades_executed: number; win_rate: number;
  avg_gain: number; avg_loss: number;
  avg_holding_label: string;   // server key is avg_holding_label, not avg_holding_time
  avg_holding_mins: number;
  profit_factor: number; recommendation_accuracy: number;
  best_strategy: string; worst_strategy: string;
}
interface CalendarDay {
  date: string; weekday: number; has_trades: boolean;
  trade_count: number; pnl: number; wins: number; losses: number;
  outcome: "WIN" | "LOSS" | "NEUTRAL" | null;
}
interface DailySummary {
  date: string;
  summary: {
    total_trades: number; opened: number; closed: number; total_pnl: number;
    wins: number; losses: number; win_rate: number; avg_confidence: number;
  };
  closed_trades: { symbol: string; pnl: number; strategy: string; exit_reason: string }[];
  best_trade:  { symbol: string; pnl: number; strategy: string } | null;
  worst_trade: { symbol: string; pnl: number; strategy: string } | null;
  timeline: { ts: string; type: string; label: string; category: string }[];
  learning: Record<string, unknown>;
}
interface TradeSnapshot {
  ts: string; action: string; symbol: string; quantity: number; price: number;
  pnl: number; cash: number; invested: number; portfolio_value: number;
  open_positions: number; cumulative_pnl: number;
}
interface ReplayData {
  date: string;
  events: { ts: string; type: string; label: string; category: string }[];
  trade_snapshots: TradeSnapshot[];
  final_pnl: number; trade_count: number;
  ai_decisions: { symbol: string; decision: string; confidence: number; ts: string }[];
}
interface CapitalConfig {
  current_capital: number; starting_capital: number; capital_mode: string;
  capital_mode_label: string; last_reset_date: string | null;
}
interface TopupEntry {
  date: string; type: string; amount: number; reason: string; balance_after: number;
}
interface SessionStatus {
  today: string;
  initialized_today: boolean;
  last_init_date: string | null;
  last_init_at: string | null;
  session_state: string;
  auto_scan_enabled: boolean;
  auto_paper_entries: boolean;
  auto_paper_exits: boolean;
  capital_mode: string;            // "A" | "B"
  capital_mode_label: string;
  starting_capital: number;
  topup_threshold: number;
  paper_only: boolean;
  advisory_only: boolean;
  no_live_orders: boolean;
}
/** Canonical agent status — served by /ops-centre/agents (same source as AI Operations Centre) */
interface CanonicalAgentStatus {
  agents: Record<string, { status: string; health_pct: number; name: string; enabled: boolean }>;
  agent_count: { total: number; active: number; error: number; disabled: number };
  health_pct: number;
  generated_at: string;
  advisory_only: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number, d = 0) {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: d, maximumFractionDigits: d,
  }).format(n);
}
function fmtK(n: number) {
  if (n == null || isNaN(n)) return "—";
  const abs  = Math.abs(n);
  const sign = n < 0 ? "-" : n > 0 ? "+" : "";
  if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(1)}L`;
  if (abs >= 1_000)    return `${sign}₹${(abs / 1_000).toFixed(1)}k`;
  return `${sign}₹${abs.toFixed(0)}`;
}
function pnlCls(v: number) {
  return v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400";
}
function istTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString("en-IN", {
      hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata",
    });
  } catch { return ts?.slice(11, 16) ?? ""; }
}
function istDateTime(s: string) {
  try {
    return new Date(s).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch { return s ?? "—"; }
}
function istNow() {
  return new Date().toLocaleTimeString("en-IN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false, timeZone: "Asia/Kolkata",
  });
}
function toArr<T>(v: unknown): T[] {
  if (!v) return [];
  if (Array.isArray(v)) return v as T[];
  if (typeof v === "object" && v !== null) {
    const o = v as Record<string, unknown>;
    for (const k of ["positions", "items", "entries", "data"]) {
      if (Array.isArray(o[k])) return o[k] as T[];
    }
  }
  return [];
}

// ── Shared micro-components ───────────────────────────────────────────────────

function SecTitle({
  icon: Icon, title, sub, color = "text-teal-400",
}: { icon: React.ElementType; title: string; sub?: string; color?: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className={`w-4 h-4 ${color} flex-shrink-0`} />
      <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">{title}</h2>
      {sub && <span className="ml-auto text-xs text-slate-500">{sub}</span>}
    </div>
  );
}

function Kpi({
  label, value, sub, hi = false, color = "",
}: { label: string; value: React.ReactNode; sub?: string; hi?: boolean; color?: string }) {
  return (
    <div className={`rounded-xl border p-3 flex flex-col gap-0.5 ${
      hi ? "bg-teal-950/40 border-teal-700/40" : "bg-slate-900/60 border-slate-800/40"
    }`}>
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-base font-bold font-mono leading-tight ${
        color || (hi ? "text-teal-300" : "text-slate-100")
      }`}>{value ?? "—"}</span>
      {sub && <span className="text-xs text-slate-600">{sub}</span>}
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const cls = level === "LOW"  ? "bg-emerald-900/50 text-emerald-300 border-emerald-700/50"
    : level === "HIGH" ? "bg-rose-900/50 text-rose-300 border-rose-700/50"
    : "bg-amber-900/50 text-amber-300 border-amber-700/50";
  return <Badge className={`text-xs px-1.5 py-0 ${cls}`}>{level}</Badge>;
}

function ConfBar({ value }: { value: number }) {
  const c = Math.min(100, Math.max(0, value ?? 0));
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${c >= 75 ? "bg-emerald-500" : c >= 55 ? "bg-amber-500" : "bg-rose-500"}`}
          style={{ width: `${c}%` }}
        />
      </div>
      <span className={`text-xs font-mono w-8 text-right tabular-nums ${
        c >= 75 ? "text-emerald-400" : c >= 55 ? "text-amber-400" : "text-rose-400"
      }`}>{c.toFixed(0)}%</span>
    </div>
  );
}

function SkeletonRows({ n = 3 }: { n?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: n }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full rounded-xl" />
      ))}
    </div>
  );
}

// ── Event helpers ─────────────────────────────────────────────────────────────

function evIcon(type: string, cat: string) {
  if (cat === "MARKET")        return <Monitor className="w-3.5 h-3.5" />;
  if (cat === "SCAN")          return <Search className="w-3.5 h-3.5" />;
  if (cat === "LEARNING")      return <BookOpen className="w-3.5 h-3.5" />;
  if (cat === "NOTIFICATION")  return <Bell className="w-3.5 h-3.5" />;
  if (type === "BUY"  || type === "ADD")                        return <TrendingUp className="w-3.5 h-3.5" />;
  if (type === "SELL" || type === "EXIT" || type === "CLOSE")   return <TrendingDown className="w-3.5 h-3.5" />;
  if (type === "PARTIAL_EXIT")                                  return <Zap className="w-3.5 h-3.5" />;
  return <Activity className="w-3.5 h-3.5" />;
}
function evCls(type: string, cat: string) {
  if (type === "BUY"  || type === "ADD")                        return "text-emerald-400 bg-emerald-950/30 border-emerald-800/40";
  if (type === "SELL" || type === "EXIT" || type === "CLOSE")   return "text-rose-400    bg-rose-950/30    border-rose-800/40";
  if (type === "PARTIAL_EXIT")                                  return "text-amber-400   bg-amber-950/30   border-amber-800/40";
  if (cat === "MARKET")   return "text-blue-400   bg-blue-950/30   border-blue-800/40";
  if (cat === "SCAN")     return "text-teal-400   bg-teal-950/30   border-teal-800/40";
  if (cat === "LEARNING") return "text-purple-400 bg-purple-950/30 border-purple-800/40";
  return "text-slate-400 bg-slate-800/30 border-slate-700/40";
}

// ══════════════════════════════════════════════════════════════════════════════
// S0 — Autonomous Trading Session Status
// ══════════════════════════════════════════════════════════════════════════════

function S0AutonomousSession() {
  const qc = useQueryClient();

  const { data: sess, isLoading: sessLoad, refetch: refetchSess } =
    useQuery<SessionStatus>({
      queryKey: ["apt", "session-status"],
      queryFn:  () => apiJson("/phase11/session/status"),
      refetchInterval: 30_000, staleTime: 15_000, retry: 1,
    });

  // Canonical agent status — same source as AI Operations Centre (/ops-centre/agents)
  const { data: agents, isLoading: agentsLoad, refetch: refetchAgents } =
    useQuery<CanonicalAgentStatus>({
      queryKey: ["apt", "session-agents"],
      queryFn:  () => apiJson("/ops-centre/agents", undefined, 30_000),
      staleTime: 60_000, retry: 1,
      refetchInterval: 120_000,
    });

  const initMut = useMutation({
    mutationFn: (force: boolean) =>
      apiJson("/phase11/session/init", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["apt", "session-status"] });
      qc.invalidateQueries({ queryKey: ["apt", "session-agents"] });
      qc.invalidateQueries({ queryKey: ["apt", "portfolio"] });
    },
  });

  const enableMut = useMutation({
    mutationFn: () =>
      apiJson("/phase11/session/enable-autonomous", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["apt", "session-status"] }),
  });

  const disableMut = useMutation({
    mutationFn: () =>
      apiJson("/phase11/session/disable-autonomous", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["apt", "session-status"] }),
  });

  const initialized = sess?.initialized_today ?? false;
  const autoEntries = sess?.auto_paper_entries ?? false;
  const crmMode     = (sess?.capital_mode ?? "A") === "B";
  const healthy     = agents?.agent_count?.active ?? 0;
  const total       = agents?.agent_count?.total  ?? 0;
  const agentOk     = healthy > 0 && healthy === total;

  const statusCls = initialized
    ? "bg-emerald-950/30 border-emerald-700/40"
    : "bg-amber-950/30 border-amber-700/40";
  const statusIcon = initialized
    ? <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
    : <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />;

  return (
    <div className={`border rounded-xl p-4 ${statusCls}`}>
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-teal-400" />
          <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
            Autonomous Trading Session
          </h2>
          <Badge className="text-xs bg-teal-950 border-teal-700/50 text-teal-300 px-2 py-0">
            {sess?.today ?? "—"}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetchSess()}
            className="text-xs text-slate-500 hover:text-teal-400 flex items-center gap-1 transition-colors">
            <RefreshCcw className="w-3 h-3" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
        {/* Session Status */}
        <div className={`rounded-xl border p-3 ${initialized
          ? "bg-emerald-950/40 border-emerald-700/40"
          : "bg-amber-950/40 border-amber-700/40"}`}>
          <span className="text-xs text-slate-500">Session</span>
          <div className="flex items-center gap-1 mt-0.5">
            {statusIcon}
            <span className={`text-sm font-bold ${initialized ? "text-emerald-400" : "text-amber-400"}`}>
              {sessLoad ? "…" : initialized ? "READY" : "NOT INIT"}
            </span>
          </div>
          {sess?.last_init_at && (
            <span className="text-xs text-slate-600">{istTime(sess.last_init_at)} IST</span>
          )}
        </div>

        {/* Auto Paper Entries */}
        <div className={`rounded-xl border p-3 ${autoEntries
          ? "bg-emerald-950/40 border-emerald-700/40"
          : "bg-slate-900/60 border-slate-800/40"}`}>
          <span className="text-xs text-slate-500">Auto Entries</span>
          <div className="flex items-center gap-1 mt-0.5">
            {autoEntries
              ? <Power className="w-3.5 h-3.5 text-emerald-400" />
              : <XCircle className="w-3.5 h-3.5 text-slate-500" />}
            <span className={`text-sm font-bold ${autoEntries ? "text-emerald-400" : "text-slate-400"}`}>
              {sessLoad ? "…" : autoEntries ? "ON" : "OFF"}
            </span>
          </div>
          <span className="text-xs text-slate-600">PAPER only</span>
        </div>

        {/* Auto Exits */}
        <div className="rounded-xl border bg-emerald-950/40 border-emerald-700/40 p-3">
          <span className="text-xs text-slate-500">Auto Exits</span>
          <div className="flex items-center gap-1 mt-0.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-sm font-bold text-emerald-400">
              {sessLoad ? "…" : (sess?.auto_paper_exits ?? true) ? "ON" : "OFF"}
            </span>
          </div>
          <span className="text-xs text-slate-600">Always active</span>
        </div>

        {/* Agents */}
        <div className={`rounded-xl border p-3 ${agentsLoad ? "bg-slate-900/60 border-slate-800/40"
          : agentOk ? "bg-emerald-950/40 border-emerald-700/40"
          : "bg-amber-950/40 border-amber-700/40"}`}>
          <span className="text-xs text-slate-500">Agents</span>
          <div className="flex items-center gap-1 mt-0.5">
            <Cpu className={`w-3.5 h-3.5 ${agentOk ? "text-emerald-400" : "text-amber-400"}`} />
            <span className={`text-sm font-bold ${agentOk ? "text-emerald-400" : "text-amber-400"}`}>
              {agentsLoad ? "…" : `${healthy}/${total}`}
            </span>
          </div>
          <button onClick={() => refetchAgents()}
            className="text-xs text-slate-600 hover:text-teal-400 transition-colors">
            verify →
          </button>
        </div>

        {/* Capital Mode */}
        <div className="rounded-xl border bg-slate-900/60 border-slate-800/40 p-3">
          <span className="text-xs text-slate-500">Capital Mode</span>
          <div className="flex items-center gap-1 mt-0.5">
            <Shield className={`w-3.5 h-3.5 ${crmMode ? "text-violet-400" : "text-teal-400"}`} />
            <span className={`text-sm font-bold font-mono ${crmMode ? "text-violet-400" : "text-teal-400"}`}>
              {sessLoad ? "…" : `Mode ${sess?.capital_mode ?? "A"}`}
            </span>
          </div>
          <span className="text-xs text-slate-600">{crmMode ? "Continuous Research" : "Daily ₹50K"}</span>
        </div>

        {/* Starting Capital */}
        <div className="rounded-xl border bg-slate-900/60 border-slate-800/40 p-3">
          <span className="text-xs text-slate-500">Daily Capital</span>
          <span className="text-sm font-bold text-blue-400 font-mono">
            {sessLoad ? "…" : `₹${((sess?.starting_capital ?? 50_000) / 1_000).toFixed(0)}K`}
          </span>
          <br />
          <span className="text-xs text-slate-600">Resets each day</span>
        </div>
      </div>

      {/* Action Row */}
      <div className="flex flex-wrap items-center gap-2">
        {!initialized && (
          <button
            disabled={initMut.isPending}
            onClick={() => initMut.mutate(false)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-700/40 hover:bg-emerald-700/60 text-emerald-300 border border-emerald-700/50 transition-colors disabled:opacity-50">
            {initMut.isPending
              ? <RefreshCcw className="w-3 h-3 animate-spin" />
              : <Power className="w-3 h-3" />}
            Initialize Today's Session
          </button>
        )}

        {initialized && !autoEntries && (
          <button
            disabled={enableMut.isPending}
            onClick={() => enableMut.mutate()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-teal-700/40 hover:bg-teal-700/60 text-teal-300 border border-teal-700/50 transition-colors disabled:opacity-50">
            {enableMut.isPending
              ? <RefreshCcw className="w-3 h-3 animate-spin" />
              : <Power className="w-3 h-3" />}
            Enable Autonomous Trading
          </button>
        )}

        {initialized && autoEntries && (
          <button
            disabled={disableMut.isPending}
            onClick={() => disableMut.mutate()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-700/40 hover:bg-slate-700/60 text-slate-400 border border-slate-700/50 transition-colors disabled:opacity-50">
            <XCircle className="w-3 h-3" />
            Pause Autonomous Trading
          </button>
        )}

        <button
          disabled={initMut.isPending}
          onClick={() => initMut.mutate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg text-slate-500 hover:text-amber-400 border border-slate-700/40 hover:border-amber-700/40 transition-colors disabled:opacity-50">
          <RotateCcw className="w-3 h-3" />
          Force Reset (₹50K)
        </button>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-slate-600 flex items-center gap-1">
            <Shield className="w-3 h-3 text-emerald-600" />
            PAPER ONLY · No live orders · No real money
          </span>
        </div>
      </div>

      {/* Error display */}
      {initMut.error && (
        <p className="text-xs text-rose-400 mt-2">
          ⚠ {String((initMut.error as Error).message).slice(0, 120)}
        </p>
      )}

      {/* CRM info banner when Mode B active */}
      {crmMode && (
        <div className="mt-3 rounded-lg bg-violet-950/30 border border-violet-800/40 px-3 py-2 text-xs text-violet-300">
          🔄 <strong>Continuous Research Mode</strong> is active (Mode B).
          Capital will automatically top up to ₹{((sess?.starting_capital ?? 50_000) / 1_000).toFixed(0)}K
          when available cash falls below ₹{((sess?.topup_threshold ?? 10_000) / 1_000).toFixed(0)}K.
          Every top-up is logged in the Capital tab.
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// SPipeline — Execution Pipeline Funnel
// ══════════════════════════════════════════════════════════════════════════════

interface PipelineFunnelStage {
  stage: string;
  label: string;
  count: number;
  detail: string;
  passed: boolean;
  blocker?: boolean;
  gates?: { gate: string; passed: boolean; reason: string }[];
}

interface PipelineStats {
  generated_at?: string;
  scan_id?: string;
  scan_available?: boolean;
  eval_available?: boolean;
  funnel?: PipelineFunnelStage[];
  first_blocker?: string | null;
  top_buy_candidates?: {
    symbol: string; action: string;
    opportunity_score: number; confidence: number;
    technical_score: number; rr_ratio: number;
    regime: string; data_quality: string;
  }[];
  candidate_gate_details?: {
    symbol: string; eligible: boolean; failed_gates: string[];
    opportunity_score: number; confidence: number;
  }[];
  settings?: {
    min_confidence?: number; min_opportunity_score?: number;
    min_trade_quality?: number; min_risk_reward?: number;
    max_trades_per_day?: number; auto_paper_entries?: boolean;
  };
  summary?: {
    stocks_scanned: number; live_data_count: number;
    passed_intelligence: number; buy_signals: number;
    global_pass: boolean; candidates_evaluated: number;
    candidates_eligible: number; paper_orders_today: number;
    open_positions: number;
  };
  stage_errors?: string[];
}

function SPipelineStats() {
  const [expanded, setExpanded] = useState(false);
  const [showGates, setShowGates] = useState<string | null>(null);

  const { data, isLoading, refetch, dataUpdatedAt } = useQuery<PipelineStats>({
    queryKey: ["apt", "pipeline"],
    queryFn:  () => apiJson("/phase20/pipeline"),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });

  const summary   = data?.summary;
  const funnel    = data?.funnel ?? [];
  const blocker   = data?.first_blocker;
  const hasBlock  = !!blocker;

  // Colour each stage
  function stageCls(s: PipelineFunnelStage) {
    if (s.blocker) return "bg-rose-950/40 border-rose-700/50";
    if (!s.passed && s.stage !== "paper_orders_today") return "bg-amber-950/30 border-amber-700/40";
    if (s.passed)  return "bg-emerald-950/30 border-emerald-700/40";
    return "bg-slate-900/50 border-slate-800/40";
  }
  function stageIcon(s: PipelineFunnelStage) {
    if (s.blocker)  return <XCircle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0" />;
    if (!s.passed && s.stage !== "paper_orders_today") return <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />;
    if (s.passed)   return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />;
    return <Clock className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />;
  }

  const overall = hasBlock ? "bg-rose-950/20 border-rose-700/30" : "bg-emerald-950/20 border-emerald-700/30";

  return (
    <div className={`border rounded-xl p-4 ${overall}`}>
      {/* Header */}
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-teal-400" />
          <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
            Execution Pipeline
          </h2>
          {isLoading
            ? <Badge className="text-xs bg-slate-900 border-slate-700 text-slate-400">loading…</Badge>
            : hasBlock
              ? <Badge className="text-xs bg-rose-950 border-rose-700/50 text-rose-300">Blocked</Badge>
              : <Badge className="text-xs bg-emerald-950 border-emerald-700/50 text-emerald-300">Flowing</Badge>
          }
        </div>
        <div className="flex items-center gap-3">
          {summary && (
            <span className="text-xs text-slate-500 font-mono">
              {summary.paper_orders_today} order{summary.paper_orders_today !== 1 ? "s" : ""} today ·{" "}
              {summary.open_positions} open
            </span>
          )}
          <button onClick={() => refetch()}
            className="text-xs text-slate-500 hover:text-teal-400 flex items-center gap-1 transition-colors">
            <RefreshCcw className="w-3 h-3" />
          </button>
          <button onClick={() => setExpanded(e => !e)}
            className="text-xs text-slate-500 hover:text-teal-400 transition-colors flex items-center gap-1">
            <ChevronDown className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
            {expanded ? "Collapse" : "Expand"}
          </button>
        </div>
      </div>

      {/* Funnel — compact horizontal strip */}
      {isLoading ? (
        <div className="flex gap-2">
          {[...Array(7)].map((_, i) => (
            <Skeleton key={i} className="h-16 flex-1 rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="flex items-stretch gap-1 overflow-x-auto pb-1">
          {funnel.map((stage, idx) => (
            <div key={stage.stage} className="flex items-center">
              {/* Stage card */}
              <div
                className={`flex flex-col min-w-[110px] rounded-lg border p-2 cursor-pointer
                  ${stageCls(stage)}
                  ${showGates === stage.stage ? "ring-1 ring-teal-500/50" : ""}
                `}
                onClick={() => setShowGates(prev => prev === stage.stage ? null : stage.stage)}
              >
                <div className="flex items-center gap-1 mb-1">
                  {stageIcon(stage)}
                  <span className="text-[10px] text-slate-400 leading-tight">{stage.label}</span>
                </div>
                <span className={`text-xl font-bold font-mono leading-none mb-0.5 ${
                  stage.blocker ? "text-rose-300"
                    : !stage.passed && stage.stage !== "paper_orders_today" ? "text-amber-300"
                    : stage.passed ? "text-emerald-300"
                    : "text-slate-400"
                }`}>
                  {stage.count}
                </span>
                <span className="text-[9px] text-slate-500 leading-tight line-clamp-2">{stage.detail}</span>
              </div>
              {/* Connector arrow */}
              {idx < funnel.length - 1 && (
                <ArrowDown className="w-3 h-3 text-slate-600 flex-shrink-0 mx-0.5 rotate-[-90deg]" />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Expanded gate detail */}
      {expanded && !isLoading && (
        <div className="mt-4 space-y-3">
          {/* Blocker explanation */}
          {blocker && (
            <div className="rounded-lg bg-rose-950/30 border border-rose-700/40 px-3 py-2">
              <p className="text-xs text-rose-300 font-medium flex items-center gap-1.5">
                <XCircle className="w-3.5 h-3.5" />
                First blockage: <code className="font-mono">{blocker}</code>
              </p>
              {funnel.find(f => f.stage === blocker)?.detail && (
                <p className="text-xs text-rose-400/80 mt-1">
                  {funnel.find(f => f.stage === blocker)?.detail}
                </p>
              )}
            </div>
          )}

          {/* Global gates */}
          {(() => {
            const gStage = funnel.find(s => s.stage === "global_gates");
            if (!gStage?.gates?.length) return null;
            return (
              <div className="rounded-lg bg-slate-900/40 border border-slate-800/40 p-3">
                <p className="text-xs font-semibold text-slate-400 mb-2 flex items-center gap-1.5">
                  <Shield className="w-3 h-3" /> Global Gates
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                  {gStage.gates.map(g => (
                    <div key={g.gate} className="flex items-start gap-1.5">
                      {g.passed
                        ? <CheckCircle2 className="w-3 h-3 text-emerald-400 flex-shrink-0 mt-px" />
                        : <XCircle className="w-3 h-3 text-rose-400 flex-shrink-0 mt-px" />}
                      <div>
                        <span className="text-[10px] font-mono text-slate-300">{g.gate}</span>
                        <p className="text-[9px] text-slate-500 leading-snug">{g.reason}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}

          {/* Top BUY candidates */}
          {(data?.top_buy_candidates?.length ?? 0) > 0 && (
            <div className="rounded-lg bg-slate-900/40 border border-slate-800/40 p-3">
              <p className="text-xs font-semibold text-slate-400 mb-2 flex items-center gap-1.5">
                <TrendingUp className="w-3 h-3 text-teal-400" /> BUY Candidates This Scan
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-[10px]">
                  <thead>
                    <tr className="text-slate-500">
                      <th className="text-left pb-1 pr-2">Symbol</th>
                      <th className="text-left pb-1 pr-2">Action</th>
                      <th className="text-right pb-1 pr-2">Opp Score</th>
                      <th className="text-right pb-1 pr-2">Confidence</th>
                      <th className="text-right pb-1 pr-2">Quality</th>
                      <th className="text-right pb-1 pr-2">R:R</th>
                      <th className="text-left pb-1">Regime</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.top_buy_candidates ?? []).map(c => (
                      <tr key={c.symbol} className="border-t border-slate-800/30">
                        <td className="py-1 pr-2 font-mono text-teal-300">{c.symbol}</td>
                        <td className="py-1 pr-2">
                          <span className={`px-1 rounded text-[9px] ${c.action === "STRONG BUY" ? "bg-emerald-900/60 text-emerald-300" : "bg-teal-900/60 text-teal-300"}`}>
                            {c.action}
                          </span>
                        </td>
                        <td className="py-1 pr-2 text-right font-mono text-emerald-300">{c.opportunity_score.toFixed(1)}</td>
                        <td className="py-1 pr-2 text-right font-mono text-blue-300">{c.confidence.toFixed(1)}%</td>
                        <td className="py-1 pr-2 text-right font-mono text-slate-300">{c.technical_score.toFixed(1)}</td>
                        <td className="py-1 pr-2 text-right font-mono text-amber-300">{c.rr_ratio.toFixed(1)}×</td>
                        <td className="py-1 text-slate-400 text-[9px]">{c.regime}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Per-candidate gate failures */}
          {(data?.candidate_gate_details?.filter(c => !c.eligible).length ?? 0) > 0 && (
            <div className="rounded-lg bg-slate-900/40 border border-slate-800/40 p-3">
              <p className="text-xs font-semibold text-slate-400 mb-2 flex items-center gap-1.5">
                <XCircle className="w-3 h-3 text-rose-400" /> Blocked Candidates
              </p>
              <div className="space-y-1">
                {(data?.candidate_gate_details ?? [])
                  .filter(c => !c.eligible)
                  .map(c => (
                    <div key={c.symbol} className="flex items-start gap-2 text-[10px]">
                      <span className="font-mono text-rose-300 w-16 flex-shrink-0">{c.symbol}</span>
                      <span className="text-slate-500">
                        {c.failed_gates.map(g => (
                          <span key={g} className="inline-block bg-rose-950/50 border border-rose-800/40 text-rose-400 rounded px-1 mr-1 mb-0.5">{g}</span>
                        ))}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Active settings thresholds */}
          {data?.settings && (
            <div className="rounded-lg bg-slate-900/30 border border-slate-800/30 px-3 py-2">
              <p className="text-[10px] text-slate-500 font-semibold mb-1">Active Thresholds</p>
              <div className="flex flex-wrap gap-3 text-[10px] text-slate-400 font-mono">
                <span>min_confidence: <strong className="text-blue-300">{data.settings.min_confidence}</strong></span>
                <span>min_opp_score: <strong className="text-emerald-300">{data.settings.min_opportunity_score}</strong></span>
                <span>min_quality: <strong className="text-amber-300">{data.settings.min_trade_quality}</strong></span>
                <span>min_rr: <strong className="text-teal-300">{data.settings.min_risk_reward}×</strong></span>
                <span>max_per_day: <strong className="text-violet-300">{data.settings.max_trades_per_day}</strong></span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Stage errors (non-blocking, shown as footer note) */}
      {(data?.stage_errors?.length ?? 0) > 0 && (
        <p className="mt-2 text-[10px] text-slate-600">
          ⚠ Pipeline diagnostics partial: {data!.stage_errors!.join("; ").slice(0, 120)}
        </p>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S1 — Market Status
// ══════════════════════════════════════════════════════════════════════════════

const REGIME_CLS: Record<string, string> = {
  BULLISH: "text-emerald-400", BEARISH: "text-rose-400",
  SIDEWAYS: "text-yellow-400", "HIGH VOLATILITY": "text-orange-400",
  "HIGH VOL": "text-orange-400", "LOW VOLATILITY": "text-blue-400",
  "LOW VOL": "text-blue-400",
};

function S1MarketStatus() {
  const [now, setNow] = useState(istNow());
  useEffect(() => {
    const t = setInterval(() => setNow(istNow()), 1000);
    return () => clearInterval(t);
  }, []);

  // health-v2 → market state / session info (nested `market` object)
  const { data: hv2, isLoading: hLoad } = useQuery<HealthV2>({
    queryKey: ["apt", "hv2"],
    queryFn: () => apiJson("/live-data/health-v2"),
    refetchInterval: 30_000, staleTime: 15_000, retry: 1,
  });

  // market-intelligence/overview → NIFTY, BANKNIFTY, VIX, regime, agent health
  const { data: ov, isLoading: ovLoad } = useQuery<MarketOverview>({
    queryKey: ["apt", "mi-overview"],
    queryFn: () => apiJson("/market-intelligence/overview"),
    refetchInterval: 60_000, staleTime: 30_000, retry: 1,
  });

  const isLoading = hLoad;
  const mkt    = hv2?.market;
  const isOpen = mkt?.is_open ?? mkt?.state === "OPEN";
  const state  = mkt?.state ?? (isOpen ? "OPEN" : "CLOSED");
  const sessionLabel = (() => {
    if (!mkt?.state) return "—";
    return mkt.state.replace(/_/g, " ");
  })();
  const nextTransLabel = (() => {
    if (!mkt?.next_transition?.at) return null;
    try {
      return `Next: ${mkt.next_transition.state} @ ${istTime(mkt.next_transition.at)} IST`;
    } catch { return null; }
  })();

  // overview.regime is a nested object: { regime: string, nifty_price, banknifty_price, vix_value, ... }
  const regimeObj = ov?.regime;
  const regimeStr = (regimeObj?.regime ?? "—").replace(/_/g, " ");
  // VIX: prefer volatility sub-object, fall back to regime object
  const vix       = ov?.volatility?.vix_value ?? regimeObj?.vix_value;
  // Market health proxy: use summary health score if present
  const healthScore = ov?.summary?.health_score;

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <SecTitle icon={Monitor} title="Market Status" />
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        <Kpi
          label="Market Status" hi={isOpen}
          value={
            <span className={isOpen ? "text-emerald-400" : "text-rose-400"}>
              {isLoading ? "…" : state}
            </span>
          }
        />
        <Kpi label="IST Time"    value={now} />
        <Kpi label="Session"     value={isLoading ? "…" : sessionLabel} />
        <Kpi label="Regime"
          value={
            <span className={REGIME_CLS[regimeStr] ?? "text-slate-400"}>
              {ovLoad ? "…" : regimeStr}
            </span>
          }
        />
        <Kpi label="NIFTY 50"
          value={ovLoad ? "…" : (regimeObj?.nifty_price ? fmt(regimeObj.nifty_price, 0) : "—")}
        />
        <Kpi label="BANK NIFTY"
          value={ovLoad ? "…" : (regimeObj?.banknifty_price ? fmt(regimeObj.banknifty_price, 0) : "—")}
        />
        <Kpi
          label="India VIX"
          value={ovLoad ? "…" : (vix != null ? vix.toFixed(2) : "—")}
          color={vix != null && vix > 20 ? "text-orange-400" : ""}
        />
        <Kpi
          label="Market Health"
          value={ovLoad ? "…" : (healthScore != null ? `${healthScore.toFixed(0)}%` : "—")}
          color={healthScore != null && healthScore >= 60 ? "text-emerald-400" : "text-amber-400"}
        />
      </div>
      {(nextTransLabel || mkt?.holiday_today) && (
        <p className="text-xs text-slate-600 mt-2 flex items-center gap-2">
          <Clock className="w-3 h-3" />
          {mkt?.holiday_today && <span>🎌 Holiday: {mkt.holiday_today}</span>}
          {nextTransLabel && <span>{nextTransLabel}</span>}
        </p>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S2 — Portfolio Summary
// ══════════════════════════════════════════════════════════════════════════════

function S2Portfolio({ data, loading }: { data?: Portfolio; loading: boolean }) {
  if (loading) return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4 h-full">
      <SecTitle icon={Wallet} title="Portfolio Summary" />
      <SkeletonRows />
    </div>
  );
  if (!data) return null;
  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <SecTitle
        icon={Wallet} title="Portfolio Summary"
        sub={`Mode ${data.capital_mode} · ${istTime(data.as_of || new Date().toISOString())} IST`}
      />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <Kpi label="Starting Capital" value={fmtK(data.starting_capital)} />
        <Kpi label="Portfolio Value"  value={fmtK(data.current_value)} hi />
        <Kpi label="Cash Available"   value={fmtK(data.cash)} />
        <Kpi label="Buying Power"     value={fmtK(data.buying_power)} />
        <Kpi label="Invested"         value={fmtK(data.invested_amount)} color="text-blue-400" />
        <Kpi label="Unrealised P/L"   value={<span className={pnlCls(data.unrealised_pnl)}>{fmtK(data.unrealised_pnl)}</span>} />
        <Kpi label="Today P/L"
          value={<span className={pnlCls(data.daily_pnl)}>{fmtK(data.daily_pnl)}</span>}
          sub={`${data.daily_return >= 0 ? "+" : ""}${(data.daily_return ?? 0).toFixed(2)}%`}
        />
        <Kpi label="Overall P/L"    value={<span className={pnlCls(data.total_pnl)}>{fmtK(data.total_pnl)}</span>} />
        <Kpi label="Today Return"   value={<span className={pnlCls(data.daily_return)}>{`${data.daily_return >= 0 ? "+" : ""}${(data.daily_return ?? 0).toFixed(2)}%`}</span>} />
        <Kpi label="Overall Return" value={<span className={pnlCls(data.portfolio_return)}>{`${data.portfolio_return >= 0 ? "+" : ""}${(data.portfolio_return ?? 0).toFixed(2)}%`}</span>} />
        <Kpi label="Drawdown"       value={<span className={(data.drawdown_pct ?? 0) < -5 ? "text-rose-400" : "text-amber-400"}>{(data.drawdown_pct ?? 0).toFixed(2)}%</span>} />
        <Kpi label="Open Positions" value={data.open_positions ?? 0} color="text-teal-400" />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S3 — Live AI Status
// ══════════════════════════════════════════════════════════════════════════════

const ACTIVITY_MAP: Record<string, string> = {
  BUY: "🟢 Buying", ADD: "🟢 Adding",
  SELL: "🔴 Selling", EXIT: "🔴 Exiting", CLOSE: "🔴 Closing",
  PARTIAL_EXIT: "🟡 Partial Exit",
  SCAN: "🔵 Scanning", LEARNING: "🟣 Learning",
};

function S3AIStatus({ portfolio, recs }: { portfolio?: Portfolio; recs?: RecsData }) {
  const qc = useQueryClient();

  // Reuse the health-v2 cache populated by S1 — zero extra network requests
  const { data: hv2 } = useQuery<HealthV2>({
    queryKey: ["apt", "hv2"],
    queryFn:  () => apiJson("/live-data/health-v2"),
    refetchInterval: 30_000, staleTime: 15_000, retry: 1,
  });

  const { data: tl, refetch: refetchTl } = useQuery<{ events: TimelineEvent[] }>({
    queryKey: ["apt", "tl-live"],
    queryFn:  () => apiJson("/phase11/timeline?limit=5"),
    refetchInterval: 20_000, staleTime: 10_000, retry: 1,
  });

  // ── Scan-and-trade mutation (fire-and-forget) ─────────────────────────────
  // POST /live-data/scan/run now responds immediately with { started: true }.
  // The actual scan runs in background on the server (90–120 s). We detect
  // completion by polling GET /live-data/scan/status every 5 s and watching
  // for snapshot_ts to advance past the moment we pressed "Run Scan".
  const [lastScanAt,    setLastScanAt]    = useState<string | null>(null);
  const [scanError,     setScanError]     = useState<string | null>(null);
  const [cooldownSec,   setCooldownSec]   = useState(0);
  const [scanRunning,   setScanRunning]   = useState(false);
  const [scanStartedAt, setScanStartedAt] = useState<number>(0);  // epoch ms

  // Lightweight status poll — only fires while scan is in flight.
  // Busts the scan-status cache (15 s server-side), so we see the new
  // snapshot_ts as soon as it arrives.
  const scanStatusPoll = useQuery<{ snapshot_ts?: string; scan_id?: string }>({
    queryKey: ["apt", "scan-status-poll"],
    queryFn:  () => apiJson("live-data/scan/status"),
    enabled:  scanRunning,
    refetchInterval: scanRunning ? 5_000 : false,
    staleTime: 0,
  });

  // Detect completion: snapshot_ts newer than when we clicked "Run Scan"
  useEffect(() => {
    if (!scanRunning || !scanStatusPoll.data?.snapshot_ts) return;
    const serverTs = new Date(scanStatusPoll.data.snapshot_ts).getTime();
    if (serverTs > scanStartedAt) {
      // Scan finished — bust every "apt" cache so all sections refresh at once
      setScanRunning(false);
      setLastScanAt(istNow());
      setScanError(null);
      qc.invalidateQueries({ queryKey: ["apt"] });
      qc.invalidateQueries({ queryKey: ["apt", "hv2"] });
      refetchTl();
    }
  }, [scanStatusPoll.data, scanRunning, scanStartedAt, qc, refetchTl]);

  const scanMut = useMutation({
    mutationFn: () =>
      // Server responds in <1 s now; no need for a long timeout.
      apiJson("/live-data/scan/run", { method: "POST" }),
    onSuccess: (resp: unknown) => {
      const r = resp as { started?: boolean; status?: string; error?: string };
      if (r?.status === "RATE_LIMITED") {
        setScanError(r.error?.slice(0, 160) ?? "Rate limited");
        return;
      }
      setScanError(null);
      // Record when the scan kicked off so we can detect completion via poll.
      // Subtract 5 s to tolerate minor clock skew between client and server.
      setScanStartedAt(Date.now() - 5_000);
      setScanRunning(true);
      // Start 30-second cooldown (server-side rate-limit gap)
      setCooldownSec(30);
    },
    onError: (err: Error) => {
      setScanError(err.message.slice(0, 160));
    },
  });

  // Tick the cooldown counter down every second
  useEffect(() => {
    if (cooldownSec <= 0) return;
    const t = setTimeout(() => setCooldownSec(s => Math.max(0, s - 1)), 1_000);
    return () => clearTimeout(t);
  }, [cooldownSec]);

  // Market state derived from the shared health cache
  const mktState     = hv2?.market?.state ?? "";
  const isMarketOpen = mktState === "OPEN" || mktState === "PRE_OPEN";
  const scanning     = scanMut.isPending || scanRunning;
  const canScan      = isMarketOpen && !scanning && cooldownSec === 0;

  // Tooltip text for the disabled states
  const disabledReason = scanning
    ? "Scan in progress…"
    : cooldownSec > 0
    ? `Rate limit — wait ${cooldownSec}s`
    : !isMarketOpen
    ? `Market is ${mktState || "closed"} — scans only run during OPEN / PRE_OPEN`
    : undefined;

  // Timeline
  const events   = tl?.events ?? [];
  const latest   = events.length > 0 ? events[events.length - 1] : null;
  const activity = latest ? (ACTIVITY_MAP[latest.type] ?? "🔵 Analysing") : "🔵 Analysing";
  const best     = recs?.items?.[0];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4 h-full flex flex-col">
      {/* Header row: title + Run Scan button */}
      <div className="flex items-center gap-2 mb-3">
        <Brain className="w-4 h-4 text-indigo-400 flex-shrink-0" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400 flex-1">
          Live AI Status
        </h2>

        {/* ▶ Run Scan button */}
        <div className="relative group">
          <button
            onClick={() => { setScanError(null); scanMut.mutate(); }}
            disabled={!canScan}
            title={disabledReason}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
              scanning
                ? "bg-teal-900/50 border-teal-700/50 text-teal-300 cursor-wait"
                : canScan
                ? "bg-teal-700/40 hover:bg-teal-700/60 border-teal-600/50 text-teal-200 hover:text-white shadow-sm hover:shadow-teal-900/40"
                : "bg-slate-800/40 border-slate-700/30 text-slate-600 cursor-not-allowed"
            }`}
          >
            {scanning
              ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              : <PlayCircle className="w-3.5 h-3.5" />}
            {scanning ? "Scanning…" : "Run Scan"}
          </button>

          {/* Tooltip shown when the button is disabled */}
          {disabledReason && !scanning && (
            <div className="absolute right-0 top-full mt-1.5 z-20 hidden group-hover:block
              w-56 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700/60
              text-xs text-slate-300 shadow-lg pointer-events-none whitespace-normal leading-snug">
              {disabledReason}
            </div>
          )}
        </div>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 gap-3 mb-3 flex-1">
        <Kpi label="Stocks Monitored" value="50"                                color="text-blue-400" />
        <Kpi label="Recommendations"  value={recs?.count ?? "—"}               color="text-amber-400" />
        <Kpi label="Open Positions"   value={portfolio?.open_positions ?? "—"} color="text-teal-400" />
        <Kpi label="Current Activity" value={<span className="text-sm">{activity}</span>} />
        {best && <Kpi label="Best Opportunity"   value={<span className="text-violet-300 font-mono">{best.symbol}</span>}  sub={`${fmt(best.confidence, 0)}% conf`} />}
        {best && <Kpi label="Highest Confidence" value={<span className="text-emerald-400">{fmt(best.confidence, 0)}%</span>} sub={best.strategy} />}
      </div>

      {/* Scan status / latest event footer */}
      <div className="space-y-1.5">
        {/* Scan error */}
        {scanError && (
          <p className="text-xs text-rose-400 flex items-center gap-1">
            <XCircle className="w-3 h-3 flex-shrink-0" />
            {scanError}
          </p>
        )}

        {/* Cooldown progress bar */}
        {cooldownSec > 0 && (
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-teal-600/60 rounded-full transition-all duration-1000"
                style={{ width: `${(cooldownSec / 30) * 100}%` }}
              />
            </div>
            <span className="text-xs text-slate-600 tabular-nums w-12 text-right">
              next in {cooldownSec}s
            </span>
          </div>
        )}

        {/* Last scan time or latest timeline event */}
        {lastScanAt ? (
          <p className="text-xs text-teal-500 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 flex-shrink-0" />
            Scan completed at {lastScanAt} IST
          </p>
        ) : latest ? (
          <p className="text-xs text-slate-500 flex items-center gap-1 truncate">
            <Clock className="w-3 h-3 flex-shrink-0" />
            {istTime(latest.ts)} — {latest.label}
          </p>
        ) : null}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PnlSparkline — compact inline SVG price-momentum chart
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Renders a 96×36 SVG sparkline for a single position.
 *
 * Colour logic:
 *   - Green  : current_price ≥ buy_price  (trending toward / above entry)
 *   - Red    : current_price <  buy_price  (trending toward stop-loss)
 *
 * A dashed reference line is drawn at buy_price so operators can see the
 * entry level at a glance.
 *
 * If fewer than 2 points are available a "no data" dash is shown instead of
 * a broken chart.
 */
export function PnlSparkline({
  points, buyPrice, target, stopLoss,
}: {
  points: number[];
  buyPrice: number;
  target: number;
  stopLoss: number;
}) {
  const W = 96, H = 36, PAD = 3;

  // Guard: need at least 2 points to draw a line
  if (points.length < 2) {
    return (
      <svg width={W} height={H} className="inline-block align-middle opacity-30">
        <line x1={PAD} y1={H / 2} x2={W - PAD} y2={H / 2}
          stroke="#64748b" strokeWidth={1} strokeDasharray="4 3" />
      </svg>
    );
  }

  // Include target / stop-loss in the y-domain so reference lines land in-frame
  const allY = [...points, buyPrice, target, stopLoss].filter(v => v > 0);
  const minY = Math.min(...allY);
  const maxY = Math.max(...allY);
  const rangeY = maxY - minY || 1;

  const toX = (i: number) =>
    PAD + ((i / (points.length - 1)) * (W - PAD * 2));
  const toY = (v: number) =>
    PAD + ((1 - (v - minY) / rangeY) * (H - PAD * 2));

  // Polyline path
  const d = points
    .map((v, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(v).toFixed(1)}`)
    .join(" ");

  // Fill path (close to bottom)
  const fillD = `${d} L${toX(points.length - 1).toFixed(1)},${H} L${toX(0).toFixed(1)},${H} Z`;

  const lastPrice  = points[points.length - 1];
  const isGreen    = lastPrice >= buyPrice;
  const lineColor  = isGreen ? "#10B981" : "#EF4444";    // emerald / rose
  const fillColor  = isGreen ? "#10B981" : "#EF4444";
  const refY       = toY(buyPrice);
  const targetY    = target > 0  ? toY(target)   : null;
  const slY        = stopLoss > 0 ? toY(stopLoss) : null;

  const gradId = `spkG_${buyPrice.toFixed(0)}_${lastPrice.toFixed(0)}`;

  return (
    <svg width={W} height={H} className="inline-block align-middle overflow-visible"
      role="img" aria-label={`Price trend: ${isGreen ? "up" : "down"}`}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={fillColor} stopOpacity={0.25} />
          <stop offset="100%" stopColor={fillColor} stopOpacity={0}    />
        </linearGradient>
      </defs>

      {/* Target line (faint green dashes at top) */}
      {targetY !== null && targetY >= PAD && targetY <= H - PAD && (
        <line x1={PAD} y1={targetY} x2={W - PAD} y2={targetY}
          stroke="#10B981" strokeWidth={0.8} strokeDasharray="3 2" opacity={0.5} />
      )}

      {/* Stop-loss line (faint red dashes at bottom) */}
      {slY !== null && slY >= PAD && slY <= H - PAD && (
        <line x1={PAD} y1={slY} x2={W - PAD} y2={slY}
          stroke="#EF4444" strokeWidth={0.8} strokeDasharray="3 2" opacity={0.5} />
      )}

      {/* Buy-price reference line (slate dashes) */}
      {refY >= PAD && refY <= H - PAD && (
        <line x1={PAD} y1={refY} x2={W - PAD} y2={refY}
          stroke="#94a3b8" strokeWidth={0.8} strokeDasharray="3 2" opacity={0.6} />
      )}

      {/* Area fill */}
      <path d={fillD} fill={`url(#${gradId})`} />

      {/* Main price line */}
      <path d={d} fill="none" stroke={lineColor} strokeWidth={1.5}
        strokeLinecap="round" strokeLinejoin="round" />

      {/* Last-price dot */}
      <circle
        cx={toX(points.length - 1)} cy={toY(lastPrice)}
        r={2.5} fill={lineColor} />
    </svg>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S4 — Current Holdings (with P&L sparklines)
// ══════════════════════════════════════════════════════════════════════════════

/**
 * Build a symbol → price-point array for sparklines.
 *
 * Priority:
 *   1. `snapshotPrices` — persisted DB snapshots recorded post-scan
 *      (up to 6–16 intraday points, oldest-first). Preferred when available.
 *   2. Inline prices from `events` (sparse — only BUY/SELL events).
 *
 * buy_price is always prepended as the entry anchor and current_price is
 * always appended so the line is grounded even when snapshots are scarce.
 */
export function buildSparkPoints(
  symbol: string,
  buyPrice: number,
  currentPrice: number,
  events: TimelineEvent[],
  snapshotPrices?: number[],
): number[] {
  // Prefer richer DB snapshots; fall back to sparse timeline event prices
  const mid: number[] =
    snapshotPrices && snapshotPrices.length > 0
      ? snapshotPrices.slice(-18)
      : events
          .filter(e => e.symbol === symbol && typeof e.price === "number" && e.price > 0)
          .map(e => e.price as number)
          .slice(-18);

  // Build: entry → intermediate snapshots → current
  const pts = [buyPrice, ...mid, currentPrice];

  // De-duplicate consecutive identical prices to avoid flat artefacts
  const deduped: number[] = [];
  for (const p of pts) {
    if (deduped.length === 0 || deduped[deduped.length - 1] !== p) {
      deduped.push(p);
    }
  }
  return deduped;
}

function S4Holdings() {
  const { data, isLoading, refetch } = useQuery<unknown>({
    queryKey: ["apt", "open-pos"],
    queryFn: () => apiJson("/phase11/portfolio/open-positions"),
    refetchInterval: 30_000, staleTime: 15_000, retry: 1,
  });
  const list = toArr<OpenPosition>(data);

  // Fetch timeline for sparkline price history — shared with S5 via same
  // query key so no extra network request is made when both are mounted.
  const { data: tlData } = useQuery<{ events: TimelineEvent[] }>({
    queryKey: ["apt", "timeline"],
    queryFn: () => apiJson("/phase11/timeline?limit=200"),
    refetchInterval: 30_000, staleTime: 15_000, retry: 1,
  });
  const tlEvents = tlData?.events ?? [];

  // Fetch persisted intraday price snapshots (all open symbols in one request).
  // Refreshed every 60 s — snapshots are only written post-scan, so polling
  // faster than that adds no value.
  const { data: phData } = useQuery<{ snapshots: Record<string, number[]>; as_of?: string }>({
    queryKey: ["apt", "price-history"],
    queryFn:  () => apiJson("/phase11/price-history"),
    refetchInterval: 60_000, staleTime: 30_000, retry: 1,
  });
  const priceSnapshots: Record<string, number[]> = phData?.snapshots ?? {};

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <SecTitle icon={Layers} title={`Current Holdings (${list.length})`} />
        <div className="flex items-center gap-3 ml-auto">
          {list.length > 0 && (
            <span className="text-xs text-slate-600 flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 bg-emerald-500 rounded" /> toward target
              <span className="inline-block w-3 h-0.5 bg-rose-500 rounded ml-2" /> toward S/L
            </span>
          )}
          <button onClick={() => refetch()} className="text-slate-500 hover:text-teal-400 transition-colors">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      {isLoading && <SkeletonRows n={4} />}
      {!isLoading && list.length === 0 && (
        <p className="text-xs text-slate-500 text-center py-8">No open positions</p>
      )}
      {list.length > 0 && (
        <div className="overflow-x-auto -mx-1 px-1">
          <table className="w-full text-xs whitespace-nowrap">
            <thead>
              <tr className="border-b border-slate-800/60">
                {[
                  "Stock","Momentum","Buy Time","Buy ₹","Qty","Cur ₹",
                  "Value","P/L","P/L %","Target","S/L","Exp Ret",
                  "Confidence","Strategy","Risk","Duration",
                ].map(h => (
                  <th key={h} className="pb-2 pr-3 text-left text-slate-500 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((p) => {
                const sparkPts = buildSparkPoints(
                  p.stock, p.buy_price, p.current_price, tlEvents,
                  priceSnapshots[p.stock],
                );
                return (
                  <tr key={p.stock} className="border-b border-slate-800/30 hover:bg-slate-800/20 transition-colors">
                    <td className="py-2 pr-3 font-bold text-slate-100">{p.stock}</td>
                    {/* ── Sparkline cell ── */}
                    <td className="py-2 pr-4">
                      <div title={`${p.stock} price trend — ${sparkPts.length} pts${priceSnapshots[p.stock]?.length ? ` (${priceSnapshots[p.stock].length} intraday snapshots)` : ""}. Entry ₹${p.buy_price.toFixed(2)} → Current ₹${p.current_price.toFixed(2)}`}>
                        <PnlSparkline
                          points={sparkPts}
                          buyPrice={p.buy_price}
                          target={p.target}
                          stopLoss={p.stop_loss}
                        />
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-slate-400">{istDateTime(p.buy_time)}</td>
                    <td className="py-2 pr-3 font-mono">₹{fmt(p.buy_price, 2)}</td>
                    <td className="py-2 pr-3 font-mono">{p.quantity}</td>
                    <td className="py-2 pr-3 font-mono">₹{fmt(p.current_price, 2)}</td>
                    <td className="py-2 pr-3 font-mono">{fmtK(p.current_value)}</td>
                    <td className={`py-2 pr-3 font-mono font-bold ${pnlCls(p.current_pnl)}`}>{fmtK(p.current_pnl)}</td>
                    <td className={`py-2 pr-3 font-mono font-bold ${pnlCls(p.current_pnl_pct)}`}>{(p.current_pnl_pct ?? 0).toFixed(2)}%</td>
                    <td className="py-2 pr-3 font-mono text-emerald-400">₹{fmt(p.target, 2)}</td>
                    <td className="py-2 pr-3 font-mono text-rose-400">₹{fmt(p.stop_loss, 2)}</td>
                    <td className={`py-2 pr-3 font-mono ${pnlCls(p.expected_return_current)}`}>{(p.expected_return_current ?? 0).toFixed(1)}%</td>
                    <td className="py-2 pr-3 w-28"><ConfBar value={p.ai_confidence} /></td>
                    <td className="py-2 pr-3 text-violet-300">{p.strategy}</td>
                    <td className="py-2 pr-3"><RiskBadge level={p.risk_level} /></td>
                    <td className="py-2 pr-3 text-slate-400">{p.holding_label}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S5 — Live Activity Feed
// ══════════════════════════════════════════════════════════════════════════════

const TL_CATS = ["ALL", "TRADE", "MARKET", "SCAN", "LEARNING"] as const;

function S5ActivityFeed() {
  const [filter, setFilter] = useState("ALL");
  const { data, isLoading } = useQuery<{ events: TimelineEvent[] }>({
    queryKey: ["apt", "timeline"],
    queryFn: () => apiJson("/phase11/timeline?limit=80"),
    refetchInterval: 20_000, staleTime: 10_000, retry: 1,
  });
  const all = data?.events ?? [];
  const shown = filter === "ALL" ? all
    : filter === "TRADE" ? all.filter(e => ["BUY","SELL","EXIT","PARTIAL_EXIT","ADD","CLOSE"].includes(e.type))
    : all.filter(e => e.category === filter);

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4 flex flex-col" style={{ height: 440 }}>
      <SecTitle icon={Activity} title="Live Activity Feed" color="text-blue-400" />
      <div className="flex gap-1 mb-2.5 flex-wrap">
        {TL_CATS.map(c => (
          <button key={c} onClick={() => setFilter(c)}
            className={`px-2 py-0.5 rounded-md text-xs font-mono transition-colors ${
              filter === c ? "bg-teal-600 text-white" : "bg-slate-800 text-slate-400 hover:text-slate-200"
            }`}>
            {c}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto space-y-1 pr-1">
        {isLoading && <SkeletonRows n={6} />}
        {!isLoading && shown.length === 0 && (
          <p className="text-xs text-slate-500 text-center py-6">No events today</p>
        )}
        {shown.map((e, i) => (
          <div key={`${e.ts}-${i}`}
            className={`flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${evCls(e.type, e.category)}`}>
            <span className="mt-0.5 flex-shrink-0">{evIcon(e.type, e.category)}</span>
            <span className="font-mono text-slate-500 flex-shrink-0 w-10">{istTime(e.ts)}</span>
            <div className="flex-1 min-w-0">
              <span className="font-semibold">{e.label}</span>
              {e.symbol && <span className="ml-1 font-bold">{e.symbol}</span>}
              {e.detail && <p className="text-slate-500 truncate mt-0.5">{e.detail}</p>}
            </div>
            {e.pnl != null && (
              <span className={`font-mono font-bold flex-shrink-0 ${pnlCls(e.pnl)}`}>{fmtK(e.pnl)}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S6 — Recommendation Queue
// ══════════════════════════════════════════════════════════════════════════════

function S6RecQueue({ data, loading }: { data?: RecsData; loading: boolean }) {
  const items = data?.items ?? [];
  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4 flex flex-col" style={{ height: 440 }}>
      <SecTitle icon={Target} title={`Recommendation Queue (${data?.count ?? 0})`} color="text-amber-400" />
      <div className="flex-1 overflow-y-auto space-y-2 pr-1">
        {loading && <SkeletonRows n={4} />}
        {!loading && items.length === 0 && (
          <p className="text-xs text-slate-500 text-center py-8">No recommendations — run a scan first</p>
        )}
        {items.map((r, i) => (
          <div key={`${r.symbol}-${i}`} className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-3 space-y-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="font-bold text-slate-100">{r.symbol}</span>
              <div className="flex items-center gap-1.5 flex-wrap">
                <RiskBadge level={r.risk_level} />
                <Badge className="text-xs px-1.5 py-0 bg-indigo-900/50 text-indigo-300 border-indigo-700/50">{r.strategy}</Badge>
              </div>
            </div>
            <ConfBar value={r.confidence} />
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div><p className="text-slate-500">Entry</p><p className="font-mono text-slate-200">₹{fmt(r.entry, 2)}</p></div>
              <div><p className="text-slate-500">Target</p><p className="font-mono text-emerald-400">₹{fmt(r.target, 2)}</p></div>
              <div><p className="text-slate-500">Stop Loss</p><p className="font-mono text-rose-400">₹{fmt(r.stop_loss, 2)}</p></div>
              <div><p className="text-slate-500">Exp Return</p><p className={`font-mono font-bold ${pnlCls(r.expected_return)}`}>{(r.expected_return ?? 0).toFixed(2)}%</p></div>
              <div><p className="text-slate-500">Hold Time</p><p className="text-slate-300">{r.estimated_holding}</p></div>
            </div>
            {r.reasoning && <p className="text-xs text-slate-500 line-clamp-2">{r.reasoning}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S7 — Today's Closed Trades
// ══════════════════════════════════════════════════════════════════════════════

function S7ClosedTrades({ data, loading }: { data?: unknown; loading: boolean }) {
  const list = toArr<ClosedPosition>(data);
  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <SecTitle icon={Trophy} title={`Today's Closed Trades (${list.length})`} color="text-emerald-400" />
      {loading && <SkeletonRows n={3} />}
      {!loading && list.length === 0 && (
        <p className="text-xs text-slate-500 text-center py-6">No closed trades today</p>
      )}
      {list.length > 0 && (
        <div className="overflow-x-auto -mx-1 px-1">
          <table className="w-full text-xs whitespace-nowrap">
            <thead>
              <tr className="border-b border-slate-800/60">
                {["Stock","Buy Time","Sell Time","Entry","Exit","Qty","P/L","Return","Exit Reason","Strategy","Lesson"].map(h => (
                  <th key={h} className="pb-2 pr-3 text-left text-slate-500 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((c, i) => (
                <tr key={`${c.symbol}-${i}`} className="border-b border-slate-800/30 hover:bg-slate-800/20">
                  <td className="py-2 pr-3 font-bold text-slate-100">{c.symbol}</td>
                  <td className="py-2 pr-3 text-slate-400">{istDateTime(c.buy_time)}</td>
                  <td className="py-2 pr-3 text-slate-400">{istDateTime(c.sell_time)}</td>
                  <td className="py-2 pr-3 font-mono">₹{fmt(c.entry_price, 2)}</td>
                  <td className="py-2 pr-3 font-mono">₹{fmt(c.exit_price, 2)}</td>
                  <td className="py-2 pr-3 font-mono">{c.quantity}</td>
                  <td className={`py-2 pr-3 font-mono font-bold ${pnlCls(c.pnl)}`}>{fmtK(c.pnl)}</td>
                  <td className={`py-2 pr-3 font-mono font-bold ${pnlCls(c.pnl_pct)}`}>{(c.pnl_pct ?? 0).toFixed(2)}%</td>
                  <td className="py-2 pr-3 text-slate-400">{c.exit_reason}</td>
                  <td className="py-2 pr-3 text-violet-300">{c.strategy}</td>
                  <td className="py-2 pr-3 text-slate-500 max-w-[180px] truncate">{c.lesson_learned || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S8 — AI Performance
// ══════════════════════════════════════════════════════════════════════════════

function S8AIPerf() {
  const { data, isLoading } = useQuery<AIPerf>({
    queryKey: ["apt", "ai-perf"],
    queryFn: () => apiJson("/phase11/ai-performance"),
    refetchInterval: 60_000, staleTime: 30_000, retry: 1,
  });
  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <SecTitle icon={BarChart2} title="AI Performance" color="text-violet-400" />
      {isLoading && <SkeletonRows n={2} />}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <Kpi label="Trades Analysed" value={data.trades_analysed ?? "—"} />
          <Kpi label="Trades Executed" value={data.trades_executed ?? "—"} />
          <Kpi label="Win Rate" hi
            value={<span className={(data.win_rate ?? 0) >= 60 ? "text-emerald-400" : "text-amber-400"}>
              {(data.win_rate ?? 0).toFixed(1)}%
            </span>}
          />
          <Kpi label="Avg Gain"    value={<span className="text-emerald-400">{fmtK(data.avg_gain)}</span>} />
          <Kpi label="Avg Loss"    value={<span className="text-rose-400">{fmtK(data.avg_loss)}</span>} />
          <Kpi label="Avg Hold"    value={data.avg_holding_label ?? "—"} />
          <Kpi label="Profit Factor"
            value={(data.profit_factor ?? 0).toFixed(2)}
            color={(data.profit_factor ?? 0) >= 1.5 ? "text-emerald-400" : "text-amber-400"}
          />
          <Kpi label="Rec Accuracy"
            value={<span className={(data.recommendation_accuracy ?? 0) >= 60 ? "text-emerald-400" : "text-amber-400"}>
              {(data.recommendation_accuracy ?? 0).toFixed(1)}%
            </span>}
          />
          <Kpi label="Best Strategy"  value={<span className="text-violet-300">{data.best_strategy  || "—"}</span>} />
          <Kpi label="Worst Strategy" value={<span className="text-rose-300">{data.worst_strategy || "—"}</span>} />
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S9 — Charts
// ══════════════════════════════════════════════════════════════════════════════

const PIE_COLORS = ["#6366F1","#14B8A6","#F59E0B","#EF4444","#10B981","#3B82F6"];

function S9Charts({ portfolio }: { portfolio?: Portfolio }) {
  const { data: tl } = useQuery<{ events: TimelineEvent[] }>({
    queryKey: ["apt", "tl-charts"],
    queryFn: () => apiJson("/phase11/timeline?limit=200"),
    refetchInterval: 60_000, staleTime: 30_000, retry: 1,
  });

  const tradeEv = (tl?.events ?? [])
    .filter(e => ["BUY","SELL","EXIT","PARTIAL_EXIT"].includes(e.type) && e.pnl != null)
    .map(e => ({ time: istTime(e.ts), pnl: e.pnl ?? 0, type: e.type }));

  let cum = 0;
  const cumLine = tradeEv.map(e => { cum += e.pnl; return { time: e.time, cumPnl: cum }; });

  let peak = 0;
  const ddLine = cumLine.map(p => {
    if (p.cumPnl > peak) peak = p.cumPnl;
    return { time: p.time, dd: peak > 0 ? Math.min(0, ((p.cumPnl - peak) / peak) * 100) : 0 };
  });

  const alloc = [
    { name: "Cash",     value: portfolio?.cash ?? 0 },
    { name: "Invested", value: portfolio?.invested_amount ?? 0 },
  ].filter(d => d.value > 0);

  const noData = <p className="text-xs text-slate-500 text-center py-10">No trade data yet — run a scan</p>;
  const ttStyle = { background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 11 };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Cumulative P/L</p>
        {cumLine.length === 0 ? noData : (
          <ResponsiveContainer width="100%" height={190}>
            <AreaChart data={cumLine} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
              <defs><linearGradient id="pnlG" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#10B981" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
              </linearGradient></defs>
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
              <Tooltip contentStyle={ttStyle} />
              <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
              <Area type="monotone" dataKey="cumPnl" stroke="#10B981" fill="url(#pnlG)" strokeWidth={2} dot={false} name="P/L ₹" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Trade Distribution</p>
        {tradeEv.length === 0 ? noData : (
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={tradeEv.slice(-25)} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
              <Tooltip contentStyle={ttStyle} />
              <ReferenceLine y={0} stroke="#475569" />
              <Bar dataKey="pnl" radius={[3, 3, 0, 0]} name="P/L ₹">
                {tradeEv.slice(-25).map((e, i) => (
                  <Cell key={i} fill={e.pnl >= 0 ? "#10B981" : "#EF4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Capital Allocation</p>
        {alloc.length === 0 ? noData : (
          <ResponsiveContainer width="100%" height={190}>
            <RechartsPie>
              <Pie data={alloc} cx="50%" cy="50%" outerRadius={72} innerRadius={38}
                dataKey="value" nameKey="name"
                label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
                labelLine fontSize={10}>
                {alloc.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={ttStyle} formatter={(v: number) => fmtK(v)} />
            </RechartsPie>
          </ResponsiveContainer>
        )}
      </div>

      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Portfolio Drawdown</p>
        {ddLine.length === 0 ? noData : (
          <ResponsiveContainer width="100%" height={190}>
            <AreaChart data={ddLine} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
              <defs><linearGradient id="ddG" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#EF4444" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
              </linearGradient></defs>
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
              <Tooltip contentStyle={ttStyle} formatter={(v: number) => [`${v.toFixed(2)}%`, "Drawdown"]} />
              <ReferenceLine y={0} stroke="#475569" />
              <Area type="monotone" dataKey="dd" stroke="#EF4444" fill="url(#ddG)" strokeWidth={2} dot={false} name="Drawdown %" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S10 — Date History
// ══════════════════════════════════════════════════════════════════════════════

const MONTHS = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];
const DAYS_SHORT = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

function S10DateHistory() {
  const n = new Date();
  const [year,  setYear]  = useState(n.getFullYear());
  const [month, setMonth] = useState(n.getMonth() + 1);
  const [sel,   setSel]   = useState<string | null>(null);

  const { data: cal, isLoading: calLoad } = useQuery<{
    days: CalendarDay[]; trading_days: number; total_pnl: number; total_trades: number;
  }>({
    queryKey: ["apt", "cal", year, month],
    queryFn:  () => apiJson(`/phase11/calendar?year=${year}&month=${month}`),
    staleTime: 120_000, retry: 1,
  });

  const { data: sum, isLoading: sumLoad } = useQuery<DailySummary>({
    queryKey: ["apt", "dsum", sel],
    queryFn:  () => apiJson(`/phase11/daily-summary?date=${sel}`),
    enabled:  !!sel, staleTime: 120_000, retry: 1,
  });

  const days = cal?.days ?? [];
  const pad  = Array(days[0]?.weekday ?? 0).fill(null);
  const prev = () => month === 1  ? (setYear(y => y - 1), setMonth(12)) : setMonth(m => m - 1);
  const next = () => month === 12 ? (setYear(y => y + 1), setMonth(1))  : setMonth(m => m + 1);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <button onClick={prev} className="p-1 text-slate-400 hover:text-slate-200"><ChevronLeft className="w-4 h-4" /></button>
          <span className="font-semibold text-slate-200">{MONTHS[month - 1]} {year}</span>
          <button onClick={next} className="p-1 text-slate-400 hover:text-slate-200"><ChevronRight className="w-4 h-4" /></button>
        </div>
        <div className="grid grid-cols-7 gap-0.5 mb-1">
          {DAYS_SHORT.map(d => <div key={d} className="text-center text-xs text-slate-600 font-medium py-1">{d}</div>)}
        </div>
        {calLoad && <SkeletonRows n={5} />}
        {!calLoad && (
          <div className="grid grid-cols-7 gap-0.5">
            {pad.map((_, i) => <div key={`p${i}`} />)}
            {days.map(day => {
              let cls = "rounded-lg p-1 text-center text-xs cursor-pointer transition-all ";
              if (sel === day.date)              cls += "ring-2 ring-teal-400 ";
              if (day.outcome === "WIN")         cls += "bg-emerald-950/50 text-emerald-300 ring-1 ring-emerald-600/50";
              else if (day.outcome === "LOSS")   cls += "bg-rose-950/50    text-rose-300    ring-1 ring-rose-600/50";
              else if (day.has_trades)           cls += "bg-amber-950/30   text-amber-300   ring-1 ring-amber-600/50";
              else if (day.weekday >= 5)         cls += "bg-slate-900/20 text-slate-700";
              else                               cls += "bg-slate-900/40 text-slate-500 hover:bg-slate-800/40";
              return (
                <div key={day.date} className={cls} onClick={() => setSel(day.date)}>
                  <div className="font-bold">{parseInt(day.date.slice(-2))}</div>
                  {day.has_trades && <div style={{ fontSize: 8 }} className="font-mono truncate">{fmtK(day.pnl)}</div>}
                </div>
              );
            })}
          </div>
        )}
        {cal && (
          <p className="text-xs text-slate-600 mt-3">
            {cal.trading_days} days · {cal.total_trades} trades ·{" "}
            <span className={pnlCls(cal.total_pnl)}>{fmtK(cal.total_pnl)} P/L</span>
          </p>
        )}
      </div>

      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4 overflow-y-auto" style={{ maxHeight: 520 }}>
        {!sel && <p className="text-xs text-slate-500 text-center py-14">← Click a trading day to drill down</p>}
        {sel && sumLoad && <SkeletonRows n={5} />}
        {sel && sum && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-slate-100">{sum.date}</h3>
              <button onClick={() => setSel(null)} className="text-slate-600 hover:text-slate-400 text-xs px-2">✕</button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Kpi label="Trades"   value={sum.summary?.total_trades ?? "—"} />
              <Kpi label="P/L"      value={<span className={pnlCls(sum.summary?.total_pnl ?? 0)}>{fmtK(sum.summary?.total_pnl ?? 0)}</span>} />
              <Kpi label="Win Rate" value={`${(sum.summary?.win_rate ?? 0).toFixed(0)}%`}
                color={(sum.summary?.win_rate ?? 0) >= 60 ? "text-emerald-400" : "text-amber-400"} />
            </div>
            {sum.best_trade && (
              <div className="text-xs bg-emerald-950/30 border border-emerald-800/40 rounded-lg px-3 py-2">
                <span className="text-emerald-400 font-bold">Best: </span>
                <span className="font-bold text-slate-200">{sum.best_trade.symbol}</span>
                <span className={`ml-2 font-mono ${pnlCls(sum.best_trade.pnl)}`}>{fmtK(sum.best_trade.pnl)}</span>
                <span className="ml-2 text-slate-500">{sum.best_trade.strategy}</span>
              </div>
            )}
            {sum.worst_trade && (
              <div className="text-xs bg-rose-950/30 border border-rose-800/40 rounded-lg px-3 py-2">
                <span className="text-rose-400 font-bold">Worst: </span>
                <span className="font-bold text-slate-200">{sum.worst_trade.symbol}</span>
                <span className={`ml-2 font-mono ${pnlCls(sum.worst_trade.pnl)}`}>{fmtK(sum.worst_trade.pnl)}</span>
                <span className="ml-2 text-slate-500">{sum.worst_trade.strategy}</span>
              </div>
            )}
            {sum.closed_trades?.length > 0 && (
              <div>
                <p className="text-xs text-slate-500 font-semibold uppercase tracking-wide mb-1.5">Trades</p>
                <div className="space-y-1">
                  {sum.closed_trades.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs border-b border-slate-800/40 pb-1">
                      <span className="font-bold w-16 text-slate-200">{t.symbol}</span>
                      <span className="text-slate-500 flex-1">{t.strategy}</span>
                      <span className={`font-mono font-bold ${pnlCls(t.pnl)}`}>{fmtK(t.pnl)}</span>
                      <span className="text-slate-600 text-xs">{t.exit_reason}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {sum.timeline?.length > 0 && (
              <div>
                <p className="text-xs text-slate-500 font-semibold uppercase tracking-wide mb-1.5">Timeline</p>
                <div className="space-y-1 max-h-44 overflow-y-auto">
                  {sum.timeline.slice(0, 15).map((e, i) => (
                    <div key={i} className={`text-xs flex items-center gap-2 rounded px-2 py-1 ${evCls(e.type, e.category)}`}>
                      <span className="font-mono text-slate-500 w-10 flex-shrink-0">{istTime(e.ts)}</span>
                      <span>{e.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S11 — Session Replay
// ══════════════════════════════════════════════════════════════════════════════

function S11Replay() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [step, setStep] = useState(0);
  const [play, setPlay] = useState(false);
  const iRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { data, isLoading } = useQuery<ReplayData>({
    queryKey: ["apt", "replay", date],
    queryFn:  () => apiJson(`/phase11/replay?date=${date}`),
    staleTime: 300_000, enabled: !!date, retry: 1,
  });

  const snaps = data?.trade_snapshots ?? [];
  const cur   = snaps[step] ?? null;
  const chart = snaps.slice(0, step + 1).map(s => ({
    time: istTime(s.ts), val: s.portfolio_value, pnl: s.cumulative_pnl,
  }));

  useEffect(() => { if (data) setStep(0); }, [data]);

  useEffect(() => {
    if (play) {
      iRef.current = setInterval(() => {
        setStep(s => {
          if (s >= snaps.length - 1) { setPlay(false); return s; }
          return s + 1;
        });
      }, 700);
    } else if (iRef.current) {
      clearInterval(iRef.current);
    }
    return () => { if (iRef.current) clearInterval(iRef.current); };
  }, [play, snaps.length]);

  const ttStyle = { background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 11 };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <input type="date" value={date}
          onChange={e => { setDate(e.target.value); setPlay(false); }}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-teal-500" />
        <div className="flex items-center gap-1.5">
          <button onClick={() => setStep(0)} disabled={!snaps.length}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-40">
            <SkipBack className="w-4 h-4" /></button>
          <button onClick={() => setStep(s => Math.max(0, s - 1))} disabled={step === 0}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-40">
            <ChevronLeft className="w-4 h-4" /></button>
          <button onClick={() => setPlay(p => !p)} disabled={!snaps.length}
            className="p-2 rounded-lg bg-teal-700 hover:bg-teal-600 text-white disabled:opacity-40">
            {play ? <PauseCircle className="w-5 h-5" /> : <PlayCircle className="w-5 h-5" />}
          </button>
          <button onClick={() => setStep(s => Math.min(snaps.length - 1, s + 1))}
            disabled={step >= snaps.length - 1}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-40">
            <ChevronRight className="w-4 h-4" /></button>
          <button onClick={() => setStep(snaps.length - 1)} disabled={!snaps.length}
            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 disabled:opacity-40">
            <SkipForward className="w-4 h-4" /></button>
        </div>
        {snaps.length > 0 && <span className="text-xs text-slate-500">Step {step + 1} / {snaps.length}</span>}
      </div>

      {isLoading && <SkeletonRows n={4} />}
      {!isLoading && snaps.length === 0 && <p className="text-xs text-slate-500 text-center py-8">No replay data for {date}</p>}

      {cur && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Kpi label="Time"      value={istTime(cur.ts)} />
          <Kpi label="Action"    value={
            <Badge className={`text-xs ${cur.action === "BUY" ? "bg-emerald-900/50 text-emerald-300" : "bg-rose-900/50 text-rose-300"}`}>
              {cur.action} {cur.symbol}
            </Badge>
          } />
          <Kpi label="Portfolio" value={fmtK(cur.portfolio_value)} hi />
          <Kpi label="Cum P/L"   value={<span className={pnlCls(cur.cumulative_pnl)}>{fmtK(cur.cumulative_pnl)}</span>} />
        </div>
      )}

      {chart.length > 0 && (
        <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 mb-2">Portfolio value — step {step + 1}</p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chart} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 10, fill: "#64748b" }} />
              <Tooltip contentStyle={ttStyle} />
              <ReferenceLine y={snaps[0]?.portfolio_value ?? 0} stroke="#475569" strokeDasharray="3 3" />
              <Line type="monotone" dataKey="val" stroke="#14B8A6" strokeWidth={2}
                dot={{ r: 3, fill: "#14B8A6" }} activeDot={{ r: 5 }} name="Portfolio ₹" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {(data?.ai_decisions?.length ?? 0) > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-slate-500 font-semibold uppercase tracking-wide">AI Decisions</p>
          {data!.ai_decisions.slice(0, 6).map((d, i) => (
            <div key={i} className="flex items-center gap-3 text-xs bg-indigo-950/30 border border-indigo-800/30 rounded-lg px-3 py-2">
              <span className="font-bold text-slate-200 w-16">{d.symbol}</span>
              <Badge className="text-xs bg-indigo-900/50 text-indigo-300 border-indigo-700/50">{d.decision}</Badge>
              <div className="flex-1"><ConfBar value={d.confidence} /></div>
              <span className="text-slate-500">{istTime(d.ts)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// S12 — Capital Reset
// ══════════════════════════════════════════════════════════════════════════════

function S12Capital() {
  const { data: cfg, isLoading: cfgLoad } = useQuery<CapitalConfig>({
    queryKey: ["apt", "cap-cfg"],
    queryFn:  () => apiJson("/phase11/capital/config"),
    staleTime: 120_000, retry: 1,
  });
  const { data: tops, isLoading: topLoad } = useQuery<unknown>({
    queryKey: ["apt", "cap-tops"],
    queryFn:  () => apiJson("/phase11/capital/topups"),
    staleTime: 120_000, retry: 1,
  });
  const topList = toArr<TopupEntry>(tops);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
        <SecTitle icon={RotateCcw} title="Capital Configuration" />
        {cfgLoad && <SkeletonRows n={3} />}
        {cfg && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Kpi label="Current Capital"  value={fmtK(cfg.current_capital)} hi />
              <Kpi label="Starting Capital" value={fmtK(cfg.starting_capital)} />
              <Kpi label="Mode"             value={<span className="text-violet-300">{cfg.capital_mode_label ?? cfg.capital_mode}</span>} />
              <Kpi label="Last Reset"       value={cfg.last_reset_date ?? "Never"} />
            </div>
            <div className="flex gap-2 items-start text-xs text-slate-500 p-3 bg-amber-950/20 border border-amber-800/30 rounded-lg">
              <Info className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              <span>Capital resets are logged with date, time, reason and amount. Paper money only — no real funds.</span>
            </div>
          </div>
        )}
      </div>

      <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
        <SecTitle icon={PieChart} title="Reset / Top-up History" />
        {topLoad && <SkeletonRows n={4} />}
        {!topLoad && topList.length === 0 && <p className="text-xs text-slate-500 text-center py-8">No capital events yet</p>}
        {topList.length > 0 && (
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {topList.map((t, i) => (
              <div key={i} className="flex items-center gap-2 text-xs border-b border-slate-800/40 pb-1.5">
                <span className="text-slate-400 w-20 flex-shrink-0">{t.date}</span>
                <Badge className={`text-xs px-1.5 py-0 ${t.type === "RESET" ? "bg-rose-900/50 text-rose-300" : "bg-teal-900/50 text-teal-300"}`}>
                  {t.type}
                </Badge>
                <span className={`font-mono font-bold ${pnlCls(t.amount)}`}>{fmtK(t.amount)}</span>
                <span className="text-slate-500 flex-1 truncate">{t.reason}</span>
                <span className="font-mono text-slate-400 flex-shrink-0">{fmtK(t.balance_after)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Page
// ══════════════════════════════════════════════════════════════════════════════

const BOTTOM_TABS = [
  { id: "charts",   label: "📊 Charts",       icon: BarChart2 },
  { id: "calendar", label: "📅 Date History",  icon: CalendarDays },
  { id: "replay",   label: "⏯  Replay",        icon: PlayCircle },
  { id: "capital",  label: "💰 Capital",        icon: RotateCcw },
] as const;
type BTab = typeof BOTTOM_TABS[number]["id"];

export default function AIPaperTraderPage() {
  const [btab, setBtab] = useState<BTab>("charts");

  const { data: portfolio, isLoading: portLoad } = useQuery<Portfolio>({
    queryKey: ["apt", "portfolio"],
    queryFn:  () => apiJson("/phase11/portfolio"),
    refetchInterval: 30_000, staleTime: 15_000, retry: 1,
  });
  const { data: recs, isLoading: recsLoad } = useQuery<RecsData>({
    queryKey: ["apt", "recs"],
    queryFn:  () => apiJson("/phase11/recommendations"),
    refetchInterval: 60_000, staleTime: 30_000, retry: 1,
  });
  const { data: closedPos, isLoading: closedLoad } = useQuery<unknown>({
    queryKey: ["apt", "closed-pos"],
    queryFn:  () => apiJson("/phase11/portfolio/closed-positions?limit=20"),
    refetchInterval: 60_000, staleTime: 30_000, retry: 1,
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">

      {/* ── Safety banner ── */}
      <div className="sticky top-0 z-40 bg-indigo-950/95 border-b border-indigo-800/50 backdrop-blur-sm px-4 py-2.5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <span className="text-xl select-none">🤖</span>
          <h1 className="font-bold text-base tracking-tight text-slate-100">AI Paper Trader</h1>
          <Badge className="text-xs bg-indigo-900/70 text-indigo-200 border-indigo-700/50 px-2">Phase 11</Badge>
          <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-indigo-950/60 text-indigo-300 border border-indigo-700/50">
            📄 PAPER ONLY
          </span>
        </div>
        <span className="hidden md:block text-xs text-indigo-400">
          READ-ONLY · ADVISORY ONLY · No live broker orders · No real money
        </span>
      </div>

      <div className="max-w-screen-2xl mx-auto px-4 py-4 space-y-4">

        {/* S0 — Autonomous Session Status */}
        <S0AutonomousSession />

        {/* Pipeline Funnel — shows stocks→signals→gates→orders at a glance */}
        <SPipelineStats />

        {/* S1 */}
        <S1MarketStatus />

        {/* S2 + S3 */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <div className="xl:col-span-2"><S2Portfolio data={portfolio} loading={portLoad} /></div>
          <S3AIStatus portfolio={portfolio} recs={recs} />
        </div>

        {/* S4 */}
        <S4Holdings />

        {/* S5 + S6 */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <S5ActivityFeed />
          <S6RecQueue data={recs} loading={recsLoad} />
        </div>

        {/* S7 */}
        <S7ClosedTrades data={closedPos} loading={closedLoad} />

        {/* S8 */}
        <S8AIPerf />

        {/* S9–S12 tabbed */}
        <div className="bg-slate-900/40 border border-slate-800/50 rounded-xl overflow-hidden">
          <div className="flex border-b border-slate-800/50 overflow-x-auto">
            {BOTTOM_TABS.map(t => (
              <button key={t.id} onClick={() => setBtab(t.id)}
                className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 ${
                  btab === t.id
                    ? "border-teal-500 text-teal-300 bg-teal-950/20"
                    : "border-transparent text-slate-500 hover:text-slate-300 hover:bg-slate-800/30"
                }`}>
                <t.icon className="w-3.5 h-3.5" />
                {t.label}
              </button>
            ))}
          </div>
          <div className="p-4">
            {btab === "charts"   && <S9Charts   portfolio={portfolio} />}
            {btab === "calendar" && <S10DateHistory />}
            {btab === "replay"   && <S11Replay />}
            {btab === "capital"  && <S12Capital />}
          </div>
        </div>

        <p className="text-center text-xs text-slate-700 pb-4">
          🤖 ApexQuant AI Paper Trader · Phase 11 · Paper only · No real money · No live orders
        </p>
      </div>
    </div>
  );
}
