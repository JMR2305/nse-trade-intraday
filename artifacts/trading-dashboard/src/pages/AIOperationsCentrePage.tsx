/**
 * AIOperationsCentrePage — 🧠 AI Operations Centre
 *
 * Real-time operational dashboard for the complete ApexQuant AI Multi-Agent
 * pipeline.  READ-ONLY · ADVISORY ONLY · No trading controls.
 *
 * Sections
 * ──────────
 * 1. Platform Status Bar
 * 2. Animated Pipeline Flow (12 nodes)
 * 3. Agent Cards  (expandable, one per agent)
 * 4. Pipeline Funnel (counts at every stage)
 * 5. Live Event Log
 */

import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Activity, AlertTriangle, Brain, CheckCircle2, ChevronDown,
  Cpu, Database, Eye, GitBranch, Globe, Heart, Info,
  Layers, RefreshCcw, Server, Shield, TrendingUp, Wifi,
  XCircle, Zap, Clock, BarChart2, BookOpen, Network,
  FlaskConical, Radio, Swords, Gauge,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AgentState {
  name: string;
  agent_id: string;
  enabled: boolean;
  status: "ACTIVE" | "WAITING" | "ERROR" | "DISABLED" | "UNKNOWN";
  health_pct: number;
  last_refresh_date: string;
  last_refresh_time: string;
  last_refresh_ts: string | null;
  avg_processing_ms: number;
  current_activity: string;
  stocks_in: number;
  stocks_out: number;
  stocks_rejected: number;
  rejection_reason: string;
  errors: string[];
  warnings: string[];
  details: Record<string, unknown>;
}

interface PipelineNode {
  id: string;
  label: string;
  agent_key: string;
  status: "ACTIVE" | "WAITING" | "ERROR" | "DISABLED" | "UNKNOWN";
  health_pct: number;
  stocks_out: number;
}

interface OpsSnapshot {
  generated_at: string;
  platform: {
    health_pct: number;
    status: string;
    scan_id: string;
    scan_number: number;
    scan_status: string;
    market_state: string;
    trading_session: string;
    current_time_ist: string;
    last_refresh_ist: string;
    next_refresh_est: string;
    scan_interval_min: number;
  };
  pipeline: {
    universe_loaded: number;
    stocks_reviewed: number;
    passed_market_data: number;
    passed_research: number;
    passed_intelligence: number;
    passed_monitoring: number;
    passed_strategy: number;
    passed_risk: number;
    buy_recommendations: number;
    paper_orders_executed: number;
    open_positions: number;
  };
  pipeline_nodes: PipelineNode[];
  agents: Record<string, AgentState>;
}

