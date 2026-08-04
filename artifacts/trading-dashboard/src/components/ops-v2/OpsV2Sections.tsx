/**
 * OpsV2Sections.tsx — AI Operations Centre V2 enhancement components
 *
 * All components receive data from the existing OpsSnapshot (no new API calls).
 * Sections 1,2,5–11,14,15 of the V2 spec are implemented here.
 * Section 3 (Pipeline Efficiency %) is built into the enhanced PipelineFunnelV2.
 * Section 4 (Blocker Explanation) is wired in the existing AgentCard.
 * Section 12 (Hover Help) uses title= attributes throughout.
 * Section 13 (Timeline) is in LiveEventLogV2 below.
 */

import { useState, useCallback } from "react";
import {
  Activity, AlertTriangle, BarChart2, BookOpen, Brain,
  CheckCircle2, ChevronDown, ChevronRight, Clock, Cpu,
  Database, Download, FileJson, FileText, Filter, Gauge,
  GitBranch, Globe, Info, Layers, Network, Radio,
  RefreshCcw, Shield, Swords, TrendingDown, TrendingUp,
  XCircle, Zap, FlaskConical, Server,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";

// ── Shared types (mirror what Python now returns) ──────────────────────────────

export interface RejectionEntry {
  agent: string;
  agent_id: string;
  reason: string;
  count: number;
}

export interface PerformanceMetrics {
  avg_agent_latency_ms: number;
  slowest_agent: string | null;
  slowest_agent_ms: number;
  enabled_agent_count: number;
  healthy_count: number;
  warning_count: number;
  error_count: number;
  waiting_count: number;
  stale_count: number;
  pipeline_efficiency_pct: number;
}

export interface Bottleneck {
  agent: string;
  agent_id: string;
  rejected_pct: number;
  suggestion: string;
}

export interface AgentStateV2 {
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
  data_age_minutes: number | null;
  is_stale: boolean;
}

export interface OpsSnapshotV2 {
  generated_at: string;
  advisory_only: boolean;
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
  pipeline_nodes: Array<{
    id: string; label: string; agent_key: string;
    status: string; health_pct: number; stocks_out: number;
  }>;
  agents: Record<string, AgentStateV2>;
  rejection_summary: RejectionEntry[];
  performance_metrics: PerformanceMetrics;
  bottleneck: Bottleneck | null;
  operator_summary: string;
}

// ── Colour helpers ─────────────────────────────────────────────────────────────

function sc(s: string) {
  switch (s) {
    case "ACTIVE":   return "text-emerald-400";
    case "WAITING":  return "text-amber-400";
    case "ERROR":    return "text-rose-400";
    case "DISABLED": return "text-slate-500";
    default:         return "text-slate-400";
  }
}
function hc(p: number) {
  if (p >= 90) return "text-emerald-400";
  if (p >= 70) return "text-amber-400";
  return "text-rose-400";
}
function hbar(p: number) {
  if (p >= 90) return "bg-emerald-500";
  if (p >= 70) return "bg-amber-500";
  return "bg-rose-500";
}
function fmtMs(ms: number) {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
function fmtAge(min: number | null) {
  if (min === null || min === undefined) return "—";
  if (min < 1) return "< 1 min";
  if (min < 60) return `${Math.round(min)} min`;
  return `${(min / 60).toFixed(1)} hr`;
}

const AGENT_ICONS: Record<string, React.ReactNode> = {
  supervisor:           <Network className="w-3.5 h-3.5" />,
  "market-data":        <Globe className="w-3.5 h-3.5" />,
  research:             <FlaskConical className="w-3.5 h-3.5" />,
  "market-intelligence":<Brain className="w-3.5 h-3.5" />,
  monitoring:           <Radio className="w-3.5 h-3.5" />,
  strategy:             <Swords className="w-3.5 h-3.5" />,
  risk:                 <Shield className="w-3.5 h-3.5" />,
  "ai-decision":        <Cpu className="w-3.5 h-3.5" />,
  execution:            <Zap className="w-3.5 h-3.5" />,
  learning:             <BookOpen className="w-3.5 h-3.5" />,
  knowledge:            <Database className="w-3.5 h-3.5" />,
  operations:           <Gauge className="w-3.5 h-3.5" />,
};

// ────────────────────────────────────────────────────────────────────────────
// SECTION 1 — Agent Health Summary
// ────────────────────────────────────────────────────────────────────────────

export function AgentHealthSummary({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  const m = data?.performance_metrics;

  const tiles = [
    {
      label: "Healthy",
      value: m?.healthy_count ?? 0,
      cls: "text-emerald-400",
      bg: "bg-emerald-950/30 border-emerald-800/40",
      icon: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
      tip: "Agents with ACTIVE status and fresh data. Expected range: 10–12.",
    },
    {
      label: "Warning",
      value: m?.warning_count ?? 0,
      cls: "text-amber-400",
      bg: "bg-amber-950/30 border-amber-800/40",
      icon: <AlertTriangle className="w-4 h-4 text-amber-400" />,
      tip: "Agents that are ACTIVE but their data is older than 2× the scan interval.",
    },
    {
      label: "Error",
      value: m?.error_count ?? 0,
      cls: "text-rose-400",
      bg: "bg-rose-950/30 border-rose-800/40",
      icon: <XCircle className="w-4 h-4 text-rose-400" />,
      tip: "Agents in ERROR state — snapshot collection failed or agent unavailable.",
    },
    {
      label: "Waiting",
      value: m?.waiting_count ?? 0,
      cls: "text-slate-400",
      bg: "bg-slate-800/30 border-slate-700/40",
      icon: <Clock className="w-4 h-4 text-slate-400" />,
      tip: "Agents in WAITING state — no input data from upstream agent yet.",
    },
    {
      label: "Stale",
      value: m?.stale_count ?? 0,
      cls: "text-orange-400",
      bg: "bg-orange-950/20 border-orange-800/40",
      icon: <RefreshCcw className="w-4 h-4 text-orange-400" />,
      tip: "Agents whose last refresh was more than 2× the scan interval ago.",
    },
  ];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Agent Health Summary</h2>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">V2</Badge>
      </div>

      {/* Status tiles */}
      <div className="grid grid-cols-5 gap-2 mb-3">
        {tiles.map(t => (
          <div key={t.label} title={t.tip}
            className={`border rounded-lg p-2.5 flex flex-col items-center gap-1 cursor-help ${t.bg}`}>
            {loading ? <Skeleton className="h-6 w-8" /> : (
              <>
                {t.icon}
                <span className={`text-xl font-bold font-mono ${t.cls}`}>{t.value}</span>
                <span className="text-[10px] text-slate-500">{t.label}</span>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-2">
        <div title="Mean processing time across all active agents. Expected: < 5 000 ms."
          className="bg-slate-800/40 rounded-lg p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Avg Processing Time</p>
          {loading ? <Skeleton className="h-4 w-20" /> :
            <p className="text-xs font-mono font-semibold text-slate-200">{fmtMs(m?.avg_agent_latency_ms ?? 0)}</p>}
        </div>
        <div title="The agent that took longest to collect its snapshot this cycle."
          className="bg-slate-800/40 rounded-lg p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Slowest Agent</p>
          {loading ? <Skeleton className="h-4 w-28" /> :
            <p className="text-xs font-mono font-semibold text-amber-300">
              {m?.slowest_agent ?? "—"} {m?.slowest_agent_ms ? `(${fmtMs(m.slowest_agent_ms)})` : ""}
            </p>}
        </div>
        <div title="Stocks that reached paper execution as a % of the universe scanned. Higher = more efficient pipeline."
          className="bg-slate-800/40 rounded-lg p-2">
          <p className="text-[10px] text-slate-500 mb-0.5">Pipeline Efficiency</p>
          {loading ? <Skeleton className="h-4 w-12" /> :
            <p className={`text-xs font-mono font-bold ${hc(m?.pipeline_efficiency_pct ?? 0)}`}>
              {m?.pipeline_efficiency_pct ?? 0}%
            </p>}
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 2 — Last Refresh Details
// ────────────────────────────────────────────────────────────────────────────

const AGENT_ORDER_IDS = [
  "supervisor","market_data","research","market_intelligence",
  "monitoring","strategy","risk","ai_decision","execution",
  "learning","knowledge","operations",
];

export function RefreshDetailsTable({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  const interval = data?.platform?.scan_interval_min ?? 5;

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Clock className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Last Refresh Details</h2>
        <span className="text-[10px] text-slate-600 ml-1">— per agent</span>
        <Badge className="ml-auto text-[10px] bg-slate-800 border-slate-700 text-slate-500">
          Interval: {interval} min
        </Badge>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="border-b border-slate-800/60">
                {["Agent","Last Refresh","Data Age","Status","Next Expected"].map(h => (
                  <th key={h} className="text-left text-[10px] text-slate-500 pb-1.5 pr-4 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/30">
              {AGENT_ORDER_IDS.map(key => {
                const a = data?.agents?.[key];
                if (!a) return null;
                const stale = a.is_stale;
                const age = a.data_age_minutes;
                return (
                  <tr key={key} className={stale ? "bg-amber-950/10" : ""}>
                    <td className="py-1.5 pr-4">
                      <div className="flex items-center gap-1.5">
                        <span className={sc(a.status)}>{AGENT_ICONS[a.agent_id] ?? <Server className="w-3.5 h-3.5"/>}</span>
                        <span className="text-slate-300 font-medium">{a.name.replace(" Agent","")}</span>
                      </div>
                    </td>
                    <td title="Last time this agent successfully produced a snapshot" className="py-1.5 pr-4 font-mono text-slate-400">
                      {a.last_refresh_time || "—"}
                    </td>
                    <td title="How old is this agent's data right now" className="py-1.5 pr-4 font-mono">
                      <span className={stale ? "text-amber-400 font-semibold" : "text-slate-400"}>
                        {fmtAge(age)}
                      </span>
                    </td>
                    <td className="py-1.5 pr-4">
                      {stale ? (
                        <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-900/40 border border-amber-700/40 text-amber-300 font-semibold">
                          ⚠ STALE
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/30 border border-emerald-700/30 text-emerald-400">
                          ✓ Fresh
                        </span>
                      )}
                    </td>
                    <td title="Estimated next refresh based on scan interval" className="py-1.5 font-mono text-slate-500">
                      {data?.platform?.next_refresh_est || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {data && (
            <div className="mt-2 pt-2 border-t border-slate-800/40">
              {(() => {
                const staleAgents = AGENT_ORDER_IDS
                  .map(k => data.agents?.[k])
                  .filter(a => a?.is_stale);
                if (!staleAgents.length) return null;
                return (
                  <p className="text-[10px] text-amber-400 flex items-center gap-1.5">
                    <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                    {staleAgents.length} agent{staleAgents.length > 1 ? "s" : ""} stale — last successful refresh was more than {interval * 2} minutes ago.
                  </p>
                );
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 3 — Pipeline Efficiency V2 (enhanced funnel with conversion %)
// ────────────────────────────────────────────────────────────────────────────

export function PipelineFunnelV2({ pipeline, loading }: {
  pipeline?: OpsSnapshotV2["pipeline"]; loading: boolean;
}) {
  if (!pipeline && !loading) return null;

  const stages = pipeline ? [
    { label: "Universe Loaded",      count: pipeline.universe_loaded,      tip: "Total symbols in the scan universe." },
    { label: "Stocks Reviewed",      count: pipeline.stocks_reviewed,       tip: "Stocks that entered the analysis pipeline." },
    { label: "Passed Market Data",   count: pipeline.passed_market_data,    tip: "Stocks with live or near-live price data." },
    { label: "Passed Research",      count: pipeline.passed_research,       tip: "Stocks that cleared news & sentiment filters." },
    { label: "Passed Intelligence",  count: pipeline.passed_intelligence,   tip: "Stocks that passed market regime and liquidity conditions." },
    { label: "Passed Monitoring",    count: pipeline.passed_monitoring,     tip: "Stocks with at least one confirmed technical signal." },
    { label: "Passed Strategy",      count: pipeline.passed_strategy,       tip: "Stocks that met minimum strategy confidence threshold." },
    { label: "Passed Risk",          count: pipeline.passed_risk,           tip: "Stocks approved by the risk gate (capital, sector, sizing)." },
    { label: "BUY Recommendations",  count: pipeline.buy_recommendations,   tip: "AI decision: BUY or STRONG BUY. Actionable signals." },
    { label: "Paper Orders Executed",count: pipeline.paper_orders_executed, tip: "Paper trades placed this session." },
    { label: "Open Positions",       count: pipeline.open_positions,        tip: "Currently held paper positions." },
  ] : [];

  const maxCount = Math.max(...stages.map(s => s.count), 1);

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        <Layers className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Pipeline Efficiency</h2>
        <span className="text-[10px] text-slate-600 ml-1">— conversion % at each stage</span>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(11)].map((_, i) => <Skeleton key={i} className="h-7 w-full rounded" />)}</div>
      ) : (
        <div className="space-y-1">
          {stages.map((s, idx) => {
            const prev  = idx > 0 ? stages[idx - 1].count : s.count;
            const drop  = prev > 0 ? Math.round(((prev - s.count) / prev) * 100) : 0;
            const pass  = prev > 0 ? Math.round((s.count / prev) * 100) : 100;
            const barPct = (s.count / maxCount) * 100;
            const isBottleneck = drop > 50 && idx > 0;
            const isFinal = idx >= stages.length - 2;
            return (
              <div key={s.label}>
                {idx > 0 && (
                  <div className="flex items-center ml-40 mb-0.5">
                    <span className={`text-[10px] font-semibold ${
                      pass === 100 ? "text-emerald-400" :
                      pass >= 70   ? "text-teal-400" :
                      pass >= 40   ? "text-amber-400" : "text-rose-400"
                    }`} title={`${pass}% of previous stage passed through`}>
                      ↓ {pass}% pass
                    </span>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <div className="w-40 flex-shrink-0 text-right">
                    <span title={s.tip} className="text-[10px] text-slate-400 cursor-help">{s.label}</span>
                  </div>
                  <div className="flex-1 h-5 bg-slate-800/60 rounded relative overflow-hidden">
                    <div
                      className={`h-full rounded transition-all duration-500 ${
                        isBottleneck ? "bg-amber-600/60" : isFinal ? "bg-emerald-600/60" : "bg-teal-700/50"
                      }`}
                      style={{ width: `${barPct}%` }}
                    />
                    <span className="absolute right-2 top-0 bottom-0 flex items-center text-[10px] font-mono font-bold text-slate-300">
                      {s.count}
                    </span>
                  </div>
                  <span className={`text-[9px] w-14 flex-shrink-0 text-right ${isBottleneck ? "text-amber-400 font-semibold" : "text-slate-600"}`}>
                    {idx > 0 && drop > 0 ? `-${drop}% drop` : ""}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTIONS 5 & 6 — Rejection Summary + Per-Agent Detail
// ────────────────────────────────────────────────────────────────────────────

export function RejectionPanel({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const rs = data?.rejection_summary ?? [];

  const totalRejected = rs.reduce((s, r) => s + r.count, 0);

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Filter className="w-4 h-4 text-rose-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Rejection Summary</h2>
        {!loading && totalRejected > 0 && (
          <Badge className="text-[10px] bg-rose-950 border-rose-800/50 text-rose-300">
            {totalRejected} rejected today
          </Badge>
        )}
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
      ) : rs.length === 0 ? (
        <p className="text-xs text-slate-500 py-4 text-center">
          No rejections recorded — all candidates passed through the pipeline.
        </p>
      ) : (
        <div className="space-y-2">
          {/* Section 5: grouped bars */}
          {rs.map(r => {
            const pct = totalRejected > 0 ? Math.round((r.count / totalRejected) * 100) : 0;
            const isOpen = expanded === r.agent_id;
            const agent = data?.agents?.[r.agent_id];
            return (
              <div key={r.agent_id} className="border border-slate-800/40 rounded-lg overflow-hidden">
                {/* Bar row */}
                <button
                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-800/30 transition-colors text-left"
                  onClick={() => setExpanded(isOpen ? null : r.agent_id)}
                  title="Click to expand rejection details for this agent"
                >
                  <span className="text-slate-500 flex-shrink-0">{AGENT_ICONS[r.agent_id] ?? <Server className="w-3.5 h-3.5"/>}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-xs text-slate-300 font-medium">{r.agent}</span>
                      <span className="text-xs font-mono font-bold text-rose-300">{r.count}</span>
                    </div>
                    <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div className="h-full bg-rose-600/60 rounded-full transition-all duration-500"
                        style={{ width: `${pct}%` }} />
                    </div>
                    <p className="text-[10px] text-slate-500 mt-0.5 truncate">{r.reason}</p>
                  </div>
                  <span className="text-[10px] text-slate-600 flex-shrink-0">{pct}%</span>
                  <ChevronDown className={`w-3.5 h-3.5 text-slate-600 transition-transform flex-shrink-0 ${isOpen ? "rotate-180" : ""}`} />
                </button>

                {/* Section 6: expanded detail */}
                {isOpen && agent && (
                  <div className="border-t border-slate-800/40 px-3 py-2.5 bg-slate-900/60 space-y-1.5">
                    <p className="text-[10px] text-rose-300 flex items-center gap-1.5 font-medium">
                      <AlertTriangle className="w-3 h-3" />
                      {r.reason}
                    </p>
                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <p className="text-[10px] text-slate-500">Stocks In</p>
                        <p className="text-xs font-mono text-slate-300">{agent.stocks_in}</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-slate-500">Stocks Out</p>
                        <p className="text-xs font-mono text-emerald-300">{agent.stocks_out}</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-slate-500">Rejected</p>
                        <p className="text-xs font-mono text-rose-300">{agent.stocks_rejected}</p>
                      </div>
                    </div>
                    <p className="text-[10px] text-slate-500">
                      Activity: <span className="text-slate-300">{agent.current_activity}</span>
                    </p>
                    {agent.is_stale && (
                      <p className="text-[10px] text-amber-400 flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        Data is stale — last refresh {fmtAge(agent.data_age_minutes)} ago
                      </p>
                    )}
                    {agent.errors.length > 0 && (
                      <div className="space-y-0.5">
                        {agent.errors.map((e, i) => (
                          <p key={i} className="text-[10px] text-rose-400 flex items-start gap-1">
                            <XCircle className="w-3 h-3 flex-shrink-0 mt-0.5" /> {e}
                          </p>
                        ))}
                      </div>
                    )}
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

// ────────────────────────────────────────────────────────────────────────────
// SECTION 7 — Agent Scorecard
// ────────────────────────────────────────────────────────────────────────────

export function AgentScorecard({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <BarChart2 className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Agent Scorecard</h2>
        <span className="text-[10px] text-slate-600">— today's success %</span>
      </div>

      {loading ? (
        <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
          {[...Array(12)].map((_, i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}
        </div>
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-2">
          {AGENT_ORDER_IDS.map(key => {
            const a = data?.agents?.[key];
            if (!a) return null;
            const pct = a.health_pct;
            return (
              <div key={key}
                title={`${a.name}: ${pct}% health · ${a.current_activity}`}
                className={`rounded-lg p-2.5 border flex flex-col items-center gap-1 cursor-help ${
                  a.status === "ACTIVE" && pct >= 90
                    ? "bg-emerald-950/20 border-emerald-800/30"
                    : a.status === "ERROR"
                    ? "bg-rose-950/20 border-rose-800/30"
                    : "bg-slate-800/30 border-slate-700/30"
                }`}
              >
                <span className={sc(a.status)}>{AGENT_ICONS[a.agent_id] ?? <Server className="w-3.5 h-3.5" />}</span>
                <span className={`text-base font-bold font-mono ${hc(pct)}`}>{pct}%</span>
                <span className="text-[9px] text-slate-500 text-center leading-tight">
                  {a.name.replace(" Agent", "")}
                </span>
                <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${hbar(pct)}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 8 — Pipeline Bottleneck
// ────────────────────────────────────────────────────────────────────────────

export function BottleneckCard({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  if (loading) return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <Skeleton className="h-4 w-48 mb-2" />
      <Skeleton className="h-12 w-full" />
    </div>
  );
  const b = data?.bottleneck;
  if (!b) {
    return (
      <div className="bg-emerald-950/20 border border-emerald-800/30 rounded-xl p-4">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <h2 className="font-semibold text-xs tracking-widest uppercase text-emerald-400">Pipeline Bottleneck</h2>
        </div>
        <p className="text-xs text-emerald-300 mt-2">No significant bottleneck detected. Pipeline is flowing efficiently.</p>
      </div>
    );
  }
  return (
    <div className="bg-amber-950/20 border border-amber-700/40 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <TrendingDown className="w-4 h-4 text-amber-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-amber-400">Pipeline Bottleneck Detected</h2>
        <Badge className="ml-auto text-[10px] bg-amber-900/50 border-amber-700/50 text-amber-300">
          {b.rejected_pct}% blocked
        </Badge>
      </div>
      <p className="text-sm font-semibold text-amber-200 mb-1">{b.agent}</p>
      <p className="text-xs text-slate-400 mb-2">
        Rejected <span className="text-amber-300 font-semibold">{b.rejected_pct}%</span> of all candidates reaching it this cycle.
      </p>
      <div className="bg-slate-900/50 rounded-lg px-3 py-2 border border-amber-800/20">
        <p className="text-[10px] text-slate-500 mb-0.5">Suggested Action</p>
        <p className="text-xs text-amber-200">{b.suggestion}</p>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 9 — Live Performance
// ────────────────────────────────────────────────────────────────────────────

export function LivePerformanceCard({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  const m = data?.performance_metrics;
  const agentLatencies = data
    ? AGENT_ORDER_IDS.map(key => {
        const a = data.agents?.[key];
        return { name: a?.name ?? key, ms: a?.avg_processing_ms ?? 0, id: key };
      }).filter(x => x.ms > 0).sort((a, b) => b.ms - a.ms)
    : [];

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Zap className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Live Performance</h2>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Summary KPIs */}
          <div className="space-y-2">
            {[
              { label: "Avg Agent Latency",  value: fmtMs(m?.avg_agent_latency_ms ?? 0),
                tip: "Mean snapshot collection time across all active agents. Target: < 5 s." },
              { label: "Slowest Agent",       value: m?.slowest_agent ? `${m.slowest_agent} (${fmtMs(m.slowest_agent_ms)})` : "—",
                tip: "Agent that took the longest to produce its snapshot this cycle." },
              { label: "Active Agents",       value: `${m?.healthy_count ?? 0} / ${m?.enabled_agent_count ?? 12}`,
                tip: "How many agents are in ACTIVE (healthy) state vs total enabled." },
              { label: "Pipeline Efficiency", value: `${m?.pipeline_efficiency_pct ?? 0}%`,
                tip: "Stocks reaching paper execution as % of universe scanned. Higher is better." },
            ].map(k => (
              <div key={k.label} title={k.tip} className="flex items-center justify-between bg-slate-800/30 rounded-lg px-3 py-2 cursor-help">
                <span className="text-[11px] text-slate-400">{k.label}</span>
                <span className="text-[11px] font-mono font-semibold text-slate-200">{k.value}</span>
              </div>
            ))}
          </div>

          {/* Per-agent latency table */}
          <div>
            <p className="text-[10px] text-slate-500 mb-2">Agent Processing Times</p>
            <div className="space-y-1">
              {agentLatencies.slice(0, 8).map(({ name, ms, id }) => {
                const maxMs = agentLatencies[0]?.ms || 1;
                const pct = (ms / maxMs) * 100;
                return (
                  <div key={id} className="flex items-center gap-2" title={`${name}: ${fmtMs(ms)}`}>
                    <span className="text-[10px] text-slate-400 w-28 flex-shrink-0 truncate">
                      {name.replace(" Agent", "")}
                    </span>
                    <div className="flex-1 h-3 bg-slate-800 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${ms > 5000 ? "bg-amber-600/60" : "bg-teal-600/60"}`}
                        style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-[10px] font-mono text-slate-400 w-12 text-right">{fmtMs(ms)}</span>
                  </div>
                );
              })}
              {agentLatencies.length === 0 && (
                <p className="text-[11px] text-slate-500">No latency data available yet.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 10 — Agent Dependency View
// ────────────────────────────────────────────────────────────────────────────

const DEPENDENCY_CHAIN = [
  { key: "supervisor",          label: "Supervisor" },
  { key: "market_data",         label: "Market Data" },
  { key: "research",            label: "Research" },
  { key: "market_intelligence", label: "Market Intelligence" },
  { key: "monitoring",          label: "Monitoring" },
  { key: "strategy",            label: "Strategy" },
  { key: "risk",                label: "Risk" },
  { key: "ai_decision",         label: "AI Decision" },
  { key: "execution",           label: "Execution" },
  { key: "learning",            label: "Learning" },
  { key: "knowledge",           label: "Knowledge" },
  { key: "operations",          label: "Operations" },
];

export function DependencyChain({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  // An agent is "blocked" when the previous agent forwarded 0 items
  const getBlocker = (idx: number): string | null => {
    if (idx === 0) return null;
    const prevKey  = DEPENDENCY_CHAIN[idx - 1]?.key;
    const prevAgent = data?.agents?.[prevKey];
    if (prevAgent && prevAgent.stocks_out === 0 && prevAgent.stocks_in > 0) {
      return `${prevAgent.name} forwarded zero candidates.`;
    }
    return null;
  };

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <GitBranch className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Agent Dependency View</h2>
        <span className="text-[10px] text-slate-600 ml-1">— shows propagation of blockages</span>
      </div>

      {loading ? (
        <div className="flex gap-2">{[...Array(12)].map((_, i) => <Skeleton key={i} className="h-20 w-16 rounded-lg" />)}</div>
      ) : (
        <div className="overflow-x-auto pb-2">
          <div className="flex items-start gap-0 min-w-max">
            {DEPENDENCY_CHAIN.map(({ key, label }, idx) => {
              const a = data?.agents?.[key];
              const blocker = getBlocker(idx);
              const status = a?.status ?? "UNKNOWN";
              const isBlocked = !!blocker;

              const dotCls =
                isBlocked        ? "bg-amber-500 animate-pulse shadow-amber-400/40 shadow-sm" :
                status === "ACTIVE"  ? "bg-emerald-400 animate-pulse shadow-emerald-400/40 shadow-sm" :
                status === "WAITING" ? "bg-slate-500" :
                status === "ERROR"   ? "bg-rose-500 animate-pulse shadow-rose-400/40 shadow-sm" :
                                       "bg-slate-700";
              const borderCls =
                isBlocked        ? "border-amber-700/50 bg-amber-950/20" :
                status === "ACTIVE"  ? "border-emerald-700/30 bg-emerald-950/10" :
                status === "ERROR"   ? "border-rose-700/40 bg-rose-950/10" :
                                       "border-slate-700/30 bg-slate-900/40";
              const statusLabel = isBlocked ? "BLOCKED" : status;

              return (
                <div key={key} className="flex items-start">
                  <div className={`flex flex-col items-center p-2.5 rounded-lg border ${borderCls} min-w-[80px] text-center`}>
                    <div className={`w-2.5 h-2.5 rounded-full mb-1.5 ${dotCls}`} />
                    <span className="text-[10px] font-semibold text-slate-300 leading-tight mb-1">{label}</span>
                    <span className={`text-[9px] font-bold ${
                      isBlocked ? "text-amber-400" :
                      status === "ACTIVE" ? "text-emerald-400" :
                      status === "ERROR"  ? "text-rose-400" :
                      "text-slate-500"
                    }`}>{statusLabel}</span>
                    {a && (
                      <span className="text-[9px] text-slate-600 mt-0.5">
                        {a.stocks_out > 0 ? `→ ${a.stocks_out}` : a.stocks_in > 0 ? "→ 0" : ""}
                      </span>
                    )}
                    {blocker && (
                      <div className="mt-1 px-1.5 py-1 bg-amber-950/50 border border-amber-800/30 rounded text-left max-w-[76px]">
                        <p className="text-[8px] text-amber-300 leading-tight">
                          Blocked: {blocker}
                        </p>
                      </div>
                    )}
                  </div>
                  {idx < DEPENDENCY_CHAIN.length - 1 && (
                    <div className={`flex items-center self-center mx-0.5 mt-2`}>
                      <div className={`w-5 h-px ${
                        status === "ACTIVE" && !isBlocked ? "bg-emerald-700/50" :
                        isBlocked ? "bg-amber-700/50" : "bg-slate-700/40"
                      }`} />
                      <ChevronRight className="w-3 h-3 text-slate-700 -ml-1" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 11 — Pipeline Explanation (Operator Summary)
// ────────────────────────────────────────────────────────────────────────────

export function OperatorSummaryCard({ data, loading }: { data?: OpsSnapshotV2; loading: boolean }) {
  const text = data?.operator_summary;
  const p = data?.pipeline;

  const kpis = p ? [
    { label: "Universe",   value: p.universe_loaded,       tip: "Total symbols scanned" },
    { label: "Strategy ✓",value: p.passed_strategy,        tip: "Passed strategy evaluation" },
    { label: "Risk ✓",     value: p.passed_risk,            tip: "Approved by risk gate" },
    { label: "BUY Recs",  value: p.buy_recommendations,    tip: "BUY recommendations generated" },
    { label: "Executed",  value: p.paper_orders_executed,   tip: "Paper orders placed" },
    { label: "Positions", value: p.open_positions,          tip: "Currently open positions" },
  ] : [];

  return (
    <div className="bg-gradient-to-br from-slate-900/80 to-teal-950/20 border border-teal-800/30 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Info className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-teal-400">Pipeline Explanation</h2>
        <Badge className="ml-auto text-[10px] bg-teal-950 border-teal-800/50 text-teal-400">AI-Generated</Badge>
      </div>

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-4/5" />
        </div>
      ) : (
        <>
          <p className="text-sm text-slate-200 leading-relaxed mb-3 font-medium">
            "{text || "No pipeline activity recorded this session yet."}"
          </p>
          {kpis.length > 0 && (
            <div className="grid grid-cols-6 gap-2">
              {kpis.map(k => (
                <div key={k.label} title={k.tip} className="text-center cursor-help">
                  <p className="text-sm font-bold font-mono text-teal-300">{k.value}</p>
                  <p className="text-[9px] text-slate-500">{k.label}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 13 — Enhanced Timeline (Live Event Log V2)
// ────────────────────────────────────────────────────────────────────────────

interface TimelineEvent {
  timestamp: string;
  ist_time?: string;
  event_type: string;
  title: string;
  description?: string;
  symbol?: string;
  severity?: string;
  agent?: string;
  duration_ms?: number;
  result?: string;
}

export function LiveEventLogV2() {
  const { data, isLoading } = useQuery<{ events: TimelineEvent[] }>({
    queryKey: ["ops-centre", "event-log-v2"],
    queryFn:  () => apiJson("/phase11/timeline?limit=40"),
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
  });

  const events = data?.events ?? [];

  function evColour(type: string) {
    const t = type.toLowerCase();
    if (t.includes("buy") || t.includes("entry"))  return "text-emerald-400 bg-emerald-950/30";
    if (t.includes("sell") || t.includes("exit"))  return "text-rose-400 bg-rose-950/20";
    if (t.includes("scan"))   return "text-blue-400 bg-blue-950/20";
    if (t.includes("reject")) return "text-amber-400 bg-amber-950/20";
    if (t.includes("error"))  return "text-rose-500 bg-rose-950/20";
    return "text-slate-400 bg-slate-800/30";
  }

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Live Event Log</h2>
        <Badge className="text-[10px] bg-teal-950/60 border-teal-700/40 text-teal-300 ml-auto">
          Auto-refresh 15s
        </Badge>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[80px_80px_1fr_60px_80px] gap-2 px-2 pb-1 border-b border-slate-800/40">
        {["Time","Agent","Action","Duration","Result"].map(h => (
          <span key={h} className="text-[9px] text-slate-600 uppercase tracking-wide">{h}</span>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-1.5 mt-2">
          {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}
        </div>
      ) : events.length === 0 ? (
        <p className="text-xs text-slate-500 text-center py-6">No events yet this session</p>
      ) : (
        <div className="space-y-0.5 max-h-80 overflow-y-auto pr-1 mt-1.5">
          {events.map((ev, i) => (
            <div key={i} className="grid grid-cols-[80px_80px_1fr_60px_80px] gap-2 items-start rounded px-2 py-1.5 hover:bg-slate-800/30 transition-colors">
              <span className="text-[10px] font-mono text-slate-500 flex-shrink-0">
                {ev.ist_time || ev.timestamp?.slice(11, 19) || "—"}
              </span>
              <span className="text-[10px] font-mono text-teal-300 truncate">
                {ev.agent ?? (ev.event_type?.split("_")[0] ?? "—")}
              </span>
              <div className="min-w-0">
                <span className="text-xs text-slate-300 truncate block">{ev.title}</span>
                {ev.symbol && (
                  <span className="text-[9px] text-slate-500">{ev.symbol}</span>
                )}
                {ev.description && (
                  <p className="text-[9px] text-slate-600 truncate">{ev.description}</p>
                )}
              </div>
              <span className="text-[10px] font-mono text-slate-500">
                {ev.duration_ms ? fmtMs(ev.duration_ms) : "—"}
              </span>
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded text-center ${evColour(ev.result ?? ev.event_type ?? "")}`}>
                {ev.result ?? ev.severity ?? "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 14 — Auto Alerts
// ────────────────────────────────────────────────────────────────────────────

export function AutoAlertsBar({ data }: { data?: OpsSnapshotV2 }) {
  if (!data) return null;

  const alerts: Array<{ msg: string; level: "warn" | "error" }> = [];

  const agents = data.agents ?? {};

  // Research stale
  const research = agents["research"];
  if (research?.is_stale) {
    alerts.push({ msg: `Research data is stale — last refresh ${fmtAge(research.data_age_minutes)} ago.`, level: "warn" });
  }

  // Market data delayed or error
  const md = agents["market_data"];
  if (md?.status === "ERROR") {
    alerts.push({ msg: "Market Data Agent is in ERROR state. Price data may be unavailable.", level: "error" });
  } else if (md?.is_stale) {
    alerts.push({ msg: `Market Data is stale — last refresh ${fmtAge(md.data_age_minutes)} ago.`, level: "warn" });
  }

  // No buy recommendations for an extended period
  const dec = agents["ai_decision"];
  const buyRecs = data.pipeline?.buy_recommendations ?? 0;
  if (buyRecs === 0 && dec?.data_age_minutes !== null && (dec?.data_age_minutes ?? 0) > 30) {
    alerts.push({ msg: "No BUY recommendations generated in the past 30 minutes.", level: "warn" });
  }

  // Execution idle
  const exec = agents["execution"];
  if (exec?.stocks_out === 0 && exec?.stocks_in > 0) {
    alerts.push({ msg: "Execution Agent is idle — no paper orders placed despite available candidates.", level: "warn" });
  }

  // Risk rejecting 100%
  const risk = agents["risk"];
  if (risk && risk.stocks_in > 0 && risk.stocks_out === 0) {
    alerts.push({ msg: `Risk Agent blocked 100% of candidates. ${risk.rejection_reason || "Review risk thresholds."}`, level: "error" });
  }

  // Decision agent not producing BUY
  if (dec && dec.stocks_in > 0) {
    const buy = Number((dec.details as Record<string, unknown>)?.buy_candidate ?? 0);
    if (buy === 0) {
      alerts.push({ msg: "AI Decision Agent is not generating BUY candidates. Review confidence floor.", level: "warn" });
    }
  }

  if (alerts.length === 0) return null;

  return (
    <div className="space-y-1.5">
      {alerts.map((a, i) => (
        <div key={i} className={`flex items-start gap-2 rounded-lg px-3 py-2 border text-xs ${
          a.level === "error"
            ? "bg-rose-950/30 border-rose-700/40 text-rose-300"
            : "bg-amber-950/20 border-amber-700/40 text-amber-300"
        }`}>
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span>{a.msg}</span>
        </div>
      ))}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// SECTION 15 — Export Panel
// ────────────────────────────────────────────────────────────────────────────

export function ExportPanel({ data }: { data?: OpsSnapshotV2 }) {
  const downloadBlob = useCallback((content: string, filename: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }, []);

  const today = new Date().toISOString().slice(0, 10);

  const exportJson = useCallback(() => {
    if (!data) return;
    downloadBlob(JSON.stringify(data, null, 2), `ops-report-${today}.json`, "application/json");
  }, [data, downloadBlob, today]);

  const exportCsv = useCallback(() => {
    if (!data) return;
    const rows = [
      ["Agent", "Status", "Health%", "Stocks In", "Stocks Out", "Rejected", "Avg Latency", "Last Refresh", "Data Age (min)", "Stale"],
      ...Object.values(data.agents ?? {}).map(a => [
        a.name, a.status, a.health_pct, a.stocks_in, a.stocks_out,
        a.stocks_rejected, a.avg_processing_ms, a.last_refresh_time,
        a.data_age_minutes ?? "", a.is_stale ? "Yes" : "No",
      ]),
    ];
    const csv = rows.map(r => r.map(v => `"${v}"`).join(",")).join("\n");
    downloadBlob(csv, `ops-report-${today}.csv`, "text/csv");
  }, [data, downloadBlob, today]);

  const exportPdf = useCallback(() => {
    window.print();
  }, []);

  return (
    <div className="bg-slate-900/60 border border-slate-800/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Download className="w-4 h-4 text-teal-400" />
        <h2 className="font-semibold text-xs tracking-widest uppercase text-slate-400">Export Operations Report</h2>
        <span className="text-[10px] text-slate-600 ml-1">— Today's full snapshot</span>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={exportJson}
          disabled={!data}
          title="Download full snapshot as JSON"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-teal-700/50 bg-teal-950/30 text-teal-300 hover:bg-teal-900/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <FileJson className="w-3.5 h-3.5" /> JSON
        </button>
        <button
          onClick={exportCsv}
          disabled={!data}
          title="Download agent scorecard as CSV"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-blue-700/50 bg-blue-950/30 text-blue-300 hover:bg-blue-900/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <FileText className="w-3.5 h-3.5" /> CSV
        </button>
        <button
          onClick={exportPdf}
          title="Print page as PDF"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-slate-700/50 bg-slate-800/40 text-slate-300 hover:bg-slate-700/40 transition-colors"
        >
          <FileText className="w-3.5 h-3.5" /> PDF
        </button>
        {data && (
          <span className="text-[10px] text-slate-600 self-center ml-2">
            Snapshot: {data.generated_at?.slice(0, 19).replace("T", " ")} UTC
          </span>
        )}
      </div>
    </div>
  );
}
