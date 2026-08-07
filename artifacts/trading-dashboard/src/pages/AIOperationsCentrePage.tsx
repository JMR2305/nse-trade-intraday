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

import { useState, useEffect, useRef, useMemo } from "react";
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
import {
  AgentHealthSummary, RefreshDetailsTable, PipelineFunnelV2,
  RejectionPanel, AgentScorecard, BottleneckCard, LivePerformanceCard,
  DependencyChain, OperatorSummaryCard, AutoAlertsBar,
  LiveEventLogV2, ExportPanel,
  type OpsSnapshotV2, type RejectionEntry, type PerformanceMetrics, type Bottleneck,
} from "@/components/ops-v2/OpsV2Sections";
import {
  StockJourneyPanel, ScanReplayPanel, MissedOpportunities,
  ConfidenceDistribution, RecommendationLeaderboard, AgentLoadMonitor,
  HistoricalAgentPerf, AIvsMarket, PipelineHeatmap,
  SmartInsights, EndOfDaySummary, FilterBar,
  type OpsSnapshotV3, type FilterState,
} from "@/components/ops-v3/OpsV3Sections";

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
  // V2 additions
  data_age_minutes: number | null;
  is_stale: boolean;
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
    /** Raw scanner-level BUY/STRONG BUY count (opportunity_score ≥ ~62).
     *  Always ≥ buy_recommendations. Shown separately so operators understand
     *  why Ops Centre and Trade Decisions can show different numbers. */
    scanner_candidates?: number;
    /** Confirmed BUY + STRONG_BUY from the decision service — same source as Trade
     *  Decisions page. null when the decision summary has not been written yet.
     *  BUY: confidence 75–84, exp > 0, PF > 1.2, R:R ≥ 2.
     *  STRONG_BUY: confidence ≥ 85, exp > 1%, PF ≥ 1.5, R:R ≥ 2, ≥ 20 trades. */
    buy_recommendations: number | null;
    paper_orders_executed: number;
    open_positions: number;
  };
  pipeline_nodes: PipelineNode[];
  agents: Record<string, AgentState>;
  // V2 additions
  rejection_summary: RejectionEntry[];
  performance_metrics: PerformanceMetrics;
  bottleneck: Bottleneck | null;
  operator_summary: string;
  // V3 additions
  missed_opportunities: import("@/components/ops-v3/OpsV3Sections").MissedOpp[];
  confidence_distribution: Record<string, number>;
  recommendation_leaderboard: {
    top_buy: import("@/components/ops-v3/OpsV3Sections").RecEntry[];
    top_watch: import("@/components/ops-v3/OpsV3Sections").RecEntry[];
    top_sell: import("@/components/ops-v3/OpsV3Sections").RecEntry[];
  };
  pipeline_heatmap: import("@/components/ops-v3/OpsV3Sections").HeatmapStage[];
  smart_insights: import("@/components/ops-v3/OpsV3Sections").SmartInsight[];
  executive_summary: string;
  agent_load_monitor: Record<string, import("@/components/ops-v3/OpsV3Sections").AgentLoad>;
}

