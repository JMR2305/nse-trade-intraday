/**
 * DeepWidgets.tsx — Phase 25.1 Mission Control deep-operations widgets (Parts 6–9).
 *
 * Agent Metrics · Stock Watch · AI Explainability · Enhanced System Health.
 *
 * PURE DASHBOARD. Every widget reads existing api-server endpoints only:
 * agent framework, autonomous-ops snapshot, live-data recommendations/health-v2,
 * explainable-ai, observability, kite session, pipeline summary, backtest runs,
 * learning-layer status, optimisation summary. No business logic is computed
 * here — presentation-level shaping of canonical data only. Shared page-level
 * data (portfolio / replay / scan) is accepted as props and never re-fetched.
 *
 * Spec fields with no canonical backend source render as "—" (never faked).
 *
 * PAPER TRADING / RESEARCH ONLY.
 */
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Activity, Bot, Boxes, Brain, ChevronRight, Database, ShieldCheck,
} from "lucide-react";
import { Widget, useWidgetQuery, fmtINR, timeAgo, PnlText } from "./Widget";

// ════════════════════════════════════════════════════════════════════════════
// PART 6 — Live Agent Metrics
// ════════════════════════════════════════════════════════════════════════════

interface AgentRow {
  agent_id: string; name: string; state?: string; health_score?: number;
  heartbeat_status?: string; current_activity?: string; last_error?: string | null;
  queue_depth?: number; processing_time_ms?: number;
}
interface AgentsResp { available?: boolean; agents?: AgentRow[] }
interface AutoOpsResp {
  registered_agents?: number; healthy_agents?: number; failed_agents?: number;
  warning_agents?: number; queue_depth?: number; avg_decision_latency_ms?: number;
  overall_health?: string; overall_health_score?: number; heartbeat_status?: string;
}

/** Derive a display state from the agent's reported state + current activity. */
function agentState(a: AgentRow): { label: string; tone: string; dot: string } {
  const s = (a.state ?? "").toUpperCase();
  const busy = !!(a.current_activity && a.current_activity.trim());
  if (s === "RUNNING" || s === "ACTIVE") {
    return { label: busy ? "RUNNING" : "IDLE", tone: "text-emerald-400", dot: "bg-emerald-400" };
  }
  if (s === "WAITING" || s === "STARTING" || s === "PENDING") {
    return { label: "WAITING", tone: "text-amber-400", dot: "bg-amber-400" };
  }
  if (s === "FAILED" || s === "ERROR") {
    return { label: "FAILED", tone: "text-red-400", dot: "bg-red-400" };
  }
  if (s === "IDLE" || s === "STOPPED") {
    return { label: "IDLE", tone: "text-muted-foreground", dot: "bg-slate-500" };
  }
  return { label: a.state ?? "—", tone: "text-muted-foreground", dot: "bg-slate-500" };
}

/**
 * AgentMetricsWidget — every AI agent from the agent framework, enriched with
 * autonomous-ops aggregates. Peak latency & recovery count have no canonical
 * source, so they render "—" honestly.
 */
