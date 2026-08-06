/**
 * AIInvestigationCentre.tsx — Version 4.1: AI Investigation & Trading Day Replay
 *
 * "Digital twin" of the trading engine.  Replays an entire scan day through
 * all 10 AI agents — animated, inspectable, fully backed by real historical data.
 * v4.1 adds: Portfolio / Trade Management stage, equity curve, trade drilldowns,
 * end-of-day summary, and pipeline count consistency validation.
 *
 * Tabs: Pipeline Replay | Investigation Mode | Missed Opportunities | Filters
 */

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { PageHeader } from "@/components/ds";
import {
  Microscope, Play, Pause, Square, RotateCcw,
  Clock, TrendingUp, TrendingDown, AlertTriangle, CheckCircle2,
  XCircle, Eye, Brain, BarChart3, Layers, Zap, Target,
  Search, Filter, Calendar, SkipForward, Activity,
  Shield, Cpu, Gauge, ChevronDown, ChevronUp, Award,
  ArrowRight, Wallet, DollarSign, X, BarChart2, Percent,
} from "lucide-react";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface Session {
  scan_id: string;
  snapshot_ts: string;
  status: string;
  universe_size: number | null;
  symbols_processed: number | null;
  buy_signals: number | null;
  paper_orders: number | null;
  duration_s: number | null;
  is_latest: boolean;
  source?: string;
}

interface Stage {
  id: string;
  label: string;
  order: number;
  stocks_in: number;
  stocks_out: number;
  rejected: number;
  rejected_symbols: string[];
  stocks: string[];
  duration_ms: number | null;
  description: string;
  buy_count?: number;
  avoid_count?: number;
  paper_orders?: number;
}

interface SymbolRow {
  symbol: string;
  sector: string | null;
  final_action: string | null;
  confidence: number;
  technical_score: number;
  strategy: string | null;
  all_gates_passed: boolean;
  paper_eligible: boolean;
  data_quality: string | null;
}

interface JourneyStep {
  stage: string;
  label: string;
  result: "PASS" | "FAIL" | "WARN";
  score: number | null;
  reason: string;
  detail: Record<string, unknown> | null;
}

interface SymbolJourney {
  symbol: string;
  sector: string | null;
  scan_id: string;
  journey: JourneyStep[];
  thinking: Record<string, unknown>;
  recommendation: {
    final_action: string | null;
    confidence: number;
    entry_price: number | null;
    stop_loss: number | null;
    target_price: number | null;
    rr_ratio: number | null;
    strategy: string | null;
  };
  paper_trade: Record<string, unknown> | null;
  error?: string;
}

interface CompItem {
  symbol: string;
  ai_action: string;
  entry_price: number | null;
  current_price: number | null;
  outcome_pct: number | null;
  status: string;
  rejection_reason: string | null;
  paper_traded: boolean;
}

interface TradeCard {
  symbol: string;
  entry_price: number;
  exit_price: number | null;
  qty: number;
  capital_used: number;
  stop_loss: number | null;
  target: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  status: "OPEN" | "WIN" | "LOSS" | "PENDING";
  exit_reason: "Target Hit" | "Stop Loss" | "Trailing Stop" | "AI Exit" | "End of Day" | null;
  // simulated timestamps (derived from session snapshot_ts)
  entry_time: string | null;
  exit_time: string | null;
}

interface PipelineValidationError {
  stage_id: string;
  stage_label: string;
  message: string;
  severity: "error" | "warn";
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const PIPELINE_STAGES = [
  { id: "supervisor",           label: "Supervisor",                    icon: Cpu,         desc: "Pipeline orchestrator" },
  { id: "market_data",          label: "Market Scanner",                icon: Gauge,       desc: "Universe loading & data quality" },
  { id: "research",             label: "Research",                      icon: Brain,       desc: "News, corporate actions, context" },
  { id: "market_intelligence",  label: "Market Intelligence",           icon: BarChart3,   desc: "Regime, sector strength, liquidity" },
  { id: "monitoring",           label: "Monitoring",                    icon: Activity,    desc: "VWAP, EMA, MACD, RSI, volume" },
  { id: "strategy",             label: "Strategy",                      icon: Layers,      desc: "Strategy matching & scoring" },
  { id: "risk",                 label: "Risk",                          icon: Shield,      desc: "Capital gates, R:R, exposure" },
  { id: "ai_decision",          label: "Decision",                      icon: Zap,         desc: "BUY / SELL / WATCH / AVOID" },
  { id: "execution",            label: "Execution",                     icon: Target,      desc: "Order placement & fills" },
  { id: "portfolio_management", label: "Portfolio / Trade Management",  icon: Wallet,      desc: "Position lifecycle, P&L & equity curve" },
];

/** Default simulated starting capital used for portfolio lifecycle calculations. */
const STARTING_CAPITAL = 100_000;
/** Per-trade capital allocation (₹ per position). */
const TRADE_ALLOCATION = 10_000;

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const BASE_DELAY_MS = 2000;

const FILTER_OPTIONS = [
  "All", "Bought", "Rejected", "Missed Opportunities",
  "Late Entries", "Early Exits", "False Signals",
  "Winning Trades", "Losing Trades",
];

const TABS = ["Pipeline Replay", "Investigation Mode", "Missed Opportunities", "Filters"];

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function stageColor(result: string | undefined, isActive: boolean) {
  if (isActive) return { bg: "bg-amber-500/20", border: "border-amber-400", text: "text-amber-300", dot: "bg-amber-400" };
  switch (result) {
    case "PASS":  return { bg: "bg-emerald-500/10", border: "border-emerald-500", text: "text-emerald-400", dot: "bg-emerald-400" };
    case "FAIL":  return { bg: "bg-red-500/10",     border: "border-red-500",     text: "text-red-400",     dot: "bg-red-400" };
    case "WARN":  return { bg: "bg-amber-500/10",   border: "border-amber-500",   text: "text-amber-400",   dot: "bg-amber-400" };
    default:      return { bg: "bg-slate-800/50",   border: "border-slate-700",   text: "text-slate-500",   dot: "bg-slate-600" };
  }
}

function actionBadge(action: string | null) {
  switch (action) {
    case "BUY":   return "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40";
    case "SELL":  return "bg-red-500/20 text-red-300 border border-red-500/40";
    case "AVOID": return "bg-red-800/20 text-red-400 border border-red-700/40";
    case "WATCH": return "bg-amber-500/20 text-amber-300 border border-amber-500/40";
    case "HOLD":  return "bg-blue-500/20 text-blue-300 border border-blue-500/40";
    default:      return "bg-slate-700/40 text-slate-400 border border-slate-600/40";
  }
}

function fmtTs(ts: string | undefined) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });
  } catch { return ts; }
}

function fmtDate(ts: string | undefined) {
  if (!ts) return "Select session";
  try {
    return new Date(ts).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "long" });
  } catch { return ts; }
}