/** Fast response from /api/ops-centre/platform — < 1 s */
interface FastPlatformStatus {
  generated_at: string;
  fast: boolean;
  advisory_only: boolean;
  /** ISO timestamp of the full snapshot that last wrote health_pct to the KV cache.
   *  null when no full snapshot has run yet (health_pct is a provisional estimate). */
  cache_ts?: string | null;
  platform: OpsSnapshot["platform"];
  pipeline_nodes: PipelineNode[];
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

function PlatformStatusBar({
  data,
  loading,
  fast,
  generatedAt,
  cacheTs,
}: {
  data?: OpsSnapshot;
  loading: boolean;
  /** true  = health_pct came from last-scan cache (fast endpoint) */
  fast?: boolean;
  /** ISO timestamp when the fast response was generated (wall-clock request time) */
  generatedAt?: string;
  /** ISO timestamp of the full snapshot that wrote health_pct to the KV cache.
   *  null/undefined = no full snapshot yet; health_pct is a provisional estimate. */
  cacheTs?: string | null;
}) {
  const p = data?.platform;
  const health = p?.health_pct ?? 0;

  // When fast=true, age the badge against cache_ts (when health was actually computed).
  // When fast=false (full snapshot), age against generated_at.
  // Falls back to generated_at when cache_ts is absent (provisional estimate path).
  const isCached = fast === true;
  const ageSource = isCached ? (cacheTs ?? generatedAt) : generatedAt;

  // Live "N seconds ago" ticker — updates every second
  const [ageSecs, setAgeSecs] = useState(0);
  useEffect(() => {
    if (!ageSource) { setAgeSecs(0); return; }
    const tick = () => {
      const diff = Math.round((Date.now() - new Date(ageSource).getTime()) / 1000);
      setAgeSecs(Math.max(0, diff));
    };
    tick();
    const id = setInterval(tick, 1_000);
    return () => clearInterval(id);
  }, [ageSource]);

  const ageLabel = ageSecs < 60
    ? `${ageSecs}s ago`
    : `${Math.round(ageSecs / 60)}m ago`;

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
      <div className="flex items-center gap-2 mb-3 flex-wrap">
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
        {/* Cache-vs-live badge — shown once we have a generatedAt timestamp */}
        {!loading && generatedAt && (
          isCached ? (
            <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5
              text-[10px] font-medium
              bg-amber-950/60 border border-amber-700/40 text-amber-300"
              title="Health % is from the last full scan, not freshly computed">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />
              Cached snapshot · {ageLabel}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5
              text-[10px] font-medium
              bg-emerald-950/60 border border-emerald-700/40 text-emerald-300"
              title="Health % was freshly computed from this snapshot">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block animate-pulse" />
              Live · {ageLabel}
            </span>
          )
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
    let gateBreakdown: Array<{ gate: string; blocked: number }> | null = null;

    // Common overrides per agent
    if (agentKey === "supervisor") {
      rows.push(
        ["Total Agents",      d.total_agents as number],
        ["Running",           d.running_agents as number],
        ["Error Agents",      d.error_agents as number],
        ["Health Score",      `${(d.health_score as number ?? 0).toFixed(0)}%`],
        ["Snapshots Published", d.snapshots_published as number],
        ["Alerts",            d.alert_count as number],
        // V4.3 pipeline integrity
        ["Dependency Violations", (d.dependency_violation_count as number) ?? 0],
        ["Stale Topics",      (d.stale_topic_count as number) ?? 0],
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
      const researchMode = d.research_mode as string || "NORMAL";
      const workerStatus = d.worker_status as string || "OK";
      rows.push(
        ["News Processed",    d.news_processed as number],
        ["Corporate Actions", d.corporate_actions as number],
        ["Sentiment +ve",     d.sentiment_positive as number],
        ["Sentiment neutral", d.sentiment_neutral as number],
        ["Sentiment -ve",     d.sentiment_negative as number],
        // V4.3 telemetry
        ["Timeouts (cycle)",  d.timeout_count as number ?? 0],
        ["Retries (cycle)",   d.retry_count as number ?? 0],
        ["Worker Status",     workerStatus],
        ["Research Mode",     researchMode],
      );
      if (d.last_failure_at) {
        rows.push(["Last Failure", d.last_failure_at as string]);
        rows.push(["Failure Reason", (d.failure_reason as string || "").slice(0, 60) + ((d.failure_reason as string || "").length > 60 ? "…" : "")]);
      }
      if (researchMode !== "NORMAL") {
        // surface the mode badge prominently below — handled in JSX
        void researchMode; // used in JSX below
      }
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
      // Capture per-gate breakdown for dedicated table below
      if (Array.isArray(d.gate_breakdown) && (d.gate_breakdown as Array<{ gate: string; blocked: number }>).length > 0) {
        gateBreakdown = d.gate_breakdown as Array<{ gate: string; blocked: number }>;
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

    if (rows.length === 0 && !gateBreakdown) return null;

    return (
      <>
        {rows.length > 0 && (
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
        )}
        {gateBreakdown && gateBreakdown.length > 0 && (
          <div className="mt-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1">
              <Shield className="w-3 h-3" /> Rejection Breakdown by Gate
            </p>
            <div className="rounded-lg overflow-hidden border border-slate-700/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-800/60">
                    <th className="text-left px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Gate</th>
                    <th className="text-right px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Blocked</th>
                  </tr>
                </thead>
                <tbody>
                  {gateBreakdown.map((row, i) => (
                    <tr key={row.gate} className={i % 2 === 0 ? "bg-slate-900/40" : "bg-slate-800/20"}>
                      <td className="px-2.5 py-1.5 text-slate-300">{row.gate}</td>
                      <td className="px-2.5 py-1.5 text-right font-mono text-rose-300 font-semibold">{row.blocked}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </>
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

          {/* V4.3 — Research Agent: mode banner */}
          {agentKey === "research" && (() => {
            const mode = agent.details?.research_mode as string | undefined;
            if (!mode || mode === "NORMAL") return null;
            const isHalted = mode === "PIPELINE_HALTED";
            return (
              <div className={`mt-2 rounded-lg border px-2.5 py-1.5 flex items-center gap-2 ${
                isHalted
                  ? "border-rose-800/50 bg-rose-950/30 text-rose-300"
                  : "border-amber-800/50 bg-amber-950/30 text-amber-300"
              }`}>
                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                <div>
                  <p className="text-[11px] font-semibold">{mode.replace("_", " ")}</p>
                  <p className="text-[10px] opacity-80">
                    {isHalted
                      ? "All research sources failed — new paper entries are paused until research recovers (fail-closed mode)."
                      : "Research sources are unavailable; pipeline is running on market-data signals only (fail-open mode)."}
                  </p>
                </div>
              </div>
            );
          })()}

          {/* V4.3 — Supervisor: dependency violations + recommendations */}
          {agentKey === "supervisor" && (() => {
            const violations     = agent.details?.dependency_violations as string[] | undefined;
            const recs           = agent.details?.recommendations as Array<{
              priority: string; category: string; message: string; action: string;
            }> | undefined;
            const coldStart      = agent.details?.pipeline_cold_start as boolean | undefined;

            // Cold-start: no pipeline topic has published yet this session.
            // Show a friendly "awaiting first scan" notice instead of alarming
            // operators with empty or spurious violation banners.
            if (coldStart) {
              return (
                <div className="mt-3 rounded-lg border border-teal-800/40 bg-teal-950/20 px-3 py-2 flex items-start gap-2">
                  <Clock className="w-3.5 h-3.5 text-teal-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-[11px] font-semibold text-teal-300">
                      Awaiting first scan
                    </p>
                    <p className="text-[10px] text-teal-400/70 mt-0.5">
                      No pipeline data has been published yet this session.
                      Pipeline health and dependency checks will appear after
                      the first scan completes.
                    </p>
                  </div>
                </div>
              );
            }

            if ((!violations || violations.length === 0) && (!recs || recs.length === 0)) return null;
            return (
              <div className="mt-3 space-y-2">
                {violations && violations.length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-rose-400 mb-1.5 flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3" /> Dependency Violations
                    </p>
                    <div className="space-y-1">
                      {violations.map((v, i) => (
                        <div key={i} className="rounded-lg bg-rose-950/20 border border-rose-800/30 px-2.5 py-1.5">
                          <p className="text-[10px] text-rose-300">{v}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {recs && recs.length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-teal-400 mb-1.5 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> Supervisor Recommendations
                    </p>
                    <div className="space-y-1.5">
                      {recs.map((r, i) => (
                        <div key={i} className={`rounded-lg border px-2.5 py-1.5 ${
                          r.priority === "HIGH"
                            ? "border-rose-800/40 bg-rose-950/20"
                            : "border-amber-800/30 bg-amber-950/10"
                        }`}>
                          <p className={`text-[10px] font-semibold ${
                            r.priority === "HIGH" ? "text-rose-300" : "text-amber-300"
                          }`}>{r.message}</p>
                          <p className="text-[9px] text-slate-500 mt-0.5">{r.action}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

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
  // scanner_candidates uses the scanner's opportunity_score threshold (~62).
  // buy_recommendations uses the decision service's stricter threshold (confidence ≥75,
  // expectancy >0, PF >1.2, R:R ≥2) — the same gate as the Trade Decisions page.
  // Both are shown so operators understand why the two pages may show different numbers.
  const hasScanner = pipeline != null && pipeline.scanner_candidates != null;

  // count is number | null; null means "not yet available" (Confirmed BUY row only)
  type FunnelStage = { label: string; count: number | null; note: string | null };
  const stages: FunnelStage[] = pipeline ? [
    { label: "Universe Loaded",        count: pipeline.universe_loaded,        note: null },
    { label: "Stocks Reviewed",        count: pipeline.stocks_reviewed,        note: null },
    { label: "Passed Market Data",     count: pipeline.passed_market_data,     note: null },
    { label: "Passed Research",        count: pipeline.passed_research,        note: null },
    { label: "Passed Intelligence",    count: pipeline.passed_intelligence,    note: null },
    { label: "Passed Monitoring",      count: pipeline.passed_monitoring,      note: null },
    { label: "Passed Strategy",        count: pipeline.passed_strategy,        note: null },
    { label: "Passed Risk",            count: pipeline.passed_risk,            note: null },
    // Scanner-level BUY candidates (shown only when the field is present)
    ...(hasScanner ? [{
      label: "Scanner Candidates",
      count: pipeline.scanner_candidates as number,
      note: "opportunity_score ≥ ~62 (pre-decision)",
    }] : []),
    // Decision-service confirmed BUY — null when not yet available.
    // BUY: confidence 75–84, exp>0, PF>1.2, R:R≥2
    // STRONG_BUY: confidence ≥85, exp>1%, PF≥1.5, R:R≥2, ≥20 trades
    {
      label: "Confirmed BUY",
      count: pipeline.buy_recommendations,    // number | null
      note: "BUY: conf 75–84, exp>0, PF>1.2, R:R≥2 · STRONG_BUY: conf≥85, exp>1%, PF≥1.5, ≥20 trades",
    },
    { label: "Paper Orders Executed",  count: pipeline.paper_orders_executed,  note: null },
    { label: "Open Positions",         count: pipeline.open_positions,         note: null },
  ] : [];

  const maxCount = Math.max(...stages.map(s => s.count ?? 0), 1);

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
            const countKnown = s.count !== null;
            const prevCount  = idx > 0 ? stages[idx - 1].count : s.count;
            const prevKnown  = prevCount !== null;
            const drop = (countKnown && prevKnown && (prevCount as number) > 0)
              ? Math.round((((prevCount as number) - (s.count as number)) / (prevCount as number)) * 100)
              : 0;
            const barPct = countKnown ? ((s.count as number) / maxCount) * 100 : 0;
            const isBottleneck   = drop > 50 && idx > 0 && countKnown;
            const isConfirmedBuy = s.label === "Confirmed BUY";
            const isScannerCand  = s.label === "Scanner Candidates";
            const isUnavailable  = isConfirmedBuy && !countKnown;
            return (
              <div key={s.label}>
                {/* Separator before the scanner→decision block for clarity */}
                {isScannerCand && (
                  <div className="flex items-center gap-2 my-1">
                    <div className="w-40" />
                    <div className="flex-1 border-t border-dashed border-slate-700/50" />
                    <span className="text-[9px] text-slate-600 flex-shrink-0 w-12">decision</span>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <div className="w-40 flex-shrink-0 text-right">
                    <span className={`text-[10px] ${
                      isConfirmedBuy && !isUnavailable ? "text-emerald-400 font-semibold" :
                      isUnavailable  ? "text-slate-500 font-semibold" :
                      isScannerCand  ? "text-amber-400" : "text-slate-400"
                    }`}>
                      {s.label}
                    </span>
                  </div>
                  {isUnavailable ? (
                    <div className="flex-1 h-5 bg-slate-800/30 rounded ring-1 ring-dashed
                                    ring-slate-700/40 flex items-center px-2">
                      <span className="text-[10px] text-slate-600 italic">
                        open Trade Decisions page to populate
                      </span>
                    </div>
                  ) : (
                    <div className={`flex-1 h-5 rounded relative overflow-hidden ${
                      isConfirmedBuy ? "bg-emerald-950/40 ring-1 ring-emerald-700/30" :
                      isScannerCand  ? "bg-amber-950/30" :
                      "bg-slate-800/60"
                    }`}>
                      <div
                        className={`h-full rounded transition-all duration-500 ${
                          isConfirmedBuy ? "bg-emerald-600/70" :
                          isScannerCand  ? "bg-amber-600/40" :
                          isBottleneck   ? "bg-amber-600/60" :
                          idx >= stages.length - 2 ? "bg-emerald-600/60" :
                          "bg-teal-700/50"
                        }`}
                        style={{ width: `${barPct}%` }}
                      />
                      <span className={`absolute right-2 top-0 bottom-0 flex items-center text-[10px] font-mono font-bold ${
                        isConfirmedBuy ? "text-emerald-300" : "text-slate-300"
                      }`}>
                        {s.count}
                      </span>
                    </div>
                  )}
                  {!isUnavailable && drop > 0 && idx > 0 && (
                    <span className={`text-[9px] w-12 flex-shrink-0 ${drop > 50 ? "text-amber-400" : "text-slate-600"}`}>
                      -{drop}%
                    </span>
                  )}
                </div>
                {/* Inline note for scanner/confirmed rows */}
                {s.note && !isUnavailable && (
                  <div className="flex items-start gap-2 mt-0.5 mb-0.5">
                    <div className="w-40 flex-shrink-0" />
                    <p className={`text-[9px] leading-tight ${isConfirmedBuy ? "text-emerald-600" : "text-slate-600"}`}>
                      {s.note}
                    </p>
                  </div>
                )}
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

// ── V4.3 Risk Audit Panel ─────────────────────────────────────────────────────

interface RiskAuditRule {
  rule_id: string;
  label: string;
  scope: string;
  required: string;
  actual: string;
  unit: string;
  passed: boolean;
}

interface RiskAuditCandidate {
  symbol: string;
  eligible: boolean;
  confidence: number;
  recommendation: string;
  rule_manifest: RiskAuditRule[];
  failed_gates: string[];
}

interface RiskAuditData {
  available: boolean;
  generated_at: string;
  scan_id?: string;
  market_state?: string;
  global_pass: boolean;
  global_manifest: RiskAuditRule[];
  candidates: RiskAuditCandidate[];
  total_count: number;
  eligible_count: number;
  blocked_count: number;
  total_rule_checks: number;
  failed_rule_checks: number;
  pass_rate: number;
  top_blockers: string[];
  thresholds: Record<string, number>;
}

function RiskAuditPanel() {
  const [expanded, setExpanded] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery<RiskAuditData>({
    queryKey: ["risk-audit"],
    queryFn: () => apiJson("/risk/audit"),
    staleTime: 60_000,
    retry: 1,
    enabled: expanded,   // only load when the panel is opened
  });

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl overflow-hidden">
      {/* Header — always visible */}
      <button
        className="w-full flex items-center gap-3 p-4 hover:bg-white/5 transition-colors text-left"
        onClick={() => setExpanded(e => !e)}
      >
        <Shield className="w-4 h-4 text-rose-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-slate-200">Risk Agent Rule Audit</p>
          <p className="text-[10px] text-slate-500">
            Full rule manifest: required vs actual for every BUY candidate · Paper only · Advisory only
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {data && (
            <Badge className={`text-[10px] ${
              data.pass_rate >= 90
                ? "bg-emerald-950 border-emerald-800 text-emerald-300"
                : data.pass_rate >= 70
                ? "bg-amber-950 border-amber-800 text-amber-300"
                : "bg-rose-950 border-rose-800 text-rose-300"
            }`}>
              {data.pass_rate.toFixed(0)}% pass
            </Badge>
          )}
          <ChevronDown className={`w-3.5 h-3.5 text-slate-500 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </div>
      </button>

      {expanded && (
        <div className="border-t border-slate-800/40 p-4 space-y-4">
          {isLoading && (
            <div className="space-y-2">
              {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}
            </div>
          )}
          {isError && (
            <div className="flex items-center gap-3 rounded-xl border border-rose-800/40 bg-rose-950/20 px-4 py-3">
              <XCircle className="w-4 h-4 text-rose-400" />
              <div className="flex-1">
                <p className="text-xs font-semibold text-rose-300">Risk audit failed to load</p>
                <p className="text-[10px] text-slate-500">No scan candidates may exist, or the scan has not run yet.</p>
              </div>
              <button onClick={() => void refetch()}
                className="px-2.5 py-1 text-xs rounded-lg bg-rose-900/40 border border-rose-700/40 text-rose-300 hover:bg-rose-800/40 transition-colors">
                Retry
              </button>
            </div>
          )}
          {data && !data.available && (
            <p className="text-xs text-slate-500 text-center py-4">No entry evaluation data available yet — run a scan first.</p>
          )}
          {data?.available && (
            <>
              {/* Summary bar */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: "Candidates", value: data.total_count, cls: "text-slate-200" },
                  { label: "Eligible",   value: data.eligible_count, cls: "text-emerald-300" },
                  { label: "Blocked",    value: data.blocked_count, cls: "text-rose-300" },
                  { label: "Pass Rate",  value: `${data.pass_rate.toFixed(0)}%`, cls: data.pass_rate >= 90 ? "text-emerald-300" : data.pass_rate >= 70 ? "text-amber-300" : "text-rose-300" },
                ].map(({ label, value, cls }) => (
                  <div key={label} className="bg-slate-800/40 rounded-lg p-3 border border-slate-700/30">
                    <p className="text-[10px] text-slate-500">{label}</p>
                    <p className={`text-lg font-bold font-mono ${cls}`}>{value}</p>
                  </div>
                ))}
              </div>

              {/* Global gates */}
              {data.global_manifest.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1">
                    <Globe className="w-3 h-3" /> Global Gates (apply to all candidates)
                  </p>
                  <div className="rounded-lg overflow-hidden border border-slate-700/40">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-slate-800/60">
                          <th className="text-left px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Gate</th>
                          <th className="text-left px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Required</th>
                          <th className="text-left px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Actual</th>
                          <th className="text-center px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.global_manifest.map((rule, i) => (
                          <tr key={rule.rule_id} className={i % 2 === 0 ? "bg-slate-900/40" : "bg-slate-800/20"}>
                            <td className="px-2.5 py-1.5 text-slate-300">{rule.label}</td>
                            <td className="px-2.5 py-1.5 font-mono text-slate-400">{rule.required}</td>
                            <td className="px-2.5 py-1.5 font-mono text-[10px] text-slate-500 max-w-[160px] truncate" title={rule.actual}>{rule.actual}</td>
                            <td className="px-2.5 py-1.5 text-center">
                              {rule.passed
                                ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 inline" />
                                : <XCircle className="w-3.5 h-3.5 text-rose-400 inline" />}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Per-candidate rule breakdown */}
              {data.candidates.length > 0 ? (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1">
                    <Layers className="w-3 h-3" /> Per-Candidate Rule Manifest
                    <span className="ml-auto text-[9px] text-slate-600 font-normal normal-case tracking-normal">
                      Click a symbol to expand
                    </span>
                  </p>
                  <div className="space-y-2">
                    {data.candidates.map(c => (
                      <div key={c.symbol} className={`rounded-lg border overflow-hidden ${c.eligible ? "border-emerald-800/40" : "border-rose-800/30"}`}>
                        <button
                          className="w-full flex items-center gap-3 px-3 py-2 hover:bg-white/5 transition-colors"
                          onClick={() => setSelectedCandidate(p => p === c.symbol ? null : c.symbol)}
                        >
                          <span className="text-xs font-mono font-bold text-slate-200">{c.symbol}</span>
                          <Badge className={`text-[9px] ${c.eligible ? "bg-emerald-950 border-emerald-800 text-emerald-300" : "bg-rose-950 border-rose-800 text-rose-300"}`}>
                            {c.eligible ? "ELIGIBLE" : "BLOCKED"}
                          </Badge>
                          <span className="text-[10px] text-slate-500">{c.recommendation}</span>
                          <span className="text-[10px] text-slate-500">conf {c.confidence.toFixed(0)}%</span>
                          {c.failed_gates.length > 0 && (
                            <span className="text-[9px] text-rose-400 ml-auto">
                              {c.failed_gates.length} gate{c.failed_gates.length > 1 ? "s" : ""} failed
                            </span>
                          )}
                          <ChevronDown className={`w-3 h-3 text-slate-600 transition-transform ml-1 ${selectedCandidate === c.symbol ? "rotate-180" : ""}`} />
                        </button>
                        {selectedCandidate === c.symbol && (
                          <div className="border-t border-slate-800/40">
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="bg-slate-800/50">
                                  <th className="text-left px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Rule</th>
                                  <th className="text-left px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Required</th>
                                  <th className="text-left px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Actual</th>
                                  <th className="text-center px-2.5 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider w-10">✓</th>
                                </tr>
                              </thead>
                              <tbody>
                                {c.rule_manifest.map((rule, i) => (
                                  <tr key={rule.rule_id} className={`${i % 2 === 0 ? "bg-slate-900/40" : "bg-slate-800/20"} ${!rule.passed ? "bg-rose-950/10" : ""}`}>
                                    <td className={`px-2.5 py-1 ${rule.passed ? "text-slate-300" : "text-rose-300 font-semibold"}`}>{rule.label}</td>
                                    <td className="px-2.5 py-1 font-mono text-slate-400">{rule.required} {rule.unit !== "bool" ? rule.unit : ""}</td>
                                    <td className="px-2.5 py-1 font-mono text-[10px] text-slate-500 max-w-[140px] truncate" title={rule.actual}>{rule.actual}</td>
                                    <td className="px-2.5 py-1 text-center">
                                      {rule.passed
                                        ? <CheckCircle2 className="w-3 h-3 text-emerald-400 inline" />
                                        : <XCircle className="w-3 h-3 text-rose-400 inline" />}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-500 text-center py-4">
                  No BUY / STRONG BUY candidates in the current scan. Run a fresh scan to populate the audit.
                </p>
              )}

              {/* Top blockers */}
              {data.top_blockers.length > 0 && (
                <div className="rounded-lg bg-amber-950/20 border border-amber-800/30 px-3 py-2">
                  <p className="text-[10px] font-semibold text-amber-300 mb-1">
                    Top blockers: {data.top_blockers.join(" · ")}
                  </p>
                  <p className="text-[10px] text-slate-500">
                    These gates are blocking the most candidates. Review the relevant settings to tune thresholds.
                  </p>
                </div>
              )}
            </>
          )}
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
  const [v3Filters, setV3Filters] = useState<FilterState>({ agent: "ALL", decision: "ALL", minConf: 0 });

  // ── Fast query: platform bar + pipeline flow  (< 1 s, 10 s refresh) ────────
  const {
    data: platformData,
    isLoading: platformLoading,
    isFetching: platformFetching,
    dataUpdatedAt: platformUpdatedAt,
    refetch: refetchPlatform,
  } = useQuery<FastPlatformStatus>({
    queryKey: ["ops-centre", "platform"],
    queryFn:  () => apiJson("/ops-centre/platform"),
    refetchInterval: 10_000,
    staleTime: 8_000,
    retry: 1,
  });

  // ── Mid-speed query: canonical agent counts (~5-8 s, shared across all pages) ──
  // Same source as AI Paper Trader, Agent Operations, and Command Centre.
  // Populates agent counts before the slow snapshot lands.
  const { data: canonicalAgents } = useQuery({
    queryKey:        ["ops-centre", "agents"],
    queryFn:         () => apiJson("/ops-centre/agents", undefined, 30_000),
    refetchInterval: 30_000,
    staleTime:       20_000,
    retry: 1,
  });
  const ca = canonicalAgents as any;

  // ── Slow query: agent cards + pipeline funnel (~22-30 s, 30 s refresh) ────
  // IMPORTANT: snapshot takes 22–30 s; apiJson default timeout is 15 s which
  // killed every request. Extended to 60 s so the response can land in time.
  const {
    data: snapshotData,
    isLoading: snapshotLoading,
    isFetching: snapshotFetching,
    isError: snapshotError,
    dataUpdatedAt: snapshotUpdatedAt,
    refetch: refetchSnapshot,
  } = useQuery<OpsSnapshot>({
    queryKey: ["ops-centre", "snapshot"],
    queryFn:  () => apiJson("/ops-centre/snapshot", undefined, 60_000),
    refetchInterval: 30_000,
    staleTime: 20_000,
    retry: 2,
  });

  // After a full snapshot lands, its platform section supersedes the fast one
  // (it has the freshly-computed health_pct, not the cached value).
  //
  // IMPORTANT: also gate on !snapshotError.  React Query preserves the last
  // successful snapshotData even when the query subsequently errors, so without
  // the error check the badge would remain "Live" after a mid-session failure.
  // When the snapshot errors we fall back to the fast/cached platform data so
  // the badge correctly reverts to amber "Cached snapshot".
  const effectivePlatform: FastPlatformStatus | undefined = (snapshotData && !snapshotError)
    ? {
        generated_at:  snapshotData.generated_at,
        fast:          false,
        advisory_only: true,
        platform:      snapshotData.platform,
        pipeline_nodes: snapshotData.pipeline_nodes,
      }
    : platformData;

  const effectiveNodes = snapshotData?.pipeline_nodes ?? platformData?.pipeline_nodes;

  useEffect(() => {
    const ts = snapshotUpdatedAt || platformUpdatedAt;
    if (ts) setLastUpdated(ts);
  }, [snapshotUpdatedAt, platformUpdatedAt]);

  const secsAgo = Math.round((Date.now() - lastUpdated) / 1000);
  const isFetching = platformFetching || snapshotFetching;

  // Debug mode: add ?debug to the URL to reveal the debug panel
  const debugMode = useMemo(
    () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("debug"),
    [],
  );

  function refetchAll() {
    void refetchPlatform();
    void refetchSnapshot();
  }

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
            <button onClick={refetchAll}
              className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-teal-300 border border-slate-700/50 hover:border-teal-700/50 rounded-lg transition-colors">
              <RefreshCcw className="w-3 h-3" /> Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-screen-2xl mx-auto px-4 py-4 space-y-4">

        {/* ── V2 §14: Auto Alerts — shown immediately when snapshot data is ready ── */}
        <AutoAlertsBar data={snapshotData as unknown as OpsSnapshotV2} />

        {/* ── V1: Platform Status — fast data, visible within ~1 s ── */}
        <PlatformStatusBar
          data={effectivePlatform as unknown as OpsSnapshot}
          loading={platformLoading && !effectivePlatform}
          fast={effectivePlatform?.fast}
          generatedAt={effectivePlatform?.generated_at}
          cacheTs={effectivePlatform?.cache_ts}
        />

        {/* ── Snapshot loading / error banner ── */}
        {snapshotLoading && !snapshotData && (
          <div className="flex items-center gap-3 rounded-xl border border-teal-800/40 bg-teal-950/20 px-4 py-3">
            <RefreshCcw className="w-4 h-4 text-teal-400 animate-spin flex-shrink-0" />
            <div>
              <p className="text-xs font-semibold text-teal-300">Fetching agent snapshot — takes ~25 seconds</p>
              <p className="text-[11px] text-slate-500 mt-0.5">
                All 12 agents are queried in parallel. Platform status above is live while this loads.
              </p>
            </div>
          </div>
        )}
        {snapshotError && !snapshotData && !snapshotLoading && (
          <div className="flex items-center gap-3 rounded-xl border border-rose-800/40 bg-rose-950/20 px-4 py-3">
            <XCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-rose-300">Agent snapshot failed to load</p>
              <p className="text-[11px] text-slate-500 mt-0.5">
                The snapshot request timed out or the API server returned an error. Use the Refresh button to retry.
              </p>
            </div>
            <button onClick={refetchAll}
              className="flex-shrink-0 px-3 py-1.5 text-xs rounded-lg bg-rose-900/40 border border-rose-700/40 text-rose-300 hover:bg-rose-800/40 transition-colors">
              Retry
            </button>
          </div>
        )}

        {/* ── V2 §11: Pipeline Explanation + §8: Bottleneck ── */}
        {(snapshotData || snapshotLoading) && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <OperatorSummaryCard data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />
            <BottleneckCard      data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />
          </div>
        )}

        {/* ── V2 §1: Agent Health Summary ── */}
        <AgentHealthSummary data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />

        {/* ── V1: Pipeline Flow — fast data for node states, visible within ~1 s ── */}
        <PipelineFlow nodes={effectiveNodes} loading={platformLoading && !effectiveNodes} />

        {/* ── V2 §10: Agent Dependency View ── */}
        <DependencyChain data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />

        {/* ── V1: Agent Cards — loaded from the slower full snapshot ── */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Cpu className="w-4 h-4 text-teal-400" />
            <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">
              Agent Details
            </h2>
            <span className="text-[10px] text-slate-600">— click any card to expand</span>
            {snapshotData ? (
              <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-400">
                {AGENT_ORDER.length} agents
              </Badge>
            ) : snapshotError ? (
              <Badge className="ml-auto text-[10px] bg-rose-950 border-rose-800 text-rose-400">
                Snapshot failed — retry above
              </Badge>
            ) : (
              <Badge className="ml-auto text-[10px] bg-amber-950 border-amber-800 text-amber-400">
                Fetching (~25s)…
              </Badge>
            )}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {AGENT_ORDER.map(([key]) => (
              <AgentCard
                key={key}
                agentKey={key}
                agent={snapshotLoading ? undefined : snapshotData?.agents?.[key]}
              />
            ))}
          </div>
        </div>

        {/* ── V2 §5+6: Rejection Summary + §7: Agent Scorecard ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <RejectionPanel  data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />
          <AgentScorecard  data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />
        </div>

        {/* ── V2 §2: Refresh Details + §9: Live Performance ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <RefreshDetailsTable  data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />
          <LivePerformanceCard  data={snapshotData as unknown as OpsSnapshotV2} loading={snapshotLoading} />
        </div>

        {/* ── V2 §3: Pipeline Efficiency + V2 §13: Enhanced Timeline ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <PipelineFunnelV2 pipeline={snapshotData?.pipeline} loading={snapshotLoading} />
          <LiveEventLogV2 />
        </div>

        {/* ── V2 §15: Export ── */}
        <ExportPanel data={snapshotData as unknown as OpsSnapshotV2} />

        {/* ════════════════════ V3 — AI INVESTIGATION CENTRE ════════════════════ */}

        {/* V3 divider */}
        <div className="flex items-center gap-3 py-2">
          <div className="flex-1 h-px bg-teal-800/30" />
          <span className="text-[10px] tracking-widest uppercase text-teal-600 font-semibold">AI Investigation Centre — V3</span>
          <div className="flex-1 h-px bg-teal-800/30" />
        </div>

        {/* ── V3 §16: Global Filters ── */}
        <FilterBar filters={v3Filters} onChange={setV3Filters} />

        {/* ── V3 §13: Smart Insights ── */}
        <SmartInsights data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />

        {/* ── V3 §14: End of Day Executive Summary ── */}
        <EndOfDaySummary data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />

        {/* ── V3 §1+§2+§10+§11+§15+§17: Stock Journey / Investigation / Search ── */}
        <StockJourneyPanel />

        {/* ── V3 §3: Scan Replay ── */}
        <ScanReplayPanel data={snapshotData as unknown as OpsSnapshotV3} />

        {/* ── V3 §6: Recommendation Leaderboard + §5: Confidence Distribution ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <RecommendationLeaderboard data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />
          <ConfidenceDistribution    data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />
        </div>

        {/* ── V3 §4: Missed Opportunities + §9: AI vs Market ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <MissedOpportunities data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />
          <AIvsMarket />
        </div>

        {/* ── V3 §12: Pipeline Heatmap ── */}
        <PipelineHeatmap data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />

        {/* ── V3 §7: Agent Load Monitor + §8: Historical Performance ── */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <AgentLoadMonitor    data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />
          <HistoricalAgentPerf data={snapshotData as unknown as OpsSnapshotV3} loading={snapshotLoading} />
        </div>

        {/* ════════════════════ V4.3 — RISK AUDIT & PIPELINE INTEGRITY ══════════ */}

        {/* V4.3 divider */}
        <div className="flex items-center gap-3 py-2">
          <div className="flex-1 h-px bg-rose-800/30" />
          <span className="text-[10px] tracking-widest uppercase text-rose-600 font-semibold">Risk Agent Audit — V4.3</span>
          <div className="flex-1 h-px bg-rose-800/30" />
        </div>

        {/* ── V4.3: Risk Audit Panel ── */}
        <RiskAuditPanel />

        {/* ── Debug Panel — visible only with ?debug in the URL ── */}
        {debugMode && (
          <div className="rounded-xl border border-violet-800/40 bg-violet-950/20 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Eye className="w-4 h-4 text-violet-400" />
              <h2 className="font-semibold text-xs tracking-widest uppercase text-violet-400">Debug Panel</h2>
              <Badge className="ml-auto text-[10px] bg-violet-900/40 border-violet-700/40 text-violet-300">Developer Mode</Badge>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
              {[
                { label: "Snapshot Status",  value: snapshotLoading ? "⏳ Loading" : snapshotError ? "❌ Error" : snapshotData ? "✅ Loaded" : "— No data" },
                { label: "Snapshot Loaded",  value: snapshotUpdatedAt ? new Date(snapshotUpdatedAt).toLocaleTimeString() : "—" },
                { label: "Platform Status",  value: platformLoading ? "⏳ Loading" : platformData ? "✅ Loaded" : "— No data" },
                { label: "Platform Loaded",  value: platformUpdatedAt ? new Date(platformUpdatedAt).toLocaleTimeString() : "—" },
                { label: "agents keys",      value: snapshotData ? Object.keys(snapshotData.agents ?? {}).join(", ") || "none" : "—" },
                { label: "performance_metrics", value: snapshotData?.performance_metrics ? `healthy=${snapshotData.performance_metrics.healthy_count} err=${snapshotData.performance_metrics.error_count}` : "—" },
                { label: "smart_insights",   value: snapshotData ? `${(snapshotData.smart_insights ?? []).length} items` : "—" },
                { label: "confidence_dist",  value: snapshotData ? JSON.stringify(snapshotData.confidence_distribution ?? {}) : "—" },
                { label: "missed_opps",      value: snapshotData ? `${(snapshotData.missed_opportunities ?? []).length} items` : "—" },
                { label: "top_buy",          value: snapshotData ? `${(snapshotData.recommendation_leaderboard?.top_buy ?? []).length} items` : "—" },
                { label: "pipeline_heatmap", value: snapshotData ? `${(snapshotData.pipeline_heatmap ?? []).length} stages` : "—" },
                { label: "agent_load_monitor", value: snapshotData ? `${Object.keys(snapshotData.agent_load_monitor ?? {}).length} agents` : "—" },
                { label: "snapshot timeout", value: "60 000 ms (extended from 15 000)" },
                { label: "refetch interval", value: "30 000 ms" },
                { label: "generated_at",     value: snapshotData?.generated_at ?? "—" },
                { label: "Tip",              value: "Remove ?debug from the URL to hide this panel" },
              ].map(({ label, value }) => (
                <div key={label} className="bg-slate-900/60 rounded-lg p-2 border border-slate-800/40">
                  <p className="text-[9px] text-slate-500 mb-0.5">{label}</p>
                  <p className="text-[10px] font-mono text-violet-200 break-all leading-tight">{String(value)}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <p className="text-center text-xs text-slate-700 pb-4">
          🧠 ApexQuant AI Operations Centre V3 · Read-only · Advisory only · No live orders ·
          Platform 10s · Agents 30s (60s timeout) · Stock Journey on-demand · Add ?debug for developer panel
        </p>
      </div>
    </div>
  );
}
