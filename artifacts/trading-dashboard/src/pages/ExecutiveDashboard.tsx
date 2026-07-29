/**
 * ExecutiveDashboard.tsx — Phase 5D.5
 * Single-page operational command centre for ApexQuant AI.
 *
 * READ-ONLY. No mutations of any kind.
 * All data flows from GET /api/executive/summary (one fetch, 60-second auto-refresh).
 * PAPER TRADING / ADVISORY ONLY.
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Activity, AlertCircle, AlertTriangle, BarChart3, Brain,
  CheckCircle, ChevronDown, ChevronRight, Clock, Cpu, Database,
  ExternalLink, Gauge, Globe2, Info, LayoutDashboard, Monitor,
  RefreshCw, Shield, ShieldAlert, Star, TrendingDown, TrendingUp,
  Wifi, Zap,
} from "lucide-react";
import { Link } from "wouter";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface ExecSummary {
  status: string;
  feature_flag?: string;
  executive_score?: {
    total: number;
    label: string;
    components: Record<string, number>;
    weights: Record<string, number>;
  };
  header?: {
    market_status: string;
    ist_time: string;
    market_regime: string;
    paper_trading: boolean;
    active_provider: string;
    watchlist_count: number;
    trading_date: string;
  };
  system_health?: {
    application_health: string;
    scheduler_health: string;
    database_status: string;
    api_status: string;
  };
  portfolio_overview?: {
    portfolio_value: number;
    today_pnl: number;
    net_pnl: number;
    cash_available: number;
    invested_capital: number;
    open_positions: number;
    win_rate: number;
    profit_factor: number;
    drawdown: number;
    total_return_pct: number;
    portfolio_utilisation_pct: number;
    initial_capital: number;
  };
  ai_health?: {
    health_score: number;
    health_label: string;
    prediction_accuracy: number;
    precision: number;
    recall: number;
    avg_confidence: number;
    trend_direction: string;
    accuracy_delta: number;
    calibration_quality: number;
    total_signals: number;
  };
  strategy_overview?: {
    best_strategy: string;
    worst_strategy: string;
    highest_win_rate: string;
    best_profit_factor: string;
    best_regime: string;
    best_sector: string;
    total_net_pnl: number;
    overall_win_rate: number;
    strong_buy_count: number;
    recommendations: Array<{ verdict: string; strategy: string }>;
  };
  execution_quality?: {
    execution_score: number;
    avg_slippage: number;
    avg_fill_delay: number;
    total_trades: number;
    best_execution: number;
    worst_execution: number;
  };
  preopen_intelligence?: {
    top_gap_up: string;
    top_gap_up_pct: number;
    top_gap_down: string;
    top_gap_down_pct: number;
    buy_imbalance: string;
    sell_imbalance: string;
    leading_sector: string;
    provider: string;
    last_refresh: string;
    symbols_analysed: number;
    trading_date: string;
  };
  portfolio_risk?: {
    utilisation: number;
    portfolio_heat: number;
    diversification_score: number;
    top_sector: string;
    sector_concentration: number;
    kill_switch_active: boolean;
    alert_count: number;
  };
  live_alerts?: {
    critical: Array<{ level: string; message?: string }>;
    warnings: Array<{ level: string; message?: string }>;
    info: Array<{ level: string; message?: string }>;
    total_critical: number;
    total_warnings: number;
  };
  market_snapshot?: {
    nifty: { price: number | null; change_pct: number | null };
    bank_nifty: { price: number | null; change_pct: number | null };
    india_vix: { price: number | null; change_pct: number | null };
    market_regime: string;
    market_status: string;
  };
  quick_actions?: Array<{ label: string; href: string }>;
  sections?: Array<{ id: string; title: string; order: number }>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmt = (v: number | null | undefined, dp = 2) =>
  v == null ? "N/A" : v.toFixed(dp);

const fmtInr = (v: number | null | undefined) =>
  v == null
    ? "N/A"
    : `₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

function statusColor(s: string): string {
  const u = (s ?? "").toUpperCase();
  if (["HEALTHY", "CONNECTED", "OPEN", "UP", "ENABLED"].some(x => u.includes(x))) return "text-emerald-400";
  if (["WARN", "DEGRADED", "PARTIAL"].some(x => u.includes(x))) return "text-amber-400";
  if (["DOWN", "ERROR", "CRITICAL", "CLOSED"].some(x => u.includes(x))) return "text-red-400";
  return "text-slate-400";
}

function statusBg(s: string): string {
  const u = (s ?? "").toUpperCase();
  if (["HEALTHY", "CONNECTED", "OPEN", "UP", "ENABLED"].some(x => u.includes(x))) return "bg-emerald-400";
  if (["WARN", "DEGRADED", "PARTIAL"].some(x => u.includes(x))) return "bg-amber-400";
  if (["DOWN", "ERROR", "CRITICAL", "CLOSED"].some(x => u.includes(x))) return "bg-red-400";
  return "bg-slate-500";
}

function scoreColor(s: number): string {
  if (s >= 90) return "text-emerald-400";
  if (s >= 75) return "text-blue-400";
  if (s >= 60) return "text-amber-400";
  if (s >= 40) return "text-orange-400";
  return "text-red-400";
}

function pnlColor(v: number): string {
  return v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-slate-400";
}

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------
function KpiCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className={cn("text-lg font-bold", color ?? "text-slate-100")}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible section card
// ---------------------------------------------------------------------------
function SectionCard({
  title, icon, children, defaultOpen = true,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-slate-900/80 border border-slate-700/60 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-800/40 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2 text-slate-200 font-semibold text-sm">
          {icon}
          {title}
        </div>
        {open
          ? <ChevronDown className="w-4 h-4 text-slate-500" />
          : <ChevronRight className="w-4 h-4 text-slate-500" />}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Executive Score ring
// ---------------------------------------------------------------------------
function ScoreRing({ score, label }: { score: number; label: string }) {
  const r = 52;
  const circ = 2 * Math.PI * r;
  const fill = (Math.min(score, 100) / 100) * circ;
  const color =
    score >= 90 ? "#34d399"
    : score >= 75 ? "#60a5fa"
    : score >= 60 ? "#fbbf24"
    : "#f87171";
  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="130" height="130" viewBox="0 0 130 130">
        <circle cx="65" cy="65" r={r} fill="none" stroke="#1e293b" strokeWidth="14" />
        <circle
          cx="65" cy="65" r={r} fill="none"
          stroke={color} strokeWidth="14"
          strokeDasharray={`${fill} ${circ - fill}`}
          strokeLinecap="round"
          transform="rotate(-90 65 65)"
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
        <text x="65" y="59" textAnchor="middle" fill={color} fontSize="26" fontWeight="bold">
          {Math.round(score)}
        </text>
        <text x="65" y="75" textAnchor="middle" fill="#94a3b8" fontSize="11">/100</text>
      </svg>
      <span className={cn("text-sm font-semibold", scoreColor(score))}>{label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Score component breakdown
// ---------------------------------------------------------------------------
function ScoreBreakdown({ score }: { score: NonNullable<ExecSummary["executive_score"]> }) {
  const labels: Record<string, string> = {
    portfolio_health:  "Portfolio",
    ai_health:         "AI",
    strategy_health:   "Strategy",
    execution_quality: "Execution",
    risk:              "Risk",
    system_health:     "System",
  };
  return (
    <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
      {Object.entries(score.components).map(([k, v]) => (
        <div key={k} className="text-center">
          <p className="text-xs text-slate-400">{labels[k] ?? k}</p>
          <p className={cn("text-base font-bold", scoreColor(v))}>{Math.round(v)}</p>
          <p className="text-xs text-slate-500">
            {Math.round((score.weights[k] ?? 0) * 100)}%
          </p>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page header
// ---------------------------------------------------------------------------
function PageHeader({
  header, onRefresh, loading,
}: {
  header: ExecSummary["header"];
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-3 mb-6">
      <div>
        <div className="flex items-center gap-2">
          <LayoutDashboard className="w-6 h-6 text-blue-400" />
          <h1 className="text-xl font-bold text-slate-100">Executive Dashboard</h1>
          <span className="px-2 py-0.5 text-xs rounded-full bg-amber-900/40 text-amber-300 border border-amber-700/50">
            PAPER / ADVISORY ONLY
          </span>
        </div>
        <p className="text-sm text-slate-400 mt-1">Read-only · Single command centre</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {header && (
          <>
            <div className="flex items-center gap-1.5 text-sm">
              <Globe2 className="w-4 h-4 text-slate-400" />
              <span className={cn("font-medium", statusColor(header.market_status))}>
                NSE {header.market_status}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-sm text-slate-400">
              <Clock className="w-4 h-4" />{header.ist_time}
            </div>
            <span className="flex items-center gap-1.5 text-xs px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded-lg text-slate-300">
              <Zap className="w-3.5 h-3.5 text-blue-400" />{header.market_regime}
            </span>
            <span className="flex items-center gap-1.5 text-xs px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded-lg text-slate-300">
              <Wifi className="w-3.5 h-3.5 text-emerald-400" />{header.active_provider}
            </span>
          </>
        )}
        <button
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-2 bg-blue-800/30 border border-blue-700/50 rounded-lg text-blue-300 text-sm hover:bg-blue-700/40 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
          Refresh
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 1 — System Health
// ---------------------------------------------------------------------------
function SystemHealthSection({ d }: { d: ExecSummary["system_health"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  const items = [
    { label: "Application", value: d.application_health, icon: <Monitor className="w-3.5 h-3.5" /> },
    { label: "Scheduler",   value: d.scheduler_health,   icon: <Clock className="w-3.5 h-3.5" /> },
    { label: "Database",    value: d.database_status,    icon: <Database className="w-3.5 h-3.5" /> },
    { label: "API",         value: d.api_status,         icon: <Cpu className="w-3.5 h-3.5" /> },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {items.map(it => (
        <div key={it.label} className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3 flex items-center gap-2">
          <span className={statusColor(it.value)}>{it.icon}</span>
          <div>
            <p className="text-xs text-slate-400">{it.label}</p>
            <div className="flex items-center gap-1">
              <span className={cn("inline-block w-1.5 h-1.5 rounded-full", statusBg(it.value))} />
              <p className={cn("text-xs font-semibold", statusColor(it.value))}>{it.value}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 2 — Portfolio Overview
// ---------------------------------------------------------------------------
function PortfolioSection({ d }: { d: ExecSummary["portfolio_overview"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      <KpiCard label="Portfolio Value" value={fmtInr(d.portfolio_value)} color="text-blue-300" />
      <KpiCard label="Today P&L"       value={fmtInr(d.today_pnl)}       color={pnlColor(d.today_pnl ?? 0)} sub={`${(d.today_pnl ?? 0) >= 0 ? "+" : ""}${fmt(d.total_return_pct)}%`} />
      <KpiCard label="Net P&L"         value={fmtInr(d.net_pnl)}         color={pnlColor(d.net_pnl ?? 0)} />
      <KpiCard label="Cash Available"  value={fmtInr(d.cash_available)} />
      <KpiCard label="Invested"        value={fmtInr(d.invested_capital)} sub={`${fmt(d.portfolio_utilisation_pct, 1)}% utilised`} />
      <KpiCard label="Open Positions"  value={String(d.open_positions)} />
      <KpiCard label="Win Rate"        value={`${fmt(d.win_rate, 1)}%`} color={d.win_rate >= 55 ? "text-emerald-400" : "text-amber-400"} />
      <KpiCard label="Profit Factor"   value={fmt(d.profit_factor)}     color={(d.profit_factor ?? 0) >= 1.5 ? "text-emerald-400" : "text-amber-400"} />
      <KpiCard label="Max Drawdown"    value={`${fmt(d.drawdown)}%`}    color={(d.drawdown ?? 0) > 5 ? "text-red-400" : "text-emerald-400"} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 3 — AI Health
// ---------------------------------------------------------------------------
function AIHealthSection({ d }: { d: ExecSummary["ai_health"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  const TrendIcon =
    d.trend_direction === "Improving" ? TrendingUp
    : d.trend_direction === "Declining" ? TrendingDown
    : Activity;
  const trendColor =
    d.trend_direction === "Improving" ? "text-emerald-400"
    : d.trend_direction === "Declining" ? "text-red-400"
    : "text-slate-400";
  return (
    <div className="flex flex-col md:flex-row gap-4">
      <div className="flex justify-center items-center shrink-0">
        <ScoreRing score={d.health_score ?? 0} label={d.health_label ?? "N/A"} />
      </div>
      <div className="flex-1 grid grid-cols-2 md:grid-cols-3 gap-3">
        <KpiCard label="Prediction Accuracy" value={`${fmt(d.prediction_accuracy, 1)}%`} color={scoreColor(d.prediction_accuracy ?? 0)} />
        <KpiCard label="Precision"           value={`${fmt(d.precision, 1)}%`}           color={scoreColor(d.precision ?? 0)} />
        <KpiCard label="Recall"              value={`${fmt(d.recall, 1)}%`}              color={scoreColor(d.recall ?? 0)} />
        <KpiCard label="Avg Confidence"      value={`${fmt(d.avg_confidence, 1)}%`} />
        <KpiCard label="Calibration Quality" value={`${fmt(d.calibration_quality, 1)}%`} color={scoreColor(d.calibration_quality ?? 0)} />
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3">
          <p className="text-xs text-slate-400 mb-1">Trend</p>
          <div className="flex items-center gap-1.5">
            <TrendIcon className={cn("w-4 h-4", trendColor)} />
            <span className="text-sm font-semibold text-slate-100">{d.trend_direction}</span>
            <span className="text-xs text-slate-400">
              ({(d.accuracy_delta ?? 0) >= 0 ? "+" : ""}{fmt(d.accuracy_delta, 1)} pp)
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">{d.total_signals} signals</p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 4 — Strategy Overview
// ---------------------------------------------------------------------------
function StrategySection({ d }: { d: ExecSummary["strategy_overview"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        <KpiCard label="Best Strategy"      value={d.best_strategy}       color="text-emerald-400" />
        <KpiCard label="Worst Strategy"     value={d.worst_strategy}      color="text-red-400" />
        <KpiCard label="Highest Win Rate"   value={d.highest_win_rate}    color="text-blue-300" />
        <KpiCard label="Best Profit Factor" value={d.best_profit_factor}  color="text-blue-300" />
        <KpiCard label="Best Regime"        value={d.best_regime} />
        <KpiCard label="Best Sector"        value={d.best_sector} />
        <KpiCard label="Overall Win Rate"   value={`${fmt(d.overall_win_rate, 1)}%`} color={d.overall_win_rate >= 55 ? "text-emerald-400" : "text-amber-400"} />
        <KpiCard label="Net P&L"            value={fmtInr(d.total_net_pnl)} color={pnlColor(d.total_net_pnl)} />
      </div>
      {d.recommendations && d.recommendations.length > 0 && (
        <div>
          <p className="text-xs text-slate-400 mb-2">Top Recommendations</p>
          <div className="flex flex-wrap gap-2">
            {d.recommendations.slice(0, 5).map((r, i) => (
              <span key={i} className={cn(
                "px-2 py-0.5 rounded text-xs font-medium border",
                r.verdict === "STRONG_BUY"
                  ? "bg-emerald-900/50 text-emerald-300 border-emerald-700/50"
                  : r.verdict === "BUY"
                  ? "bg-blue-900/50 text-blue-300 border-blue-700/50"
                  : "bg-slate-800/60 text-slate-300 border-slate-600/50"
              )}>
                {r.verdict} · {r.strategy}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 5 — Execution Quality
// ---------------------------------------------------------------------------
function ExecutionSection({ d }: { d: ExecSummary["execution_quality"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      <KpiCard label="Execution Score" value={fmt(d.execution_score, 1)}    color={scoreColor(d.execution_score ?? 0)} />
      <KpiCard label="Avg Slippage"    value={`${fmt(d.avg_slippage, 3)}%`} color={(d.avg_slippage ?? 0) < 0.2 ? "text-emerald-400" : "text-amber-400"} />
      <KpiCard label="Avg Fill Delay"  value={`${fmt(d.avg_fill_delay, 2)}s`} color={(d.avg_fill_delay ?? 0) < 1 ? "text-emerald-400" : "text-amber-400"} />
      <KpiCard label="Best Execution"  value={fmt(d.best_execution, 1)}     color="text-emerald-400" />
      <KpiCard label="Worst Execution" value={fmt(d.worst_execution, 1)}    color="text-red-400" sub={`${d.total_trades} trades`} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 6 — Pre-Open Intelligence
// ---------------------------------------------------------------------------
function PreOpenSection({ d }: { d: ExecSummary["preopen_intelligence"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <KpiCard label="Top Gap Up"     value={d.top_gap_up}    color="text-emerald-400" sub={`+${fmt(d.top_gap_up_pct, 2)}%`} />
      <KpiCard label="Top Gap Down"   value={d.top_gap_down}  color="text-red-400"     sub={`${fmt(d.top_gap_down_pct, 2)}%`} />
      <KpiCard label="Buy Imbalance"  value={d.buy_imbalance}  color="text-blue-300" />
      <KpiCard label="Sell Imbalance" value={d.sell_imbalance} color="text-amber-400" />
      <KpiCard label="Leading Sector" value={d.leading_sector} />
      <KpiCard label="Provider"       value={d.provider} />
      <KpiCard label="Last Refresh"   value={d.last_refresh}   color="text-slate-400" />
      <KpiCard label="Symbols"        value={String(d.symbols_analysed)} sub={d.trading_date} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 7 — Portfolio Risk
// ---------------------------------------------------------------------------
function RiskSection({ d }: { d: ExecSummary["portfolio_risk"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  return (
    <div className="space-y-3">
      {d.kill_switch_active && (
        <div className="flex items-center gap-2 bg-red-900/30 border border-red-700/50 rounded-lg px-3 py-2">
          <ShieldAlert className="w-4 h-4 text-red-400" />
          <span className="text-sm text-red-300 font-semibold">Kill Switch Active — trading halted</span>
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <KpiCard label="Utilisation"     value={`${fmt(d.utilisation, 1)}%`}           color={(d.utilisation ?? 0) > 80 ? "text-red-400" : "text-emerald-400"} />
        <KpiCard label="Portfolio Heat"  value={`${fmt(d.portfolio_heat, 1)}%`}        color={(d.portfolio_heat ?? 0) > 70 ? "text-amber-400" : "text-slate-200"} />
        <KpiCard label="Diversification" value={fmt(d.diversification_score, 1)}       color={scoreColor(d.diversification_score ?? 0)} />
        <KpiCard label="Top Sector"      value={d.top_sector}                          sub={`${fmt(d.sector_concentration, 1)}% conc.`} />
        <KpiCard label="Risk Alerts"     value={String(d.alert_count)}                 color={(d.alert_count ?? 0) > 0 ? "text-amber-400" : "text-emerald-400"} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 8 — Live Alerts
// ---------------------------------------------------------------------------
function AlertsSection({ d }: { d: ExecSummary["live_alerts"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No alerts</p>;
  if (!d.total_critical && !d.total_warnings) {
    return (
      <div className="flex items-center gap-2 text-emerald-400 text-sm">
        <CheckCircle className="w-4 h-4" />
        All systems nominal — no active alerts
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {d.critical.map((a, i) => (
        <div key={i} className="flex items-start gap-2 bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2">
          <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
          <span className="text-sm text-red-300">{(a as Record<string, unknown>).message as string ?? "Critical alert"}</span>
        </div>
      ))}
      {d.warnings.map((a, i) => (
        <div key={i} className="flex items-start gap-2 bg-amber-900/20 border border-amber-700/40 rounded-lg px-3 py-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <span className="text-sm text-amber-300">{(a as Record<string, unknown>).message as string ?? "Warning"}</span>
        </div>
      ))}
      {d.info.map((a, i) => (
        <div key={i} className="flex items-start gap-2 bg-blue-900/20 border border-blue-700/40 rounded-lg px-3 py-2">
          <Info className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
          <span className="text-sm text-blue-300">{(a as Record<string, unknown>).message as string ?? "Info"}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 9 — Market Snapshot
// ---------------------------------------------------------------------------
function MarketSection({ d }: { d: ExecSummary["market_snapshot"] }) {
  if (!d) return <p className="text-slate-500 text-sm">No data</p>;
  const indices = [
    { label: "NIFTY 50",   data: d.nifty },
    { label: "BANK NIFTY", data: d.bank_nifty },
    { label: "INDIA VIX",  data: d.india_vix },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {indices.map(idx => (
        <div key={idx.label} className="bg-slate-800/60 border border-slate-700/50 rounded-lg p-3">
          <p className="text-xs text-slate-400">{idx.label}</p>
          <p className="text-lg font-bold text-slate-100">
            {idx.data.price != null ? idx.data.price.toLocaleString("en-IN") : "—"}
          </p>
          {idx.data.change_pct != null && (
            <p className={cn("text-xs font-medium", pnlColor(idx.data.change_pct))}>
              {idx.data.change_pct >= 0 ? "+" : ""}{idx.data.change_pct.toFixed(2)}%
            </p>
          )}
        </div>
      ))}
      <KpiCard label="Market Regime" value={d.market_regime} sub={d.market_status} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 10 — Quick Actions
// ---------------------------------------------------------------------------
function QuickActionsSection({ actions }: { actions: ExecSummary["quick_actions"] }) {
  if (!actions?.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {actions.map(a => (
        <Link key={a.href} href={a.href}>
          <a className="flex items-center gap-1.5 px-3 py-2 bg-blue-800/30 border border-blue-700/50 rounded-lg text-blue-300 text-sm hover:bg-blue-700/40 transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />
            {a.label}
          </a>
        </Link>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function ExecutiveDashboard() {
  const { data, isLoading, isError, error, refetch } = useQuery<ExecSummary>({
    queryKey: ["executive-summary"],
    queryFn: () => apiJson<ExecSummary>("executive/summary"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 gap-3 text-slate-400">
        <RefreshCw className="w-5 h-5 animate-spin" />
        <span>Loading Executive Dashboard…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-6">
        <div className="bg-red-900/20 border border-red-700/50 rounded-xl p-4 text-red-300 flex items-center gap-2">
          <AlertCircle className="w-5 h-5" />{String(error)}
        </div>
      </div>
    );
  }

  if (!data || data.status === "DISABLED") {
    return (
      <div className="p-6">
        <div className="bg-amber-900/20 border border-amber-700/50 rounded-xl p-6 text-center">
          <LayoutDashboard className="w-10 h-10 text-amber-400 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-amber-300 mb-2">Executive Dashboard is disabled</h2>
          <p className="text-sm text-slate-400">
            Set{" "}
            <code className="bg-slate-800 px-1.5 py-0.5 rounded text-amber-300">
              EXECUTIVE_DASHBOARD_ENABLED=true
            </code>{" "}
            to enable.
          </p>
        </div>
      </div>
    );
  }

  const d = data;

  return (
    <div className="p-4 md:p-6 max-w-[1600px] mx-auto space-y-4">
      <PageHeader header={d.header} onRefresh={() => refetch()} loading={isLoading} />

      {/* Executive Score */}
      {d.executive_score && (
        <div className="bg-slate-900/80 border border-blue-800/50 rounded-xl p-4">
          <div className="flex flex-col md:flex-row items-center gap-6">
            <ScoreRing score={d.executive_score.total} label={d.executive_score.label} />
            <div className="flex-1 w-full">
              <p className="text-xs text-slate-400 uppercase tracking-wider mb-3 font-semibold">
                Score Components
              </p>
              <ScoreBreakdown score={d.executive_score} />
            </div>
          </div>
        </div>
      )}

      {/* 2-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SectionCard title="System Health"      icon={<Monitor   className="w-4 h-4 text-blue-400" />}>
          <SystemHealthSection d={d.system_health} />
        </SectionCard>

        <SectionCard title="Portfolio Overview" icon={<TrendingUp className="w-4 h-4 text-emerald-400" />}>
          <PortfolioSection d={d.portfolio_overview} />
        </SectionCard>

        <SectionCard title="AI Health"          icon={<Brain      className="w-4 h-4 text-purple-400" />}>
          <AIHealthSection d={d.ai_health} />
        </SectionCard>

        <SectionCard title="Strategy Overview"  icon={<Zap        className="w-4 h-4 text-amber-400" />}>
          <StrategySection d={d.strategy_overview} />
        </SectionCard>

        <SectionCard title="Execution Quality"  icon={<Gauge      className="w-4 h-4 text-blue-400" />}>
          <ExecutionSection d={d.execution_quality} />
        </SectionCard>

        <SectionCard title="Pre-Open Intelligence" icon={<Activity className="w-4 h-4 text-teal-400" />}>
          <PreOpenSection d={d.preopen_intelligence} />
        </SectionCard>

        <SectionCard title="Portfolio Risk"     icon={<Shield     className="w-4 h-4 text-red-400" />}>
          <RiskSection d={d.portfolio_risk} />
        </SectionCard>

        <SectionCard title="Live Alerts"        icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}>
          <AlertsSection d={d.live_alerts} />
        </SectionCard>
      </div>

      {/* Full-width sections */}
      <SectionCard title="Market Snapshot" icon={<Globe2 className="w-4 h-4 text-blue-400" />}>
        <MarketSection d={d.market_snapshot} />
      </SectionCard>

      <SectionCard title="Quick Actions" icon={<Star className="w-4 h-4 text-amber-400" />}>
        <QuickActionsSection actions={d.quick_actions} />
      </SectionCard>

      <p className="text-xs text-slate-600 text-center pb-2">
        Executive Dashboard · Read-only · Paper Trading · Advisory Only · ApexQuant AI
      </p>
    </div>
  );
}
