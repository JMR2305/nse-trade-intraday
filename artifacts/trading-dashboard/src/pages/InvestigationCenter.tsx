/**
 * InvestigationCenter.tsx — Phase 23 Parts 2–5: Historical Backtest Engine +
 * AI Investigation Center + Advanced Replay Engine + AI Decision Explorer.
 *
 * Everything renders from the canonical stores:
 *   * /api/backtest/*          — runs, isolated backtest portfolio, trades,
 *                                missed opportunities, validation, candles,
 *                                replay bundle, trade stories, explanations,
 *                                search, replay-integrity verification
 *   * /api/pipeline/events     — BACKTEST-mode events (same store as LIVE)
 *
 * The replay cursor is a TICK index over the run's union timeline (from the
 * replay bundle) — chart, animated pipeline, portfolio, trade list, event
 * feed and decision tree are all synchronized to the same tick.
 *
 * BACKTEST — SIMULATED, ISOLATED FROM LIVE. No live ledger data on this page.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertTriangle, Ban, BookOpen, CheckCircle2, ChevronLeft, ChevronRight,
  Clock, FlaskConical, History, Pause, Play, Search, ShieldCheck, ShieldX,
  Square, SkipBack, SkipForward, Wallet, XCircle, Zap,
} from "lucide-react";

const LABEL = "BACKTEST — SIMULATED, ISOLATED FROM LIVE";

// ── Types ────────────────────────────────────────────────────────────────────

interface RunSizing {
  scale_in_enabled?: boolean;
  risk_per_trade_pct?: number;
  max_position_cap_pct?: number;
  max_symbol_exposure_pct?: number;
  max_total_exposure_pct?: number;
  max_scale_in_count?: number;
}

interface BacktestRun {
  run_id: string;
  created_at?: string;
  status: string;
  config?: {
    interval?: string; start?: string; end?: string; capital?: number;
    symbols?: string[] | null; universe?: string;
    sizing?: RunSizing; volume_time_normalized?: boolean;
  };
  progress?: { phase?: string; done?: number; total?: number; ts?: string; cash?: number; symbol?: string };
  metrics?: Record<string, unknown> | null;
  missed?: MissedOpp[] | null;
  validation?: ValidationResult | null;
  error?: string | null;
}

interface RunStats {
  run_id: string;
  event_counts: Record<string, number>;
  profit_factor: number | null;
  avg_hold_min: number | null;
  symbol_count: number;
  gross_win: number;
  gross_loss: number;
}

interface Candle { ts: string; open: number; high: number; low: number; close: number; volume: number }

interface PipelineEvent {
  id: number; ts: string; mode: string; run_id: string | null; scan_id: string | null;
  event_type: string; stage: string; symbol: string | null; payload: Record<string, unknown>;
}

interface BacktestTrade {
  trade_id: string; symbol: string; strategy_name?: string; quantity: number;
  fill_ts?: string; fill_price: number; stop_loss?: number; target?: number;
  status: string; exit_ts?: string | null; exit_price?: number | null;
  exit_rule?: string | null; realized_pnl?: number | null; confidence?: number;
}

interface PortfolioSnap {
  starting_capital: number; cash: number; realized_pnl: number; unrealized_pnl: number;
  portfolio_value: number; net_return_pct: number; win_rate: number; wins: number;
  losses: number; max_drawdown_pct: number; open_positions_count: number;
  closed_positions_count: number; total_trades: number;
  equity_curve: Array<{ ts: string; equity: number }>;
  open_positions: Array<Record<string, unknown>>;
}

interface MissedOpp {
  symbol: string; scan_id: string; decision: string; reason: string;
  base_price: number; potential_return_pct: number; return_at_horizon_pct: number;
  would_have_been_profitable: boolean; horizon_bars: number;
  single_rule_relax_hint?: string | null;
}

interface ValidationResult {
  ok: boolean; checked: number; skipped?: number; verdict?: string;
  learning_state_changed?: boolean;
  mismatches: Array<{ symbol: string; time: string; expected_decision: string; actual_decision: string; reason: string }>;
}

interface DecisionTree {
  symbol: string;
  stages: Array<{ stage: string; events: PipelineEvent[] }>;
  trades: BacktestTrade[];
  total_events: number;
}

interface StageCounter { in: number; out: number; rejected: number; cancelled: number; events: number }

interface ReplayTick {
  tick: number; ts: string | null;
  stages: Record<string, StageCounter>;
  portfolio: { cash?: number; portfolio_value?: number; open_positions?: number; realized_pnl?: number } | null;
  decisions: Array<{ symbol: string | null; action?: string; confidence?: number }>;
  buys: Array<{ symbol: string | null; trade_id?: string; fill_price?: number; qty?: number }>;
  sells: Array<{ symbol: string | null; trade_id?: string; exit_rule?: string; exit_price?: number; realized_pnl?: number }>;
  rejected: Array<{ symbol: string; type: string }>;
  processing_ms: number | null;
}

interface ReplayBundle {
  ok: boolean; run_id: string; timeline: string[]; stage_order: string[];
  ticks: ReplayTick[];
  trade_markers: Array<{ trade_id: string; symbol: string; strategy?: string | null; entry_tick: number | null; exit_tick: number | null; realized_pnl?: number | null; status?: string }>;
  total_events: number;
}

interface TradeStory {
  ok: boolean; trade: BacktestTrade; entry_tick: number | null; exit_tick: number | null;
  steps: Array<{ tick: number; ts: string; event_type: string; stage: string; label: string; detail: Record<string, unknown> }>;
}

interface Explanation {
  ok: boolean; error?: string; symbol: string; scan_id?: string; ts?: string; verdict: string;
  indicators?: Record<string, unknown>; research_summary?: Record<string, unknown>;
  market_context?: Record<string, unknown>; monitoring?: Record<string, unknown>;
  strategy_explanation?: Record<string, unknown>; risk_explanation?: Record<string, unknown>;
  confidence_breakdown?: Record<string, unknown>;
  execution?: Record<string, unknown>; position_size_calc?: Record<string, unknown>;
  target?: number; stop_loss?: number; expected_risk_pct?: number; expected_reward_pct?: number;
  exit_logic?: string;
  rejection?: { failed_gates?: Record<string, unknown>; strategy_reason?: string; order_reason?: string; confidence?: number };
  relax_analysis?: { available: boolean; would_relaxing_have_helped?: boolean; gates_failed?: string[]; expected_outcome_pct?: number; highest_gain_pct?: number; horizon_bars?: number; note?: string };
}

interface ReplayVerify {
  ok: boolean; verdict?: string;
  checks?: Array<{ check: string; status: string; detail: string }>;
  error?: string;
}

interface SearchResult { ok: boolean; query: string; trades: BacktestTrade[]; events: PipelineEvent[] }

const STAGE_LABELS: Record<string, string> = {
  SUPERVISOR: "Supervisor", SCANNER: "Scanner", RESEARCH: "Research",
  MARKET_INTELLIGENCE: "Market Intel", MONITORING: "Monitoring",
  STRATEGY: "Strategy", RISK: "Risk", AI_DECISION: "AI Decision",
  EXECUTION: "Execution", PORTFOLIO: "Portfolio",
};

type ReplayMode = "candle" | "trade" | "decision" | "day" | "week" | "month";
const MODES: Array<{ id: ReplayMode; label: string }> = [
  { id: "candle", label: "Candle" }, { id: "trade", label: "Trade" },
  { id: "decision", label: "AI Decision" }, { id: "day", label: "Day" },
  { id: "week", label: "Week" }, { id: "month", label: "Month" },
];
const SPEEDS = [1, 5, 20, 100, 0] as const; // 0 = Instant (jump to end)

/** Derive a human label for a run config (e.g. "A Baseline", "D Recommended"). */
function configLabel(run: BacktestRun): string {
  const s = run.config?.sizing;
  const vol = !!run.config?.volume_time_normalized;
  if (!s) return "Default";
  const si = s.scale_in_enabled === true;
  const risk = s.risk_per_trade_pct ?? 1;
  if (!si && risk <= 1 && !vol) return "A Baseline";
  if (si && risk <= 1 && !vol) return "B Scale-in";
  if (!si && risk <= 1 && vol) return "C Vol-Normalized";
  if (si && risk <= 1 && vol) return "D Recommended";
  if (!si && risk > 1 && vol) return "E Higher Sizing";
  return si ? "Scale-in" : risk > 1 ? "Higher Risk" : "Custom";
}