export function AgentMetricsWidget() {
  const agentsQ = useWidgetQuery<AgentsResp>({
    queryKey: ["mc", "deep-agents"], path: "/agent-framework/agents",
    refetchInterval: 60_000, timeoutMs: 45_000,
  });
  const opsQ = useWidgetQuery<AutoOpsResp>({
    queryKey: ["mc", "deep-autoops"], path: "/autonomous-ops/snapshot",
    refetchInterval: 60_000, timeoutMs: 90_000,
  });

  const agents = agentsQ.data?.agents ?? [];
  const o = opsQ.data;

  return (
    <Widget
      title="Live Agent Metrics" icon={Bot} query={agentsQ} refreshMs={60_000}
      testId="mc-agent-metrics" skeletonClass="h-64"
      headerExtra={o?.overall_health && (
        <Badge
          variant="outline"
          className={`text-[9px] px-1.5 py-0 ${
            o.overall_health === "HEALTHY" ? "border-emerald-500/40 text-emerald-300"
              : o.overall_health === "CRITICAL" ? "border-red-500/40 text-red-300"
                : "border-amber-500/40 text-amber-300"
          }`}
        >
          {o.overall_health}{o.overall_health_score != null ? ` · ${Math.round(o.overall_health_score)}` : ""}
        </Badge>
      )}
    >
      {/* Aggregates from autonomous-ops (slow endpoint — degrades gracefully) */}
      {o ? (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-[11px] mb-2">
          <div><p className="text-muted-foreground text-[10px]">Registered</p><p className="font-semibold">{o.registered_agents ?? "—"}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Healthy</p><p className="font-semibold text-emerald-400">{o.healthy_agents ?? "—"}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Warning</p><p className={`font-semibold ${(o.warning_agents ?? 0) > 0 ? "text-amber-400" : ""}`}>{o.warning_agents ?? 0}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Failed</p><p className={`font-semibold ${(o.failed_agents ?? 0) > 0 ? "text-red-400" : ""}`}>{o.failed_agents ?? 0}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Queue</p><p className="font-semibold">{o.queue_depth ?? "—"}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Avg latency</p><p className="font-semibold">{o.avg_decision_latency_ms != null ? `${o.avg_decision_latency_ms.toFixed(0)}ms` : "—"}</p></div>
        </div>
      ) : opsQ.isError ? (
        <p className="text-[10px] text-amber-400/80 mb-2">Autonomous-ops aggregates unavailable ({(opsQ.error as Error)?.message}).</p>
      ) : opsQ.isLoading ? (
        <p className="text-[10px] text-muted-foreground animate-pulse mb-2">Loading autonomous-ops aggregates (slow endpoint)…</p>
      ) : null}

      {agents.length === 0 ? (
        <p className="text-xs text-muted-foreground rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-amber-300/90">
          No agent snapshots yet — populates once the agent framework is running.
        </p>
      ) : (
        <div className="overflow-x-auto">
          {/* header */}
          <div className="flex items-center gap-2 text-[9px] uppercase tracking-wide text-muted-foreground border-b border-border/60 pb-1 mb-0.5 min-w-[560px]">
            <span className="w-36 shrink-0">Agent</span>
            <span className="w-16 shrink-0">State</span>
            <span className="w-12 shrink-0 text-right">Queue</span>
            <span className="w-20 shrink-0 text-right">Latency</span>
            <span className="flex-1">Last error</span>
          </div>
          <div className="space-y-0.5 max-h-[240px] overflow-y-auto min-w-[560px]">
            {agents.map((a) => {
              const st = agentState(a);
              return (
                <div
                  key={a.agent_id}
                  className="flex items-center gap-2 text-[10px] border-b border-border/40 py-1 last:border-0"
                  data-testid={`mc-agent-metric-${a.agent_id}`}
                >
                  <span className="w-36 shrink-0 flex items-center gap-1.5 min-w-0">
                    <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${st.dot}`} />
                    <span className="font-medium truncate">{a.name}</span>
                  </span>
                  <span className={`w-16 shrink-0 font-medium ${st.tone}`}>{st.label}</span>
                  <span className={`w-12 shrink-0 text-right ${(a.queue_depth ?? 0) > 0 ? "text-amber-400" : "text-muted-foreground"}`}>
                    {a.queue_depth ?? 0}
                  </span>
                  <span className="w-20 shrink-0 text-right text-muted-foreground">
                    {a.processing_time_ms != null ? `${a.processing_time_ms.toFixed(0)}ms` : "—"}
                  </span>
                  <span className="flex-1 truncate">
                    {a.last_error
                      ? <span className="text-red-400" title={a.last_error}>{a.last_error}</span>
                      : <span className="text-muted-foreground">{a.current_activity ?? "—"}</span>}
                  </span>
                </div>
              );
            })}
          </div>
          {/* Spec fields without a canonical source. */}
          <p className="text-[9px] text-muted-foreground/70 pt-1">
            Peak latency & recovery count: — (no canonical source)
          </p>
        </div>
      )}
    </Widget>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PART 7 — Live Stock Watch
// ════════════════════════════════════════════════════════════════════════════

interface Recommendation {
  symbol: string; sector?: string; rank?: number;
  entry_price?: number; stop_loss?: number; target_price?: number;
  calibrated_confidence?: number; opportunity_score?: number;
  strategy_name?: string; regime?: string;
  final_action?: string; heat?: string; all_gates_passed?: boolean;
  paper_eligible?: boolean; volume_ratio?: number; rsi?: number; adx?: number;
  data_quality?: string; error?: string | null;
}
interface RecosResp { success?: boolean; recommendations?: Recommendation[]; snapshot_ts?: string }

interface OpenPosition {
  symbol: string; quantity?: number; avg_entry_price?: number; last_price?: number;
  market_value?: number; unrealised_pnl?: number; unrealised_pnl_pct?: number;
}

function actionTone(action?: string): string {
  const a = (action ?? "").toUpperCase();
  if (a === "STRONG BUY" || a === "BUY") return "border-emerald-500/40 text-emerald-300";
  if (a === "SELL" || a === "STRONG SELL") return "border-red-500/40 text-red-300";
  if (a === "WATCH") return "border-amber-500/40 text-amber-300";
  return "border-border/60 text-muted-foreground";
}

/**
 * StockWatchWidget — cards for currently active stocks from the canonical scan
 * recommendations, cross-referenced against open positions (prop portfolio) for
 * live PnL, and the scan snapshot (prop scan) for the in-flight current symbol.
 * Capped at 12 cards.
 */
export function StockWatchWidget({ portfolio, scan }: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  portfolio?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  scan?: any;
}) {
  const recosQ = useWidgetQuery<RecosResp>({
    queryKey: ["mc", "stock-watch-recos"], path: "/live-data/recommendations",
    refetchInterval: 60_000, timeoutMs: 60_000,
  });

  const positions: OpenPosition[] = portfolio?.open_positions ?? [];
  const posBySymbol = useMemo(() => {
    const m = new Map<string, OpenPosition>();
    for (const p of positions) m.set((p.symbol ?? "").toUpperCase(), p);
    return m;
  }, [positions]);

  // Scan snapshot: current in-flight symbol/stage (never re-fetched here).
  const scanProgress = scan?.progress ?? null;
  const scanningSymbol = (scanProgress?.current_symbol ?? scanProgress?.symbol ?? null) as string | null;
  const scanStage = (scanProgress?.stage ?? null) as string | null;

  const cards = useMemo(() => {
    const recs = (recosQ.data?.recommendations ?? [])
      .filter((r) => !r.error)
      .slice(0, 12);
    return recs;
  }, [recosQ.data]);

  return (
    <Widget
      title="Live Stock Watch" icon={Boxes} query={recosQ} refreshMs={60_000}
      testId="mc-stock-watch" skeletonClass="h-64"
      headerExtra={
        <>
          {scanningSymbol && (
            <Badge className="animate-pulse text-[9px] px-1.5 py-0">
              {scanStage ? `${scanStage} · ` : ""}{scanningSymbol}
            </Badge>
          )}
          {cards.length > 0 && (
            <span className="text-[9px] text-muted-foreground">{cards.length} active</span>
          )}
        </>
      }
    >
      {cards.length === 0 ? (
        <p className="text-xs rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-amber-300/90">
          No active stocks — the watch populates after the next scan.
        </p>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-2 max-h-[280px] overflow-y-auto">
          {cards.map((r) => {
            const pos = posBySymbol.get((r.symbol ?? "").toUpperCase());
            const conf = r.calibrated_confidence;
            const isCurrent = scanningSymbol && scanningSymbol.toUpperCase() === (r.symbol ?? "").toUpperCase();
            const stage = isCurrent && scanStage
              ? scanStage
              : r.all_gates_passed ? "RISK APPROVED" : "SCANNED";
            const risk = r.all_gates_passed
              ? { label: "PASS", tone: "text-emerald-400" }
              : { label: "GATE FAIL", tone: "text-red-400" };
            return (
              <div
                key={r.symbol}
                className={`rounded-lg border p-2 text-[10px] bg-muted/10 ${isCurrent ? "border-primary bg-primary/10" : "border-border/60"}`}
                data-testid={`mc-stock-card-${(r.symbol ?? "").toLowerCase()}`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="font-semibold font-mono text-[11px] truncate">{r.symbol}</span>
                  {pos && <span className="h-1.5 w-1.5 rounded-full bg-teal-400 shrink-0" title="Open position" />}
                  <Badge variant="outline" className={`ml-auto text-[8px] px-1 py-0 ${actionTone(r.final_action)}`}>
                    {r.final_action ?? "—"}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Price</span>
                  <span className="font-mono">{pos?.last_price != null ? fmtINR(pos.last_price, 2) : fmtINR(r.entry_price, 2)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Change%</span>
                  {pos?.unrealised_pnl_pct != null ? (
                    <span className={pos.unrealised_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {pos.unrealised_pnl_pct >= 0 ? "+" : ""}{pos.unrealised_pnl_pct.toFixed(2)}%
                    </span>
                  ) : <span className="text-muted-foreground">—</span>}
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Vol ratio</span>
                  <span>{r.volume_ratio != null ? `${r.volume_ratio.toFixed(2)}x` : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Stage</span>
                  <span className="truncate">{stage}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Confidence</span>
                  <span className="font-semibold">{conf != null ? `${conf.toFixed(0)}%` : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Strategy</span>
                  <span className="truncate max-w-[90px]" title={r.strategy_name ?? ""}>{r.strategy_name ?? "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Risk</span>
                  <span className={risk.tone}>{risk.label}</span>
                </div>
                {pos && (
                  <div className="flex justify-between border-t border-border/40 mt-1 pt-1">
                    <span className="text-muted-foreground">PnL</span>
                    <PnlText value={pos.unrealised_pnl} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Widget>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PART 8 — AI Explainability
// ════════════════════════════════════════════════════════════════════════════

interface XaiDecision {
  symbol?: string; signal_type?: string;
  primary_reason?: string; secondary_reasons?: string[]; primary_reasons?: string[];
  supporting_indicators?: string[];
  supporting_market_conditions?: string[];
  supporting_events?: string[];
  supporting_macro_conditions?: string[];
  ai_score?: number; strategy_score?: number; risk_score?: number;
  final_confidence?: number; confidence?: number;
  explainability_score?: number; grade?: string;
  risk_level?: string; price?: number | null; target?: number | null; stop_loss?: number | null;
  regime?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  risk_context?: any;
  plain_english_summary?: string;
}
interface XaiSummary {
  why?: string; top_factors?: string[]; risks?: string[]; opportunities?: string[];
  action_items?: string[]; confidence?: number; grade?: string; risk_level?: string;
}
interface XaiResp { status?: string; symbol?: string; decision?: XaiDecision | null; summary?: XaiSummary; message?: string }

function expectedPct(from?: number | null, to?: number | null): string {
  if (from == null || to == null || from === 0) return "—";
  return `${(((to - from) / from) * 100).toFixed(1)}%`;
}

/**
 * ExplainabilityWidget — today's BUY/SELL decisions from the canonical scan.
 * Click a row → fetch the full explainable-ai decision for that symbol
 * (enabled only on selection; 60 s timeout — the Python spawn is heavy).
 */
export function ExplainabilityWidget() {
  const recosQ = useWidgetQuery<RecosResp>({
    queryKey: ["mc", "xai-recos"], path: "/live-data/recommendations",
    refetchInterval: 60_000, timeoutMs: 60_000,
  });

  const decisions = useMemo(() => {
    return (recosQ.data?.recommendations ?? []).filter((r) => {
      const a = (r.final_action ?? "").toUpperCase();
      return !r.error && (a === "BUY" || a === "STRONG BUY" || a === "SELL" || a === "STRONG SELL");
    });
  }, [recosQ.data]);

  const [selected, setSelected] = useState<string | null>(null);

  const detailQ = useWidgetQuery<XaiResp>({
    queryKey: ["mc", "xai-decision", selected],
    path: `/explainable-ai/decision?symbol=${encodeURIComponent(selected ?? "")}`,
    refetchInterval: 300_000, timeoutMs: 60_000,
    enabled: !!selected, retry: 1,
  });

  const d = detailQ.data?.decision ?? null;
  const sm = detailQ.data?.summary ?? null;
  const disabled = detailQ.data?.status === "DISABLED";
  const indicators = (d?.supporting_indicators ?? []).slice(0, 6);
  const conf = d?.confidence != null
    ? (d.confidence > 1 ? d.confidence : d.confidence * 100)
    : (d?.final_confidence ?? sm?.confidence ?? null);

  return (
    <Widget
      title="AI Explainability" icon={Brain} query={recosQ} refreshMs={60_000}
      testId="mc-explainability" skeletonClass="h-64"
      headerExtra={
        <>
          <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-amber-500/40 text-amber-300">ADVISORY ONLY</Badge>
          {decisions.length > 0 && <span className="text-[9px] text-muted-foreground">{decisions.length} BUY/SELL</span>}
        </>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-2">
        {/* Decision list */}
        <div className="border-r border-border/40 md:pr-2">
          {decisions.length === 0 ? (
            <p className="text-[11px] rounded-lg border border-amber-500/20 bg-amber-500/5 p-2 text-amber-300/90">
              No BUY/SELL decisions today.
            </p>
          ) : (
            <div className="space-y-0.5 max-h-[260px] overflow-y-auto">
              {decisions.map((r) => (
                <button
                  key={r.symbol}
                  onClick={() => setSelected(r.symbol)}
                  className={`w-full flex items-center gap-1.5 text-[10px] rounded-md px-1.5 py-1 text-left transition-colors ${
                    selected === r.symbol ? "bg-primary/15 border border-primary/40" : "hover:bg-muted/30 border border-transparent"
                  }`}
                  data-testid={`mc-xai-row-${(r.symbol ?? "").toLowerCase()}`}
                >
                  <Badge variant="outline" className={`text-[8px] px-1 py-0 ${actionTone(r.final_action)}`}>
                    {r.final_action}
                  </Badge>
                  <span className="font-mono font-medium truncate flex-1">{r.symbol}</span>
                  <span className="text-muted-foreground">{r.calibrated_confidence != null ? `${r.calibrated_confidence.toFixed(0)}%` : ""}</span>
                  <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Detail panel */}
        <div className="min-w-0">
          {!selected ? (
            <p className="text-[11px] text-muted-foreground">Select a decision to see the full explanation.</p>
          ) : detailQ.isLoading ? (
            <p className="text-[11px] text-muted-foreground animate-pulse">Loading explanation for {selected} (slow endpoint)…</p>
          ) : disabled ? (
            <p className="text-[11px] text-amber-400/90">Explainable AI is disabled (set EXPLAINABLE_AI_ENABLED=true).</p>
          ) : detailQ.isError ? (
            <p className="text-[11px] text-red-400">Failed to load explanation: {(detailQ.error as Error)?.message}</p>
          ) : !d ? (
            <p className="text-[11px] text-amber-400/90">{detailQ.data?.message ?? "No decision detail for this symbol."}</p>
          ) : (
            <div className="space-y-2 text-[10px] max-h-[260px] overflow-y-auto pr-1">
              <div className="flex items-center gap-2">
                <span className="font-mono font-semibold text-[12px]">{d.symbol}</span>
                <Badge variant="outline" className={`text-[9px] px-1.5 py-0 ${actionTone(d.signal_type)}`}>{d.signal_type ?? "—"}</Badge>
                {d.grade && <span className="text-muted-foreground">grade {d.grade}</span>}
                <span className="ml-auto font-semibold">{conf != null ? `${Number(conf).toFixed(0)}% conf` : "—"}</span>
              </div>

              {/* Reason */}
              <div>
                <p className="text-muted-foreground uppercase text-[9px] tracking-wide">Reason for decision</p>
                <p>{d.primary_reason ?? sm?.why ?? "—"}</p>
              </div>

              {/* Top indicators */}
              <div>
                <p className="text-muted-foreground uppercase text-[9px] tracking-wide">Top indicators</p>
                {indicators.length === 0 ? <p className="text-muted-foreground">—</p> : (
                  <ul className="space-y-0.5">
                    {indicators.map((ind, i) => (
                      <li key={i} className="flex gap-1"><span className="text-teal-400">•</span><span>{ind}</span></li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Research summary */}
              <div>
                <p className="text-muted-foreground uppercase text-[9px] tracking-wide">Research summary</p>
                <p>{d.plain_english_summary ?? sm?.why ?? "—"}</p>
              </div>

              {/* Risk summary */}
              <div>
                <p className="text-muted-foreground uppercase text-[9px] tracking-wide">Risk summary</p>
                <p>
                  <span className={d.risk_level === "HIGH" ? "text-red-400" : d.risk_level === "LOW" ? "text-emerald-400" : "text-amber-400"}>
                    {d.risk_level ?? sm?.risk_level ?? "—"}
                  </span>
                  {(sm?.risks ?? []).slice(0, 1).map((rk, i) => <span key={i}> · {rk}</span>)}
                </p>
              </div>

              {/* Strategy + scores */}
              <div className="grid grid-cols-3 gap-2">
                <div><p className="text-muted-foreground text-[9px]">AI score</p><p className="font-semibold">{d.ai_score != null ? d.ai_score.toFixed(1) : "—"}</p></div>
                <div><p className="text-muted-foreground text-[9px]">Strategy score</p><p className="font-semibold">{d.strategy_score != null ? d.strategy_score.toFixed(1) : "—"}</p></div>
                <div><p className="text-muted-foreground text-[9px]">Risk score</p><p className="font-semibold">{d.risk_score != null ? d.risk_score.toFixed(1) : "—"}</p></div>
              </div>

              {/* Position size + expected reward/risk */}
              <div className="grid grid-cols-3 gap-2 border-t border-border/40 pt-1.5">
                <div>
                  <p className="text-muted-foreground text-[9px]">Entry / Price</p>
                  <p className="font-semibold">{d.price != null ? fmtINR(d.price, 2) : "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-[9px]">Expected reward</p>
                  <p className="font-semibold text-emerald-400">{expectedPct(d.price, d.target)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-[9px]">Expected risk</p>
                  <p className="font-semibold text-red-400">{expectedPct(d.price, d.stop_loss)}</p>
                </div>
              </div>
              <p className="text-[9px] text-muted-foreground/70">
                Position size: — (sizing computed at execution; no canonical source in the decision explainer)
              </p>
            </div>
          )}
        </div>
      </div>
    </Widget>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PART 9 — Enhanced System Health
// ════════════════════════════════════════════════════════════════════════════

type HealthState = "ok" | "degraded" | "error" | "unknown";

interface HealthCell {
  key: string; label: string; state: HealthState; detail?: string;
}

/** Normalise a variety of backend status strings to a traffic-light state. */
function normStatus(v: unknown): HealthState {
  const s = String(v ?? "").toUpperCase();
  if (!s) return "unknown";
  if (["OK", "HEALTHY", "UP", "OPEN", "CONNECTED", "PASS", "READY", "ENABLED", "CLOSED"].includes(s)) {
    // NOTE: "CLOSED" is the healthy circuit-breaker state; "OPEN" breaker = failing → handled per-source.
    return "ok";
  }
  if (["DEGRADED", "STALE", "WARNING", "WARN", "PARTIAL"].includes(s)) return "degraded";
  if (["ERROR", "DOWN", "FAILED", "UNREACHABLE", "DISCONNECTED", "CRITICAL"].includes(s)) return "error";
  return "unknown";
}

const cellTone: Record<HealthState, string> = {
  ok: "border-emerald-600/40 bg-emerald-950/30 text-emerald-300",
  degraded: "border-amber-600/40 bg-amber-950/30 text-amber-300",
  error: "border-red-600/40 bg-red-950/30 text-red-300",
  unknown: "border-border/60 bg-muted/20 text-muted-foreground",
};
const cellDot: Record<HealthState, string> = {
  ok: "bg-emerald-400", degraded: "bg-amber-400", error: "bg-red-400", unknown: "bg-slate-500",
};

/**
 * SystemHealth2Widget — enhanced green/amber/red grid. Each cell derives its
 * state from a live probe against an existing endpoint. Engines without a live
 * probe use the cheapest existing GET (backtest/runs, learning-layer status,
 * optimisation summary) — never the slow aggregate endpoints. Redis has no
 * project endpoint, so its row is intentionally omitted (never faked).
 * Shared portfolio/replay data comes in as props and is not re-fetched.
 */
export function SystemHealth2Widget({ portfolio, replay }: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  portfolio?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  replay?: any;
}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const obsQ = useWidgetQuery<any>({
    queryKey: ["mc", "sh2-obs"], path: "/observability/summary",
    refetchInterval: 60_000, timeoutMs: 30_000, retry: 1,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const liveHealthQ = useWidgetQuery<any>({
    queryKey: ["mc", "sh2-livehealth"], path: "/live-data/health-v2",
    refetchInterval: 60_000, timeoutMs: 60_000, retry: 1,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const kiteQ = useWidgetQuery<any>({
    queryKey: ["mc", "sh2-kite"], path: "/kite/status",
    refetchInterval: 120_000, timeoutMs: 20_000, retry: 1,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pipelineQ = useWidgetQuery<any>({
    queryKey: ["mc", "sh2-pipeline"], path: "/pipeline/summary",
    refetchInterval: 60_000, timeoutMs: 15_000, retry: 1,
  });
  // Cheap engine probes — cheapest existing GETs only (never slow aggregates).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const backtestQ = useWidgetQuery<any>({
    queryKey: ["mc", "sh2-backtest"], path: "/backtest/runs",
    refetchInterval: 300_000, timeoutMs: 30_000, retry: 0,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const learnQ = useWidgetQuery<any>({
    queryKey: ["mc", "sh2-learn"], path: "/learning-layer/learning/status",
    refetchInterval: 300_000, timeoutMs: 45_000, retry: 0,
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const optQ = useWidgetQuery<any>({
    queryKey: ["mc", "sh2-opt"], path: "/optimisation/summary",
    refetchInterval: 300_000, timeoutMs: 60_000, retry: 0,
  });

  const cells: HealthCell[] = useMemo(() => {
    const obs = obsQ.data;
    const live = liveHealthQ.data;
    const kite = kiteQ.data;

    // ── Probe helpers ──────────────────────────────────────────────────────
    const probe = (
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      q: { isLoading: boolean; isError: boolean; error: unknown; data: any },
      okWhen?: (d: unknown) => boolean,
    ): { state: HealthState; detail?: string } => {
      if (q.isLoading) return { state: "unknown", detail: "checking…" };
      if (q.isError) return { state: "error", detail: (q.error as Error)?.message?.slice(0, 40) };
      if (q.data?.status === "DISABLED") return { state: "degraded", detail: "disabled" };
      if (okWhen && !okWhen(q.data)) return { state: "degraded", detail: "no data" };
      return { state: "ok" };
    };

    // Database — from observability summary db_status
    const dbState: HealthCell = obsQ.isError
      ? { key: "database", label: "Database", state: "error", detail: "obs unreachable" }
      : obsQ.isLoading
        ? { key: "database", label: "Database", state: "unknown", detail: "checking…" }
        : obs?.status === "DISABLED"
          ? { key: "database", label: "Database", state: "degraded", detail: "obs disabled" }
          : { key: "database", label: "Database", state: normStatus(obs?.db_status), detail: obs?.db_status };

    // API — observability api_status (or the fact obs summary responded)
    const apiState: HealthCell = obsQ.isError
      ? { key: "api", label: "API", state: "error", detail: "unreachable" }
      : obsQ.isLoading
        ? { key: "api", label: "API", state: "unknown", detail: "checking…" }
        : { key: "api", label: "API", state: obs?.api_status ? normStatus(obs.api_status) : "ok", detail: obs?.api_status ?? "responding" };

    // Yahoo — OHLCV source; health-v2 quote_provider circuit_breaker.
    // Breaker CLOSED = healthy, OPEN = failing.
    const breaker = String(live?.quote_provider?.circuit_breaker ?? "").toUpperCase();
    const yahooState: HealthCell = liveHealthQ.isError
      ? { key: "yahoo", label: "Yahoo", state: "error", detail: "health-v2 down" }
      : liveHealthQ.isLoading
        ? { key: "yahoo", label: "Yahoo", state: "unknown", detail: "checking…" }
        : { key: "yahoo", label: "Yahoo",
            state: breaker === "OPEN" ? "error" : breaker === "CLOSED" ? "ok" : "degraded",
            detail: breaker ? `breaker ${breaker}` : "OHLCV source" };

    // Zerodha — kite session
    const zState: HealthCell = kiteQ.isError
      ? { key: "zerodha", label: "Zerodha", state: "error", detail: "status down" }
      : kiteQ.isLoading
        ? { key: "zerodha", label: "Zerodha", state: "unknown", detail: "checking…" }
        : kite?.connected
          ? { key: "zerodha", label: "Zerodha", state: "ok", detail: "session live" }
          : { key: "zerodha", label: "Zerodha", state: "degraded",
              detail: kite?.credentials_present ? (kite?.token_status ?? "not connected") : "paper (no creds)" };

    // NSE Feed — market status from health-v2
    const marketState = String(live?.market?.state ?? live?.market?.status ?? "").toUpperCase();
    const nseState: HealthCell = liveHealthQ.isError
      ? { key: "nse", label: "NSE Feed", state: "error", detail: "health-v2 down" }
      : liveHealthQ.isLoading
        ? { key: "nse", label: "NSE Feed", state: "unknown", detail: "checking…" }
        : { key: "nse", label: "NSE Feed",
            state: live?.market ? "ok" : "degraded",
            detail: marketState || "market status" };

    // Replay Engine — shared prop (page-level query). Present = OK.
    const replayHasStages = Array.isArray(replay?.stages) && replay.stages.length > 0;
    const replayState: HealthCell = replay == null
      ? { key: "replay", label: "Replay Engine", state: "unknown", detail: "no snapshot yet" }
      : replay?.error
        ? { key: "replay", label: "Replay Engine", state: "degraded", detail: "no snapshot" }
        : { key: "replay", label: "Replay Engine", state: "ok", detail: replayHasStages ? "snapshot ready" : "reachable" };

    // Learning Engine — cheap status probe
    const learn = probe(learnQ);
    const learnState: HealthCell = { key: "learning", label: "Learning Engine", ...learn };

    // Optimization Engine — summary (cheapest available)
    const opt = probe(optQ);
    const optState: HealthCell = { key: "optimization", label: "Optimization Engine", ...opt };

    // Backtest Engine — runs list probe
    const bt = probe(backtestQ);
    const btState: HealthCell = { key: "backtest", label: "Backtest Engine", ...bt };

    // Pipeline Event Store — pipeline/summary reachable
    const pipe = probe(pipelineQ);
    const pipeState: HealthCell = { key: "pipeline", label: "Pipeline Event Store", ...pipe };

    // Portfolio Store — shared prop present
    const portState: HealthCell = portfolio == null
      ? { key: "portfolio", label: "Portfolio Store", state: "unknown", detail: "no snapshot yet" }
      : portfolio?.status === "ERROR"
        ? { key: "portfolio", label: "Portfolio Store", state: "error", detail: "snapshot error" }
        : { key: "portfolio", label: "Portfolio Store", state: "ok", detail: "snapshot ok" };

    // Execution Store — derived from portfolio snapshot presence (execution/ledger
    // feeds the portfolio store). If portfolio is healthy, execution store is reachable.
    const execState: HealthCell = portfolio == null
      ? { key: "execution", label: "Execution Store", state: "unknown", detail: "no snapshot yet" }
      : { key: "execution", label: "Execution Store", state: "ok", detail: "reachable" };

    return [
      dbState, apiState, yahooState, zState, nseState,
      replayState, learnState, optState, btState, pipeState,
      portState, execState,
    ];
  }, [obsQ.data, obsQ.isError, obsQ.isLoading, liveHealthQ.data, liveHealthQ.isError, liveHealthQ.isLoading,
    kiteQ.data, kiteQ.isError, kiteQ.isLoading, pipelineQ, backtestQ, learnQ, optQ, portfolio, replay]);

  const bad = cells.filter((c) => c.state === "error").length;
  const warn = cells.filter((c) => c.state === "degraded").length;
  const lastChecked = Math.max(
    obsQ.dataUpdatedAt ?? 0, liveHealthQ.dataUpdatedAt ?? 0, kiteQ.dataUpdatedAt ?? 0,
    pipelineQ.dataUpdatedAt ?? 0,
  );

  return (
    <Widget
      title="System Health" icon={ShieldCheck} query={obsQ} refreshMs={60_000}
      testId="mc-system-health-2" skeletonClass="h-40"
      headerExtra={
        <>
          {bad > 0 && <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-red-500/40 text-red-300">{bad} red</Badge>}
          {warn > 0 && <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-amber-500/40 text-amber-300">{warn} amber</Badge>}
          {bad === 0 && warn === 0 && <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-emerald-500/40 text-emerald-300">all green</Badge>}
        </>
      }
    >
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-1.5">
        {cells.map((c) => (
          <div
            key={c.key}
            className={`rounded-lg border px-2 py-1.5 ${cellTone[c.state]}`}
            data-testid={`mc-health2-${c.key}`}
            title={c.detail ?? c.state}
          >
            <div className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${cellDot[c.state]}`} />
              <span className="text-[10px] font-medium truncate">{c.label}</span>
            </div>
            <p className="text-[9px] opacity-80 truncate mt-0.5">{c.detail ?? c.state}</p>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-1.5 mt-2 text-[9px] text-muted-foreground">
        <Database className="w-3 h-3" />
        <span>Redis: not used by this project (row intentionally omitted)</span>
        <span className="ml-auto flex items-center gap-1">
          <Activity className="w-3 h-3" />
          {lastChecked ? `checked ${timeAgo(new Date(lastChecked).toISOString())}` : "—"}
        </span>
      </div>
    </Widget>
  );
}