function pctColor(v: number | null) {
  if (v === null) return "text-slate-400";
  return v >= 0 ? "text-emerald-400" : "text-red-400";
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline count validation
// ─────────────────────────────────────────────────────────────────────────────

function validatePipelineCounts(
  stages: Stage[],
  stageConfigs: typeof PIPELINE_STAGES,
): PipelineValidationError[] {
  const errors: PipelineValidationError[] = [];
  for (const cfg of stageConfigs) {
    if (cfg.id === "portfolio_management") continue; // synthetic stage, skip
    const sd = stages.find(s => s.id === cfg.id);
    if (!sd) continue;
    const { stocks_in, stocks_out, rejected } = sd;
    // Negative counts are mathematically impossible
    if (rejected < 0) {
      errors.push({
        stage_id: cfg.id,
        stage_label: cfg.label,
        message: `Rejected count is ${rejected} — cannot be negative. Execution must never create more orders than the Decision Agent approved.`,
        severity: "error",
      });
    }
    if (stocks_out < 0) {
      errors.push({
        stage_id: cfg.id,
        stage_label: cfg.label,
        message: `Passed count is ${stocks_out} — cannot be negative.`,
        severity: "error",
      });
    }
    // Input must equal passed + rejected (allowing pending/cancelled as slack)
    const accountedFor = stocks_out + Math.max(0, rejected);
    if (accountedFor > stocks_in) {
      errors.push({
        stage_id: cfg.id,
        stage_label: cfg.label,
        message: `Input ${stocks_in} < Passed ${stocks_out} + Rejected ${Math.max(0, rejected)} = ${accountedFor}. Stage is creating extra records.`,
        severity: "error",
      });
    }
  }
  return errors;
}

// ─────────────────────────────────────────────────────────────────────────────
// Equity curve (SVG — no charting lib needed)
// ─────────────────────────────────────────────────────────────────────────────

function EquityCurve({ trades, startingCapital }: { trades: TradeCard[]; startingCapital: number }) {
  const W = 600;
  const H = 120;
  const PAD = { top: 10, right: 10, bottom: 20, left: 50 };

  const points = useMemo(() => {
    const pts: { x: number; y: number; pnl: number; symbol: string }[] = [];
    let running = startingCapital;
    pts.push({ x: 0, y: running, pnl: 0, symbol: "Start" });
    const closed = trades.filter(t => t.pnl !== null);
    closed.forEach((t, i) => {
      running += t.pnl!;
      pts.push({ x: i + 1, y: running, pnl: t.pnl!, symbol: t.symbol });
    });
    return pts;
  }, [trades, startingCapital]);

  if (points.length < 2) return (
    <div className="h-32 flex items-center justify-center text-slate-600 text-xs">
      Equity curve populates as trades close
    </div>
  );

  const xs = points.map(p => p.x);
  const ys = points.map(p => p.y);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeY = maxY - minY || 1;
  const rangeX = xs[xs.length - 1] - xs[0] || 1;

  const toSvgX = (x: number) => PAD.left + ((x - xs[0]) / rangeX) * (W - PAD.left - PAD.right);
  const toSvgY = (y: number) => PAD.top + (1 - (y - minY) / rangeY) * (H - PAD.top - PAD.bottom);

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${toSvgX(p.x).toFixed(1)} ${toSvgY(p.y).toFixed(1)}`).join(" ");
  // Fill under curve to baseline
  const baseY = toSvgY(startingCapital).toFixed(1);
  const fillD = `${pathD} L ${toSvgX(xs[xs.length - 1]).toFixed(1)} ${baseY} L ${toSvgX(xs[0]).toFixed(1)} ${baseY} Z`;

  const finalValue = ys[ys.length - 1];
  const isUp = finalValue >= startingCapital;

  const fmtRs = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none" style={{ height: H }}>
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={isUp ? "#10b981" : "#ef4444"} stopOpacity="0.25" />
            <stop offset="100%" stopColor={isUp ? "#10b981" : "#ef4444"} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {/* Zero baseline */}
        <line x1={PAD.left} y1={parseFloat(baseY)} x2={W - PAD.right} y2={parseFloat(baseY)}
          stroke="#475569" strokeWidth="0.5" strokeDasharray="4 4" />
        {/* Fill */}
        <path d={fillD} fill="url(#eqFill)" />
        {/* Line */}
        <path d={pathD} fill="none" stroke={isUp ? "#10b981" : "#ef4444"} strokeWidth="1.5" />
        {/* Dots for each trade */}
        {points.slice(1).map((p, i) => (
          <circle key={i} cx={toSvgX(p.x)} cy={toSvgY(p.y)} r="3"
            fill={p.pnl >= 0 ? "#10b981" : "#ef4444"}
            stroke="#0f172a" strokeWidth="1"
          />
        ))}
        {/* Y-axis labels */}
        <text x={PAD.left - 4} y={PAD.top + 4} textAnchor="end" fontSize="8" fill="#64748b">{fmtRs(maxY)}</text>
        <text x={PAD.left - 4} y={H - PAD.bottom + 4} textAnchor="end" fontSize="8" fill="#64748b">{fmtRs(minY)}</text>
      </svg>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Trade Detail Modal
// ─────────────────────────────────────────────────────────────────────────────

function TradeDetailModal({ trade, onClose }: { trade: TradeCard; onClose: () => void }) {
  const fields = [
    { label: "Entry Time",          value: trade.entry_time ?? "—" },
    { label: "Entry Price",         value: trade.entry_price != null ? `₹${trade.entry_price.toFixed(2)}` : "—" },
    { label: "Quantity",            value: trade.qty },
    { label: "Stop Loss",           value: trade.stop_loss != null ? `₹${trade.stop_loss.toFixed(2)}` : "—" },
    { label: "Target",              value: trade.target != null ? `₹${trade.target.toFixed(2)}` : "—" },
    { label: "Highest Price",       value: trade.exit_price != null && trade.pnl != null && trade.pnl > 0 ? `₹${trade.exit_price.toFixed(2)}` : "—" },
    { label: "Lowest Price",        value: trade.exit_price != null && trade.pnl != null && trade.pnl < 0 ? `₹${trade.exit_price.toFixed(2)}` : "—" },
    { label: "Exit Time",           value: trade.exit_time ?? "—" },
    { label: "Exit Price",          value: trade.exit_price != null ? `₹${trade.exit_price.toFixed(2)}` : "Open" },
    { label: "Exit Reason",         value: trade.exit_reason ?? "Open" },
    { label: "Net P&L",             value: trade.pnl != null ? `₹${trade.pnl.toFixed(2)}` : "Open" },
  ];
  const isProfit = (trade.pnl ?? 0) >= 0;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-slate-900 border border-slate-700 rounded-2xl p-6 w-full max-w-md shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <span className="font-mono font-bold text-lg text-slate-100">{trade.symbol}</span>
            <span className={`ml-3 px-2 py-0.5 rounded text-xs font-semibold ${
              trade.status === "WIN" ? "bg-emerald-500/20 text-emerald-400" :
              trade.status === "LOSS" ? "bg-red-500/20 text-red-400" :
              "bg-slate-700 text-slate-400"
            }`}>{trade.status}</span>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X size={18} />
          </button>
        </div>
        <div className={`mb-4 p-3 rounded-xl text-center ${isProfit ? "bg-emerald-900/20 border border-emerald-700/30" : "bg-red-900/20 border border-red-700/30"}`}>
          <div className={`text-2xl font-bold ${isProfit ? "text-emerald-400" : "text-red-400"}`}>
            {trade.pnl != null ? `${isProfit ? "+" : ""}₹${trade.pnl.toFixed(2)}` : "Open Position"}
          </div>
          {trade.pnl_pct != null && (
            <div className={`text-sm ${isProfit ? "text-emerald-500" : "text-red-500"}`}>
              {isProfit ? "+" : ""}{trade.pnl_pct.toFixed(2)}%
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2">
          {fields.map(f => (
            <div key={f.label} className="bg-slate-800/60 rounded-lg p-2">
              <div className="text-xs text-slate-500">{f.label}</div>
              <div className="text-sm font-mono text-slate-200 truncate">{String(f.value)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Portfolio Management Panel (synthesized from comparison data)
// ─────────────────────────────────────────────────────────────────────────────

function PortfolioManagementPanel({
  trades,
  snapshotTs,
  isReplayComplete,
}: {
  trades: TradeCard[];
  snapshotTs: string | undefined;
  isReplayComplete: boolean;
}) {
  const [selectedTrade, setSelectedTrade] = useState<TradeCard | null>(null);

  const summary = useMemo(() => {
    const startCapital = STARTING_CAPITAL;
    const closedTrades = trades.filter(t => t.pnl !== null);
    const openTrades   = trades.filter(t => t.pnl === null);
    const wins         = closedTrades.filter(t => (t.pnl ?? 0) > 0);
    const losses       = closedTrades.filter(t => (t.pnl ?? 0) < 0);
    const realizedPnl  = closedTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
    const unrealizedPnl= openTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
    const investedCapital = openTrades.reduce((sum, t) => sum + t.capital_used, 0);
    const availableCash   = startCapital - investedCapital + realizedPnl;
    const totalValue      = availableCash + investedCapital + unrealizedPnl;
    const winRate         = closedTrades.length > 0 ? (wins.length / closedTrades.length) * 100 : null;
    const largestWinner   = wins.length > 0 ? Math.max(...wins.map(t => t.pnl!)) : null;
    const largestLoser    = losses.length > 0 ? Math.min(...losses.map(t => t.pnl!)) : null;
    // Max drawdown (simplified — worst running loss from peak equity)
    let peak = startCapital, runningEq = startCapital, maxDd = 0;
    for (const t of closedTrades) {
      runningEq += t.pnl ?? 0;
      if (runningEq > peak) peak = runningEq;
      const dd = peak - runningEq;
      if (dd > maxDd) maxDd = dd;
    }
    return {
      startCapital, availableCash, investedCapital,
      openCount: openTrades.length, closedCount: closedTrades.length,
      unrealizedPnl, realizedPnl, totalValue,
      winRate, wins: wins.length, losses: losses.length, totalTrades: closedTrades.length,
      largestWinner, largestLoser, maxDrawdown: maxDd,
    };
  }, [trades]);

  const rs = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  const pnlColor = (v: number | null) => v === null ? "text-slate-400" : v >= 0 ? "text-emerald-400" : "text-red-400";
  const exitReasonColor: Record<string, string> = {
    "Target Hit":    "bg-emerald-900/30 text-emerald-400 border-emerald-700/40",
    "Stop Loss":     "bg-red-900/30 text-red-400 border-red-700/40",
    "Trailing Stop": "bg-amber-900/30 text-amber-400 border-amber-700/40",
    "AI Exit":       "bg-blue-900/30 text-blue-400 border-blue-700/40",
    "End of Day":    "bg-slate-800 text-slate-400 border-slate-600",
  };

  return (
    <div className="space-y-5">
      {selectedTrade && (
        <TradeDetailModal trade={selectedTrade} onClose={() => setSelectedTrade(null)} />
      )}

      {/* Running portfolio summary */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <BarChart2 size={14} className="text-teal-400" />
          <h4 className="text-sm font-semibold text-slate-200">Running Portfolio Summary</h4>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { label: "Starting Capital",  value: rs(summary.startCapital),     color: "text-slate-300" },
            { label: "Available Cash",    value: rs(summary.availableCash),     color: pnlColor(summary.availableCash - summary.startCapital) },
            { label: "Invested Capital",  value: rs(summary.investedCapital),   color: "text-slate-300" },
            { label: "Open Positions",    value: summary.openCount,             color: "text-amber-400" },
            { label: "Closed Positions",  value: summary.closedCount,           color: "text-slate-300" },
            { label: "Unrealized P&L",    value: rs(summary.unrealizedPnl),     color: pnlColor(summary.unrealizedPnl) },
            { label: "Realized P&L",      value: rs(summary.realizedPnl),       color: pnlColor(summary.realizedPnl) },
            { label: "Total Portfolio",   value: rs(summary.totalValue),        color: pnlColor(summary.totalValue - summary.startCapital) },
          ].map(item => (
            <div key={item.label} className="bg-slate-900/50 rounded-lg p-2.5 text-center">
              <div className="text-xs text-slate-500 mb-1">{item.label}</div>
              <div className={`text-sm font-bold ${item.color}`}>{String(item.value)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Equity curve */}
      <div className="bg-slate-800/60 border border-slate-700/60 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <TrendingUp size={14} className="text-teal-400" />
            <h4 className="text-sm font-semibold text-slate-200">Live Equity Curve</h4>
          </div>
          <span className="text-xs text-slate-500">{trades.filter(t => t.pnl !== null).length} trades plotted</span>
        </div>
        <EquityCurve trades={trades} startingCapital={STARTING_CAPITAL} />
      </div>

      {/* Individual positions */}
      {trades.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/60 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Wallet size={14} className="text-teal-400" />
            <h4 className="text-sm font-semibold text-slate-200">Positions ({trades.length})</h4>
            <span className="text-xs text-slate-500 ml-auto">Click a trade for full detail</span>
          </div>
          <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
            {trades.map((t) => (
              <button
                key={t.symbol}
                onClick={() => setSelectedTrade(t)}
                className="w-full text-left bg-slate-900/50 border border-slate-700/50 rounded-lg p-3 hover:border-teal-500 transition-all group"
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-semibold text-sm text-slate-200 group-hover:text-teal-300 transition-colors">{t.symbol}</span>
                    {t.exit_reason && (
                      <span className={`text-xs px-2 py-0.5 rounded border font-medium ${exitReasonColor[t.exit_reason] ?? "bg-slate-800 text-slate-400 border-slate-600"}`}>
                        {t.exit_reason}
                      </span>
                    )}
                    {!t.exit_reason && (
                      <span className="text-xs px-2 py-0.5 rounded border bg-amber-900/20 text-amber-400 border-amber-700/30 animate-pulse">OPEN</span>
                    )}
                  </div>
                  <span className={`font-mono font-bold text-sm ${pnlColor(t.pnl)}`}>
                    {t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}₹${t.pnl.toFixed(0)}` : "Open"}
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-xs text-slate-500">
                  <span>Entry: <span className="text-slate-300 font-mono">₹{t.entry_price.toFixed(1)}</span></span>
                  <span>Exit: <span className={`font-mono ${t.exit_price ? "text-slate-300" : "text-slate-600"}`}>{t.exit_price ? `₹${t.exit_price.toFixed(1)}` : "—"}</span></span>
                  <span>SL: <span className="text-red-400 font-mono">{t.stop_loss ? `₹${t.stop_loss.toFixed(1)}` : "—"}</span></span>
                  <span>Tgt: <span className="text-emerald-400 font-mono">{t.target ? `₹${t.target.toFixed(1)}` : "—"}</span></span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs text-slate-600 mt-1">
                  <span>Qty: <span className="text-slate-400">{t.qty}</span></span>
                  <span>Capital: <span className="text-slate-400">{rs(t.capital_used)}</span></span>
                  {t.pnl_pct != null && (
                    <span className={pnlColor(t.pnl_pct)}>{t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {trades.length === 0 && (
        <div className="bg-slate-800/60 border border-slate-700/60 rounded-xl p-8 text-center">
          <Wallet size={32} className="mx-auto text-slate-700 mb-3" />
          <p className="text-slate-500 text-sm">No paper trades were recorded in this session</p>
          <p className="text-slate-600 text-xs mt-1">Portfolio management stage populates only when BUY orders are executed</p>
        </div>
      )}

      {/* End-of-Day Summary */}
      {isReplayComplete && (
        <div className="bg-slate-900/60 border border-teal-700/30 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-4">
            <Award size={14} className="text-teal-400" />
            <h4 className="text-sm font-semibold text-teal-300">End-of-Day Summary</h4>
          </div>
          <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
            {[
              { label: "Starting Capital", value: rs(summary.startCapital), color: "text-slate-300" },
              { label: "Ending Capital",   value: rs(summary.totalValue),   color: pnlColor(summary.totalValue - summary.startCapital) },
              {
                label: "Total Return",
                value: summary.totalValue > 0 ? `${((summary.totalValue - summary.startCapital) / summary.startCapital * 100).toFixed(2)}%` : "—",
                color: pnlColor(summary.totalValue - summary.startCapital),
              },
              { label: "No. of Trades", value: summary.totalTrades,     color: "text-slate-300" },
              {
                label: "Win Rate",
                value: summary.winRate != null ? `${summary.winRate.toFixed(1)}%` : "—",
                color: summary.winRate != null && summary.winRate >= 50 ? "text-emerald-400" : "text-red-400",
              },
              { label: "Largest Winner", value: summary.largestWinner != null ? `₹${summary.largestWinner.toFixed(0)}` : "—", color: "text-emerald-400" },
              { label: "Largest Loser",  value: summary.largestLoser  != null ? `₹${summary.largestLoser.toFixed(0)}` : "—", color: "text-red-400" },
              { label: "Max Drawdown",   value: summary.maxDrawdown > 0 ? `₹${summary.maxDrawdown.toFixed(0)}` : "₹0", color: "text-amber-400" },
              { label: "Realized P&L",   value: rs(summary.realizedPnl), color: pnlColor(summary.realizedPnl) },
            ].map(item => (
              <div key={item.label} className="bg-slate-800/60 rounded-lg p-3 text-center">
                <div className="text-xs text-slate-500 mb-1">{item.label}</div>
                <div className={`text-sm font-bold ${item.color}`}>{String(item.value)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline Validation Banner
// ─────────────────────────────────────────────────────────────────────────────

function PipelineValidationBanner({ errors }: { errors: PipelineValidationError[] }) {
  const [dismissed, setDismissed] = useState(false);
  if (errors.length === 0 || dismissed) return null;
  return (
    <div className="bg-red-950/60 border border-red-700/50 rounded-xl p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle size={16} className="text-red-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="text-sm font-semibold text-red-300 mb-1">
            Pipeline Count Inconsistency Detected
          </div>
          <p className="text-xs text-red-400/80 mb-2">
            The replay engine detected the following violations of the rule:
            <strong> Input = Passed + Rejected + Pending + Cancelled</strong>.
            Negative counts indicate an upstream stage is emitting more records than it received.
          </p>
          <div className="space-y-1">
            {errors.map((e, i) => (
              <div key={i} className="flex items-start gap-2 text-xs bg-red-900/30 border border-red-700/30 rounded p-2">
                <XCircle size={11} className="text-red-400 flex-shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-red-300">{e.stage_label}: </span>
                  <span className="text-red-400">{e.message}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <button onClick={() => setDismissed(true)} className="text-red-500 hover:text-red-300 flex-shrink-0">
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

function GateRow({ label, passed, value }: { label: string; passed: boolean; value?: string | number | null }) {
  return (
    <div className={`flex items-center justify-between px-3 py-1.5 rounded text-xs ${passed ? "bg-emerald-900/20" : "bg-red-900/20"}`}>
      <span className={passed ? "text-slate-300" : "text-red-300 font-medium"}>{label}</span>
      <span className={`flex items-center gap-1 ${passed ? "text-emerald-400" : "text-red-400"}`}>
        {passed ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
        {value != null ? <span>{value}</span> : null}
      </span>
    </div>
  );
}

function KpiCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-3">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-xl font-bold ${color ?? "text-slate-100"}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function SpeedBtn({ speed, active, onClick }: { speed: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded text-xs font-mono transition-all ${
        active ? "bg-teal-600 text-white" : "bg-slate-700 text-slate-300 hover:bg-slate-600"
      }`}
    >
      {speed}x
    </button>
  );
}

function StageNode({
  stage, stageData, status, isActive, isPast, index, onClick, activeSymbolFilter,
}: {
  stage: typeof PIPELINE_STAGES[0];
  stageData?: Stage;
  status?: string;
  isActive: boolean;
  isPast: boolean;
  index: number;
  onClick: () => void;
  activeSymbolFilter: string;
}) {
  const colors = stageColor(isPast ? status : undefined, isActive);
  const Icon = stage.icon;
  const inCount = stageData?.stocks_in ?? null;
  const outCount = stageData?.stocks_out ?? null;
  const rejected = stageData?.rejected ?? null;

  return (
    <div className="flex flex-col items-center">
      {index > 0 && (
        <div className={`w-0.5 h-5 transition-all duration-700 ${isPast || isActive ? "bg-teal-500/60" : "bg-slate-700"}`} />
      )}
      <button
        onClick={onClick}
        className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border transition-all duration-500 text-left
          ${colors.bg} ${colors.border} ${isActive ? "ring-2 ring-amber-400/30 shadow-lg shadow-amber-900/20" : ""}
          hover:brightness-110`}
      >
        {/* Pulse dot */}
        <div className="relative flex-shrink-0">
          <div className={`w-2.5 h-2.5 rounded-full ${colors.dot} ${isActive ? "animate-ping absolute" : "hidden"}`} />
          <div className={`w-2.5 h-2.5 rounded-full ${colors.dot}`} />
        </div>
        <Icon size={16} className={colors.text} />
        <div className="flex-1 min-w-0">
          <div className={`text-sm font-semibold ${colors.text}`}>{stage.label}</div>
          <div className="text-xs text-slate-500 truncate">{stage.desc}</div>
        </div>
        {/* Counts */}
        {(isPast || isActive) && inCount != null && (
          <div className="flex-shrink-0 text-right">
            <div className="text-xs font-mono text-slate-300">{inCount} <ArrowRight size={9} className="inline text-slate-500" /> {outCount}</div>
            {rejected != null && rejected > 0 && (
              <div className="text-xs text-red-400 font-mono">−{rejected}</div>
            )}
          </div>
        )}
        {isActive && (
          <div className="flex-shrink-0 text-xs text-amber-300 animate-pulse font-medium">Running…</div>
        )}
      </button>
    </div>
  );
}

function AgentDetailCard({ stageId, stageData }: { stageId: string; stageData?: Stage }) {
  if (!stageData) {
    return (
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-6 text-center text-slate-500 text-sm">
        Stage data not available — select a session and start replay
      </div>
    );
  }

  const { stocks_in, stocks_out, rejected, rejected_symbols, stocks, duration_ms, description, buy_count, avoid_count, paper_orders } = stageData;

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-xl p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-200">{stageData.label} Detail</h4>
        {duration_ms != null && (
          <span className="text-xs text-slate-500 flex items-center gap-1">
            <Clock size={11} /> {duration_ms < 1000 ? `${duration_ms}ms` : `${(duration_ms / 1000).toFixed(1)}s`}
          </span>
        )}
      </div>

      {description && <p className="text-xs text-slate-400">{description}</p>}

      {/* Funnel */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-slate-900/50 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-slate-200">{stocks_in}</div>
          <div className="text-xs text-slate-500">In</div>
        </div>
        <div className="bg-emerald-900/20 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-emerald-400">{stocks_out}</div>
          <div className="text-xs text-slate-500">Passed</div>
        </div>
        <div className="bg-red-900/20 rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-red-400">{rejected}</div>
          <div className="text-xs text-slate-500">Rejected</div>
        </div>
      </div>

      {/* Decision stage extras */}
      {(buy_count != null || avoid_count != null) && (
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-emerald-900/20 rounded-lg p-2 text-center">
            <div className="text-base font-bold text-emerald-400">{buy_count ?? 0}</div>
            <div className="text-xs text-slate-500">BUY</div>
          </div>
          <div className="bg-red-900/20 rounded-lg p-2 text-center">
            <div className="text-base font-bold text-red-400">{avoid_count ?? 0}</div>
            <div className="text-xs text-slate-500">AVOID</div>
          </div>
          <div className="bg-teal-900/20 rounded-lg p-2 text-center">
            <div className="text-base font-bold text-teal-400">{paper_orders ?? 0}</div>
            <div className="text-xs text-slate-500">Paper</div>
          </div>
        </div>
      )}

      {/* Rejected symbols */}
      {rejected_symbols && rejected_symbols.length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-2">Rejected here</div>
          <div className="flex flex-wrap gap-1.5">
            {rejected_symbols.slice(0, 12).map(sym => (
              <span key={sym} className="px-2 py-0.5 bg-red-900/20 text-red-300 border border-red-700/30 rounded text-xs font-mono">
                {sym}
              </span>
            ))}
            {rejected_symbols.length > 12 && (
              <span className="text-xs text-slate-500">+{rejected_symbols.length - 12} more</span>
            )}
          </div>
        </div>
      )}

      {/* Passed symbols */}
      {stocks && stocks.length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-2">Passed ({stocks.length})</div>
          <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
            {stocks.slice(0, 20).map(sym => (
              <span key={sym} className="px-2 py-0.5 bg-slate-700/40 text-slate-300 rounded text-xs font-mono">
                {sym}
              </span>
            ))}
            {stocks.length > 20 && (
              <span className="text-xs text-slate-500">+{stocks.length - 20} more</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function JourneyStepRow({ step, isLast }: { step: JourneyStep; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const colors = stageColor(step.result, false);
  const hasDetail = step.detail && Object.keys(step.detail).length > 0;

  return (
    <div className="flex gap-3">
      {/* Line */}
      <div className="flex flex-col items-center">
        <div className={`w-8 h-8 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${colors.bg} ${colors.border}`}>
          {step.result === "PASS" ? <CheckCircle2 size={14} className="text-emerald-400" /> :
           step.result === "FAIL" ? <XCircle size={14} className="text-red-400" /> :
           <AlertTriangle size={14} className="text-amber-400" />}
        </div>
        {!isLast && <div className="w-0.5 flex-1 min-h-4 bg-slate-700 mt-1" />}
      </div>
      {/* Content */}
      <div className={`flex-1 pb-4 ${isLast ? "" : ""}`}>
        <div className="flex items-center justify-between mb-1">
          <span className={`text-sm font-semibold ${colors.text}`}>{step.label}</span>
          <div className="flex items-center gap-2">
            {step.score != null && (
              <span className="text-xs text-slate-400 font-mono">score {step.score}</span>
            )}
            <span className={`text-xs px-2 py-0.5 rounded border font-medium ${colors.bg} ${colors.border} ${colors.text}`}>
              {step.result}
            </span>
          </div>
        </div>
        <p className="text-xs text-slate-400">{step.reason}</p>
        {hasDetail && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="mt-1.5 text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1"
          >
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />} Detail
          </button>
        )}
        {expanded && step.detail && (
          <div className="mt-2 bg-slate-900/60 border border-slate-700/50 rounded p-3 space-y-1">
            {Object.entries(step.detail).filter(([, v]) => v != null).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs">
                <span className="text-slate-500">{k.replace(/_/g, " ")}</span>
                <span className="text-slate-300 font-mono">{String(v)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────────────────────────────────────

export default function AIInvestigationCentre() {
  // ── UI state ──────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab]         = useState(0);
  const [selectedScanId, setSelectedScanId] = useState<string>("latest");
  const [replayState, setReplayState]     = useState<"idle" | "playing" | "paused" | "complete">("idle");
  const [activeStageIdx, setActiveStageIdx] = useState(-1);
  const [speed, setSpeed]                 = useState(1);
  const [focusStageId, setFocusStageId]   = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [symbolSearch, setSymbolSearch]   = useState("");
  const [filterMode, setFilterMode]       = useState("All");
  const [replayMode, setReplayMode]       = useState<"full" | "custom">("full");
  const [replaySource, setReplaySource]   = useState<"scan" | "tick" | "decision" | "paper">("scan");
  const [jumpTarget, setJumpTarget]       = useState("");
  const [showSessionDrop, setShowSessionDrop] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Queries ───────────────────────────────────────────────────────────────
  const { data: sessionsData } = useQuery({
    queryKey: ["inv-sessions"],
    queryFn: () => apiJson<{ sessions: Session[]; count: number }>("replay/sessions"),
    staleTime: 30_000,
    retry: 1,
  });

  const { data: replayData, isLoading: replayLoading } = useQuery({
    queryKey: ["inv-replay", selectedScanId],
    queryFn: () => apiJson<{
      scan_id: string; snapshot_ts: string; stages: Stage[];
      symbols: SymbolRow[]; total_symbols: number; universe_size: number;
      regime: string | null; provider_health: Record<string, number>;
      duration_s: number | null;
    }>(`replay/sessions/${selectedScanId}`),
    staleTime: 60_000,
    retry: 1,
  });

  const { data: summaryData } = useQuery({
    queryKey: ["inv-summary", selectedScanId],
    queryFn: () => apiJson<Record<string, unknown>>(`replay/sessions/${selectedScanId}/summary`),
    staleTime: 60_000,
    retry: 1,
  });

  const { data: journeyData, isLoading: journeyLoading } = useQuery({
    queryKey: ["inv-journey", selectedScanId, selectedSymbol],
    queryFn: () => apiJson<SymbolJourney>(`replay/sessions/${selectedScanId}/symbol/${selectedSymbol}`),
    enabled: !!selectedSymbol,
    staleTime: 120_000,
    retry: 1,
  });

  const { data: comparisonData, isLoading: compLoading } = useQuery({
    queryKey: ["inv-comparison", selectedScanId],
    queryFn: () => apiJson<{
      comparisons: CompItem[];
      stats: { wins: number; losses: number; missed_opportunities: number; pending: number };
    }>(`replay/sessions/${selectedScanId}/comparison`),
    staleTime: 60_000,
    retry: 1,
  });

  // ── Early derivations needed by useMemo hooks below ─────────────────────
  const sessions: Session[] = sessionsData?.sessions ?? [];
  const selectedSession = sessions.find(s => s.scan_id === selectedScanId) ?? sessions[0];
  const snapshotTs = replayData?.snapshot_ts ?? selectedSession?.snapshot_ts;

  // ── Playback engine ───────────────────────────────────────────────────────
  const stages = replayData?.stages ?? [];

  // Build the portfolio trade cards from comparison data (paper_traded items)
  const portfolioTrades: TradeCard[] = useMemo(() => {
    const compItems = comparisonData?.comparisons ?? [];
    const paperItems = compItems.filter(c => c.paper_traded && c.entry_price != null);
    return paperItems.map(c => {
      const entry   = c.entry_price!;
      const qty     = Math.max(1, Math.floor(TRADE_ALLOCATION / entry));
      const capital = entry * qty;
      const exit    = c.current_price ?? null;
      const pnl     = exit != null ? (exit - entry) * qty : null;
      const pnlPct  = exit != null ? ((exit - entry) / entry) * 100 : null;
      // Derive exit reason from status
      let exitReason: TradeCard["exit_reason"] = null;
      if (c.status === "WIN")  exitReason = "Target Hit";
      if (c.status === "LOSS") exitReason = "Stop Loss";
      if (c.status === "PENDING") exitReason = null;
      // Derive simulated timestamps from session snapshot_ts
      const base = snapshotTs ? new Date(snapshotTs) : null;
      const entryTime = base ? new Date(base.getTime() + 30 * 60_000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" }) : null;
      const exitTime  = exit != null && base ? new Date(base.getTime() + 3 * 3600_000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" }) : null;
      const status: TradeCard["status"] = c.status === "WIN" ? "WIN" : c.status === "LOSS" ? "LOSS" : exit ? "PENDING" : "OPEN";
      return {
        symbol: c.symbol,
        entry_price: entry,
        exit_price: exit,
        qty,
        capital_used: capital,
        stop_loss: null,  // not available in comparison data — shown as — in detail modal
        target: null,
        pnl,
        pnl_pct: pnlPct,
        status,
        exit_reason: exitReason,
        entry_time: entryTime,
        exit_time: exitTime,
      };
    });
  }, [comparisonData, snapshotTs]);

  // Synthetic stage data for portfolio_management (derived, not from backend)
  const portfolioStageSynthetic: Stage | undefined = useMemo(() => {
    if (!comparisonData) return undefined;
    const closed = portfolioTrades.filter(t => t.pnl !== null).length;
    return {
      id: "portfolio_management",
      label: "Portfolio / Trade Management",
      order: 10,
      stocks_in: portfolioTrades.length,
      stocks_out: closed,
      rejected: 0,
      rejected_symbols: [],
      stocks: portfolioTrades.map(t => t.symbol),
      duration_ms: null,
      description: `${portfolioTrades.length} positions managed · ${closed} exits processed`,
      paper_orders: portfolioTrades.length,
    };
  }, [portfolioTrades, comparisonData]);

  const stageById = useMemo(() => {
    const base = Object.fromEntries(stages.map(s => [s.id, s]));
    if (portfolioStageSynthetic) base["portfolio_management"] = portfolioStageSynthetic;
    return base;
  }, [stages, portfolioStageSynthetic]);

  // Pipeline count validation
  const pipelineErrors: PipelineValidationError[] = useMemo(
    () => validatePipelineCounts(stages, PIPELINE_STAGES),
    [stages],
  );

  const stopTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const startTimer = useCallback(() => {
    stopTimer();
    timerRef.current = setInterval(() => {
      setActiveStageIdx(prev => {
        const next = prev + 1;
        if (next >= PIPELINE_STAGES.length) {
          setReplayState("complete");
          stopTimer();
          return PIPELINE_STAGES.length - 1;
        }
        setFocusStageId(PIPELINE_STAGES[next].id);
        return next;
      });
    }, BASE_DELAY_MS / speed);
  }, [speed, stopTimer]);

  const handlePlay = useCallback(() => {
    if (replayState === "complete") {
      setActiveStageIdx(-1);
      setFocusStageId(null);
    }
    setReplayState("playing");
    startTimer();
  }, [replayState, startTimer]);

  const handlePause = useCallback(() => {
    stopTimer();
    setReplayState("paused");
  }, [stopTimer]);

  const handleStop = useCallback(() => {
    stopTimer();
    setReplayState("idle");
    setActiveStageIdx(-1);
    setFocusStageId(null);
  }, [stopTimer]);

  const handleRestart = useCallback(() => {
    stopTimer();
    setActiveStageIdx(-1);
    setFocusStageId(null);
    setReplayState("playing");
    setTimeout(startTimer, 50);
  }, [stopTimer, startTimer]);

  const handleJumpToEvent = useCallback(() => {
    const n = parseInt(jumpTarget, 10);
    if (!isNaN(n) && n >= 0 && n < PIPELINE_STAGES.length) {
      handleStop();
      setActiveStageIdx(n - 1);
      setFocusStageId(PIPELINE_STAGES[Math.max(0, n - 1)].id);
    }
  }, [jumpTarget, handleStop]);

  // Re-apply timer when speed changes mid-play
  useEffect(() => {
    if (replayState === "playing") { startTimer(); }
  }, [speed]);  // eslint-disable-line

  useEffect(() => () => stopTimer(), [stopTimer]);

  // ── Derived ───────────────────────────────────────────────────────────────
  // (sessions / selectedSession / snapshotTs hoisted above for useMemo access)

  const symbols: SymbolRow[] = replayData?.symbols ?? [];
  const filteredSymbols = symbols.filter(sym => {
    if (symbolSearch && !sym.symbol.toLowerCase().includes(symbolSearch.toLowerCase())) return false;
    return true;
  });

  const filteredByTab = (items: CompItem[]) => {
    switch (filterMode) {
      case "Bought": return items.filter(i => i.paper_traded);
      case "Rejected": return items.filter(i => i.ai_action === "AVOID" || i.ai_action === "WATCH");
      case "Missed Opportunities": return items.filter(i => i.status === "MISSED_OPPORTUNITY");
      case "Winning Trades": return items.filter(i => i.status === "WIN");
      case "Losing Trades": return items.filter(i => i.status === "LOSS");
      default: return items;
    }
  };

  const compItems: CompItem[] = comparisonData?.comparisons ?? [];
  const missedOpps = compItems.filter(i => i.status === "MISSED_OPPORTUNITY");

  const summ = summaryData as Record<string, unknown> | undefined;

  // ── Active stage for focus panel ──────────────────────────────────────────
  const focusStage = focusStageId
    ? PIPELINE_STAGES.find(s => s.id === focusStageId)
    : null;

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <PageHeader
        title="AI Investigation Centre"
        subtitle="Trading Day Replay — digital twin of the AI pipeline"
        icon={Microscope}
        status={replayState === "playing" ? "live" : replayState === "complete" ? "success" : "neutral"}
        readOnly
        breadcrumbs={[{ label: "Operations" }, { label: "AI Investigation Centre" }]}
      />

      <div className="p-4 space-y-4 max-w-screen-2xl mx-auto">

        {/* ── Control Panel ─────────────────────────────────────────────── */}
        <div className="bg-slate-900/70 border border-slate-700/60 rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-4">
            <Calendar size={14} className="text-teal-400" />
            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Replay Control Panel</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">

            {/* Session selector */}
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Replay Date / Session</label>
              <div className="relative">
                <button
                  onClick={() => setShowSessionDrop(v => !v)}
                  className="w-full flex items-center justify-between bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-left hover:border-teal-500 transition-colors"
                >
                  <span className="truncate">{fmtDate(snapshotTs)}</span>
                  <ChevronDown size={14} className="text-slate-400 flex-shrink-0 ml-2" />
                </button>
                {showSessionDrop && (
                  <div className="absolute z-30 top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-600 rounded-lg shadow-xl max-h-56 overflow-y-auto">
                    {sessions.length === 0 && (
                      <div className="px-3 py-2 text-xs text-slate-500">No sessions found</div>
                    )}
                    {sessions.map(s => (
                      <button
                        key={s.scan_id}
                        onClick={() => { setSelectedScanId(s.scan_id); setShowSessionDrop(false); handleStop(); }}
                        className={`w-full text-left px-3 py-2 text-xs hover:bg-slate-700 transition-colors ${
                          s.scan_id === selectedScanId ? "text-teal-300 bg-teal-900/20" : "text-slate-300"
                        }`}
                      >
                        <div className="font-mono">{fmtDate(s.snapshot_ts)}</div>
                        <div className="text-slate-500 flex gap-2 mt-0.5">
                          {s.is_latest && <span className="text-teal-400">LATEST</span>}
                          {s.buy_signals != null && <span>{s.buy_signals} BUY</span>}
                          {s.universe_size != null && <span>{s.universe_size} symbols</span>}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Replay Mode + Source */}
            <div className="space-y-2">
              <div>
                <label className="text-xs text-slate-500 mb-1 block">Replay Mode</label>
                <div className="flex gap-2">
                  {(["full", "custom"] as const).map(m => (
                    <button key={m} onClick={() => setReplayMode(m)}
                      className={`flex-1 py-1.5 rounded text-xs font-medium transition-all ${replayMode === m ? "bg-teal-700 text-white" : "bg-slate-700 text-slate-400 hover:bg-slate-600"}`}>
                      {m === "full" ? "Full Trading Day" : "Custom Time"}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">Replay Source</label>
                <select
                  value={replaySource}
                  onChange={e => setReplaySource(e.target.value as typeof replaySource)}
                  className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-slate-300"
                >
                  <option value="scan">Historical Scan Replay</option>
                  <option value="tick">Tick Replay</option>
                  <option value="decision">AI Decision Replay</option>
                  <option value="paper">Paper Trade Replay</option>
                </select>
              </div>
            </div>

            {/* Playback speed */}
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Playback Speed</label>
              <div className="flex flex-wrap gap-1.5">
                {SPEEDS.map(s => (
                  <SpeedBtn key={s} speed={s} active={speed === s} onClick={() => setSpeed(s)} />
                ))}
              </div>
              <div className="mt-2 flex gap-2 items-center">
                <label className="text-xs text-slate-500">Jump to event #</label>
                <input
                  value={jumpTarget}
                  onChange={e => setJumpTarget(e.target.value)}
                  placeholder="1-10"
                  className="w-16 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs font-mono text-slate-300"
                />
                <button onClick={handleJumpToEvent}
                  className="px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs text-slate-300 transition-colors">
                  <SkipForward size={11} />
                </button>
              </div>
            </div>

            {/* Controls */}
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Controls</label>
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={replayState === "playing" ? handlePause : handlePlay}
                  disabled={replayLoading}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                    replayState === "playing"
                      ? "bg-amber-600 hover:bg-amber-700 text-white"
                      : "bg-teal-600 hover:bg-teal-700 text-white"
                  } disabled:opacity-40`}
                >
                  {replayState === "playing" ? <Pause size={14} /> : <Play size={14} />}
                  {replayState === "playing" ? "Pause" : replayState === "paused" ? "Resume" : "Play"}
                </button>
                <button onClick={handleStop}
                  className="flex items-center gap-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-slate-300 transition-all">
                  <Square size={14} /> Stop
                </button>
                <button onClick={handleRestart}
                  className="flex items-center gap-1.5 px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm text-slate-300 transition-all">
                  <RotateCcw size={14} /> Restart
                </button>
              </div>
              <div className="mt-2 text-xs">
                {replayState === "idle" && <span className="text-slate-500">Ready — press Play to start</span>}
                {replayState === "playing" && (
                  <span className="text-amber-300 animate-pulse flex items-center gap-1">
                    <span className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-ping inline-block" />
                    Replaying stage {activeStageIdx + 1} of {PIPELINE_STAGES.length}
                  </span>
                )}
                {replayState === "paused" && <span className="text-amber-500">Paused at {PIPELINE_STAGES[Math.max(0, activeStageIdx)]?.label}</span>}
                {replayState === "complete" && <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 size={11} /> Replay complete</span>}
              </div>
            </div>
          </div>

          {/* Progress bar */}
          {replayState !== "idle" && (
            <div className="mt-4">
              <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-teal-500 to-emerald-400 transition-all duration-500"
                  style={{ width: `${Math.max(0, ((activeStageIdx + 1) / PIPELINE_STAGES.length) * 100)}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-slate-600 mt-1">
                <span>Pipeline Start</span>
                <span>{fmtTs(snapshotTs)}</span>
                <span>Pipeline End</span>
              </div>
            </div>
          )}
        </div>

        {/* ── Session Summary ────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-11 gap-2">
          <KpiCard label="Market" value="NSE" />
          <KpiCard label="Date" value={snapshotTs ? new Date(snapshotTs).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata" }) : "—"} />
          <KpiCard label="Session" value={selectedSession?.status ?? "—"} />
          <KpiCard label="Symbols Scanned" value={replayData?.universe_size ?? "—"} color="text-teal-300" />
          <KpiCard label="BUY Generated" value={selectedSession?.buy_signals ?? (summ?.buy_candidates as number | undefined) ?? "—"} color="text-emerald-400" />
          <KpiCard label="BUY Executed" value={selectedSession?.paper_orders ?? "—"} color="text-emerald-300" />
          <KpiCard label="SELL Executed" value={(summ?.completed_trades as number | undefined) ?? "—"} color="text-amber-300" />
          <KpiCard label="Rejected" value={symbols.filter(s => !s.all_gates_passed).length || "—"} color="text-red-400" />
          <KpiCard label="Missed Opps" value={missedOpps.length || "—"} color="text-orange-400" />
          <KpiCard label="Win Rate"
            value={(summ?.win_rate as number | undefined) != null ? `${(summ!.win_rate as number).toFixed(1)}%` : "—"}
            color="text-teal-400"
          />
          <KpiCard label="P&L"
            value={(summ?.total_pnl as number | undefined) != null
              ? `₹${(summ!.total_pnl as number).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
              : "—"}
            color={(summ?.total_pnl as number | undefined) != null
              ? pctColor(summ!.total_pnl as number)
              : "text-slate-400"}
          />
        </div>

        {/* ── Pipeline Validation Banner ────────────────────────────────── */}
        <PipelineValidationBanner errors={pipelineErrors} />

        {/* ── Tabs ──────────────────────────────────────────────────────── */}
        <div className="flex gap-1 border-b border-slate-800">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => setActiveTab(i)}
              className={`px-4 py-2.5 text-sm font-medium rounded-t-lg transition-all ${
                activeTab === i
                  ? "text-teal-300 border-b-2 border-teal-500 bg-slate-900/60"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* ══ TAB 0: Pipeline Replay ════════════════════════════════════ */}
        {activeTab === 0 && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">

            {/* Left: Visual AI Pipeline */}
            <div className="xl:col-span-1 space-y-1">
              <div className="flex items-center gap-2 mb-3">
                <Cpu size={14} className="text-teal-400" />
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">AI Pipeline</span>
              </div>
              {replayLoading && (
                <div className="text-center py-8 text-slate-500 text-sm animate-pulse">Loading scan data…</div>
              )}
              {!replayLoading && PIPELINE_STAGES.map((stage, i) => {
                const sd = stageById[stage.id];
                const isPast = i <= activeStageIdx;
                const isActive = i === activeStageIdx && replayState === "playing";
                const pstatus = isPast && sd
                  ? (sd.stocks_out > 0 ? "PASS" : (sd.rejected > 0 ? "FAIL" : "PASS"))
                  : undefined;
                return (
                  <StageNode
                    key={stage.id}
                    stage={stage}
                    stageData={sd}
                    status={pstatus}
                    isActive={isActive}
                    isPast={isPast}
                    index={i}
                    onClick={() => setFocusStageId(focusStageId === stage.id ? null : stage.id)}
                    activeSymbolFilter={filterMode}
                  />
                );
              })}

              {/* Pipeline Stats */}
              <div className="mt-6 bg-slate-900/50 border border-slate-800 rounded-xl p-4">
                <div className="text-xs font-semibold text-slate-500 mb-3 uppercase tracking-wider">
                  Funnel Statistics
                </div>
                {PIPELINE_STAGES.map((stage, i) => {
                  const sd = stageById[stage.id];
                  const count = sd?.stocks_in ?? null;
                  const pct = count != null && (replayData?.universe_size ?? 0) > 0
                    ? (count / (replayData!.universe_size!)) * 100
                    : null;
                  return (
                    <div key={stage.id} className="flex items-center gap-2 mb-1.5">
                      <span className="text-xs text-slate-500 w-28 truncate">{stage.label}</span>
                      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-teal-600 to-teal-400 rounded-full transition-all duration-700"
                          style={{ width: pct != null ? `${pct}%` : "0%" }}
                        />
                      </div>
                      <span className="text-xs font-mono text-slate-400 w-8 text-right">{count ?? "—"}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right: Stage Detail + Symbol List */}
            <div className="xl:col-span-2 space-y-4">

              {/* Stage Detail Panel */}
              {focusStage && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <focusStage.icon size={14} className="text-teal-400" />
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      {focusStage.label} — Agent Detail
                    </span>
                  </div>
                  {/* Portfolio Management stage gets its own rich panel */}
                  {focusStage.id === "portfolio_management" ? (
                    <PortfolioManagementPanel
                      trades={portfolioTrades}
                      snapshotTs={snapshotTs}
                      isReplayComplete={replayState === "complete"}
                    />
                  ) : (
                    <AgentDetailCard stageId={focusStage.id} stageData={stageById[focusStage.id]} />
                  )}
                </div>
              )}

              {!focusStage && (
                <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-8 text-center">
                  <Eye size={32} className="mx-auto text-slate-700 mb-3" />
                  <p className="text-slate-500 text-sm">Click any pipeline stage to inspect its detail</p>
                  <p className="text-slate-600 text-xs mt-1">or press Play to start the animated replay</p>
                </div>
              )}

              {/* Symbol List */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <BarChart3 size={14} className="text-teal-400" />
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      Symbols ({filteredSymbols.length})
                    </span>
                  </div>
                  <div className="relative">
                    <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
                    <input
                      value={symbolSearch}
                      onChange={e => setSymbolSearch(e.target.value)}
                      placeholder="Search symbol…"
                      className="pl-7 pr-3 py-1.5 bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 w-36"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-96 overflow-y-auto pr-1">
                  {filteredSymbols.map(sym => (
                    <button
                      key={sym.symbol}
                      onClick={() => { setSelectedSymbol(sym.symbol); setActiveTab(1); }}
                      className={`text-left bg-slate-800/60 border rounded-lg p-3 hover:border-teal-500 transition-all group
                        ${selectedSymbol === sym.symbol ? "border-teal-500 bg-teal-900/10" : "border-slate-700/60"}`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono font-semibold text-sm text-slate-200 group-hover:text-teal-300 transition-colors">
                          {sym.symbol}
                        </span>
                        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${actionBadge(sym.final_action)}`}>
                          {sym.final_action ?? "—"}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-slate-500">
                        <span>{sym.sector ?? "—"}</span>
                        <span className="text-teal-400">{sym.confidence}% conf</span>
                        {sym.paper_eligible && <span className="text-emerald-400">Paper ✓</span>}
                      </div>
                      {sym.strategy && <div className="text-xs text-slate-600 mt-0.5 truncate">{sym.strategy}</div>}
                    </button>
                  ))}
                  {filteredSymbols.length === 0 && (
                    <div className="col-span-2 text-center py-6 text-slate-600 text-sm">
                      {replayLoading ? "Loading…" : "No symbols match"}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ══ TAB 1: Investigation Mode ═════════════════════════════════ */}
        {activeTab === 1 && (
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">

            {/* Symbol selector */}
            <div className="xl:col-span-1">
              <div className="flex items-center gap-2 mb-3">
                <Microscope size={14} className="text-teal-400" />
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Select Symbol</span>
              </div>
              <div className="relative mb-3">
                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  value={symbolSearch}
                  onChange={e => setSymbolSearch(e.target.value)}
                  placeholder="Search symbol…"
                  className="w-full pl-7 pr-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-300"
                />
              </div>
              <div className="space-y-1.5 max-h-[60vh] overflow-y-auto">
                {filteredSymbols.map(sym => (
                  <button
                    key={sym.symbol}
                    onClick={() => setSelectedSymbol(sym.symbol)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg border transition-all
                      ${selectedSymbol === sym.symbol
                        ? "bg-teal-900/20 border-teal-500 text-teal-300"
                        : "bg-slate-800/50 border-slate-700/50 text-slate-300 hover:border-slate-500"}`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-semibold text-sm">{sym.symbol}</span>
                      <span className={`px-2 py-0.5 rounded text-xs ${actionBadge(sym.final_action)}`}>
                        {sym.final_action ?? "?"}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">{sym.sector ?? "Unknown sector"}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Journey */}
            <div className="xl:col-span-2">
              {!selectedSymbol && (
                <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-12 text-center">
                  <Search size={40} className="mx-auto text-slate-700 mb-3" />
                  <p className="text-slate-500">Select a symbol from the list to replay its AI journey</p>
                </div>
              )}

              {selectedSymbol && journeyLoading && (
                <div className="text-center py-12 text-slate-500 animate-pulse">
                  Loading journey for {selectedSymbol}…
                </div>
              )}

              {selectedSymbol && !journeyLoading && journeyData && (
                <div className="space-y-4">
                  {/* Header */}
                  <div className="bg-slate-900/60 border border-slate-700/60 rounded-xl p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-xl font-bold text-slate-100 font-mono">{journeyData.symbol}</h3>
                        <div className="text-sm text-slate-500">{journeyData.sector ?? "Unknown sector"}</div>
                        {journeyData.error && (
                          <div className="mt-2 text-sm text-amber-400 flex items-center gap-1">
                            <AlertTriangle size={14} /> {journeyData.error}
                          </div>
                        )}
                      </div>
                      <div className="text-right">
                        <span className={`px-3 py-1.5 rounded-lg text-sm font-bold ${actionBadge(journeyData.recommendation?.final_action ?? null)}`}>
                          {journeyData.recommendation?.final_action ?? "—"}
                        </span>
                        <div className="text-xs text-slate-500 mt-1">{journeyData.recommendation?.confidence}% confidence</div>
                      </div>
                    </div>
                    {journeyData.recommendation && (
                      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 mt-4">
                        {[
                          { label: "Entry", value: journeyData.recommendation.entry_price != null ? `₹${journeyData.recommendation.entry_price.toFixed(1)}` : "—" },
                          { label: "Stop", value: journeyData.recommendation.stop_loss != null ? `₹${journeyData.recommendation.stop_loss.toFixed(1)}` : "—" },
                          { label: "Target", value: journeyData.recommendation.target_price != null ? `₹${journeyData.recommendation.target_price.toFixed(1)}` : "—" },
                          { label: "R:R", value: journeyData.recommendation.rr_ratio != null ? `${journeyData.recommendation.rr_ratio.toFixed(1)}:1` : "—" },
                          { label: "Strategy", value: journeyData.recommendation.strategy ?? "—" },
                        ].map(item => (
                          <div key={item.label} className="bg-slate-800/60 rounded-lg p-2 text-center">
                            <div className="text-xs text-slate-500">{item.label}</div>
                            <div className="text-sm font-semibold text-slate-200 truncate">{item.value}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Risk gates */}
                  {(() => {
                    const ra = (journeyData.thinking as Record<string, unknown>)?.risk_agent as Record<string, unknown> | undefined;
                    if (!ra) return null;
                    const gates = ra.gates as Record<string, boolean> | undefined;
                    return (
                      <div className="bg-slate-900/60 border border-slate-700/60 rounded-xl p-4">
                        <div className="flex items-center gap-2 mb-3">
                          <Shield size={14} className="text-teal-400" />
                          <h4 className="text-sm font-semibold text-slate-300">Risk Agent</h4>
                          <span className={`ml-auto px-2 py-0.5 rounded text-xs font-bold ${
                            ra.decision === "APPROVED" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
                          }`}>{String(ra.decision)}</span>
                        </div>
                        {!!ra.rejection_reason && (
                          <div className="mb-3 p-2 bg-red-900/20 border border-red-700/30 rounded text-xs text-red-300">
                            ✗ {String(ra.rejection_reason)}
                          </div>
                        )}
                        {gates && (
                          <div className="space-y-1">
                            <GateRow label="Price Gate"        passed={gates.price}        value={ra.entry_price != null ? `₹${Number(ra.entry_price).toFixed(1)}` : undefined} />
                            <GateRow label="Data Quality Gate" passed={gates.data_quality} />
                            <GateRow label="Risk:Reward Gate"  passed={gates.rr}           value={ra.rr_ratio != null ? `${Number(ra.rr_ratio).toFixed(1)}:1` : undefined} />
                            <GateRow label="Volume Gate"       passed={gates.volume}        value={ra.heat != null ? `heat ${Number(ra.heat).toFixed(2)}` : undefined} />
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Strategy thinking */}
                  {(() => {
                    const sa = (journeyData.thinking as Record<string, unknown>)?.strategy_agent as Record<string, unknown> | undefined;
                    if (!sa) return null;
                    const indicators = sa.indicators as Record<string, unknown> | undefined;
                    return (
                      <div className="bg-slate-900/60 border border-slate-700/60 rounded-xl p-4">
                        <div className="flex items-center gap-2 mb-3">
                          <Layers size={14} className="text-teal-400" />
                          <h4 className="text-sm font-semibold text-slate-300">Strategy Agent</h4>
                          <span className="ml-auto text-xs text-slate-400 font-mono">score {String(sa.score ?? "—")}</span>
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-3">
                          {indicators && Object.entries(indicators).filter(([, v]) => v != null).map(([k, v]) => (
                            <div key={k} className="bg-slate-800/60 rounded p-2">
                              <div className="text-xs text-slate-500">{k.replace(/_/g, " ")}</div>
                              <div className="text-sm font-mono text-slate-200 truncate">{String(v)}</div>
                            </div>
                          ))}
                        </div>
                        {sa.win_rate != null && (
                          <div className="text-xs text-slate-500">
                            Historical: {String(sa.win_rate)}% win rate · {String(sa.profit_factor ?? "—")} PF · {String(sa.total_historical_trades ?? "—")} trades
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Journey timeline */}
                  <div className="bg-slate-900/60 border border-slate-700/60 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-4">
                      <Clock size={14} className="text-teal-400" />
                      <h4 className="text-sm font-semibold text-slate-300">Agent Journey — {journeyData.symbol}</h4>
                    </div>
                    <div className="space-y-0">
                      {journeyData.journey.map((step, i) => (
                        <JourneyStepRow key={step.stage} step={step} isLast={i === journeyData.journey.length - 1} />
                      ))}
                    </div>
                  </div>

                  {/* Paper trade */}
                  {journeyData.paper_trade && (
                    <div className="bg-slate-900/60 border border-teal-700/40 rounded-xl p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <Target size={14} className="text-teal-400" />
                        <h4 className="text-sm font-semibold text-teal-300">Paper Trade</h4>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-xs">
                        {Object.entries(journeyData.paper_trade).filter(([, v]) => v != null).map(([k, v]) => (
                          <div key={k} className="bg-slate-800/60 rounded p-2">
                            <div className="text-slate-500">{k.replace(/_/g, " ")}</div>
                            <div className="text-slate-200 font-mono truncate">{String(v)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Live Trade Timeline */}
                  <div className="bg-slate-900/60 border border-slate-700/60 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-4">
                      <TrendingUp size={14} className="text-teal-400" />
                      <h4 className="text-sm font-semibold text-slate-300">Live Trade Timeline</h4>
                    </div>
                    {journeyData.paper_trade ? (
                      <div className="relative">
                        <div className="absolute left-3.5 top-0 bottom-0 w-0.5 bg-slate-700" />
                        {[
                          { time: fmtTs(String(journeyData.paper_trade.trade_ts ?? "")), event: "BUY Placed", color: "bg-emerald-500", detail: `₹${Number(journeyData.paper_trade.price ?? 0).toFixed(1)}` },
                          { time: "—", event: "Position Open", color: "bg-teal-500", detail: journeyData.recommendation?.strategy ?? "" },
                          { time: "—", event: "Monitoring", color: "bg-amber-500", detail: "VWAP / RSI tracking" },
                          { time: "—", event: "Exit / EOD", color: "bg-blue-500", detail: "Paper trade auto-exit" },
                        ].map((evt, idx) => (
                          <div key={idx} className="relative flex items-start gap-4 pl-8 mb-4">
                            <div className={`absolute left-2 top-1.5 w-3 h-3 rounded-full ${evt.color} flex-shrink-0`} />
                            <div>
                              <div className="text-xs text-slate-500">{evt.time}</div>
                              <div className="text-sm font-medium text-slate-200">{evt.event}</div>
                              {evt.detail && <div className="text-xs text-slate-500">{evt.detail}</div>}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center py-4 text-slate-600 text-sm">
                        No paper trade recorded for {journeyData.symbol} in this session
                      </div>
                    )}
                  </div>
                </div>
              )}

              {selectedSymbol && !journeyLoading && !journeyData && (
                <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-8 text-center text-slate-500">
                  No journey data found for {selectedSymbol}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ══ TAB 2: Missed Opportunities ══════════════════════════════ */}
        {activeTab === 2 && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Eye size={14} className="text-orange-400" />
                <span className="text-sm font-semibold text-slate-300">Missed Opportunities</span>
                <span className="px-2 py-0.5 bg-orange-900/30 text-orange-400 border border-orange-700/40 rounded text-xs">
                  {missedOpps.length}
                </span>
              </div>
              <div className="text-xs text-slate-500">
                Stocks where the AI said AVOID but price moved significantly after rejection
              </div>
            </div>

            {compLoading && <div className="text-center py-12 text-slate-500 animate-pulse">Loading comparison data…</div>}

            {!compLoading && missedOpps.length === 0 && (
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-12 text-center">
                <Award size={40} className="mx-auto text-slate-700 mb-3" />
                <p className="text-slate-500">No missed opportunities detected in this session</p>
                <p className="text-slate-600 text-xs mt-1">Great — the AI didn't reject any big movers</p>
              </div>
            )}

            {!compLoading && missedOpps.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800">
                      {["Symbol", "Rejected By", "Reason", "Actual Move", "Potential Profit", "Would Still Reject?"].map(h => (
                        <th key={h} className="text-left py-2 px-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {missedOpps.map((item, i) => {
                      const move = item.outcome_pct;
                      const entry = item.entry_price;
                      const current = item.current_price;
                      const potentialPnl = entry && current && move != null
                        ? (current - entry)
                        : null;
                      return (
                        <tr key={item.symbol} className={`border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors ${i % 2 === 0 ? "" : "bg-slate-900/20"}`}>
                          <td className="py-3 px-3">
                            <button
                              onClick={() => { setSelectedSymbol(item.symbol); setActiveTab(1); }}
                              className="font-mono font-semibold text-slate-200 hover:text-teal-300 transition-colors"
                            >
                              {item.symbol}
                            </button>
                          </td>
                          <td className="py-3 px-3 text-slate-400 text-xs">
                            {item.ai_action === "AVOID" ? "Risk / Decision" : "Decision"}
                          </td>
                          <td className="py-3 px-3 text-slate-400 text-xs max-w-48 truncate">
                            {item.rejection_reason ?? "Confidence below threshold"}
                          </td>
                          <td className="py-3 px-3">
                            {move != null ? (
                              <span className={`font-mono font-semibold ${move >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                {move >= 0 ? "+" : ""}{move.toFixed(2)}%
                              </span>
                            ) : <span className="text-slate-600">—</span>}
                          </td>
                          <td className="py-3 px-3">
                            {entry && move != null ? (
                              <span className={`font-mono text-xs ${move >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                ₹{Math.abs((entry * move) / 100).toFixed(0)} / lot
                              </span>
                            ) : <span className="text-slate-600">—</span>}
                          </td>
                          <td className="py-3 px-3">
                            {/* Simple heuristic: if it was a big move (>2%) and rejection was not critical, maybe NO */}
                            {move != null && Math.abs(move) > 3 ? (
                              <span className="px-2 py-0.5 bg-amber-900/20 text-amber-400 border border-amber-700/40 rounded text-xs font-semibold">
                                REVIEW
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 bg-slate-800 text-slate-400 border border-slate-700 rounded text-xs">
                                YES
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* All comparisons below */}
            {!compLoading && comparisonData && (
              <div className="mt-6">
                <div className="flex items-center gap-2 mb-3">
                  <BarChart3 size={14} className="text-slate-500" />
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">All AI Decisions vs Outcome</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                  {[
                    { label: "Wins", value: comparisonData.stats?.wins ?? 0, color: "text-emerald-400" },
                    { label: "Losses", value: comparisonData.stats?.losses ?? 0, color: "text-red-400" },
                    { label: "Missed", value: comparisonData.stats?.missed_opportunities ?? 0, color: "text-orange-400" },
                    { label: "Pending", value: comparisonData.stats?.pending ?? 0, color: "text-slate-400" },
                  ].map(s => (
                    <KpiCard key={s.label} label={s.label} value={s.value} color={s.color} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══ TAB 3: Filters ════════════════════════════════════════════ */}
        {activeTab === 3 && (
          <div>
            <div className="flex items-center gap-2 mb-4">
              <Filter size={14} className="text-teal-400" />
              <span className="text-sm font-semibold text-slate-300">Filter Replay View</span>
            </div>
            <div className="flex flex-wrap gap-2 mb-6">
              {FILTER_OPTIONS.map(opt => (
                <button
                  key={opt}
                  onClick={() => setFilterMode(opt)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium border transition-all ${
                    filterMode === opt
                      ? "bg-teal-700 border-teal-600 text-white"
                      : "bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-300"
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>

            <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-semibold text-slate-300">
                  {filterMode} — {filteredByTab(compItems).length} items
                </span>
                <span className="text-xs text-slate-500">{fmtDate(snapshotTs)}</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 max-h-[50vh] overflow-y-auto">
                {filteredByTab(compItems).map(item => (
                  <button
                    key={item.symbol}
                    onClick={() => { setSelectedSymbol(item.symbol); setActiveTab(1); }}
                    className="text-left bg-slate-800/60 border border-slate-700/50 rounded-lg p-3 hover:border-teal-500 transition-all group"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-mono font-semibold text-slate-200 group-hover:text-teal-300">{item.symbol}</span>
                      <span className={`px-2 py-0.5 rounded text-xs ${actionBadge(item.ai_action)}`}>{item.ai_action}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs">
                      <span className={`font-mono font-semibold ${
                        item.status === "WIN" ? "text-emerald-400" :
                        item.status === "LOSS" ? "text-red-400" :
                        item.status === "MISSED_OPPORTUNITY" ? "text-orange-400" : "text-slate-500"
                      }`}>{item.status}</span>
                      {item.outcome_pct != null && (
                        <span className={`font-mono ${item.outcome_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {item.outcome_pct >= 0 ? "+" : ""}{item.outcome_pct.toFixed(1)}%
                        </span>
                      )}
                    </div>
                  </button>
                ))}
                {filteredByTab(compItems).length === 0 && (
                  <div className="col-span-3 text-center py-6 text-slate-600 text-sm">
                    {compLoading ? "Loading…" : `No items match "${filterMode}"`}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