/** Format elapsed seconds as Xh Ym Zs. */
function fmtElapsed(createdAt?: string): string {
  if (!createdAt) return "—";
  const sec = Math.max(0, (Date.now() - new Date(createdAt).getTime()) / 1000);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/** Estimate remaining time given done/total and elapsed seconds. */
function fmtETA(done?: number, total?: number, createdAt?: string): string {
  if (!done || !total || done <= 0 || !createdAt) return "—";
  const elapsed = (Date.now() - new Date(createdAt).getTime()) / 1000;
  const rate = done / elapsed; // ticks/sec
  if (rate <= 0) return "—";
  const remaining = (total - done) / rate;
  const m = Math.floor(remaining / 60);
  const s = Math.floor(remaining % 60);
  return m > 0 ? `~${m}m ${s}s left` : `~${s}s left`;
}

function fmtINR(v: unknown): string {
  const n = typeof v === "number" ? v : null;
  if (n === null || !isFinite(n)) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function tsShort(ts?: string | null): string {
  if (!ts) return "—";
  return ts.slice(0, 16).replace("T", " ");
}

function tickOf(scanId?: string | null): number | null {
  const m = /-T(\d+)$/.exec(scanId ?? "");
  return m ? Number(m[1]) : null;
}

/** Format a past ISO timestamp as a human relative age string, e.g. "2 min ago". */
function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const ageMs = Date.now() - new Date(iso).getTime();
  if (ageMs < 0) return "just now";
  const s = Math.floor(ageMs / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ago`;
}

function rangePreset(days: number): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - days * 86400_000);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function kv(obj: Record<string, unknown> | undefined | null): string {
  if (!obj) return "—";
  return Object.entries(obj)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(" · ") || JSON.stringify(obj).slice(0, 160);
}

// ── Candle chart with overlays (Part I) ──────────────────────────────────────

function CandleChart({ candles, cursorIdx, trades, rejectedIdx, missedIdx }: {
  candles: Candle[]; cursorIdx: number; trades: BacktestTrade[];
  rejectedIdx: number[]; missedIdx: number[];
}) {
  const W = 860, H = 280, PAD = 8;
  if (!candles.length) {
    return <div className="text-sm text-muted-foreground py-10 text-center">No candles cached for this selection.</div>;
  }
  const lo = Math.min(...candles.map((c) => c.low));
  const hi = Math.max(...candles.map((c) => c.high));
  const y = (v: number) => PAD + (H - 2 * PAD) * (1 - (v - lo) / Math.max(1e-9, hi - lo));
  const bw = Math.max(1.5, (W - 2 * PAD) / candles.length - 1.5);
  const x = (i: number) => PAD + ((W - 2 * PAD) * i) / candles.length;
  const tsToIdx = new Map(candles.map((c, i) => [c.ts, i]));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" data-testid="chart-candles">
      {candles.map((c, i) => {
        const up = c.close >= c.open;
        const seen = i <= cursorIdx;
        const color = !seen ? "hsl(var(--muted-foreground) / 0.25)" : up ? "#22c55e" : "#ef4444";
        return (
          <g key={c.ts}>
            <line x1={x(i) + bw / 2} x2={x(i) + bw / 2} y1={y(c.high)} y2={y(c.low)} stroke={color} strokeWidth={1} />
            <rect x={x(i)} width={bw} y={y(Math.max(c.open, c.close))}
              height={Math.max(1, Math.abs(y(c.open) - y(c.close)))} fill={color} />
          </g>
        );
      })}
      {/* stop-loss / target lines per trade, drawn from entry to exit */}
      {trades.map((t) => {
        const ei = t.fill_ts ? tsToIdx.get(t.fill_ts) : undefined;
        if (ei === undefined || ei > cursorIdx) return null;
        const xiRaw = t.exit_ts ? tsToIdx.get(t.exit_ts) : undefined;
        const xi = Math.min(xiRaw ?? candles.length - 1, cursorIdx);
        return (
          <g key={`levels-${t.trade_id}`}>
            {typeof t.stop_loss === "number" && (
              <line x1={x(ei)} x2={x(xi) + bw} y1={y(t.stop_loss)} y2={y(t.stop_loss)}
                stroke="#ef4444" strokeDasharray="3 3" strokeWidth={1} opacity={0.8} data-testid={`line-stop-${t.trade_id}`} />
            )}
            {typeof t.target === "number" && (
              <line x1={x(ei)} x2={x(xi) + bw} y1={y(t.target)} y2={y(t.target)}
                stroke="#22c55e" strokeDasharray="3 3" strokeWidth={1} opacity={0.8} data-testid={`line-target-${t.trade_id}`} />
            )}
          </g>
        );
      })}
      {/* rejected BUY opportunities (red ×) + missed opportunities (amber ◆) */}
      {rejectedIdx.filter((i) => i <= cursorIdx).map((i) => (
        <text key={`rej-${i}`} x={x(i) + bw / 2} y={y(candles[i].high) - 4} fontSize={9}
          textAnchor="middle" fill="#ef4444" data-testid={`marker-rejected-${i}`}>×</text>
      ))}
      {missedIdx.filter((i) => i <= cursorIdx).map((i) => (
        <text key={`miss-${i}`} x={x(i) + bw / 2} y={y(candles[i].low) + 12} fontSize={9}
          textAnchor="middle" fill="#f59e0b" data-testid={`marker-missed-${i}`}>◆</text>
      ))}
      {trades.map((t) => {
        const ei = t.fill_ts ? tsToIdx.get(t.fill_ts) : undefined;
        const xi = t.exit_ts ? tsToIdx.get(t.exit_ts) : undefined;
        return (
          <g key={t.trade_id}>
            {ei !== undefined && ei <= cursorIdx && (
              <polygon points={`${x(ei) + bw / 2},${y(t.fill_price) - 10} ${x(ei) - 2},${y(t.fill_price)} ${x(ei) + bw + 2},${y(t.fill_price)}`}
                fill="#3b82f6" data-testid={`marker-entry-${t.trade_id}`} />
            )}
            {xi !== undefined && xi <= cursorIdx && typeof t.exit_price === "number" && (
              <polygon points={`${x(xi) + bw / 2},${y(t.exit_price) + 10} ${x(xi) - 2},${y(t.exit_price)} ${x(xi) + bw + 2},${y(t.exit_price)}`}
                fill={(t.realized_pnl ?? 0) >= 0 ? "#22c55e" : "#ef4444"} />
            )}
          </g>
        );
      })}
      {cursorIdx >= 0 && cursorIdx < candles.length && (
        <line x1={x(cursorIdx) + bw / 2} x2={x(cursorIdx) + bw / 2} y1={PAD} y2={H - PAD}
          stroke="hsl(var(--primary))" strokeDasharray="4 3" strokeWidth={1.2} />
      )}
    </svg>
  );
}

// ── Visual AI pipeline replay (Part B) ───────────────────────────────────────

function PipelineFlow({ order, tick }: { order: string[]; tick: ReplayTick | null }) {
  return (
    <div className="flex flex-wrap items-stretch gap-1" data-testid="pipeline-flow">
      {order.map((stage, i) => {
        const c = tick?.stages?.[stage];
        const active = !!c && c.events > 0;
        const hasReject = !!c && c.rejected > 0;
        return (
          <div key={stage} className="flex items-center gap-1">
            <div className={`rounded border px-2 py-1 text-center min-w-20 transition-colors ${
              hasReject ? "border-red-500 bg-red-500/10"
                : active ? "border-green-500 bg-green-500/10"
                  : "border-border bg-muted/30 opacity-60"}`}
              data-testid={`stage-${stage}`}>
              <div className="text-[10px] font-semibold">{STAGE_LABELS[stage] ?? stage}</div>
              <div className="text-[10px] text-muted-foreground">
                {c ? <>
                  <span className="text-green-500">{c.out}✓</span>
                  {c.rejected > 0 && <span className="text-red-500"> {c.rejected}✗</span>}
                  {c.cancelled > 0 && <span className="text-amber-500"> {c.cancelled}⊘</span>}
                </> : "idle"}
              </div>
            </div>
            {i < order.length - 1 && <span className="text-muted-foreground text-xs">→</span>}
          </div>
        );
      })}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function InvestigationCenter() {
  const qc = useQueryClient();

  // Deep-link params (Phase 25.1 Part 5): ?run=&symbol=&trade=&ts=
  // Parsed once on mount; applied progressively as data loads, then consumed.
  const deepLink = useRef<{ run?: string; symbol?: string; trade?: string; ts?: string } | null>(null);
  if (deepLink.current === null) {
    const p = new URLSearchParams(window.location.search);
    deepLink.current = {
      run: p.get("run") ?? undefined,
      symbol: p.get("symbol") ?? undefined,
      trade: p.get("trade") ?? undefined,
      ts: p.get("ts") ?? undefined,
    };
  }

  // run launcher form
  const [interval, setIntervalStr] = useState("1d");
  const [preset, setPreset] = useState<"1w" | "1m" | "3m" | "6m" | "1y" | "custom">("1m");
  const [start, setStart] = useState(rangePreset(30).start);
  const [end, setEnd] = useState(rangePreset(30).end);
  const [symbolsText, setSymbolsText] = useState("");
  const [universe, setUniverse] = useState("configured");
  const [capital, setCapital] = useState(100000);

  useEffect(() => {
    if (preset === "custom") return;
    const days = preset === "1w" ? 7 : preset === "1m" ? 30
      : preset === "3m" ? 90 : preset === "6m" ? 180 : 365;
    const r = rangePreset(days);
    setStart(r.start); setEnd(r.end);
  }, [preset]);

  const runsQ = useQuery({
    queryKey: ["bt-runs"],
    queryFn: () => apiJson<{ runs: BacktestRun[] }>("/backtest/runs", undefined, 60_000),
    refetchInterval: 5_000,
  });
  const runs = runsQ.data?.runs ?? [];

  const schedulerQ = useQuery({
    queryKey: ["bt-scheduler-status"],
    queryFn: () => apiJson<{
      enabled: boolean;
      last_sweep_at: string | null;
      last_attempt_at: string | null;
      consecutive_failures: number;
      last_error: string | null;
    }>("/backtest/scheduler/status", undefined, 10_000),
    refetchInterval: 30_000,
  });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const runId = selectedRunId ?? runs[0]?.run_id ?? null;
  const run = runs.find((r) => r.run_id === runId) ?? null;
  const running = ["RUNNING", "PENDING", "CANCEL_REQUESTED"].includes(run?.status ?? "");

  const launch = useMutation({
    mutationFn: (overrides?: Partial<{ interval: string; start: string; end: string; capital: number; symbols: string[] }>) =>
      apiJson<{ ok: boolean; run_id?: string; error?: string }>("/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          interval, start, end, capital,
          symbols: symbolsText.trim() ? symbolsText.split(/[\s,]+/).filter(Boolean) : undefined,
          universe,
          ...(overrides ?? {}),
        }),
      }, 30_000),
    onSuccess: (d) => {
      if (d.run_id) setSelectedRunId(d.run_id);
      void qc.invalidateQueries({ queryKey: ["bt-runs"] });
    },
  });

  // ── Run controls: filter, hide, cancel, stale, retry ──────────────────────

  // Filter: which runs to show
  const [runFilter, setRunFilter] = useState<"all" | "active" | "completed" | "failed">("all");

  // Hidden runs: persisted in localStorage, never deleted from DB
  const [hiddenRunIds, setHiddenRunIds] = useState<Set<string>>(() => {
    try {
      const s = localStorage.getItem("bt-hidden-runs");
      return s ? new Set<string>(JSON.parse(s)) : new Set<string>();
    } catch { return new Set<string>(); }
  });
  const hideRun = (rid: string) => setHiddenRunIds(prev => {
    const next = new Set(prev); next.add(rid);
    localStorage.setItem("bt-hidden-runs", JSON.stringify([...next]));
    return next;
  });
  const showAllRuns = () => {
    setHiddenRunIds(new Set());
    localStorage.removeItem("bt-hidden-runs");
  };

  // Mutations
  const cancelMut = useMutation({
    mutationFn: (rid: string) =>
      apiJson<{ ok: boolean; message?: string }>(`/backtest/run/${rid}/cancel`, { method: "POST" }, 15_000),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["bt-runs"] }),
  });
  const markStaleMut = useMutation({
    mutationFn: (rid: string) =>
      apiJson<{ ok: boolean; message?: string }>(`/backtest/run/${rid}/mark-stale`, { method: "POST" }, 15_000),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["bt-runs"] }),
  });
  const retryMut = useMutation({
    mutationFn: (rid: string) =>
      apiJson<{ ok: boolean; new_run_id?: string }>(`/backtest/run/${rid}/retry`, { method: "POST" }, 15_000),
    onSuccess: (d) => {
      if (d.new_run_id) setSelectedRunId(d.new_run_id);
      void qc.invalidateQueries({ queryKey: ["bt-runs"] });
    },
  });

  // Filtered + visible runs list
  const filteredRuns = useMemo(() => {
    let out = runs.filter(r => !hiddenRunIds.has(r.run_id));
    if (runFilter === "active")
      out = out.filter(r => ["PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(r.status));
    else if (runFilter === "completed")
      out = out.filter(r => r.status === "COMPLETED");
    else if (runFilter === "failed")
      out = out.filter(r => ["FAILED", "STALE", "CANCELLED", "CANCEL_REQUESTED"].includes(r.status));
    return out;
  }, [runs, hiddenRunIds, runFilter]);

  // Watchdog: RUNNING runs with no progress_updated_at or updated_at for 30+ min
  const staleRunIds = useMemo(() => {
    const now = Date.now();
    return new Set(
      runs
        .filter(r => r.status === "RUNNING")
        .filter(r => {
          const ts = (r.progress as Record<string, unknown> | undefined)?.progress_updated_at
                     ?? r.created_at;
          if (!ts) return true; // no timestamp = treat as stale
          return now - new Date(String(ts)).getTime() > 30 * 60 * 1000;
        })
        .map(r => r.run_id),
    );
  }, [runs]);

  // Per-run event-count stats for completed runs (comparison table).
  // We fetch for every completed run in the list; queries are cached.
  const completedRuns = useMemo(() => runs.filter((r) => r.status === "COMPLETED"), [runs]);
  const statsQueries = completedRuns.map((r) => ({
    queryKey: ["bt-stats", r.run_id],
    queryFn: () => apiJson<RunStats>(`/backtest/run/${r.run_id}/stats`, undefined, 30_000),
    staleTime: 300_000,
  }));
  // We can't call hooks in a loop, so we pre-fetch via the query client in a
  // single useEffect whenever the completed run list changes. Errors are
  // caught and suppressed — the comparison table shows "…" for missing stats.
  useEffect(() => {
    for (const q of statsQueries) {
      void qc.fetchQuery({
        ...q,
        queryFn: () => apiJson<RunStats>(`/backtest/run/${q.queryKey[1]}/stats`, undefined, 30_000)
          .catch(() => null),
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completedRuns.map((r) => r.run_id).join(",")]);
  const statsCache: Record<string, RunStats> = useMemo(() => {
    const out: Record<string, RunStats> = {};
    for (const r of completedRuns) {
      const d = qc.getQueryData<RunStats | null>(["bt-stats", r.run_id]);
      if (d) out[r.run_id] = d;
    }
    return out;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completedRuns, qc]);

  const eventsQ = useQuery({
    queryKey: ["bt-events", runId],
    queryFn: () => apiJson<{ events: PipelineEvent[] }>(`/pipeline/events?mode=BACKTEST&run_id=${runId}&limit=3000`, undefined, 60_000),
    enabled: !!runId,
    refetchInterval: running ? 5_000 : false,
  });
  const events = eventsQ.data?.events ?? [];

  const tradesQ = useQuery({
    queryKey: ["bt-trades", runId],
    queryFn: () => apiJson<{ trades: BacktestTrade[] }>(`/backtest/run/${runId}/trades`, undefined, 60_000),
    enabled: !!runId,
    refetchInterval: running ? 5_000 : false,
  });
  const trades = tradesQ.data?.trades ?? [];

  const portfolioQ = useQuery({
    queryKey: ["bt-portfolio", runId],
    queryFn: () => apiJson<PortfolioSnap>(`/backtest/run/${runId}/portfolio`, undefined, 60_000),
    enabled: !!runId,
    refetchInterval: running ? 5_000 : false,
  });
  const pf = portfolioQ.data;

  // synchronized replay bundle (Parts A/B/H) — canonical union timeline
  const bundleQ = useQuery({
    queryKey: ["bt-bundle", runId],
    queryFn: () => apiJson<ReplayBundle>(`/backtest/run/${runId}/replay`, undefined, 180_000),
    enabled: !!runId && !running,
    staleTime: 60_000,
  });
  const bundle = bundleQ.data?.ok ? bundleQ.data : null;
  const timeline = bundle?.timeline ?? [];
  const ticksByIdx = useMemo(() => {
    const m = new Map<number, ReplayTick>();
    for (const t of bundle?.ticks ?? []) m.set(t.tick, t);
    return m;
  }, [bundle]);

  // replay symbol + candles
  const symbols = useMemo(() => {
    const s = new Set<string>();
    for (const t of trades) s.add(t.symbol);
    for (const e of events) if (e.symbol) s.add(e.symbol);
    return Array.from(s).sort();
  }, [trades, events]);
  const [symbol, setSymbol] = useState<string | null>(null);
  const sym = symbol && symbols.includes(symbol) ? symbol : symbols[0] ?? null;

  const candlesQ = useQuery({
    queryKey: ["bt-candles", runId, sym],
    queryFn: () => apiJson<{ candles: Candle[] }>(`/backtest/candles?symbol=${sym}&interval=${run?.config?.interval ?? "1d"}&start=${run?.config?.start}&end=${run?.config?.end}`, undefined, 60_000),
    enabled: !!runId && !!sym && !!run?.config?.start,
  });
  const candles = candlesQ.data?.candles ?? [];

  // ── Advanced replay engine (Parts A + H): tick cursor over union timeline ──
  const [cursor, setCursor] = useState(-1);       // tick index into timeline
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);  // 0 = Max
  const [mode, setMode] = useState<ReplayMode>("candle");
  const timerRef = useRef<ReturnType<typeof window.setInterval> | null>(null);
  const total = timeline.length || candles.length;

  useEffect(() => { setCursor(total ? total - 1 : -1); setPlaying(false); }, [runId, total]);

  // Apply deep-link params (Part 5) in strict order: run selection must resolve
  // BEFORE symbol/trade/ts are applied, or they would match against the default
  // latest run and be consumed prematurely.
  useEffect(() => {
    const dl = deepLink.current;
    if (!dl?.run || !runsQ.isSuccess) return;
    if (runs.some((r) => r.run_id === dl.run)) setSelectedRunId(dl.run);
    // Requested run not found in the list: drop it so the other params
    // don't stay gated forever (they'll apply against the default run).
    dl.run = undefined;
  }, [runs, runsQ.isSuccess]);
  useEffect(() => {
    const dl = deepLink.current;
    if (!dl?.symbol || dl.run) return; // wait until the run param is resolved
    if (symbols.includes(dl.symbol)) {
      setSymbol(dl.symbol);
      dl.symbol = undefined;
    }
  }, [symbols, runId]);
  useEffect(() => {
    const dl = deepLink.current;
    if (!dl || dl.run || !bundle || !timeline.length) return;
    if (bundle.run_id && dl.trade && bundle.run_id !== runId) return; // stale bundle
    if (dl.trade) {
      const tm = (bundle.trade_markers ?? []).find((m) => m.trade_id === dl.trade);
      if (tm && tm.entry_tick !== null) {
        setCursor(tm.entry_tick);
        if (tm.symbol) setSymbol(tm.symbol);
        dl.trade = undefined;
        dl.ts = undefined;
        return;
      }
    }
    if (dl.ts) {
      // last tick at or before the requested timestamp (never guess forward)
      let idx = -1;
      for (let i = 0; i < timeline.length; i++) {
        if (timeline[i] <= dl.ts) idx = i; else break;
      }
      if (idx >= 0) setCursor(idx);
      dl.ts = undefined;
    }
  }, [bundle, timeline]);

  // mode-aware step targets
  const stepTargets = useMemo(() => {
    if (!total) return [] as number[];
    const all = Array.from({ length: total }, (_, i) => i);
    const tsAt = (i: number) => timeline[i] ?? candles[i]?.ts ?? "";
    if (mode === "candle") return all;
    if (mode === "trade") {
      const s = new Set<number>();
      for (const tm of bundle?.trade_markers ?? []) {
        if (tm.entry_tick !== null) s.add(tm.entry_tick);
        if (tm.exit_tick !== null) s.add(tm.exit_tick);
      }
      return Array.from(s).sort((a, b) => a - b);
    }
    if (mode === "decision") {
      return all.filter((i) => (ticksByIdx.get(i)?.decisions.length ?? 0) > 0);
    }
    // day / week / month: last tick of each calendar bucket
    const bucket = (iso: string) => {
      const d = new Date(iso);
      if (mode === "day") return iso.slice(0, 10);
      if (mode === "month") return iso.slice(0, 7);
      const wk = new Date(d); wk.setDate(d.getDate() - d.getDay());
      return wk.toISOString().slice(0, 10);
    };
    const lastOf = new Map<string, number>();
    for (const i of all) lastOf.set(bucket(tsAt(i)), i);
    return Array.from(lastOf.values()).sort((a, b) => a - b);
  }, [mode, total, timeline, candles, bundle, ticksByIdx]);

  const stepNext = (from: number) => stepTargets.find((i) => i > from) ?? from;
  const stepPrev = (from: number) => [...stepTargets].reverse().find((i) => i < from) ?? from;

  useEffect(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (playing && total) {
      if (speed === 0) {
        // Instant: jump straight to the final tick.
        setCursor(total - 1);
        setPlaying(false);
        return;
      }
      const period = Math.max(20, 900 / speed);
      timerRef.current = setInterval(() => {
        setCursor((c) => {
          const nxt = stepNext(c);
          if (nxt === c || c >= total - 1) { setPlaying(false); return c; }
          return nxt;
        });
      }, period);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, speed, total, stepTargets]);

  const cursorTs = cursor >= 0 && cursor < timeline.length ? timeline[cursor]
    : cursor >= 0 && cursor < candles.length ? candles[cursor].ts : null;

  // chart cursor: last candle of the selected symbol at or before the tick ts
  const candleCursorIdx = useMemo(() => {
    if (!candles.length) return -1;
    if (!cursorTs) return candles.length - 1;
    let idx = -1;
    for (let i = 0; i < candles.length; i++) {
      if (candles[i].ts <= cursorTs) idx = i; else break;
    }
    return idx;
  }, [candles, cursorTs]);

  // jump helpers (Part A)
  const jumpToNext = (pred: (t: ReplayTick) => boolean) => {
    for (let i = cursor + 1; i < total; i++) {
      const t = ticksByIdx.get(i);
      if (t && pred(t)) { setCursor(i); return; }
    }
    for (let i = 0; i <= cursor; i++) {
      const t = ticksByIdx.get(i);
      if (t && pred(t)) { setCursor(i); return; }
    }
  };

  const currentTick = ticksByIdx.get(cursor) ?? null;

  // portfolio at cursor (synchronized, from PORTFOLIO_UPDATED events)
  const portfolioAtCursor = useMemo(() => {
    for (let i = cursor; i >= 0; i--) {
      const p = ticksByIdx.get(i)?.portfolio;
      if (p) return p;
    }
    return null;
  }, [cursor, ticksByIdx]);

  // ── Filters (Part J) ──────────────────────────────────────────────────────
  const [typeFilter, setTypeFilter] = useState<"all" | "buy" | "sell" | "rejected" | "cancelled">("all");
  const [minConf, setMinConf] = useState(0);

  const visibleEvents = useMemo(() => {
    let list = events.filter((e) => !sym || !e.symbol || e.symbol === sym);
    if (cursorTs && cursor < total - 1) {
      list = list.filter((e) => {
        // Tickless events (END_OF_BACKTEST closes carry a run-level scan_id)
        // belong to the final tick — never leak them into earlier positions.
        const t = tickOf(e.scan_id);
        return t !== null && t <= cursor;
      });
    }
    if (typeFilter !== "all") {
      const match: Record<string, (t: string) => boolean> = {
        buy: (t) => t.includes("BUY") || t === "ORDER_EXECUTED" || t === "POSITION_OPENED",
        sell: (t) => t.includes("SELL") || t === "POSITION_CLOSED",
        rejected: (t) => t.includes("REJECTED"),
        cancelled: (t) => t.includes("CANCELLED"),
      };
      list = list.filter((e) => match[typeFilter](e.event_type));
    }
    if (minConf > 0) {
      list = list.filter((e) => {
        const c = e.payload?.confidence;
        return typeof c !== "number" || c >= minConf;
      });
    }
    return list.slice().reverse().slice(0, 80);
  }, [events, sym, cursorTs, cursor, total, typeFilter, minConf]);

  const treeQ = useQuery({
    queryKey: ["bt-tree", runId, sym],
    queryFn: () => apiJson<DecisionTree>(`/backtest/run/${runId}/decision/${sym}`, undefined, 60_000),
    enabled: !!runId && !!sym,
    refetchInterval: running ? 8_000 : false,
  });
  const tree = treeQ.data;

  // Why BUY / Why REJECT (Parts D + E)
  const explainQ = useQuery({
    queryKey: ["bt-explain", runId, sym],
    queryFn: () => apiJson<Explanation>(`/backtest/run/${runId}/explain/${sym}`, undefined, 120_000),
    enabled: !!runId && !!sym && !running,
    staleTime: 60_000,
  });
  const explain = explainQ.data?.ok ? explainQ.data : null;

  // Trade story (Part G)
  const [storyTradeId, setStoryTradeId] = useState<string | null>(null);
  const storyQ = useQuery({
    queryKey: ["bt-story", runId, storyTradeId],
    queryFn: () => apiJson<TradeStory>(`/backtest/run/${runId}/story/${storyTradeId}`, undefined, 120_000),
    enabled: !!runId && !!storyTradeId,
    staleTime: 300_000,
  });
  const story = storyQ.data?.ok ? storyQ.data : null;

  // Global search (Part K)
  const [searchText, setSearchText] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const searchQ = useQuery({
    queryKey: ["bt-search", runId, searchTerm],
    queryFn: () => apiJson<SearchResult>(`/backtest/run/${runId}/search?q=${encodeURIComponent(searchTerm)}`, undefined, 120_000),
    enabled: !!runId && searchTerm.length >= 2,
    staleTime: 60_000,
  });
  const searchRes = searchQ.data;

  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const validate = useMutation({
    mutationFn: () => apiJson<ValidationResult>(`/backtest/run/${runId}/validate?sample=25`, undefined, 240_000),
    onSuccess: setValidation,
  });
  const storedValidation = validation ?? run?.validation ?? null;

  // Replay integrity verification (Part L)
  const [verify, setVerify] = useState<ReplayVerify | null>(null);
  const verifyM = useMutation({
    mutationFn: () => apiJson<ReplayVerify>(`/backtest/run/${runId}/replay-verify`, undefined, 180_000),
    onSuccess: setVerify,
  });
  useEffect(() => { setVerify(null); setValidation(null); setStoryTradeId(null); }, [runId]);

  const missed: MissedOpp[] = (run?.missed as MissedOpp[]) ?? [];
  const rejections = useMemo(
    () => events.filter((e) => e.event_type.includes("REJECTED")).slice().reverse(),
    [events]);

  // chart overlay indexes for the selected symbol (Part I)
  const symTickToCandleIdx = useMemo(() => {
    const m = new Map<number, number>();
    if (!candles.length || !timeline.length) return m;
    const tsIdx = new Map(candles.map((c, i) => [c.ts, i]));
    timeline.forEach((ts, tick) => {
      const ci = tsIdx.get(ts);
      if (ci !== undefined) m.set(tick, ci);
    });
    return m;
  }, [candles, timeline]);

  const rejectedIdx = useMemo(() => {
    const out: number[] = [];
    for (const e of events) {
      if (e.symbol !== sym || !e.event_type.includes("REJECTED")) continue;
      const t = tickOf(e.scan_id);
      const ci = t !== null ? symTickToCandleIdx.get(t) : undefined;
      if (ci !== undefined) out.push(ci);
    }
    return Array.from(new Set(out));
  }, [events, sym, symTickToCandleIdx]);

  const missedIdx = useMemo(() => {
    const out: number[] = [];
    for (const mo of missed) {
      if (mo.symbol !== sym) continue;
      const t = tickOf(mo.scan_id);
      const ci = t !== null ? symTickToCandleIdx.get(t) : undefined;
      if (ci !== undefined) out.push(ci);
    }
    return Array.from(new Set(out));
  }, [missed, sym, symTickToCandleIdx]);

  const m = run?.metrics as Record<string, number> | undefined;
  const decisionCount = useMemo(() => {
    let n = 0;
    for (let i = 0; i <= cursor; i++) n += ticksByIdx.get(i)?.decisions.length ?? 0;
    return n;
  }, [cursor, ticksByIdx]);

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="page-investigation-center">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <FlaskConical className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-xl font-semibold">Pipeline Backtest — Production Logic</h1>
          <p className="text-xs text-muted-foreground">
            Replays the real ApexQuant AI production pipeline using historical data. This is the canonical
            backtest page for answering: What would the real system have done?
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/validation-v2" className="text-xs text-primary underline underline-offset-2 whitespace-nowrap"
            data-testid="link-validation-v2">
            Open Strategy Validation Centre
          </Link>
          <Badge variant="outline" className="border-amber-500 text-amber-500">{LABEL}</Badge>
        </div>
      </div>

      {/* Run launcher */}
      <Card data-testid="card-launcher">
        <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><History className="h-4 w-4" />New Backtest</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Interval</span>
            <select className="bg-background border rounded px-2 py-1.5" value={interval}
              onChange={(e) => setIntervalStr(e.target.value)} data-testid="select-interval">
              <option value="1d">Daily</option>
              <option value="15m">15 minute</option>
              <option value="10m">10 minute</option>
              <option value="5m">5 minute</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Range</span>
            <select className="bg-background border rounded px-2 py-1.5" value={preset}
              onChange={(e) => setPreset(e.target.value as typeof preset)} data-testid="select-range">
              <option value="1w">One week</option>
              <option value="1m">One month</option>
              <option value="3m">Three months</option>
              <option value="6m">Six months</option>
              <option value="1y">One year</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Start</span>
            <input type="date" className="bg-background border rounded px-2 py-1" value={start}
              onChange={(e) => { setPreset("custom"); setStart(e.target.value); }} data-testid="input-start" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">End</span>
            <input type="date" className="bg-background border rounded px-2 py-1" value={end}
              onChange={(e) => { setPreset("custom"); setEnd(e.target.value); }} data-testid="input-end" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Universe</span>
            <select className="bg-background border rounded px-2 py-1.5" value={universe}
              onChange={(e) => setUniverse(e.target.value)} data-testid="select-universe">
              <option value="configured">Configured universe</option>
              <option value="nifty50">Nifty 50</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 min-w-48">
            <span className="text-xs text-muted-foreground">Symbols (optional, overrides universe)</span>
            <input className="bg-background border rounded px-2 py-1.5" placeholder="e.g. RELIANCE, TCS"
              value={symbolsText} onChange={(e) => setSymbolsText(e.target.value)} data-testid="input-symbols" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Capital (₹)</span>
            <input type="number" className="bg-background border rounded px-2 py-1.5 w-28" value={capital}
              onChange={(e) => setCapital(Number(e.target.value) || 100000)} data-testid="input-capital" />
          </label>
          <Button onClick={() => launch.mutate(undefined)} disabled={launch.isPending} data-testid="button-run-backtest">
            {launch.isPending ? "Launching…" : "Run Backtest"}
          </Button>
          {launch.data && !launch.data.ok && (
            <span className="text-xs text-red-500">{String(launch.data.error)}</span>
          )}
          {interval !== "1d" && start && end &&
            (new Date(end).getTime() - new Date(start).getTime()) / 86400_000 > 55 && (
            <span className="text-xs text-amber-500" data-testid="text-intraday-range-warning">
              Intraday ({interval}) history is only available for roughly the last 55 days —
              older candles in this range will be reported as missing data, not fabricated.
            </span>
          )}
          {start && end &&
            (new Date(end).getTime() - new Date(start).getTime()) / 86400_000 < 90 && (
            <span className="text-xs text-amber-400" data-testid="text-short-window-warning">
              Short backtest window (&lt;90 days). Confidence and opportunity scores may be
              structurally limited by low walk-backtest trade count. Results are valid, but
              BUY scoring may underestimate strategy quality. Consider a longer range for
              reliable calibration.
            </span>
          )}
        </CardContent>
      </Card>

      {/* Runs + status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card data-testid="card-runs">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <CardTitle className="text-sm">Backtest Runs</CardTitle>
              <div className="flex items-center gap-1.5 flex-wrap">
                <select
                  className="text-[10px] bg-background border rounded px-1.5 py-0.5"
                  value={runFilter}
                  onChange={e => setRunFilter(e.target.value as typeof runFilter)}
                  data-testid="select-run-filter">
                  <option value="all">All</option>
                  <option value="active">Active</option>
                  <option value="completed">Completed</option>
                  <option value="failed">Failed/Stale</option>
                </select>
                {hiddenRunIds.size > 0 && (
                  <button className="text-[10px] text-blue-400 hover:text-blue-300"
                    onClick={showAllRuns} data-testid="btn-show-all-runs">
                    Show all ({hiddenRunIds.size} hidden)
                  </button>
                )}
                <button
                  className="text-[10px] text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    const toHide = runs
                      .filter(r => ["FAILED", "STALE", "CANCELLED"].includes(r.status))
                      .map(r => r.run_id);
                    setHiddenRunIds(prev => {
                      const next = new Set([...prev, ...toHide]);
                      localStorage.setItem("bt-hidden-runs", JSON.stringify([...next]));
                      return next;
                    });
                  }}
                  data-testid="btn-hide-failed-runs">
                  Hide failed
                </button>
                <span className="text-[10px] text-muted-foreground">auto-refresh 5s</span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-1 max-h-96 overflow-auto">
            {/* Scheduler health status */}
            {(() => {
              const s = schedulerQ.data;
              if (!s) return null;
              const sweepAgeMs = s.last_sweep_at
                ? Date.now() - new Date(s.last_sweep_at).getTime()
                : Infinity;
              const sweepOverdue = sweepAgeMs > 5 * 60 * 1000; // > 5 min
              const hasFailed = s.consecutive_failures > 0;
              // Degraded = scheduler is on but either: recent failures, or no
              // successful sweep in > 5 min (could be still warming up if < 5 min
              // since startup, but amber is a safe conservative indicator).
              const isAmber = s.enabled && (hasFailed || sweepOverdue);
              return (
                <div
                  className={`flex flex-col gap-0.5 pb-1 border-b border-border/50 text-[10px] ${
                    !s.enabled ? "text-muted-foreground"
                    : isAmber ? "text-amber-400"
                    : "text-muted-foreground"
                  }`}
                  data-testid="scheduler-status"
                >
                  <div className="flex items-center gap-1.5">
                    <Clock className="h-3 w-3 shrink-0" />
                    <span>
                      {!s.enabled
                        ? "Auto-sweep: scheduler disabled"
                        : `Last auto-sweep: ${fmtAgo(s.last_sweep_at)}`}
                    </span>
                    {isAmber && (
                      <AlertTriangle
                        className="h-3 w-3 text-amber-400 shrink-0"
                        aria-label="Sweep overdue or failing"
                      />
                    )}
                  </div>
                  {hasFailed && s.last_error && (
                    <div
                      className="text-amber-400/80 pl-4 truncate"
                      title={s.last_error}
                      data-testid="scheduler-last-error"
                    >
                      {s.consecutive_failures} failure{s.consecutive_failures > 1 ? "s" : ""}:{" "}
                      {s.last_error}
                    </div>
                  )}
                </div>
              );
            })()}
            {runs.length === 0 && runsQ.isSuccess && (
              <div className="space-y-2" data-testid="empty-state-runs">
                <div className="text-xs text-muted-foreground">
                  No pipeline backtest runs yet. Run your first production-pipeline backtest.
                </div>
                <div className="text-xs text-muted-foreground">
                  Safe defaults: RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK · 1d · 3 months · ₹50,000 · PAPER / RESEARCH ONLY.
                </div>
                <Button size="sm" disabled={launch.isPending} data-testid="button-first-backtest"
                  onClick={() => {
                    setIntervalStr("1d"); setPreset("3m"); setCapital(50000);
                    setSymbolsText("RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK");
                    const r = rangePreset(90);
                    launch.mutate({ interval: "1d", start: r.start, end: r.end, capital: 50000,
                      symbols: ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"] });
                  }}>
                  {launch.isPending ? "Launching…" : "Run First Pipeline Backtest"}
                </Button>
                {launch.data && !launch.data.ok && (
                  <div className="text-xs text-red-500">{String(launch.data.error)}</div>
                )}
              </div>
            )}
            {filteredRuns.map((r) => {
              const isActive = ["RUNNING", "PENDING", "CANCEL_REQUESTED"].includes(r.status);
              const pct = (r.progress?.done && r.progress?.total)
                ? Math.round((r.progress.done / r.progress.total) * 100) : null;
              const symsTotal = r.config?.symbols?.length ?? (r.metrics as Record<string,number>|undefined)?.symbols ?? null;
              const symsDone = (r.metrics as Record<string,number>|undefined)?.symbols
                ?? (r.progress?.done && r.progress?.total && symsTotal
                    ? Math.ceil((r.progress.done / r.progress.total) * Number(symsTotal)) : null);
              const isWatchdogStale = staleRunIds.has(r.run_id);
              return (
                <div key={r.run_id}
                  className={`w-full text-xs rounded border ${r.run_id === runId ? "border-primary bg-primary/10" : "border-transparent hover:bg-muted"}`}
                  data-testid={`row-run-${r.run_id}`}>
                  {/* Clickable body: select this run */}
                  <div className="text-left px-2 pt-2 cursor-pointer"
                    onClick={() => setSelectedRunId(r.run_id)}>
                    {/* Row 1: ID + config label + status */}
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-foreground">{configLabel(r)}</span>
                      <span className="font-mono text-muted-foreground text-[10px]">{r.run_id}</span>
                      <Badge variant="outline" className={`ml-auto ${
                        r.status === "COMPLETED" ? "border-green-500 text-green-500"
                          : r.status === "FAILED" ? "border-red-500 text-red-500"
                            : r.status === "STALE" ? "border-amber-500 text-amber-500"
                              : r.status === "CANCEL_REQUESTED" ? "border-orange-400 text-orange-400"
                                : r.status === "CANCELLED" ? "border-red-400/60 text-red-400/60"
                                  : r.status === "RUNNING" ? "border-blue-400 text-blue-400"
                                    : r.status === "QUEUED" ? "border-yellow-500 text-yellow-500"
                                      : "border-amber-400 text-amber-400"}`}>{r.status}</Badge>
                    </div>
                    {/* Row 2: interval · date range · symbol list */}
                    <div className="text-muted-foreground mt-0.5 truncate">
                      {r.config?.interval} · {r.config?.start} → {r.config?.end}
                      {r.config?.symbols?.length
                        ? ` · [${r.config.symbols.slice(0,4).join(",")}${r.config.symbols.length > 4 ? `…+${r.config.symbols.length-4}` : ""}]`
                        : ` · ${r.config?.universe ?? "configured"}`}
                    </div>
                    {/* Row 3: progress bar + tick count (active only) */}
                    {isActive && r.progress?.total != null && (
                      <div className="mt-1 space-y-0.5">
                        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                          <span>{r.progress.done ?? 0}/{r.progress.total} ticks</span>
                          {symsTotal != null && <span>· {symsDone ?? "?"}/{symsTotal} syms</span>}
                          {pct != null && <span className="text-foreground font-semibold">{pct}%</span>}
                          <span className="ml-auto">{fmtElapsed(r.created_at)}</span>
                          <span className="text-blue-400">{fmtETA(r.progress.done, r.progress.total, r.created_at)}</span>
                        </div>
                        <div className="h-1 bg-muted rounded overflow-hidden">
                          <div className="h-full bg-blue-500 rounded transition-all" style={{ width: `${pct ?? 0}%` }} />
                        </div>
                      </div>
                    )}
                    {/* Row 4: latest symbol + timestamp (active) */}
                    {isActive && (r.progress?.symbol || r.progress?.ts) && (
                      <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-2">
                        {r.progress.symbol && <span>↳ {r.progress.symbol}</span>}
                        {r.progress.ts && <span>{tsShort(r.progress.ts)}</span>}
                      </div>
                    )}
                    {/* Row 5: completed metrics summary */}
                    {r.status === "COMPLETED" && r.metrics && (() => {
                      const mm = r.metrics as Record<string, number>;
                      return (
                        <div className="mt-1 flex items-center gap-3 text-[10px]">
                          <span className={`font-semibold ${mm.realized_pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
                            {fmtINR(mm.realized_pnl)} ({mm.net_return_pct}%)
                          </span>
                          <span className="text-muted-foreground">{mm.total_trades} trades · {mm.win_rate}% WR · {fmtElapsed(r.created_at)} total</span>
                        </div>
                      );
                    })()}
                    {/* Row 6: watchdog warning (RUNNING, no progress for 30+ min) */}
                    {r.status === "RUNNING" && isWatchdogStale && (
                      <div className="text-amber-500 mt-0.5 text-[10px]"
                        data-testid={`text-stale-${r.run_id}`}>
                        Run stalled — no progress for 30+ minutes. Worker likely stopped. Retry required.
                      </div>
                    )}
                    {/* Row 6b: queued notice */}
                    {r.status === "QUEUED" && (
                      <div className="text-yellow-500 mt-0.5 text-[10px]"
                        data-testid={`text-queued-${r.run_id}`}>
                        ⏳ Queued — will start automatically when a running slot opens (max {2} concurrent).
                      </div>
                    )}
                    {/* Row 7: error */}
                    {r.error && (
                      <div className="text-red-500 mt-0.5 text-[10px] break-words">{r.error.slice(0, 120)}</div>
                    )}
                  </div>
                  {/* Control buttons row — click is isolated from row selection */}
                  <div className="px-2 pb-2 pt-1 flex items-center gap-1 flex-wrap"
                    onClick={e => e.stopPropagation()}>
                    {/* Stop / Cancel (also cancels QUEUED runs before they start) */}
                    {["QUEUED", "PENDING", "RUNNING", "CANCEL_REQUESTED"].includes(r.status) && (
                      <button
                        className="text-[10px] px-1.5 py-0.5 rounded border border-red-500/50 text-red-400 hover:bg-red-500/10 disabled:opacity-40"
                        disabled={cancelMut.isPending || r.status === "CANCEL_REQUESTED"}
                        onClick={() => cancelMut.mutate(r.run_id)}
                        data-testid={`btn-cancel-${r.run_id}`}>
                        {r.status === "CANCEL_REQUESTED" ? "Stopping…"
                          : r.status === "RUNNING" ? "Stop" : "Cancel"}
                      </button>
                    )}
                    {/* Mark Stale (only visible when watchdog fires) */}
                    {r.status === "RUNNING" && isWatchdogStale && (
                      <button
                        className="text-[10px] px-1.5 py-0.5 rounded border border-amber-500/50 text-amber-400 hover:bg-amber-500/10 disabled:opacity-40"
                        disabled={markStaleMut.isPending}
                        onClick={() => markStaleMut.mutate(r.run_id)}
                        data-testid={`btn-mark-stale-${r.run_id}`}>
                        Mark Stale
                      </button>
                    )}
                    {/* Retry (fresh run, original preserved) */}
                    {["FAILED", "STALE", "CANCELLED"].includes(r.status) && (
                      <button
                        className="text-[10px] px-1.5 py-0.5 rounded border border-blue-500/50 text-blue-400 hover:bg-blue-500/10 disabled:opacity-40"
                        disabled={retryMut.isPending}
                        onClick={() => retryMut.mutate(r.run_id)}
                        data-testid={`btn-retry-${r.run_id}`}>
                        Retry
                      </button>
                    )}
                    {/* Hide (client-only, reversible via Show all) */}
                    <button
                      className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted/50 ml-auto"
                      onClick={() => hideRun(r.run_id)}
                      data-testid={`btn-hide-${r.run_id}`}>
                      Hide
                    </button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Performance summary */}
        <Card data-testid="card-performance">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Performance Summary</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-2 text-sm">
            {!m && <div className="text-xs text-muted-foreground col-span-2">Completes when the run finishes.</div>}
            {m && (<>
              <div>Net return <div className={`font-semibold ${(m.net_return_pct ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`} data-testid="text-net-return">{m.net_return_pct}%</div></div>
              <div>Win rate <div className="font-semibold">{m.win_rate}% ({m.wins}W/{m.losses}L)</div></div>
              <div>Realized P&L <div className="font-semibold">{fmtINR(m.realized_pnl)}</div></div>
              <div>Max drawdown <div className="font-semibold text-amber-500">{m.max_drawdown_pct}%</div></div>
              <div>Trades <div className="font-semibold">{m.total_trades}</div></div>
              <div>Ticks × symbols <div className="font-semibold">{m.ticks} × {m.symbols}</div></div>
            </>)}
          </CardContent>
        </Card>

        {/* Backtest portfolio — synchronized to the replay cursor when scrubbing */}
        <Card data-testid="card-bt-portfolio">
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Wallet className="h-4 w-4" />Backtest Portfolio</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            {!pf && <div className="text-xs text-muted-foreground">Select a run.</div>}
            {pf && (<>
              <div className="flex justify-between"><span>Starting capital</span><span>{fmtINR(pf.starting_capital)}</span></div>
              <div className="flex justify-between"><span>Cash</span><span data-testid="text-bt-cash">{fmtINR(pf.cash)}</span></div>
              <div className="flex justify-between"><span>Portfolio value</span><span className="font-semibold">{fmtINR(pf.portfolio_value)}</span></div>
              <div className="flex justify-between"><span>Realized / Unrealized</span>
                <span>{fmtINR(pf.realized_pnl)} / {fmtINR(pf.unrealized_pnl)}</span></div>
              <div className="flex justify-between"><span>Open / Closed</span>
                <span>{pf.open_positions_count} / {pf.closed_positions_count}</span></div>
              {portfolioAtCursor && cursor < total - 1 && (
                <div className="mt-2 border-t pt-1 text-xs text-muted-foreground" data-testid="text-portfolio-at-cursor">
                  At replay cursor: cash {fmtINR(portfolioAtCursor.cash)} · value {fmtINR(portfolioAtCursor.portfolio_value)} · open {portfolioAtCursor.open_positions}
                </div>
              )}
            </>)}
          </CardContent>
        </Card>
      </div>

      {/* ── Run Comparison Panel ─────────────────────────────────────────── */}
      {completedRuns.length > 0 && (
        <Card data-testid="card-run-comparison">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              Run Comparison — completed runs
              <span className="text-xs text-muted-foreground font-normal ml-2">PAPER / RESEARCH ONLY · drawdown = realized-equity only (no MTM)</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="text-xs w-full min-w-[800px]">
              <thead>
                <tr className="text-muted-foreground text-left border-b border-border">
                  <th className="pb-1 pr-3">Config</th>
                  <th className="pb-1 pr-3">Symbols</th>
                  <th className="pb-1 pr-3 text-right">Trades</th>
                  <th className="pb-1 pr-3 text-right">P&L</th>
                  <th className="pb-1 pr-3 text-right">Return</th>
                  <th className="pb-1 pr-3 text-right">Win%</th>
                  <th className="pb-1 pr-3 text-right">PF</th>
                  <th className="pb-1 pr-3 text-right">DD%</th>
                  <th className="pb-1 pr-3 text-right">Cancelled</th>
                  <th className="pb-1 pr-3 text-right">SI✓/✗</th>
                  <th className="pb-1 pr-3 text-right">Vol-rej</th>
                  <th className="pb-1 pr-3 text-right">Missed</th>
                  <th className="pb-1 text-right">Hold</th>
                </tr>
              </thead>
              <tbody>
                {completedRuns.map((r) => {
                  const mm = r.metrics as Record<string, number> | undefined;
                  const st = statsCache[r.run_id];
                  const ev = st?.event_counts ?? {};
                  const cancelled = ev["ORDER_CANCELLED"] ?? 0;
                  const siApproved = ev["SCALE_IN_APPROVED"] ?? 0;
                  const siExecuted = ev["SCALE_IN_EXECUTED"] ?? 0;
                  const siRejected = ev["SCALE_IN_REJECTED"] ?? 0;
                  const volRej = ev["RISK_REJECTED"] ?? 0;
                  const missedCount = (r.missed ?? []).length;
                  const pf = st?.profit_factor;
                  const hold = st?.avg_hold_min;
                  const symList = r.config?.symbols?.slice(0, 3).join(",") ?? r.config?.universe ?? "—";
                  const isSelected = r.run_id === runId;
                  return (
                    <tr key={r.run_id}
                      className={`border-b border-border/40 cursor-pointer hover:bg-muted/40 transition-colors ${isSelected ? "bg-primary/5" : ""}`}
                      onClick={() => setSelectedRunId(r.run_id)}
                      data-testid={`cmp-row-${r.run_id}`}>
                      <td className="py-1.5 pr-3 font-semibold whitespace-nowrap">{configLabel(r)}</td>
                      <td className="py-1.5 pr-3 text-muted-foreground text-[10px]">{symList}{(r.config?.symbols?.length ?? 0) > 3 ? `…` : ""}</td>
                      <td className="py-1.5 pr-3 text-right">{mm?.total_trades ?? "—"}</td>
                      <td className={`py-1.5 pr-3 text-right font-semibold ${(mm?.realized_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                        {mm ? fmtINR(mm.realized_pnl) : "—"}
                      </td>
                      <td className={`py-1.5 pr-3 text-right font-semibold ${(mm?.net_return_pct ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                        {mm ? `${mm.net_return_pct}%` : "—"}
                      </td>
                      <td className="py-1.5 pr-3 text-right">{mm ? `${mm.win_rate}%` : "—"}</td>
                      <td className="py-1.5 pr-3 text-right">
                        {pf === null ? "—" : pf === Infinity ? "∞" : pf != null ? pf : <span className="text-muted-foreground text-[10px]">…</span>}
                      </td>
                      <td className="py-1.5 pr-3 text-right">{mm ? `${mm.max_drawdown_pct}%` : "—"}</td>
                      <td className="py-1.5 pr-3 text-right text-amber-500">{cancelled > 0 ? cancelled.toLocaleString() : "—"}</td>
                      <td className="py-1.5 pr-3 text-right">
                        {siExecuted > 0 || siRejected > 0
                          ? <span><span className="text-green-500">{siExecuted}</span>/<span className="text-red-500">{siRejected}</span></span>
                          : siApproved > 0 ? <span className="text-green-500">{siApproved}</span> : "—"}
                      </td>
                      <td className="py-1.5 pr-3 text-right text-red-400">{volRej > 0 ? volRej.toLocaleString() : "—"}</td>
                      <td className="py-1.5 pr-3 text-right text-amber-400">{missedCount > 0 ? missedCount : "—"}</td>
                      <td className="py-1.5 text-right text-muted-foreground">
                        {hold != null ? `${hold >= 60 ? `${Math.floor(hold/60)}h${Math.round(hold%60)}m` : `${hold}m`}` : "…"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="mt-2 text-[10px] text-muted-foreground">
              PF = profit factor (gross win ÷ gross loss) · SI = scale-in executions/rejections · Vol-rej = RISK_REJECTED events · DD = realized-equity drawdown only, no mark-to-market · click a row to load it in the replay panel below
            </div>
          </CardContent>
        </Card>
      )}

      {/* Advanced replay: chart + controls (Parts A, H, I) */}
      <Card data-testid="card-replay">
        <CardHeader className="pb-2 space-y-2">
          <div className="flex flex-row flex-wrap items-center gap-3">
            <CardTitle className="text-sm">Advanced Replay — Chart & Timeline</CardTitle>
            <select className="bg-background border rounded px-2 py-1 text-xs" value={sym ?? ""}
              onChange={(e) => setSymbol(e.target.value)} data-testid="select-symbol">
              {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select className="bg-background border rounded px-2 py-1 text-xs" value={mode}
              onChange={(e) => setMode(e.target.value as ReplayMode)} data-testid="select-replay-mode">
              {MODES.map((md) => <option key={md.id} value={md.id}>Step: {md.label}</option>)}
            </select>
            <div className="ml-auto flex items-center gap-1 flex-wrap">
              <Button size="icon" variant="ghost" onClick={() => setCursor(0)} data-testid="button-jump-start"><SkipBack className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => setCursor((c) => stepPrev(c))} data-testid="button-prev"><ChevronLeft className="h-4 w-4" /></Button>
              <Button size="icon" variant={playing ? "default" : "outline"} onClick={() => setPlaying((p) => !p)} data-testid="button-play">
                {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              </Button>
              <Button size="icon" variant="ghost" onClick={() => { setPlaying(false); setCursor(0); }} data-testid="button-stop"><Square className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => setCursor((c) => stepNext(c))} data-testid="button-next"><ChevronRight className="h-4 w-4" /></Button>
              <Button size="icon" variant="ghost" onClick={() => setCursor(total - 1)} data-testid="button-jump-end"><SkipForward className="h-4 w-4" /></Button>
              {SPEEDS.map((s) => (
                <Button key={s} size="sm" variant={speed === s ? "default" : "ghost"} onClick={() => setSpeed(s)} data-testid={`button-speed-${s || "max"}`}>
                  {s === 0 ? "Instant" : `${s}x`}
                </Button>
              ))}
              <input type="range" min={0} max={Math.max(0, total - 1)} value={Math.max(0, cursor)}
                onChange={(e) => setCursor(Number(e.target.value))} className="w-40" data-testid="slider-jump" />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1 text-xs">
            <span className="text-muted-foreground mr-1">Jump to:</span>
            <Button size="sm" variant="outline" onClick={() => jumpToNext((t) => t.buys.length > 0)} data-testid="button-jump-buy">Next BUY</Button>
            <Button size="sm" variant="outline" onClick={() => jumpToNext((t) => t.sells.length > 0)} data-testid="button-jump-sell">Next SELL</Button>
            <Button size="sm" variant="outline" onClick={() => jumpToNext((t) => t.buys.length > 0 || t.sells.length > 0)} data-testid="button-jump-trade">Next Trade</Button>
            <Button size="sm" variant="outline" onClick={() => jumpToNext((t) => t.rejected.length > 0)} data-testid="button-jump-rejection">Next Rejection</Button>
            <input type="datetime-local" className="bg-background border rounded px-2 py-1 ml-2"
              onChange={(e) => {
                if (!e.target.value || !timeline.length) return;
                const target = new Date(e.target.value).toISOString();
                let best = 0;
                for (let i = 0; i < timeline.length; i++) if (timeline[i] <= target) best = i;
                setCursor(best);
              }} data-testid="input-jump-timestamp" />
          </div>
        </CardHeader>
        <CardContent>
          <CandleChart candles={candles} cursorIdx={candleCursorIdx}
            trades={trades.filter((t) => t.symbol === sym)}
            rejectedIdx={rejectedIdx} missedIdx={missedIdx} />
          <div className="text-xs text-muted-foreground mt-1 flex items-center gap-3 flex-wrap">
            <span className="flex items-center gap-1"><Clock className="h-3 w-3" />
              {cursorTs ? `Tick ${cursor + 1}/${total} · ${tsShort(cursorTs)}` : "No replay data"}</span>
            <span>Decisions so far: {decisionCount}</span>
            {currentTick && (() => {
              const order = bundle?.stage_order ?? [];
              const agent = [...order].reverse().find(
                (st) => (currentTick.stages?.[st]?.events ?? 0) > 0) ?? null;
              const stock = currentTick.buys[0]?.symbol ?? currentTick.decisions[0]?.symbol
                ?? currentTick.sells[0]?.symbol ?? currentTick.rejected[0]?.symbol ?? null;
              const dec = currentTick.decisions[0];
              return (
                <span className="flex items-center gap-3" data-testid="text-current-tick-context">
                  {agent && <span>Agent: <span className="font-semibold text-foreground">{STAGE_LABELS[agent] ?? agent}</span></span>}
                  {stock && <span>Stock: <span className="font-semibold text-foreground">{stock}</span></span>}
                  {dec?.action && <span>Decision: <span className="font-semibold text-foreground">{dec.symbol} {dec.action}</span></span>}
                </span>
              );
            })()}
            {currentTick?.processing_ms !== null && currentTick?.processing_ms !== undefined && (
              <span className="flex items-center gap-1"><Zap className="h-3 w-3" />tick processed in {currentTick.processing_ms}ms</span>
            )}
            <span className="ml-auto">Overlays: <span className="text-blue-400">▲ entry</span> · ▼ exit · <span className="text-green-500">- - target</span> · <span className="text-red-500">- - stop</span> · <span className="text-red-500">× rejected</span> · <span className="text-amber-500">◆ missed</span></span>
          </div>
        </CardContent>
      </Card>

      {/* Visual AI pipeline replay (Part B) */}
      <Card data-testid="card-pipeline-replay">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Visual AI Pipeline Replay (at replay cursor)</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {!bundle && <div className="text-xs text-muted-foreground">{running ? "Available when the run completes." : bundleQ.isLoading ? "Building replay bundle from the canonical event store…" : "Select a completed run."}</div>}
          {bundle && (<>
            <PipelineFlow order={bundle.stage_order} tick={currentTick} />
            {currentTick && currentTick.decisions.length > 0 && (
              <div className="text-xs flex flex-wrap gap-2" data-testid="tick-decisions">
                {currentTick.decisions.map((d, i) => (
                  <Badge key={i} variant="outline" className={
                    d.action === "BUY" ? "border-green-500 text-green-500"
                      : d.action === "SELL" ? "border-blue-400 text-blue-400"
                        : d.action === "WATCH" ? "border-yellow-500 text-yellow-500" : "border-muted-foreground"}>
                    {d.symbol} {d.action}{typeof d.confidence === "number" ? ` · ${d.confidence}%` : ""}
                  </Badge>
                ))}
              </div>
            )}
          </>)}
        </CardContent>
      </Card>

      {/* Why did the AI buy/reject? (Parts D + E) */}
      <Card data-testid="card-explain">
        <CardHeader className="pb-2"><CardTitle className="text-sm">
          {explain?.verdict === "BUY" ? `Why did the AI BUY ${sym}?`
            : explain?.verdict === "REJECTED" ? `Why did the AI REJECT ${sym}?`
              : `AI Decision Explanation — ${sym ?? "—"}`}
        </CardTitle></CardHeader>
        <CardContent className="text-xs space-y-2">
          {!explain && <div className="text-muted-foreground">{explainQ.isLoading ? "Assembling explanation from the event store…" : "Select a completed run and symbol."}</div>}
          {explain && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={
                    explain.verdict === "BUY" ? "border-green-500 text-green-500"
                      : explain.verdict === "REJECTED" ? "border-red-500 text-red-500" : "border-yellow-500 text-yellow-500"}
                    data-testid="badge-explain-verdict">{explain.verdict}</Badge>
                  <span className="text-muted-foreground">{explain.scan_id} · {tsShort(explain.ts)}</span>
                </div>
                <div><span className="font-semibold">Indicators:</span> {kv(explain.indicators)}</div>
                <div><span className="font-semibold">Research:</span> {kv(explain.research_summary)}</div>
                <div><span className="font-semibold">Market:</span> {kv(explain.market_context)}</div>
                <div><span className="font-semibold">Monitoring:</span> {kv(explain.monitoring)}</div>
                <div><span className="font-semibold">Strategy:</span> {kv(explain.strategy_explanation)}</div>
                <div><span className="font-semibold">Confidence breakdown:</span> {kv(explain.confidence_breakdown)}</div>
              </div>
              <div className="space-y-1.5">
                {explain.verdict === "BUY" && (<>
                  <div><span className="font-semibold">Position size:</span> {kv(explain.position_size_calc)}</div>
                  <div><span className="font-semibold">Execution:</span> {kv(explain.execution)}</div>
                  <div className="flex gap-3">
                    <span><span className="font-semibold">Target:</span> {fmtINR(explain.target)} (<span className="text-green-500">+{explain.expected_reward_pct}%</span>)</span>
                    <span><span className="font-semibold">Stop:</span> {fmtINR(explain.stop_loss)} (<span className="text-red-500">-{explain.expected_risk_pct}%</span>)</span>
                  </div>
                  <div><span className="font-semibold">Exit logic:</span> {explain.exit_logic}</div>
                </>)}
                {explain.verdict === "REJECTED" && explain.rejection && (<>
                  <div className="font-semibold text-red-500">Exact rejection rules:</div>
                  {Object.entries(explain.rejection.failed_gates ?? {}).map(([g, v]) => (
                    <div key={g} className="border border-red-500/40 rounded p-1.5" data-testid={`gate-${g}`}>
                      <span className="font-mono">{g}</span>: {kv(v as Record<string, unknown>)}
                    </div>
                  ))}
                  {explain.rejection.strategy_reason && <div>Strategy: {explain.rejection.strategy_reason}</div>}
                  {explain.rejection.order_reason && <div>Order: {explain.rejection.order_reason}</div>}
                  {explain.relax_analysis?.available && (
                    <div className="border border-amber-500/40 rounded p-1.5 text-amber-500" data-testid="relax-analysis">
                      Would relaxing have helped? <b>{explain.relax_analysis.would_relaxing_have_helped ? "YES" : "NO"}</b> —
                      outcome {explain.relax_analysis.expected_outcome_pct}% over {explain.relax_analysis.horizon_bars} bars
                      (peak +{explain.relax_analysis.highest_gain_pct}%). {explain.relax_analysis.note}
                    </div>
                  )}
                </>)}
                <div><span className="font-semibold">Risk gates:</span> {kv((explain.risk_explanation?.gates ?? explain.risk_explanation) as Record<string, unknown>)}</div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Decision tree + event timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card data-testid="card-decision-tree">
          <CardHeader className="pb-2"><CardTitle className="text-sm">AI Decision Tree — {sym ?? "—"}</CardTitle></CardHeader>
          <CardContent className="space-y-2 max-h-96 overflow-auto">
            {!tree && <div className="text-xs text-muted-foreground">Select a run and symbol.</div>}
            {tree?.stages.map((s) => (
              <div key={s.stage} className="border rounded p-2">
                <div className="text-xs font-semibold flex items-center gap-2">
                  {STAGE_LABELS[s.stage] ?? s.stage}
                  <span className="text-muted-foreground font-normal">{s.events.length} events</span>
                </div>
                {s.events.slice(-3).map((e) => (
                  <div key={e.id} className="mt-1 text-xs flex items-start gap-1.5">
                    {e.event_type.includes("REJECTED") ? <ShieldX className="h-3.5 w-3.5 text-red-500 mt-0.5" />
                      : e.event_type.includes("APPROVED") || e.event_type === "BUY_GENERATED" ? <ShieldCheck className="h-3.5 w-3.5 text-green-500 mt-0.5" />
                        : <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground mt-0.5" />}
                    <div className="min-w-0">
                      <span className="font-mono">{e.event_type}</span>
                      <span className="text-muted-foreground"> · {e.scan_id}</span>
                      <div className="text-muted-foreground truncate">{JSON.stringify(e.payload).slice(0, 220)}</div>
                    </div>
                  </div>
                ))}
                {s.events.length === 0 && <div className="text-xs text-muted-foreground mt-1">No events at this stage.</div>}
              </div>
            ))}
          </CardContent>
        </Card>

        <Card data-testid="card-event-timeline">
          <CardHeader className="pb-2 flex flex-row flex-wrap items-center gap-2">
            <CardTitle className="text-sm">Event Timeline (follows replay cursor)</CardTitle>
            <div className="ml-auto flex items-center gap-1 text-xs">
              {(["all", "buy", "sell", "rejected", "cancelled"] as const).map((f) => (
                <Button key={f} size="sm" variant={typeFilter === f ? "default" : "ghost"}
                  onClick={() => setTypeFilter(f)} data-testid={`filter-${f}`}>{f}</Button>
              ))}
              <select className="bg-background border rounded px-1 py-0.5" value={minConf}
                onChange={(e) => setMinConf(Number(e.target.value))} data-testid="select-min-confidence">
                <option value={0}>conf ≥ 0</option>
                <option value={50}>conf ≥ 50</option>
                <option value={70}>conf ≥ 70</option>
              </select>
            </div>
          </CardHeader>
          <CardContent className="space-y-1 max-h-96 overflow-auto">
            {visibleEvents.length === 0 && <div className="text-xs text-muted-foreground">No events match the filter at this position.</div>}
            {visibleEvents.map((e) => (
              <div key={e.id} className="text-xs flex items-center gap-2 border-b border-border/40 pb-1" data-testid={`event-${e.id}`}>
                {e.event_type.includes("REJECTED") || e.event_type.includes("FAILED") ? <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                  : e.event_type.includes("EXECUTED") || e.event_type.includes("OPENED") || e.event_type.includes("CLOSED") ? <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                    : <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
                <span className="font-mono">{e.event_type}</span>
                <span className="text-muted-foreground">{e.symbol ?? ""}</span>
                <span className="text-muted-foreground ml-auto">{e.scan_id}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Global search (Part K) */}
      <Card data-testid="card-search">
        <CardHeader className="pb-2 flex flex-row items-center gap-2">
          <CardTitle className="text-sm flex items-center gap-2"><Search className="h-4 w-4" />Global Search</CardTitle>
          <form className="ml-auto flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); setSearchTerm(searchText.trim()); }}>
            <input className="bg-background border rounded px-2 py-1 text-xs w-64" placeholder="trade id, symbol, strategy, reason, confidence…"
              value={searchText} onChange={(e) => setSearchText(e.target.value)} data-testid="input-search" />
            <Button type="submit" size="sm" variant="outline" data-testid="button-search">Search</Button>
          </form>
        </CardHeader>
        {searchTerm.length >= 2 && (
          <CardContent className="text-xs space-y-2 max-h-64 overflow-auto">
            {searchQ.isLoading && <div className="text-muted-foreground">Searching…</div>}
            {searchRes && (<>
              <div className="text-muted-foreground">{searchRes.trades.length} trades · {searchRes.events.length} events for “{searchRes.query}”</div>
              {searchRes.trades.map((t) => (
                <div key={t.trade_id} className="border rounded p-1.5 flex items-center gap-2" data-testid={`search-trade-${t.trade_id}`}>
                  <Badge variant="outline">TRADE</Badge>
                  <span className="font-medium">{t.symbol}</span> {t.strategy_name} · {t.trade_id} ·
                  <span className={(t.realized_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}>{fmtINR(t.realized_pnl)}</span>
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setStoryTradeId(t.trade_id)}>Story</Button>
                </div>
              ))}
              {searchRes.events.slice(0, 30).map((e) => (
                <div key={e.id} className="border-b border-border/40 pb-1 flex items-center gap-2">
                  <span className="font-mono">{e.event_type}</span>
                  <span className="text-muted-foreground">{e.symbol} · {e.scan_id}</span>
                  <span className="text-muted-foreground ml-auto truncate max-w-64">{JSON.stringify(e.payload).slice(0, 100)}</span>
                </div>
              ))}
            </>)}
          </CardContent>
        )}
      </Card>

      {/* Trades + trade story */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card data-testid="card-trade-list">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Trade List (click a trade for its story)</CardTitle></CardHeader>
          <CardContent className="max-h-80 overflow-auto">
            {trades.length === 0 && (
              <div className="text-xs text-muted-foreground" data-testid="text-no-trades">
                {run?.status === "COMPLETED"
                  ? "Backtest completed — no trades met entry criteria."
                  : "No backtest trades in this run."}
              </div>
            )}
            {trades.length > 0 && (
              <table className="w-full text-xs">
                <thead><tr className="text-muted-foreground text-left">
                  <th className="py-1">Symbol</th><th>Strategy</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Rule</th><th className="text-right">P&L</th>
                </tr></thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={t.trade_id}
                      className={`border-t border-border/40 cursor-pointer hover:bg-muted/60 ${storyTradeId === t.trade_id ? "bg-primary/10" : ""}`}
                      onClick={() => setStoryTradeId(t.trade_id)}
                      data-testid={`row-trade-${t.trade_id}`}>
                      <td className="py-1 font-medium">{t.symbol}</td>
                      <td>{t.strategy_name ?? "—"}</td>
                      <td>{t.quantity}</td>
                      <td>{fmtINR(t.fill_price)}</td>
                      <td>{t.exit_price != null ? fmtINR(t.exit_price) : <Badge variant="outline">OPEN</Badge>}</td>
                      <td>{t.exit_rule ?? "—"}</td>
                      <td className={`text-right font-semibold ${(t.realized_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                        {t.realized_pnl != null ? fmtINR(t.realized_pnl) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        {/* Trade story (Part G) */}
        <Card data-testid="card-trade-story">
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><BookOpen className="h-4 w-4" />Trade Story</CardTitle></CardHeader>
          <CardContent className="text-xs space-y-1 max-h-80 overflow-auto">
            {!storyTradeId && <div className="text-muted-foreground">Click a trade in the list to read its full story.</div>}
            {storyTradeId && storyQ.isLoading && <div className="text-muted-foreground">Assembling story from the event store…</div>}
            {story && (<>
              <div className="flex items-center gap-2 mb-2">
                <span className="font-semibold">{story.trade.symbol}</span>
                <span className="text-muted-foreground">{story.trade.strategy_name} · {story.trade.trade_id}</span>
                <span className={`ml-auto font-semibold ${(story.trade.realized_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                  {fmtINR(story.trade.realized_pnl)}
                </span>
              </div>
              {story.steps.map((s, i) => (
                <div key={i} className="flex items-start gap-2" data-testid={`story-step-${i}`}>
                  <div className="flex flex-col items-center">
                    <div className={`h-2 w-2 rounded-full mt-1 ${
                      s.event_type.includes("REJECTED") ? "bg-red-500"
                        : s.event_type.includes("EXECUTED") || s.event_type.includes("CLOSED") ? "bg-green-500"
                          : "bg-primary"}`} />
                    {i < story.steps.length - 1 && <div className="w-px h-4 bg-border" />}
                  </div>
                  <div>
                    <span className="text-muted-foreground mr-2">tick {s.tick} · {tsShort(s.ts)}</span>
                    <span>{s.label}</span>
                    <Button size="sm" variant="ghost" className="h-5 px-1 ml-1 text-[10px]"
                      onClick={() => setCursor(Math.min(s.tick, Math.max(0, total - 1)))}>jump</Button>
                  </div>
                </div>
              ))}
            </>)}
          </CardContent>
        </Card>
      </div>

      {/* Missed opportunities + rejection analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card data-testid="card-missed">
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-500" />Missed Opportunities (advisory only)</CardTitle></CardHeader>
          <CardContent className="space-y-2 max-h-80 overflow-auto">
            {missed.length === 0 && <div className="text-xs text-muted-foreground">None recorded — appears after a completed run.</div>}
            {missed.slice(0, 25).map((mo, i) => (
              <div key={`${mo.symbol}-${mo.scan_id}-${i}`} className="border rounded p-2 text-xs" data-testid={`row-missed-${i}`}>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{mo.symbol}</span>
                  <Badge variant="outline" className={mo.decision === "RISK_REJECTED" ? "border-red-500 text-red-500" : "border-yellow-500 text-yellow-500"}>{mo.decision}</Badge>
                  <span className={`ml-auto font-semibold ${mo.would_have_been_profitable ? "text-green-500" : "text-red-500"}`}>
                    peak +{mo.potential_return_pct}% · horizon {mo.return_at_horizon_pct}%
                  </span>
                </div>
                <div className="text-muted-foreground mt-1">{mo.reason}</div>
                <div className="mt-0.5">
                  Would the AI have made money? <b className={mo.would_have_been_profitable ? "text-green-500" : "text-red-500"}>{mo.would_have_been_profitable ? "YES" : "NO"}</b>
                </div>
                {mo.single_rule_relax_hint && <div className="text-amber-500 mt-0.5">{mo.single_rule_relax_hint}</div>}
              </div>
            ))}
          </CardContent>
        </Card>

        <Card data-testid="card-rejection-analysis">
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Ban className="h-4 w-4 text-red-500" />Rejection Analysis</CardTitle></CardHeader>
          <CardContent className="space-y-1 max-h-80 overflow-auto">
            {rejections.length === 0 && <div className="text-xs text-muted-foreground">No rejections recorded in this run.</div>}
            {rejections.slice(0, 40).map((e) => (
              <div key={e.id} className="text-xs border-b border-border/40 pb-1">
                <span className="font-medium">{e.symbol}</span>{" "}
                <span className="font-mono text-red-500">{e.event_type}</span>
                <div className="text-muted-foreground truncate">{JSON.stringify(e.payload).slice(0, 200)}</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Validation (pipeline ≡ replay) + replay integrity (Part L) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card data-testid="card-validation">
          <CardHeader className="pb-2 flex flex-row items-center gap-2">
            <CardTitle className="text-sm flex items-center gap-2"><ShieldCheck className="h-4 w-4" />Historical Validation (replay ≡ pipeline)</CardTitle>
            <Button size="sm" variant="outline" className="ml-auto" disabled={!runId || validate.isPending || running}
              onClick={() => validate.mutate()} data-testid="button-validate">
              {validate.isPending ? "Validating…" : "Run Validation"}
            </Button>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            {!storedValidation && <div className="text-xs text-muted-foreground">
              Re-runs the production pipeline on the exact as-of candles and recorded cash the replay used and compares every sampled decision.
            </div>}
            {storedValidation && (<>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className={
                  storedValidation.verdict === "MATCH" || storedValidation.verdict === "NO_DECISIONS" ? "border-green-500 text-green-500"
                    : storedValidation.verdict === "INDETERMINATE" ? "border-amber-500 text-amber-500"
                      : "border-red-500 text-red-500"} data-testid="badge-validation-verdict">
                  {storedValidation.verdict ?? (storedValidation.mismatches?.length ? "MISMATCH" : "MATCH")}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {storedValidation.checked} re-checked{typeof storedValidation.skipped === "number" ? ` · ${storedValidation.skipped} skipped` : ""}
                  {storedValidation.learning_state_changed ? " · learning state changed since run" : ""}
                </span>
              </div>
              {(storedValidation.mismatches ?? []).map((mm, i) => (
                <div key={i} className="text-xs border rounded p-2 text-red-500">
                  {mm.symbol} @ {tsShort(mm.time)} — expected {mm.expected_decision}, got {mm.actual_decision}: {mm.reason}
                </div>
              ))}
            </>)}
          </CardContent>
        </Card>

        <Card data-testid="card-replay-verify">
          <CardHeader className="pb-2 flex flex-row items-center gap-2">
            <CardTitle className="text-sm flex items-center gap-2"><ShieldCheck className="h-4 w-4" />Replay Integrity (events ≡ ledger ≡ portfolio)</CardTitle>
            <Button size="sm" variant="outline" className="ml-auto" disabled={!runId || verifyM.isPending || running}
              onClick={() => verifyM.mutate()} data-testid="button-replay-verify">
              {verifyM.isPending ? "Verifying…" : "Verify Replay"}
            </Button>
          </CardHeader>
          <CardContent className="text-xs space-y-1.5">
            {!verify && <div className="text-muted-foreground">
              Proves the replay layer is faithful: no missing/duplicate events, execution events match the isolated ledger, portfolio trail matches the run result.
            </div>}
            {verify && (<>
              <Badge variant="outline" className={verify.verdict === "PASS" ? "border-green-500 text-green-500" : "border-red-500 text-red-500"}
                data-testid="badge-replay-verify">{verify.verdict ?? "ERROR"}</Badge>
              {(verify.checks ?? []).map((c) => (
                <div key={c.check} className="flex items-start gap-2" data-testid={`verify-${c.check}`}>
                  {c.status === "PASS" ? <CheckCircle2 className="h-3.5 w-3.5 text-green-500 mt-0.5 shrink-0" /> : <XCircle className="h-3.5 w-3.5 text-red-500 mt-0.5 shrink-0" />}
                  <div><span className="font-mono">{c.check}</span> — <span className="text-muted-foreground">{c.detail}</span></div>
                </div>
              ))}
              {verify.error && <div className="text-red-500">{verify.error}</div>}
            </>)}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