interface TimelineEvent {
  timestamp: string;
  ist_time?: string;
  event_type: string;
  title: string;
  description?: string;
  symbol?: string;
  severity?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusColour(s: string) {
  switch (s) {
    case "ACTIVE":   return "text-emerald-400";
    case "WAITING":  return "text-amber-400";
    case "ERROR":    return "text-rose-400";
    case "DISABLED": return "text-slate-500";
    default:         return "text-slate-400";
  }
}
function statusBg(s: string) {
  switch (s) {
    case "ACTIVE":   return "bg-emerald-950/40 border-emerald-700/40";
    case "WAITING":  return "bg-amber-950/30 border-amber-700/40";
    case "ERROR":    return "bg-rose-950/40 border-rose-700/40";
    case "DISABLED": return "bg-slate-900/60 border-slate-800/40";
    default:         return "bg-slate-900/60 border-slate-800/40";
  }
}
function statusIcon(s: string, cls = "w-3.5 h-3.5") {
  switch (s) {
    case "ACTIVE":   return <CheckCircle2 className={`${cls} text-emerald-400`} />;
    case "WAITING":  return <Clock className={`${cls} text-amber-400`} />;
    case "ERROR":    return <XCircle className={`${cls} text-rose-400`} />;
    case "DISABLED": return <XCircle className={`${cls} text-slate-500`} />;
    default:         return <Activity className={`${cls} text-slate-500`} />;
  }
}
function healthColour(pct: number) {
  if (pct >= 90) return "text-emerald-400";
  if (pct >= 70) return "text-amber-400";
  return "text-rose-400";
}
function healthBarColour(pct: number) {
  if (pct >= 90) return "bg-emerald-500";
  if (pct >= 70) return "bg-amber-500";
  return "bg-rose-500";
}

const AGENT_ICONS: Record<string, React.ReactNode> = {
  supervisor:          <Network className="w-4 h-4" />,
  "market-data":       <Globe className="w-4 h-4" />,
  research:            <FlaskConical className="w-4 h-4" />,
  "market-intelligence":<Brain className="w-4 h-4" />,
  monitoring:          <Radio className="w-4 h-4" />,
  strategy:            <Swords className="w-4 h-4" />,
  risk:                <Shield className="w-4 h-4" />,
  "ai-decision":       <Cpu className="w-4 h-4" />,
  execution:           <Zap className="w-4 h-4" />,
  learning:            <BookOpen className="w-4 h-4" />,
  knowledge:           <Database className="w-4 h-4" />,
  operations:          <Gauge className="w-4 h-4" />,
};

function fmtMs(ms: number) {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── Platform Status Bar ───────────────────────────────────────────────────────

function PlatformStatusBar({ data, loading }: { data?: OpsSnapshot; loading: boolean }) {
  const p = data?.platform;
  const health = p?.health_pct ?? 0;

  const kpis = [
    { label: "Platform Health",  value: loading ? "—" : `${health}%`,
      cls: health >= 90 ? "text-emerald-400" : health >= 70 ? "text-amber-400" : "text-rose-400" },
    { label: "Market State",     value: loading ? "—" : (p?.market_state ?? "—"),
      cls: p?.market_state === "OPEN" ? "text-emerald-400" : "text-amber-400" },
    { label: "Scan Status",      value: loading ? "—" : (p?.scan_status ?? "—"),
      cls: "text-blue-300" },
    { label: "Scan #",           value: loading ? "—" : (p?.scan_number ? `#${p.scan_number}` : p?.scan_id ?? "—"),
      cls: "text-slate-300 font-mono text-xs" },
    { label: "Session",          value: loading ? "—" : (p?.trading_session ?? "—"),
      cls: "text-teal-300" },
    { label: "Current Time",     value: loading ? "—" : (p?.current_time_ist ?? "—"),
      cls: "text-slate-300 font-mono" },
    { label: "Last Refresh",     value: loading ? "—" : (p?.last_refresh_ist ?? "—"),
      cls: "text-slate-400 font-mono text-xs" },
    { label: "Next Refresh",     value: loading ? "—" : (p?.next_refresh_est ?? "—"),
      cls: "text-slate-400 font-mono text-xs" },
  ];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
          Platform Status
        </h2>
        {!loading && p && (
          <Badge className={`text-xs px-2 py-0 ${health >= 80
            ? "bg-emerald-950 border-emerald-700/50 text-emerald-300"
            : "bg-amber-950 border-amber-700/50 text-amber-300"}`}>
            {health >= 80 ? "OPERATIONAL" : "DEGRADED"}
          </Badge>
        )}
      </div>

      {/* Health bar */}
      <div className="mb-3">
        <div className="flex justify-between text-[10px] text-slate-500 mb-1">
          <span>Overall Health</span>
          <span className={healthColour(health)}>{health}%</span>
        </div>
        <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-700 rounded-full ${healthBarColour(health)}`}
            style={{ width: `${health}%` }}
          />
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {kpis.map(k => (
          <div key={k.label} className="bg-slate-800/40 rounded-lg p-2">
            <p className="text-[10px] text-slate-500 mb-0.5">{k.label}</p>
            {loading
              ? <Skeleton className="h-4 w-full" />
              : <p className={`text-xs font-semibold ${k.cls}`}>{k.value}</p>
            }
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Pipeline Flow ─────────────────────────────────────────────────────────────

function PipelineFlow({ nodes, loading }: { nodes?: PipelineNode[]; loading: boolean }) {
  const displayNodes = nodes ?? [
    { id: "supervisor", label: "Supervisor", agent_key: "supervisor", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "market_data", label: "Market Data", agent_key: "market_data", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "research", label: "Research", agent_key: "research", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "market_intelligence", label: "Intelligence", agent_key: "market_intelligence", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "monitoring", label: "Monitoring", agent_key: "monitoring", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "strategy", label: "Strategy", agent_key: "strategy", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "risk", label: "Risk", agent_key: "risk", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "ai_decision", label: "AI Decision", agent_key: "ai_decision", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "execution", label: "Execution", agent_key: "execution", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "learning", label: "Learning", agent_key: "learning", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "knowledge", label: "Knowledge", agent_key: "knowledge", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
    { id: "operations", label: "Operations", agent_key: "operations", status: "UNKNOWN", health_pct: 0, stocks_out: 0 },
  ] as PipelineNode[];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        <GitBranch className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
          AI Pipeline Flow
        </h2>
        <span className="text-[10px] text-slate-600 ml-auto">
          🟢 Running  🟡 Waiting  🔴 Error  ⚫ Disabled
        </span>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="flex items-center gap-1 min-w-max">
          {displayNodes.map((node, idx) => {
            const dotCls =
              node.status === "ACTIVE"   ? "bg-emerald-400 animate-pulse shadow-emerald-400/50 shadow-sm" :
              node.status === "WAITING"  ? "bg-amber-400" :
              node.status === "ERROR"    ? "bg-rose-400 animate-pulse shadow-rose-400/50 shadow-sm" :
              node.status === "DISABLED" ? "bg-slate-600" :
                                           "bg-slate-700";
            const ringCls =
              node.status === "ACTIVE"   ? "ring-emerald-500/40" :
              node.status === "WAITING"  ? "ring-amber-500/30" :
              node.status === "ERROR"    ? "ring-rose-500/40" :
                                           "ring-slate-700/30";

            return (
              <div key={node.id} className="flex items-center">
                <div className={`flex flex-col items-center p-2 rounded-lg ring-1 ${ringCls}
                  ${loading ? "opacity-50" : ""} min-w-[72px] text-center`}>
                  <div className={`w-2.5 h-2.5 rounded-full mb-1 ${dotCls}`} />
                  <span className="text-[10px] font-medium text-slate-300 leading-tight">
                    {node.label}
                  </span>
                  {!loading && node.stocks_out > 0 && (
                    <span className="text-[9px] text-teal-400 font-mono mt-0.5">
                      {node.stocks_out}
                    </span>
                  )}
                </div>
                {idx < displayNodes.length - 1 && (
                  <div className={`w-6 h-px mx-0.5 ${
                    node.status === "ACTIVE" ? "bg-emerald-600/60" :
                    node.status === "WAITING" ? "bg-amber-600/40" :
                    "bg-slate-700/60"
                  }`} />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Agent Card ────────────────────────────────────────────────────────────────

function AgentCard({ agent, agentKey }: { agent?: AgentState; agentKey: string }) {
  const [open, setOpen] = useState(false);

  if (!agent) {
    return (
      <div className="border rounded-xl p-4 bg-slate-900/40 border-slate-800/40">
        <Skeleton className="h-5 w-40 mb-2" />
        <Skeleton className="h-3 w-full" />
      </div>
    );
  }

  const icon = AGENT_ICONS[agent.agent_id] ?? <Server className="w-4 h-4" />;

  // Per-agent detail rendering
  const renderDetails = () => {
    const d = agent.details;
    if (!d) return null;

    const rows: Array<[string, string | number | boolean | null | undefined]> = [];

    // Common overrides per agent
    if (agentKey === "supervisor") {
      rows.push(
        ["Total Agents",      d.total_agents as number],
        ["Running",           d.running_agents as number],
        ["Error Agents",      d.error_agents as number],
        ["Health Score",      `${(d.health_score as number ?? 0).toFixed(0)}%`],
        ["Snapshots Published", d.snapshots_published as number],
        ["Alerts",            d.alert_count as number],
      );
    } else if (agentKey === "market_data") {
      rows.push(
        ["Data Provider",     d.data_provider as string],
        ["Coverage",          `${(d.coverage_pct as number ?? 0).toFixed(0)}%`],
        ["NIFTY 50",          d.nifty50_price ? `₹${(d.nifty50_price as number).toLocaleString()}  (${(d.nifty50_change_pct as number) >= 0 ? "+" : ""}${(d.nifty50_change_pct as number ?? 0).toFixed(2)}%)` : "—"],
        ["India VIX",         d.india_vix ? String(d.india_vix) : "—"],
        ["Market Regime",     d.market_regime as string],
        ["Strongest Sector",  d.strongest_sector as string],
        ["Weakest Sector",    d.weakest_sector as string],
        ["Failed Symbols",    (d.failed_symbols as string[])?.join(", ") || "None"],
      );
    } else if (agentKey === "research") {
      rows.push(
        ["News Processed",    d.news_processed as number],
        ["Corporate Actions", d.corporate_actions as number],
        ["Sentiment +ve",     d.sentiment_positive as number],
        ["Sentiment neutral", d.sentiment_neutral as number],
        ["Sentiment -ve",     d.sentiment_negative as number],
      );
    } else if (agentKey === "market_intelligence") {
      rows.push(
        ["Market Regime",     d.market_regime as string],
        ["Liquidity",         d.liquidity_condition as string],
        ["Volatility",        d.volatility_regime as string],
        ["Regime Confidence", `${(d.regime_confidence as number ?? 0).toFixed(0)}%`],
      );
    } else if (agentKey === "monitoring") {
      rows.push(
        ["Symbols Monitored", d.symbols_monitored as number],
        ["Breakouts",         d.breakouts as number],
        ["Volume Spikes",     d.volume_spikes as number],
        ["Gap Events",        d.gap_events as number],
        ["Momentum Events",   d.momentum_events as number],
        ["RS Events",         d.rs_events as number],
        ["Total Events",      d.total_events as number],
        ["Candidates",        d.candidates as number],
      );
    } else if (agentKey === "strategy") {
      rows.push(
        ["Strategies Registered", d.strategies_registered as number],
        ["Symbols Evaluated",     d.symbols_evaluated as number],
        ["Top Strategy",          d.top_strategy as string || "—"],
        ["Highest Confidence",    `${(d.highest_confidence as number ?? 0).toFixed(0)}%`],
        ["Top Symbol",            d.highest_confidence_symbol as string || "—"],
        ["Breakout Signals",      d.breakout_count as number],
        ["Momentum Signals",      d.momentum_count as number],
        ["VWAP Signals",          d.vwap_count as number],
        ["ORB Signals",           d.orb_count as number],
        ["Gap Signals",           d.gap_count as number],
      );
    } else if (agentKey === "risk") {
      rows.push(
        ["Candidates Evaluated", d.candidates_evaluated as number],
        ["Approved",             d.approved as number],
        ["Rejected",             d.rejected as number],
        ["Capital Used",         d.capital_used as string || "—"],
        ["Risk Score",           d.risk_score ? `${(d.risk_score as number).toFixed(1)}` : "—"],
        ["R:R",                  d.reward_risk ? `${(d.reward_risk as number).toFixed(2)}×` : "—"],
      );
      if (Array.isArray(d.rejection_reasons) && (d.rejection_reasons as string[]).length > 0) {
        (d.rejection_reasons as string[]).forEach((r, i) =>
          rows.push([`Rejection ${i + 1}`, r]));
      }
    } else if (agentKey === "ai_decision") {
      rows.push(
        ["Total Candidates",    d.total_candidates as number],
        ["BUY Candidates",      d.buy_candidate as number],
        ["SELL Candidates",     d.sell_candidate as number],
        ["WATCH",               d.watch as number],
        ["HOLD",                d.hold as number],
        ["AVOID",               d.avoid as number],
        ["Avg Confidence",      `${(d.avg_confidence as number ?? 0).toFixed(0)}%`],
        ["Market Regime",       d.market_regime as string],
        ["Decision Latency",    fmtMs(d.decision_latency_ms as number)],
      );
    } else if (agentKey === "execution") {
      rows.push(
        ["Paper BUY Orders",    d.paper_buy_orders as number],
        ["Paper SELL Orders",   d.paper_sell_orders as number],
        ["Open Positions",      d.open_positions as number],
        ["Closed Positions",    d.closed_positions as number],
        ["Capital Used",        d.capital_used ? `₹${(d.capital_used as number).toLocaleString()}` : "—"],
        ["Capital Available",   d.capital_available ? `₹${(d.capital_available as number).toLocaleString()}` : "—"],
      );
      if (Array.isArray(d.execution_errors) && (d.execution_errors as string[]).length > 0) {
        (d.execution_errors as string[]).forEach((e, i) =>
          rows.push([`Error ${i + 1}`, e]));
      }
    } else if (agentKey === "learning") {
      rows.push(
        ["Trades Analysed",    d.trades_analysed as number],
        ["Winning Trades",     d.winning_trades as number],
        ["Losing Trades",      d.losing_trades as number],
        ["Lessons Generated",  d.lessons_generated as number],
        ["Knowledge Updated",  d.knowledge_updated ? "Yes" : "No"],
      );
    } else if (agentKey === "knowledge") {
      rows.push(
        ["Knowledge Records",  d.knowledge_records as number],
        ["Learning Sessions",  d.learning_sessions as number],
        ["Reports Generated",  d.reports_generated as number],
        ["Last Update",        d.last_update as string],
      );
    } else if (agentKey === "operations") {
      rows.push(
        ["CPU Usage",          `${d.cpu_pct as number ?? 0}%`],
        ["Memory Usage",       `${d.memory_pct as number ?? 0}%`],
        ["Queue Size",         d.queue_size as number],
        ["Heartbeat",          d.heartbeat as string],
        ["Database",           (d.database_ok as boolean) ? "OK" : "⚠ Unavailable"],
        ["API Status",         (d.api_status_ok as boolean) ? "OK" : "⚠ Degraded"],
        ["System Health",      d.system_health as string],
      );
    }

    if (rows.length === 0) return null;

    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1.5 mt-3">
        {rows.map(([label, value]) => (
          <div key={label}>
            <p className="text-[10px] text-slate-500">{label}</p>
            <p className="text-xs text-slate-300 font-mono truncate">
              {value == null ? "—" : String(value) || "—"}
            </p>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className={`border rounded-xl overflow-hidden ${statusBg(agent.status)}`}>
      {/* Card header — always visible */}
      <button
        className="w-full flex items-center justify-between gap-3 p-3 hover:bg-white/5 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={statusColour(agent.status)}>{icon}</span>
          <div className="min-w-0 text-left">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-semibold text-slate-200 truncate">{agent.name}</span>
              {statusIcon(agent.status)}
            </div>
            <p className="text-[10px] text-slate-500 truncate">{agent.current_activity}</p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {/* In / Out counts */}
          <div className="hidden sm:flex items-center gap-2 text-[10px]">
            {agent.stocks_in > 0 && (
              <>
                <span className="text-slate-500">in <span className="text-slate-300 font-mono">{agent.stocks_in}</span></span>
                <span className="text-slate-600">→</span>
                <span className="text-slate-500">out <span className={`font-mono ${agent.stocks_out > 0 ? "text-emerald-300" : "text-slate-400"}`}>{agent.stocks_out}</span></span>
              </>
            )}
          </div>
          {/* Health % */}
          <span className={`text-xs font-mono font-bold ${healthColour(agent.health_pct)}`}>
            {agent.enabled ? `${agent.health_pct}%` : "—"}
          </span>
          <ChevronDown className={`w-3.5 h-3.5 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
        </div>
      </button>

      {/* Expanded body */}
      {open && (
        <div className="border-t border-slate-800/40 px-3 pb-3 pt-2">
          {/* Common fields */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1.5">
            <div>
              <p className="text-[10px] text-slate-500">Last Refresh Date</p>
              <p className="text-xs text-slate-300 font-mono">{agent.last_refresh_date}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500">Last Refresh Time</p>
              <p className="text-xs text-slate-300 font-mono">{agent.last_refresh_time}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500">Avg Processing</p>
              <p className="text-xs text-slate-300 font-mono">{fmtMs(agent.avg_processing_ms)}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500">Status</p>
              <p className={`text-xs font-bold ${statusColour(agent.status)}`}>{agent.status}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500">Stocks In</p>
              <p className="text-xs text-slate-300 font-mono">{agent.stocks_in}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500">Stocks Out</p>
              <p className="text-xs font-mono text-emerald-300">{agent.stocks_out}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500">Rejected</p>
              <p className={`text-xs font-mono ${agent.stocks_rejected > 0 ? "text-rose-300" : "text-slate-400"}`}>
                {agent.stocks_rejected}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-slate-500">Health</p>
              <div className="flex items-center gap-1.5">
                <div className="flex-1 h-1 bg-slate-800 rounded-full">
                  <div className={`h-full rounded-full ${healthBarColour(agent.health_pct)}`}
                       style={{ width: `${agent.health_pct}%` }} />
                </div>
                <span className={`text-xs font-mono ${healthColour(agent.health_pct)}`}>
                  {agent.health_pct}%
                </span>
              </div>
            </div>
          </div>

          {/* Rejection reason */}
          {agent.stocks_out === 0 && (
            <div className="mt-2 rounded-lg bg-amber-950/30 border border-amber-800/30 px-2.5 py-1.5">
              <p className="text-[10px] text-amber-300 flex items-start gap-1.5">
                <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-0.5" />
                {agent.rejection_reason || `No ${agentKey === "execution" ? "orders" : "stocks"} forwarded this cycle.`}
              </p>
            </div>
          )}
          {agent.stocks_out > 0 && agent.rejection_reason && (
            <div className="mt-2 rounded-lg bg-slate-800/30 px-2.5 py-1.5">
              <p className="text-[10px] text-slate-400 flex items-start gap-1.5">
                <Info className="w-3 h-3 flex-shrink-0 mt-0.5" />
                {agent.rejection_reason}
              </p>
            </div>
          )}

          {/* Agent-specific details */}
          {renderDetails()}

          {/* Errors */}
          {agent.errors.length > 0 && (
            <div className="mt-2 space-y-1">
              {agent.errors.map((e, i) => (
                <p key={i} className="text-[10px] text-rose-400 flex items-start gap-1">
                  <XCircle className="w-3 h-3 flex-shrink-0 mt-0.5" /> {e}
                </p>
              ))}
            </div>
          )}
          {/* Warnings */}
          {agent.warnings.length > 0 && (
            <div className="mt-1 space-y-0.5">
              {agent.warnings.map((w, i) => (
                <p key={i} className="text-[10px] text-amber-400 flex items-start gap-1">
                  <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-0.5" /> {w}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Pipeline Funnel ───────────────────────────────────────────────────────────

function PipelineFunnel({ pipeline, loading }: {
  pipeline?: OpsSnapshot["pipeline"]; loading: boolean;
}) {
  const stages = pipeline ? [
    { label: "Universe Loaded",        count: pipeline.universe_loaded },
    { label: "Stocks Reviewed",        count: pipeline.stocks_reviewed },
    { label: "Passed Market Data",     count: pipeline.passed_market_data },
    { label: "Passed Research",        count: pipeline.passed_research },
    { label: "Passed Intelligence",    count: pipeline.passed_intelligence },
    { label: "Passed Monitoring",      count: pipeline.passed_monitoring },
    { label: "Passed Strategy",        count: pipeline.passed_strategy },
    { label: "Passed Risk",            count: pipeline.passed_risk },
    { label: "BUY Recommendations",   count: pipeline.buy_recommendations },
    { label: "Paper Orders Executed", count: pipeline.paper_orders_executed },
    { label: "Open Positions",        count: pipeline.open_positions },
  ] : [];

  const maxCount = Math.max(...stages.map(s => s.count), 1);

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        <Layers className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
          Pipeline Funnel
        </h2>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[...Array(11)].map((_, i) => <Skeleton key={i} className="h-7 w-full rounded" />)}
        </div>
      ) : (
        <div className="space-y-1.5">
          {stages.map((s, idx) => {
            const prev = idx > 0 ? stages[idx - 1].count : s.count;
            const drop = prev > 0 ? Math.round(((prev - s.count) / prev) * 100) : 0;
            const barPct = (s.count / maxCount) * 100;
            const isBottleneck = drop > 50 && idx > 0;
            return (
              <div key={s.label}>
                <div className="flex items-center gap-2">
                  <div className="w-40 flex-shrink-0 text-right">
                    <span className="text-[10px] text-slate-400">{s.label}</span>
                  </div>
                  <div className="flex-1 h-5 bg-slate-800/60 rounded relative overflow-hidden">
                    <div
                      className={`h-full rounded transition-all duration-500 ${
                        isBottleneck ? "bg-amber-600/60" :
                        idx >= stages.length - 2 ? "bg-emerald-600/60" :
                        "bg-teal-700/50"
                      }`}
                      style={{ width: `${barPct}%` }}
                    />
                    <span className="absolute right-2 top-0 bottom-0 flex items-center text-[10px] font-mono font-bold text-slate-300">
                      {s.count}
                    </span>
                  </div>
                  {drop > 0 && idx > 0 && (
                    <span className={`text-[9px] w-12 flex-shrink-0 ${drop > 50 ? "text-amber-400" : "text-slate-600"}`}>
                      -{drop}%
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Live Event Log ────────────────────────────────────────────────────────────

function LiveEventLog() {
  const { data, isLoading } = useQuery<{ events: TimelineEvent[] }>({
    queryKey: ["ops-centre", "event-log"],
    queryFn:  () => apiJson("/phase11/timeline?limit=30"),
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
  });

  const events = data?.events ?? [];

  function evIcon(type: string) {
    const t = type.toLowerCase();
    if (t.includes("buy") || t.includes("entry"))  return <TrendingUp className="w-3 h-3 text-emerald-400 flex-shrink-0" />;
    if (t.includes("sell") || t.includes("exit"))  return <TrendingUp className="w-3 h-3 text-rose-400 flex-shrink-0 rotate-180" />;
    if (t.includes("scan"))    return <Radio className="w-3 h-3 text-blue-400 flex-shrink-0" />;
    if (t.includes("reject"))  return <XCircle className="w-3 h-3 text-amber-400 flex-shrink-0" />;
    if (t.includes("error"))   return <AlertTriangle className="w-3 h-3 text-rose-400 flex-shrink-0" />;
    if (t.includes("learn"))   return <BookOpen className="w-3 h-3 text-violet-400 flex-shrink-0" />;
    return <Activity className="w-3 h-3 text-slate-500 flex-shrink-0" />;
  }

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
          Live Event Log
        </h2>
        <Badge className="text-[10px] bg-teal-950/60 border-teal-700/40 text-teal-300 ml-auto">
          Auto-refresh 15s
        </Badge>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}
        </div>
      ) : events.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-6">No events yet this session</p>
      ) : (
        <div className="space-y-1.5 max-h-96 overflow-y-auto pr-1">
          {events.map((ev, i) => (
            <div key={i} className="flex items-start gap-2.5 rounded-lg px-2 py-1.5 hover:bg-slate-800/30 transition-colors">
              {evIcon(ev.event_type ?? "")}
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  <span className="text-[10px] font-mono text-slate-500 flex-shrink-0">
                    {ev.ist_time || ev.timestamp?.slice(11, 19) || "—"}
                  </span>
                  {ev.symbol && (
                    <span className="text-[10px] font-mono text-teal-300 flex-shrink-0">{ev.symbol}</span>
                  )}
                  <span className="text-xs text-slate-300 truncate">{ev.title}</span>
                </div>
                {ev.description && (
                  <p className="text-[10px] text-slate-500 leading-tight mt-0.5 truncate">
                    {ev.description}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const AGENT_ORDER: Array<[string, string]> = [
  ["supervisor",          "Supervisor Agent"],
  ["market_data",         "Market Data Agent"],
  ["research",            "Research Agent"],
  ["market_intelligence", "Market Intelligence Agent"],
  ["monitoring",          "Monitoring Agent"],
  ["strategy",            "Strategy Agent"],
  ["risk",                "Risk Agent"],
  ["ai_decision",         "AI Decision Agent"],
  ["execution",           "Execution Agent"],
  ["learning",            "Learning Agent"],
  ["knowledge",           "Knowledge Agent"],
  ["operations",          "Operations Agent"],
];

export default function AIOperationsCentrePage() {
  const [lastUpdated, setLastUpdated] = useState<number>(Date.now());

  const { data, isLoading, isFetching, dataUpdatedAt, refetch } = useQuery<OpsSnapshot>({
    queryKey: ["ops-centre", "snapshot"],
    queryFn:  () => apiJson("/ops-centre/snapshot"),
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 1,
  });

  useEffect(() => {
    if (dataUpdatedAt) setLastUpdated(dataUpdatedAt);
  }, [dataUpdatedAt]);

  const secsAgo = Math.round((Date.now() - lastUpdated) / 1000);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      {/* Page Header */}
      <div className="sticky top-0 z-10 bg-slate-950/90 backdrop-blur border-b border-slate-800/50 px-4 py-3">
        <div className="max-w-screen-2xl mx-auto flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-teal-400" />
            <h1 className="text-base font-bold text-slate-100">AI Operations Centre</h1>
            <Badge className="text-[10px] bg-slate-800 border-slate-700 text-slate-400">READ-ONLY</Badge>
            <Badge className="text-[10px] bg-teal-950 border-teal-800 text-teal-300">ADVISORY ONLY</Badge>
          </div>
          <div className="flex items-center gap-3">
            {isFetching && (
              <span className="text-[10px] text-teal-400 flex items-center gap-1">
                <RefreshCcw className="w-3 h-3 animate-spin" /> Refreshing…
              </span>
            )}
            <span className="text-[10px] text-slate-500">
              Updated {secsAgo}s ago
            </span>
            <button onClick={() => refetch()}
              className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-teal-300 border border-slate-700/50 hover:border-teal-700/50 rounded-lg transition-colors">
              <RefreshCcw className="w-3 h-3" /> Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-screen-2xl mx-auto px-4 py-4 space-y-4">

        {/* 1. Platform Status */}
        <PlatformStatusBar data={data} loading={isLoading} />

        {/* 2. Pipeline Flow */}
        <PipelineFlow nodes={data?.pipeline_nodes} loading={isLoading} />

        {/* 3. Agent Cards — 2-col grid on desktop */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Cpu className="w-4 h-4 text-teal-400" />
            <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
              Agent Details
            </h2>
            <span className="text-[10px] text-slate-600">— click any card to expand</span>
            {data && (
              <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-400">
                {AGENT_ORDER.length} agents
              </Badge>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {AGENT_ORDER.map(([key]) => (
              <AgentCard
                key={key}
                agentKey={key}
                agent={isLoading ? undefined : data?.agents?.[key]}
              />
            ))}
          </div>
        </div>

        {/* 4. Pipeline Funnel + Event Log (side by side on wide screens) */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <PipelineFunnel pipeline={data?.pipeline} loading={isLoading} />
          <LiveEventLog />
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-slate-700 pb-4">
          🧠 ApexQuant AI Operations Centre · Read-only · Advisory only · No live orders · Auto-refresh every 30s
        </p>
      </div>
    </div>
  );
}
