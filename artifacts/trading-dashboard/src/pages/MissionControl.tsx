/**
 * MissionControl.tsx — Phase 25A: Mission Control shell & core live panels.
 *
 * Unified operational landing screen for ApexQuant AI. PURE DASHBOARD:
 * every widget reads existing backend endpoints — pipeline event store,
 * canonical portfolio snapshot, unified replay snapshot, phase20 ledger,
 * live scan status. NO business logic is computed here.
 *
 * Layout:
 *   ┌──────────────── Top status bar ─────────────────┐
 *   │ market · IST clock · indices · value · P&L · … │
 *   ├──────────┬──────────────────────┬───────────────┤
 *   │ AI       │  Scanner             │ Portfolio     │
 *   │ Pipeline │  Paper Trading       │ (sidebar)     │
 *   ├──────────┴──────────────────────┴───────────────┤
 *   │ Event stream strip                              │
 *   └─────────────────────────────────────────────────┘
 *
 * Each panel is an independent <Widget> with its own query key, refresh
 * cadence and error state, so one slow endpoint never blanks the page.
 *
 * PAPER TRADING / RESEARCH ONLY.
 */
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "wouter";
import { useLiveStream, type PipelineStreamEvent } from "@/hooks/useLiveStream";
import { useIsMobile } from "@/hooks/use-mobile";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { Badge } from "@/components/ui/badge";
import {
  Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock, Cpu,
  HeartPulse, LayoutGrid, PieChart, Radar, Radio, Rocket, Search, Smartphone,
  Wallet, Wifi, WifiOff, XCircle,
} from "lucide-react";
import { Widget, useWidgetQuery, fmtINR, timeAgo, PnlText } from "@/components/mission/Widget";
import { CommandBar } from "@/components/mission/CommandBar";
import { MissionMapWidget, AlertCenterWidget } from "@/components/mission/IntelWidgets";
import { useLedgerToday } from "@/components/mission/SessionWidgets";
import {
  useLayoutManager, SectionShell, CustomizeControls, type SectionDef,
} from "@/components/mission/LayoutManager";

// Below-the-fold widget rows are lazy-loaded so the page shell (status bar,
// pipeline, scanner, portfolio) paints fast; charts/timeline code arrives in
// separate chunks.
const AiHealthWidget = lazy(() =>
  import("@/components/mission/IntelWidgets").then((m) => ({ default: m.AiHealthWidget })));
const AiLearningWidget = lazy(() =>
  import("@/components/mission/IntelWidgets").then((m) => ({ default: m.AiLearningWidget })));
const ReplayWidget = lazy(() =>
  import("@/components/mission/OpsWidgets").then((m) => ({ default: m.ReplayWidget })));
const BacktestWidget = lazy(() =>
  import("@/components/mission/OpsWidgets").then((m) => ({ default: m.BacktestWidget })));
const MissionTimelineWidget = lazy(() =>
  import("@/components/mission/OpsWidgets").then((m) => ({ default: m.MissionTimelineWidget })));
const BrokerWidget = lazy(() =>
  import("@/components/mission/OpsWidgets").then((m) => ({ default: m.BrokerWidget })));
// SystemHealthWidget (OpsWidgets) export kept intact but replaced on-page by the
// superset SystemHealth2Widget (below), so it is intentionally not imported here.

// Phase 25.1 session/deep widgets — lazy chunks behind Suspense skeletons.
const MarketSessionWidget = lazy(() =>
  import("@/components/mission/SessionWidgets").then((m) => ({ default: m.MarketSessionWidget })));
const ThroughputWidget = lazy(() =>
  import("@/components/mission/SessionWidgets").then((m) => ({ default: m.ThroughputWidget })));
const LivePerformanceWidget = lazy(() =>
  import("@/components/mission/SessionWidgets").then((m) => ({ default: m.LivePerformanceWidget })));
const MarketBreadthWidget = lazy(() =>
  import("@/components/mission/SessionWidgets").then((m) => ({ default: m.MarketBreadthWidget })));
const AgentMetricsWidget = lazy(() =>
  import("@/components/mission/DeepWidgets").then((m) => ({ default: m.AgentMetricsWidget })));
const StockWatchWidget = lazy(() =>
  import("@/components/mission/DeepWidgets").then((m) => ({ default: m.StockWatchWidget })));
const ExplainabilityWidget = lazy(() =>
  import("@/components/mission/DeepWidgets").then((m) => ({ default: m.ExplainabilityWidget })));
const SystemHealth2Widget = lazy(() =>
  import("@/components/mission/DeepWidgets").then((m) => ({ default: m.SystemHealth2Widget })));

const WidgetFallback = ({ h = "h-40" }: { h?: string }) => (
  <div className={`animate-pulse rounded-xl bg-muted/20 border border-border/40 ${h}`} />
);

const LABEL = "PAPER TRADING / RESEARCH ONLY";

// ── Refresh cadences (ms) per panel ──────────────────────────────────────────
const R = {
  pipeline: 5_000,     // pipeline/summary — 5 s Node cache behind it
  replay: 30_000,      // unified replay snapshot — heavier Python build
  scan: 5_000,
  portfolio: 15_000,
  ledger: 10_000,
  events: 4_000,
  health: 30_000,
} as const;

// ── Types (mirror backend responses; all fields optional-defensive) ─────────

interface StageSummary {
  stage: string; events: number; completed: number; rejected: number;
  errors: number; last_ts: string | null; last_symbol: string | null;
}
interface PipelineSummary {
  scan_id: string | null; mode: string; total_events: number;
  stages: StageSummary[]; generated_at: string;
}
interface ReplayStage {
  id: string; label: string; order: number;
  stocks_in: number; stocks_out: number;
  rejected: number; pending: number; cancelled: number;
  duration_ms: number | null; status: string;
}
interface ReplayResp { stages?: ReplayStage[]; scan_id?: string; snapshot_ts?: string; error?: string }
interface ScanStatus {
  success?: boolean; status?: string; scan_id?: string; snapshot_ts?: string;
  age_minutes?: number | null;
  scan_count_today?: number | null;   // how many scans completed today (if backend provides)
  cadence_minutes?: number | null;    // expected minutes between scans
  rotation?: number | null;           // sequential rotation index for today
  latest_scan?: {
    scan_id?: string; snapshot_ts?: string; status?: string;
    symbols_total?: number; symbols_done?: number; duration_s?: number | null;
    universe_size?: number;
  } | null;
  progress?: {
    stage?: string; scan_id?: string; symbol?: string; current_symbol?: string;
    symbols_done?: number; symbols_total?: number; started_at?: string;
  } | null;
}
interface ScanHistoryEntry {
  started_at?: string | null; completed_at?: string | null;
  duration_s?: number | null; symbols_scanned?: number | null;
  gap_from_prev_s?: number | null; status?: string;
}
interface ScanHistoryResp {
  success?: boolean; history?: ScanHistoryEntry[]; count?: number; ist_date?: string;
}

interface SectorExposure { sector: string; total_value: number; exposure_pct: number; position_count: number }
interface OpenPosition {
  symbol: string; quantity: number; avg_entry_price: number; last_price: number;
  market_value: number; unrealised_pnl: number; unrealised_pnl_pct: number;
  sector?: string | null; exposure_pct?: number;
}
interface PortfolioSnapshot {
  status?: string; equity?: number; cash?: number; invested_value?: number;
  initial_capital?: number; unrealised_pnl?: number; realised_pnl_today?: number;
  total_pnl?: number; drawdown_pct?: number;
  open_positions?: OpenPosition[]; open_position_count?: number;
  closed_positions_today?: number; sector_exposures?: SectorExposure[];
  snapshotted_at?: string;
}
interface LedgerItem {
  trade_id: string; symbol: string; side: string; status: string;
  quantity: number; fill_price: number | null; fill_ts: string | null;
  exit_price: number | null; realized_pnl: number | null; created_at?: string;
  strategy_name?: string | null;
}
interface PipelineEvent {
  id: number; ts: string; event_type: string; stage: string;
  symbol: string | null; payload: Record<string, unknown>;
}

const STAGE_LABELS: Record<string, string> = {
  SUPERVISOR: "Supervisor", SCANNER: "Scanner", RESEARCH: "Research",
  MARKET_INTELLIGENCE: "Market Intel", MONITORING: "Monitoring",
  STRATEGY: "Strategy", PORTFOLIO_PRECHECK: "Portfolio Pre-Check",
  RISK: "Risk", AI_DECISION: "AI Decision",
  EXECUTION: "Execution", PORTFOLIO: "Portfolio",
};

// ── Active-stage selection (pure, exported for unit tests) ───────────────────
// Returns the pipeline stage that should be auto-expanded during an active scan.
// Priority: backend progress.stage (authoritative) → stage with newest last_ts
// within 60 s (fallback for gaps between progress updates).

export function selectActiveStage(
  stages: StageSummary[],
  progressStage: string | null | undefined,
  nowMs: number = Date.now(),
): string | null {
  if (progressStage) return progressStage;
  return (
    stages.reduce<{ stage: string; ts: number } | null>((best, s) => {
      if (!s.last_ts) return best;
      const t = new Date(s.last_ts).getTime();
      if (nowMs - t >= 60_000) return best;
      if (!best || t > best.ts) return { stage: s.stage, ts: t };
      return best;
    }, null)?.stage ?? null
  );
}

// ── Symbol-level pipeline grid ────────────────────────────────────────────────
// Shows one coloured box per symbol in the universe so operators can see at a
// glance which stocks each pipeline stage has processed, passed, rejected, etc.
// Pure display — no strategy logic, no thresholds, no order generation.

type SymState = "pending" | "processing" | "passed" | "rejected" | "cancelled" | "skipped" | "warning";

const SYM_BOX: Record<SymState, string> = {
  pending:    "bg-slate-800/70 border-slate-600/30 text-slate-500/70",
  processing: "bg-blue-500/80 border-blue-400/60 text-blue-100 animate-pulse",
  passed:     "bg-emerald-600/80 border-emerald-500/50 text-emerald-50",
  rejected:   "bg-red-600/80 border-red-500/50 text-red-50",
  cancelled:  "bg-slate-600/50 border-slate-500/30 text-slate-400",
  skipped:    "bg-slate-700/40 border-slate-600/20 text-slate-500",
  warning:    "bg-amber-600/70 border-amber-500/50 text-amber-50",
};

function symStateFromEventType(et: string): SymState | null {
  const u = et.toUpperCase();
  if (u.includes("REJECT") || u.includes("FAIL"))   return "rejected";
  if (u.includes("CANCEL"))                          return "cancelled";
  if (u.includes("SKIP"))                            return "skipped";
  if (u.includes("WATCH") || u.includes("WARN"))     return "warning";
  if (
    u.includes("COMPLET") || u.includes("APPROV") || u.includes("PASS") ||
    u.includes("BUY_GEN") || u.includes("EXECUT")  || u.includes("SELECT") ||
    u.includes("_OPEN")   || u.includes("_CLOS")
  ) return "passed";
  if (u.includes("START") || u.includes("PROCESS"))  return "processing";
  return null;
}

interface SymEntry {
  sym: string; state: SymState; reason?: string; score?: number; ts?: string;
}

/** Derive per-symbol state for every stage from a flat event list. */
function buildStageSymbolMap(events: PipelineEvent[]): Map<string, Map<string, SymEntry>> {
  const out = new Map<string, Map<string, SymEntry>>();
  const isTerminal = (s: SymState) => s === "passed" || s === "rejected" || s === "cancelled";
  // Events arrive newest-first; process oldest-first so terminal states win.
  for (const e of [...events].reverse()) {
    if (!e.symbol) continue;
    const newState = symStateFromEventType(e.event_type);
    if (!newState) continue;
    if (!out.has(e.stage)) out.set(e.stage, new Map());
    const stageMap = out.get(e.stage)!;
    const cur = stageMap.get(e.symbol);
    if (!cur || !isTerminal(cur.state)) {
      stageMap.set(e.symbol, {
        sym: e.symbol,
        state: newState,
        reason: (e.payload?.reason as string | undefined) ?? undefined,
        score: (e.payload?.score as number | undefined) ?? undefined,
        ts: e.ts,
      });
    }
  }
  return out;
}

/** Single symbol box with CSS-only hover tooltip. */
function SymbolBox({ sym, state, reason, score, ts, stage }: SymEntry & { stage?: string }) {
  // Strip exchange suffix for display; cap at 5 chars
  const label = sym.replace(/\.(NS|BSE)$/i, "").slice(0, 5);
  return (
    <div className="relative group/sym">
      <div
        className={`w-8 h-8 rounded border text-[8px] font-bold flex items-center justify-center cursor-default select-none ${SYM_BOX[state]}`}
        data-testid={`sym-box-${sym}`}
      >
        {label}
      </div>
      {/* Hover tooltip — pure CSS, no portal needed */}
      <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover/sym:block z-50 w-44">
        <div className="rounded-lg border border-border bg-popover shadow-xl p-2 text-[10px] space-y-0.5">
          <p className="font-semibold font-mono truncate">{sym}</p>
          <p className="capitalize text-muted-foreground">{state}</p>
          {stage && <p className="text-muted-foreground text-[9px]">Stage: {STAGE_LABELS[stage] ?? stage}</p>}
          {score != null && (
            <p>Score: <span className="font-semibold">{score.toFixed ? score.toFixed(2) : score}</span></p>
          )}
          {reason && (
            <p className="text-amber-300/80 text-[9px] leading-snug">{String(reason).slice(0, 80)}</p>
          )}
          {ts && <p className="text-muted-foreground/60 text-[9px]">{timeAgo(ts)}</p>}
        </div>
      </div>
    </div>
  );
}

/** Grid of symbol boxes for one pipeline stage. */
function SymbolPipelineGrid({
  entries, stage, currentSym, total,
}: {
  entries: SymEntry[]; stage: string; currentSym?: string | null; total?: number;
}) {
  const counts = entries.reduce(
    (acc, e) => { acc[e.state] = (acc[e.state] ?? 0) + 1; return acc; },
    {} as Record<string, number>,
  );
  // If we have fewer entries than the universe size, add placeholder "pending" boxes
  const padCount = Math.max(0, (total ?? 0) - entries.length);

  return (
    <div className="mt-1.5">
      {/* Summary chips */}
      <div className="flex flex-wrap gap-x-2.5 gap-y-0.5 text-[9px] mb-1.5">
        {(counts.passed ?? 0) > 0 && <span className="text-emerald-400">{counts.passed} passed</span>}
        {(counts.rejected ?? 0) > 0 && <span className="text-red-400">{counts.rejected} rej</span>}
        {(counts.warning ?? 0) > 0 && <span className="text-amber-400">{counts.warning} watch</span>}
        {(counts.processing ?? 0) > 0 && (
          <span className="text-blue-400 animate-pulse">{counts.processing} active</span>
        )}
        {(counts.cancelled ?? 0) > 0 && <span className="text-muted-foreground">{counts.cancelled} canc</span>}
        {(counts.skipped ?? 0) > 0 && <span className="text-muted-foreground">{counts.skipped} skip</span>}
        {padCount > 0 && <span className="text-muted-foreground/50">{padCount} pending</span>}
        {currentSym && (
          <span className="font-mono text-blue-300 animate-pulse ml-auto">▶ {currentSym.replace(/\.(NS|BSE)$/i, "")}</span>
        )}
      </div>
      {/* Symbol boxes */}
      <div className="flex flex-wrap gap-1">
        {entries.map((e) => (
          <SymbolBox key={e.sym} {...e} stage={stage} />
        ))}
        {/* Pending placeholders */}
        {Array.from({ length: padCount }).map((_, i) => (
          <div
            key={`pad-${i}`}
            className="w-8 h-8 rounded border bg-slate-800/40 border-slate-700/20"
            aria-hidden
          />
        ))}
      </div>
    </div>
  );
}

// ── Scan info chips ───────────────────────────────────────────────────────────
// Compact strip of scan metadata shown at the top of Pipeline, Scanner, and
// Paper Trader panels so operators always see the current rotation context.

function ScanInfoChips({ scanData, summaryData }: {
  scanData: ScanStatus | undefined;
  summaryData?: PipelineSummary;
}) {
  const meta     = scanData?.latest_scan ?? {};
  const progress = scanData?.progress;
  const scanId   = (progress?.scan_id ?? (meta as {scan_id?: string}).scan_id ?? scanData?.scan_id) ?? null;
  const universeSize =
    progress?.symbols_total ??
    (meta as { universe_size?: number; symbols_total?: number }).universe_size ??
    (meta as { universe_size?: number; symbols_total?: number }).symbols_total ?? null;
  const ageMin     = scanData?.age_minutes ?? null;
  const durationS  = (meta as { duration_s?: number | null }).duration_s ?? null;
  const startedAt  = progress?.started_at ?? null;
  const countToday = scanData?.scan_count_today ?? null;
  const cadence    = scanData?.cadence_minutes ?? null;
  const rotation   = scanData?.rotation ?? null;

  // Derive a rough rotation count from pipeline summary events when the backend
  // doesn't provide it. Advisory display only — not used for any logic.
  const derivedCount =
    countToday ?? (summaryData ? undefined : undefined); // extend here if backend adds a count

  type Chip = { label: string; value: string; cls?: string; mono?: boolean };
  const chips: Chip[] = [];

  if (rotation != null)        chips.push({ label: "Rotation", value: `#${rotation}` });
  if (derivedCount != null)    chips.push({ label: "Today", value: `${derivedCount} scans` });
  if (cadence != null)         chips.push({ label: "Cadence", value: `${cadence} min` });
  if (universeSize != null)    chips.push({ label: "Universe", value: `${universeSize} symbols` });
  if (scanId)                  chips.push({ label: "Scan ID", value: scanId.slice(0, 10) + (scanId.length > 10 ? "…" : ""), mono: true });
  if (startedAt)               chips.push({ label: "Started", value: timeAgo(startedAt) });
  if (durationS != null)       chips.push({ label: "Duration", value: `${durationS.toFixed(0)}s` });
  if (ageMin != null)          chips.push({ label: "Age", value: `${Math.round(ageMin)}m`, cls: ageMin > 30 ? "text-amber-400" : "" });

  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1 mb-2">
      {chips.map((c) => (
        <span
          key={c.label}
          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 bg-muted/30 border border-border/50 text-[9px] ${c.cls ?? ""}`}
          title={`${c.label}: ${c.value}`}
        >
          <span className="text-muted-foreground">{c.label}</span>
          <span className={`font-medium ${c.mono ? "font-mono" : ""}`}>{c.value}</span>
        </span>
      ))}
    </div>
  );
}

function eventTone(et: string): "ok" | "warn" | "bad" | "info" {
  if (et.includes("REJECTED") || et.includes("FAILED") || et.includes("CANCELLED")) return "bad";
  if (et.includes("EXECUTED") || et.includes("OPENED") || et.includes("CLOSED") || et === "BUY_GENERATED") return "ok";
  if (et.includes("WATCH")) return "warn";
  return "info";
}
const toneClass = { ok: "text-emerald-400", warn: "text-amber-400", bad: "text-red-400", info: "text-muted-foreground" } as const;

/**
 * Phase 25.1 Part 5 — Investigation Center deep-link for a pipeline event.
 * InvestigationCenter parses ?run=&symbol=&trade=&ts=.
 */
function eventInvestigateHref(e: PipelineEvent | PipelineStreamEvent): string {
  const p = new URLSearchParams();
  if (e.symbol) p.set("symbol", e.symbol);
  if (e.ts) p.set("ts", e.ts);
  const payload = (e as { payload?: Record<string, unknown> }).payload ?? {};
  const run = (e as { run_id?: string | null }).run_id ?? (payload.run_id as string | undefined);
  if (run) p.set("run", String(run));
  const trade = payload.trade_id as string | undefined;
  if (trade) p.set("trade", String(trade));
  return `/investigation-center?${p.toString()}`;
}

// ── IST clock ─────────────────────────────────────────────────────────────────

function IstClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(id);
  }, []);
  const ist = now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
  return <span className="font-mono text-xs">{ist} IST</span>;
}

// ── Top status bar ───────────────────────────────────────────────────────────

function StatusBar({
  portfolio, portfolioErr, stream,
}: {
  portfolio: PortfolioSnapshot | undefined; portfolioErr: boolean;
  stream: ReturnType<typeof useLiveStream>;
}) {
  const { connection, market, quotes } = stream;
  const healthQ = useWidgetQuery<{ status?: string; uptime_s?: number }>({
    queryKey: ["mc", "health"], path: "/health/live", refetchInterval: R.health, timeoutMs: 10_000,
  });

  const idx = (key: string, label: string) => {
    const q = quotes[key];
    return (
      <div className="flex items-baseline gap-1.5" key={key}>
        <span className="text-[10px] text-muted-foreground">{label}</span>
        <span className="text-xs font-semibold">
          {q?.ltp != null ? q.ltp.toLocaleString("en-IN", { maximumFractionDigits: key === "INDIAVIX" ? 2 : 0 }) : "—"}
        </span>
        {q?.change_pct != null && (
          <span className={`text-[10px] ${q.change_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {q.change_pct >= 0 ? "▲" : "▼"}{Math.abs(q.change_pct).toFixed(2)}%
          </span>
        )}
      </div>
    );
  };

  const healthy = healthQ.data?.status === "ok";
  const todayPnl = portfolio != null
    ? (portfolio.realised_pnl_today ?? 0) + (portfolio.unrealised_pnl ?? 0)
    : null;

  return (
    <div className="bg-card border border-border rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-2" data-testid="mc-status-bar">
      {/* Market status */}
      <div className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${market?.is_open ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`} />
        <span className="text-xs font-semibold">NSE {market?.state ?? "—"}</span>
        {market?.next_transition && (
          <span className="text-[10px] text-muted-foreground hidden xl:inline">
            {market.next_transition.event} {market.next_transition.at_ist?.slice(11, 16)}
          </span>
        )}
      </div>
      <IstClock />
      {/* Indices */}
      {idx("NIFTY", "NIFTY")}
      {idx("BANKNIFTY", "BANK NIFTY")}
      {idx("INDIAVIX", "VIX")}
      <span className="hidden md:inline-block w-px h-4 bg-border" />
      {/* Portfolio strip */}
      <div className="flex items-baseline gap-1.5">
        <span className="text-[10px] text-muted-foreground">Value</span>
        <span className="text-xs font-semibold">{portfolioErr ? "—" : fmtINR(portfolio?.equity)}</span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[10px] text-muted-foreground">Today P&L</span>
        <PnlText value={todayPnl} className="text-xs font-semibold" />
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[10px] text-muted-foreground">Open</span>
        <span className="text-xs font-semibold">{portfolioErr ? "—" : (portfolio?.open_position_count ?? "—")}</span>
      </div>
      <span className="ml-auto flex items-center gap-3">
        {/* System health */}
        <span className="flex items-center gap-1" title={`API server ${healthy ? "healthy" : "unreachable"}`}>
          <HeartPulse className={`w-3.5 h-3.5 ${healthy ? "text-emerald-400" : "text-red-400"}`} />
          <span className={`text-[10px] ${healthy ? "text-emerald-400" : "text-red-400"}`}>
            {healthQ.isLoading ? "…" : healthy ? "HEALTHY" : "DOWN"}
          </span>
        </span>
        {/* Stream connection */}
        <span className="flex items-center gap-1" title={`Live stream: ${connection}`}>
          {connection === "connected"
            ? <Wifi className="w-3.5 h-3.5 text-emerald-400" />
            : <WifiOff className="w-3.5 h-3.5 text-amber-400" />}
        </span>
        <Badge variant="outline" className="text-[9px] border-amber-500/40 text-amber-300">PAPER</Badge>
      </span>
    </div>
  );
}

// ── Panel 1 — Live AI Pipeline ───────────────────────────────────────────────

export function PipelinePanel({ scanning, replayQ, scanQ }: {
  scanning: boolean;
  /** Shared unified replay snapshot query — the ONLY source of in/out/rejected/pending/cancelled. */
  replayQ: ReturnType<typeof useWidgetQuery<ReplayResp>>;
  /** Shared scan-status query — for scan info chips and universe size. */
  scanQ: ReturnType<typeof useWidgetQuery<ScanStatus>>;
}) {
  const summaryQ = useWidgetQuery<PipelineSummary>({
    queryKey: ["mc", "pipeline-summary"], path: "/pipeline/summary", refetchInterval: R.pipeline,
  });

  // Fetch pipeline events at a higher limit to build the per-symbol grid.
  // This query is separate from EventStreamPanel's 80-event feed so each panel
  // can choose its own limit without blocking the other.
  const gridEventsQ = useWidgetQuery<{ events?: PipelineEvent[] }>({
    queryKey: ["mc", "pipeline-events-grid"],
    path: "/pipeline/events?limit=400&newest_first=true",
    refetchInterval: R.pipeline,
  });

  const replayByLabel = useMemo(() => {
    const m = new Map<string, ReplayStage>();
    for (const s of replayQ.data?.stages ?? []) {
      m.set(s.label.toUpperCase().replace(/[\s&]+/g, "_"), s);
      m.set(s.id.toUpperCase(), s);
    }
    return m;
  }, [replayQ.data]);

  // Build per-stage symbol state map from the high-limit event feed.
  const stageSymbolMap = useMemo(
    () => buildStageSymbolMap(gridEventsQ.data?.events ?? []),
    [gridEventsQ.data],
  );

  const stages       = summaryQ.data?.stages ?? [];
  const universeSize =
    scanQ.data?.progress?.symbols_total ??
    (scanQ.data?.latest_scan as { universe_size?: number } | null | undefined)?.universe_size ??
    (scanQ.data?.latest_scan as { symbols_total?: number } | null | undefined)?.symbols_total ?? 0;
  const currentSym   = scanQ.data?.progress?.current_symbol ?? scanQ.data?.progress?.symbol ?? null;

  // Per-stage grid expansion state — collapsed by default, toggled per stage.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const toggle = (stage: string) =>
    setExpanded((p) => ({ ...p, [stage]: !p[stage] }));

  // Auto-expand the active stage during a live scan, then collapse it when the
  // scan ends or a new stage becomes active.  Uses no extra API calls — reads
  // the existing `stages` array (from summaryQ) and the `scanning` flag.
  //
  // progressStage is extracted so it can be listed as an explicit effect dep:
  // when ONLY the progress stage changes (stages summary unchanged), the effect
  // must still re-run to transition the highlighted stage.
  const progressStage = scanQ.data?.progress?.stage ?? null;
  const autoExpandedStageRef = useRef<string | null>(null);
  useEffect(() => {
    if (!scanning) {
      // Scan ended: collapse whichever stage we auto-expanded so idle view stays collapsed.
      if (autoExpandedStageRef.current) {
        const prev = autoExpandedStageRef.current;
        autoExpandedStageRef.current = null;
        setExpanded((p) => ({ ...p, [prev]: false }));
      }
      return;
    }

    const activeStage = selectActiveStage(stages, progressStage);

    if (activeStage === autoExpandedStageRef.current) return; // nothing changed

    setExpanded((prev) => {
      const next = { ...prev };
      // Collapse the stage we previously auto-expanded.
      if (autoExpandedStageRef.current) next[autoExpandedStageRef.current] = false;
      // Expand the newly active stage.
      if (activeStage) next[activeStage] = true;
      return next;
    });
    autoExpandedStageRef.current = activeStage;
  }, [scanning, stages, progressStage]);

  return (
    <Widget
      title="Live AI Pipeline" icon={Cpu} query={summaryQ} refreshMs={R.pipeline}
      testId="mc-pipeline" skeletonClass="h-64"
      headerExtra={
        <>
          {summaryQ.data?.scan_id && (
            <span
              className="text-[9px] text-muted-foreground font-mono truncate max-w-[120px]"
              title={summaryQ.data.scan_id}
            >
              {summaryQ.data.scan_id.slice(0, 10)}…
            </span>
          )}
          {scanning && (
            <Badge className="animate-pulse text-[9px] px-1.5 py-0">
              <Radio className="h-2.5 w-2.5 mr-1" />SCANNING
            </Badge>
          )}
        </>
      }
    >
      {/* Scan metadata strip */}
      <ScanInfoChips scanData={scanQ.data} summaryData={summaryQ.data} />

      {stages.length === 0 ? (
        <p className="text-xs text-muted-foreground">No pipeline events recorded yet — the flow populates on the next scan.</p>
      ) : (
        <div className="space-y-1.5">
          {stages.map((s) => {
            const active = scanning && s.last_ts != null && Date.now() - new Date(s.last_ts).getTime() < 60_000;
            const r = replayByLabel.get(s.stage) ?? replayByLabel.get(STAGE_LABELS[s.stage]?.toUpperCase().replace(/[\s]+/g, "_") ?? "");

            // Symbol entries for this stage (from high-limit event feed)
            const symEntries = [...(stageSymbolMap.get(s.stage)?.values() ?? [])];
            const isExpanded = expanded[s.stage] ?? false;

            // Is this the currently-active stage for this scan?
            const isCurrentStage = scanning && currentSym != null &&
              s.stage === (scanQ.data?.progress?.stage ?? "");

            return (
              <div
                key={s.stage}
                data-testid={`mc-stage-${s.stage.toLowerCase()}`}
                className={`rounded-lg border transition-colors ${
                  active ? "border-primary bg-primary/10" : "border-border/60 bg-muted/20"
                }`}
              >
                {/* Stage header row — clickable to expand symbol grid */}
                <button
                  className="w-full text-left px-2.5 py-1.5 text-[11px]"
                  onClick={() => toggle(s.stage)}
                  aria-expanded={isExpanded}
                  data-testid={`mc-stage-toggle-${s.stage.toLowerCase()}`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`font-medium ${active ? "animate-pulse" : ""}`}>
                      {STAGE_LABELS[s.stage] ?? s.stage}
                    </span>
                    {isCurrentStage && currentSym && (
                      <span className="text-[9px] font-mono text-blue-300 animate-pulse">
                        ▶ {currentSym.replace(/\.(NS|BSE)$/i, "")}
                      </span>
                    )}
                    {s.errors > 0 && (
                      <span className="text-red-400 flex items-center gap-0.5" title={`${s.errors} errors`}>
                        <AlertTriangle className="w-3 h-3" />{s.errors}
                      </span>
                    )}
                    {symEntries.length > 0 && (
                      <span className="text-[9px] text-muted-foreground/60">
                        {isExpanded ? "▲" : "▼"} {symEntries.length} symbols
                      </span>
                    )}
                    <span className="ml-auto text-[9px] text-muted-foreground">
                      {r?.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s · ` : ""}{timeAgo(s.last_ts)}
                    </span>
                  </div>
                  {/* In / out / rejected counts */}
                  <div className="flex flex-wrap gap-x-2.5 mt-0.5 text-[10px] text-muted-foreground">
                    {r ? (
                      <>
                        <span>in <b className="text-foreground">{r.stocks_in}</b></span>
                        <span>out <b className="text-emerald-400">{r.stocks_out}</b></span>
                        <span>rej <b className={r.rejected > 0 ? "text-red-400" : "text-foreground"}>{r.rejected}</b></span>
                        <span>pend <b className={r.pending > 0 ? "text-amber-400" : "text-foreground"}>{r.pending}</b></span>
                        <span>canc <b className="text-foreground">{r.cancelled}</b></span>
                      </>
                    ) : (
                      <>
                        <span className="text-emerald-400">{s.completed}✓</span>
                        {s.rejected > 0 && <span className="text-red-400">{s.rejected}✗</span>}
                        <span>{s.events} events</span>
                      </>
                    )}
                    {s.last_symbol && (
                      <span className="truncate font-mono text-muted-foreground/80">
                        last: {s.last_symbol.replace(/\.(NS|BSE)$/i, "")}
                      </span>
                    )}
                  </div>
                </button>

                {/* Symbol box grid — shown when expanded */}
                {isExpanded && symEntries.length > 0 && (
                  <div className="px-2.5 pb-2.5 pt-0 border-t border-border/40">
                    <SymbolPipelineGrid
                      entries={symEntries}
                      stage={s.stage}
                      currentSym={isCurrentStage ? currentSym : null}
                      total={universeSize || symEntries.length}
                    />
                  </div>
                )}
              </div>
            );
          })}
          {replayQ.isError && (
            <p className="text-[10px] text-amber-400/80 pt-1">
              Replay counts unavailable ({(replayQ.error as Error)?.message}); showing event counts only.
            </p>
          )}
        </div>
      )}
    </Widget>
  );
}

// ── Panel 2 — Live Scanner ───────────────────────────────────────────────────

function ScannerPanel({ scanQ }: { scanQ: ReturnType<typeof useWidgetQuery<ScanStatus>> }) {
  const d = scanQ.data;
  const meta = d?.latest_scan ?? d ?? {};
  const progress = d?.progress ?? null;
  const scanning = !!progress?.stage;
  const done  = progress?.symbols_done ?? 0;
  const total = progress?.symbols_total ??
    (meta as { symbols_total?: number; universe_size?: number }).universe_size ??
    (meta as { symbols_total?: number }).symbols_total ?? 0;
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  const currentSymbol = progress?.current_symbol ?? progress?.symbol ?? null;
  const ageMin = d?.age_minutes;
  const scanId = (meta as { scan_id?: string }).scan_id ?? d?.scan_id ?? null;
  const durationS = (meta as { duration_s?: number | null }).duration_s ?? null;

  // Rotation / count labels
  const rotation   = d?.rotation ?? null;
  const countToday = d?.scan_count_today ?? null;
  const cadence    = d?.cadence_minutes ?? null;

  // Today's scan history — 30 s cache, same TTL as the backend route.
  const historyQ = useWidgetQuery<ScanHistoryResp>({
    queryKey: ["mc", "scan-history"], path: "/live-data/scan/history", refetchInterval: 30_000,
  });
  const [showHistory, setShowHistory] = useState(false);

  return (
    <Widget
      title="Live Scanner" icon={Radar} query={scanQ} refreshMs={R.scan} testId="mc-scanner"
      headerExtra={
        <div className="flex items-center gap-2 flex-wrap">
          {rotation != null && (
            <span className="text-[9px] font-semibold text-teal-300">Rotation #{rotation}</span>
          )}
          {countToday != null && (
            <span className="text-[9px] text-muted-foreground">{countToday} today</span>
          )}
          {cadence != null && (
            <span className="text-[9px] text-muted-foreground">{cadence} min cadence</span>
          )}
          {scanning
            ? <Badge className="animate-pulse text-[9px] px-1.5 py-0">RUNNING · {progress?.stage}</Badge>
            : <Badge variant="secondary" className="text-[9px] px-1.5 py-0">IDLE</Badge>}
        </div>
      }
    >
      {/* Scan info chips */}
      <ScanInfoChips scanData={d} />

      {/* Primary counters */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] mb-2">
        <div>
          <p className="text-muted-foreground text-[10px]">Universe</p>
          <p className="font-semibold">{total || "—"} <span className="text-muted-foreground text-[9px]">symbols</span></p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Scanned</p>
          <p className="font-semibold">{scanning ? done : (total || "—")}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Remaining</p>
          <p className="font-semibold">{scanning && total ? total - done : 0}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Scan Age</p>
          <p className={`font-semibold ${ageMin != null && ageMin > 30 ? "text-amber-400" : ""}`}>
            {ageMin != null ? `${Math.round(ageMin)}m` : "—"}
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-muted mb-1.5">
        <div
          className={`h-1.5 rounded-full transition-all ${scanning ? "bg-primary animate-pulse" : "bg-emerald-500"}`}
          style={{ width: `${scanning ? pct : 100}%` }}
        />
      </div>

      {/* Current symbol / last scan info */}
      <div className="flex items-center gap-2 text-[10px] text-muted-foreground flex-wrap">
        {scanning ? (
          <>
            <span>{done}/{total} · {pct.toFixed(0)}%</span>
            {currentSymbol && (
              <span className="font-mono text-foreground font-semibold animate-pulse">
                ▶ {currentSymbol}
              </span>
            )}
          </>
        ) : (
          <>
            <Clock className="w-3 h-3 shrink-0" />
            <span>Last scan {d?.snapshot_ts ? timeAgo(d.snapshot_ts) : "—"}</span>
            {durationS != null && <span>({durationS.toFixed(0)}s)</span>}
          </>
        )}
      </div>

      {/* Scan ID — shown when idle (during a scan it's in the info chips) */}
      {!scanning && scanId && (
        <p
          className="text-[9px] font-mono text-muted-foreground/60 mt-1 truncate"
          title={`Current scan: ${scanId}`}
        >
          Current scan: {scanId}
        </p>
      )}

      {/* ── Today's scans history ─────────────────────────────────────────── */}
      {/* Collapsible list: every completed scan today with time, duration,   */}
      {/* symbol count and gap-from-previous so gaps/delays are visible.      */}
      <div className="mt-3 border-t border-border/40 pt-2" data-testid="mc-scan-history">
        <button
          className="w-full text-left flex items-center justify-between text-[10px] text-muted-foreground hover:text-foreground transition-colors py-0.5"
          onClick={() => setShowHistory((p) => !p)}
          aria-expanded={showHistory}
          data-testid="mc-scan-history-toggle"
        >
          <span className="flex items-center gap-1.5">
            <Clock className="w-3 h-3 shrink-0" />
            <span>Today's scans</span>
            {historyQ.data?.count != null && (
              <span className="font-semibold text-foreground ml-0.5">{historyQ.data.count}</span>
            )}
            {historyQ.isLoading && <span className="text-muted-foreground/50">…</span>}
          </span>
          <span className="text-[9px]">{showHistory ? "▲" : "▼"}</span>
        </button>

        {showHistory && (() => {
          const history = historyQ.data?.history ?? [];
          if (historyQ.isLoading) {
            return <p className="text-[10px] text-muted-foreground mt-1.5 animate-pulse">Loading…</p>;
          }
          if (history.length === 0) {
            return <p className="text-[10px] text-muted-foreground mt-1.5">No completed scans today.</p>;
          }
          return (
            <div className="mt-1.5" data-testid="mc-scan-history-list">
              {/* Column headers */}
              <div className="grid grid-cols-4 text-[9px] text-muted-foreground/60 px-1 pb-1 border-b border-border/30 font-medium">
                <span>Time (IST)</span>
                <span>Duration</span>
                <span>Symbols</span>
                <span>Gap</span>
              </div>
              {history.map((entry, i) => {
                const timeIST = entry.completed_at
                  ? new Date(entry.completed_at).toLocaleTimeString("en-IN", {
                      timeZone: "Asia/Kolkata", hour12: false,
                      hour: "2-digit", minute: "2-digit",
                    })
                  : "—";
                const dur = entry.duration_s != null ? `${entry.duration_s}s` : "—";
                const syms = entry.symbols_scanned != null ? String(entry.symbols_scanned) : "—";
                // Gap in minutes, highlight if > 10 min (2× expected 4-min cadence + buffer)
                const gapMin = entry.gap_from_prev_s != null
                  ? Math.round(entry.gap_from_prev_s / 60)
                  : null;
                const gapLabel = gapMin != null ? `${gapMin}m` : (i === history.length - 1 ? "first" : "—");
                const gapCls = gapMin != null && gapMin > 10 ? "text-amber-400 font-semibold" : "text-muted-foreground";
                return (
                  <div
                    key={i}
                    className="grid grid-cols-4 text-[10px] px-1 py-0.5 rounded hover:bg-muted/20 font-mono"
                    data-testid={`mc-scan-history-row-${i}`}
                  >
                    <span className="text-foreground">{timeIST}</span>
                    <span className="text-muted-foreground">{dur}</span>
                    <span className="text-muted-foreground">{syms}</span>
                    <span className={gapCls}>{gapLabel}</span>
                  </div>
                );
              })}
            </div>
          );
        })()}
      </div>
    </Widget>
  );
}

// ── Panel 3 — Live Paper Trading ─────────────────────────────────────────────

function PaperTradingPanel({ portfolio }: { portfolio: PortfolioSnapshot | undefined }) {
  // Single canonical ledger query shared with Throughput/LivePerformance
  // (same key/path as useLedgerToday — React Query dedupes to one fetch).
  const ledgerQ = useLedgerToday();

  const ledger = (ledgerQ.data?.ledger ?? []) as LedgerItem[];
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const t of ledger) {
      const st = (t.status || "UNKNOWN").toUpperCase();
      c[st] = (c[st] || 0) + 1;
    }
    return c;
  }, [ledger]);

  const open = counts["OPEN"] ?? 0;
  const closed = counts["CLOSED"] ?? 0;
  const pending = (counts["PENDING"] ?? 0) + (counts["EXIT_PENDING"] ?? 0);
  const rejected = counts["REJECTED"] ?? 0;
  const cancelled = counts["CANCELLED"] ?? 0;
  const filled = ledger.filter((t) => t.fill_ts != null).length;

  const equity = portfolio?.equity ?? 0;
  const invested = portfolio?.invested_value ?? 0;
  const utilisation = equity > 0 ? (invested / equity) * 100 : 0;
  const recent = ledger.slice(0, 6);

  return (
    <Widget
      title="Live Paper Trading" icon={Rocket} query={ledgerQ} refreshMs={R.ledger} testId="mc-paper-trading"
      headerExtra={pending > 0 && <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-amber-500/40 text-amber-300">{pending} pending</Badge>}
    >
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Filled</p><p className="font-semibold text-emerald-400">{filled}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Pending</p><p className={`font-semibold ${pending > 0 ? "text-amber-400" : ""}`}>{pending}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Rejected</p><p className={`font-semibold ${rejected > 0 ? "text-red-400" : ""}`}>{rejected}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Cancelled</p><p className="font-semibold">{cancelled}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Open / Closed</p><p className="font-semibold">{open} / {closed}</p></div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Portfolio Value</p><p className="font-semibold">{fmtINR(portfolio?.equity)}</p></div>
        <div>
          <p className="text-muted-foreground text-[10px]">Today P&L</p>
          <PnlText
            value={portfolio != null ? (portfolio.realised_pnl_today ?? 0) + (portfolio.unrealised_pnl ?? 0) : null}
            className="font-semibold"
          />
        </div>
        <div><p className="text-muted-foreground text-[10px]">Cash</p><p className="font-semibold">{fmtINR(portfolio?.cash)}</p></div>
        <div>
          <p className="text-muted-foreground text-[10px]">Utilisation</p>
          <p className="font-semibold">{portfolio != null ? `${utilisation.toFixed(1)}%` : "—"}</p>
        </div>
      </div>
      {/* Recent fills */}
      <p className="text-[10px] text-muted-foreground mb-1">Recent trades</p>
      {recent.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No paper trades recorded yet.</p>
      ) : (
        <div className="space-y-0.5 max-h-[130px] overflow-y-auto">
          {recent.map((t) => (
            <div key={t.trade_id} className="flex items-center gap-2 text-[10px] border-b border-border/40 py-0.5 last:border-0">
              <span className={`w-8 shrink-0 font-semibold ${t.side === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{t.side}</span>
              <span className="w-20 shrink-0 font-mono truncate">{t.symbol}</span>
              <span className="text-muted-foreground">{t.quantity} @ {fmtINR(t.fill_price, 2)}</span>
              <span className="ml-auto flex items-center gap-1.5">
                {t.realized_pnl != null && <PnlText value={t.realized_pnl} />}
                <span className="text-muted-foreground">{t.status}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </Widget>
  );
}

// ── Panel 5 — Live Portfolio (right sidebar) ─────────────────────────────────

function PortfolioSidebar({ q }: { q: ReturnType<typeof useWidgetQuery<PortfolioSnapshot>> }) {
  const p = q.data;
  const equity = p?.equity ?? 0;
  const initial = p?.initial_capital ?? 0;
  const netReturnPct = initial > 0 ? ((equity - initial) / initial) * 100 : null;
  const exposurePct = equity > 0 ? ((p?.invested_value ?? 0) / equity) * 100 : 0;
  const positions = p?.open_positions ?? [];
  const largest = positions.length
    ? [...positions].sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))[0]
    : null;
  const sectors = (p?.sector_exposures ?? []).slice(0, 5);
  const realisedToday = p?.realised_pnl_today ?? 0;

  return (
    <Widget title="Live Portfolio" icon={Wallet} query={q} refreshMs={R.portfolio} testId="mc-portfolio" skeletonClass="h-72">
      <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
        <div><p className="text-muted-foreground text-[10px]">Value</p><p className="font-semibold text-sm">{fmtINR(p?.equity)}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Cash</p><p className="font-semibold text-sm">{fmtINR(p?.cash)}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Invested</p><p className="font-semibold">{fmtINR(p?.invested_value)}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Exposure</p><p className="font-semibold">{p != null ? `${exposurePct.toFixed(1)}%` : "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Realized (today)</p><PnlText value={realisedToday} className="font-semibold" /></div>
        <div><p className="text-muted-foreground text-[10px]">Unrealized</p><PnlText value={p?.unrealised_pnl} className="font-semibold" /></div>
        <div className="col-span-2">
          <p className="text-muted-foreground text-[10px]">Net Return</p>
          <p className={`font-semibold ${netReturnPct == null ? "" : netReturnPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {netReturnPct == null ? "—" : `${netReturnPct >= 0 ? "+" : ""}${netReturnPct.toFixed(2)}%`}
          </p>
        </div>
      </div>

      {/* Sector allocation */}
      <p className="text-[10px] text-muted-foreground mb-1 flex items-center gap-1"><PieChart className="w-3 h-3" /> Sector allocation</p>
      {sectors.length === 0 ? (
        <p className="text-[11px] text-muted-foreground mb-3">No open exposure.</p>
      ) : (
        <div className="space-y-1 mb-3">
          {sectors.map((s) => (
            <div key={s.sector} className="text-[10px]">
              <div className="flex justify-between">
                <span className="truncate">{s.sector}</span>
                <span className="text-muted-foreground">{s.exposure_pct.toFixed(1)}%</span>
              </div>
              <div className="h-1 rounded-full bg-muted mt-0.5">
                <div className="h-1 rounded-full bg-teal-500" style={{ width: `${Math.min(100, s.exposure_pct)}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Largest position */}
      <p className="text-[10px] text-muted-foreground mb-1">Largest position</p>
      {largest ? (
        <div className="rounded-lg bg-muted/20 border border-border/60 p-2 text-[11px]">
          <div className="flex justify-between">
            <span className="font-semibold font-mono">{largest.symbol}</span>
            <PnlText value={largest.unrealised_pnl} />
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground mt-0.5">
            <span>{largest.quantity} @ {fmtINR(largest.avg_entry_price, 2)}</span>
            <span>{fmtINR(largest.market_value)}</span>
          </div>
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">No open positions.</p>
      )}
    </Widget>
  );
}

// ── Panel 4 — Live Event Stream (bottom strip) ───────────────────────────────

const EVENT_ROW_H = 22; // px — fixed row height enables windowed rendering

function EventStreamPanel({ streamEvents }: { streamEvents: PipelineStreamEvent[] }) {
  const feedQ = useWidgetQuery<{ events?: PipelineEvent[] }>({
    queryKey: ["mc", "event-feed"], path: "/pipeline/events?limit=80&newest_first=true", refetchInterval: R.events,
  });
  // Merge SSE-streamed events (rendered immediately) ahead of the REST feed,
  // deduped by event id, newest first.
  const allEvents = useMemo(() => {
    const rest = feedQ.data?.events ?? [];
    const seen = new Set(rest.map((e) => e.id));
    const fresh = streamEvents.filter((e) => !seen.has(e.id));
    return [...fresh, ...rest].sort((a, b) => b.id - a.id).slice(0, 200);
  }, [feedQ.data, streamEvents]);

  // Windowed (virtualized) rendering: only the visible slice + overscan is in
  // the DOM, so the feed stays cheap even at the 200-event cap during scans.
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const viewportH = 180;
  const start = Math.max(0, Math.floor(scrollTop / EVENT_ROW_H) - 5);
  const end = Math.min(allEvents.length, Math.ceil((scrollTop + viewportH) / EVENT_ROW_H) + 5);
  const events = allEvents.slice(start, end);

  return (
    <Widget title="Live Event Stream" icon={Activity} query={feedQ} refreshMs={R.events} testId="mc-event-stream" skeletonClass="h-24"
      headerExtra={<span className="text-[9px] text-muted-foreground">SSE + polling · virtualized · pipeline event store</span>}
    >
      {allEvents.length === 0 ? (
        <p className="text-xs text-muted-foreground">No events yet — the feed populates as the pipeline runs.</p>
      ) : (
        <div
          ref={scrollRef}
          onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
          className="overflow-y-auto font-mono text-[10px]"
          style={{ maxHeight: viewportH }}
          data-testid="mc-event-viewport"
        >
          <div style={{ height: allEvents.length * EVENT_ROW_H, position: "relative" }}>
            <div style={{ position: "absolute", top: start * EVENT_ROW_H, left: 0, right: 0 }}>
          {events.map((e) => {
            const tone = eventTone(e.event_type);
            const Icon = tone === "bad" ? XCircle : tone === "ok" ? CheckCircle2 : tone === "warn" ? AlertTriangle : ChevronRight;
            return (
              <div key={e.id} style={{ height: EVENT_ROW_H }} className="flex items-center gap-2 border-b border-border/30 last:border-0 group">
                <Icon className={`h-3 w-3 shrink-0 ${toneClass[tone]}`} />
                <span className="text-muted-foreground w-14 shrink-0">{timeAgo(e.ts)}</span>
                <span className="w-28 shrink-0 truncate text-muted-foreground/70">{e.stage}</span>
                <span className={`w-44 shrink-0 truncate ${toneClass[tone]}`}>{e.event_type}</span>
                <span className="w-24 shrink-0 font-semibold truncate">{e.symbol ?? ""}</span>
                <span className="text-muted-foreground truncate flex-1 min-w-0">
                  {String(e.payload?.reason ?? e.payload?.action ?? e.payload?.strategy_name ?? e.payload?.trade_id ?? "")}
                </span>
                <Link
                  href={eventInvestigateHref(e)}
                  title="Investigate in Investigation Center"
                  className="shrink-0 text-muted-foreground/40 hover:text-teal-400 opacity-0 group-hover:opacity-100 transition-opacity"
                  data-testid={`mc-event-investigate-${e.id}`}
                >
                  <Search className="h-2.5 w-2.5" />
                </Link>
              </div>
            );
          })}
            </div>
          </div>
        </div>
      )}
    </Widget>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

// Stable section ids + labels for the customization layout (Part 11).
// Order here is the default layout; SectionShell renders each in this order
// unless the operator has pinned/reordered/hidden them.
const MC_SECTIONS: SectionDef[] = [
  { id: "market-session", label: "Market Session" },
  { id: "mission-map",    label: "Mission Map" },
  { id: "pipeline-row",   label: "Pipeline · Scanner · Portfolio" },
  { id: "throughput-row", label: "Throughput · Performance · Breadth" },
  { id: "stockwatch-row", label: "Stock Watch · Explainability" },
  { id: "intel-row",      label: "AI Health · Learning · Alerts" },
  { id: "ops-row",        label: "Replay · Backtest · Broker · Agents · Health" },
  { id: "timeline",       label: "Mission Timeline" },
  { id: "event-feed",     label: "Live Event Stream" },
];

export default function MissionControl() {
  const stream = useLiveStream(); // single SSE connection shared with the status bar
  const { pipelineEventId, scanEvent } = stream;
  const queryClient = useQueryClient();

  // SSE tail: new pipeline events invalidate every affected canonical query so
  // the page reacts within a second instead of waiting for the next poll.
  useEffect(() => {
    if (!pipelineEventId) return;
    void queryClient.invalidateQueries({ queryKey: ["mc", "event-feed"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "pipeline-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "phase20-ledger-today"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "portfolio"] });
  }, [pipelineEventId, queryClient]);

  // Scan lifecycle events (scan.started / scan.completed) refresh the scanner,
  // replay counts and portfolio immediately.
  useEffect(() => {
    if (!scanEvent) return;
    void queryClient.invalidateQueries({ queryKey: ["mc", "scan-status"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "replay-latest"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "pipeline-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "portfolio"] });
  }, [scanEvent, queryClient]);

  // Shared queries used by multiple regions (fetched ONCE each).
  const portfolioQ = useWidgetQuery<PortfolioSnapshot>({
    queryKey: ["mc", "portfolio"], path: "/portfolio/snapshot", refetchInterval: R.portfolio, timeoutMs: 30_000,
  });
  const scanQ = useWidgetQuery<ScanStatus>({
    queryKey: ["mc", "scan-status"], path: "/live-data/scan/status", refetchInterval: R.scan,
  });
  const scanning = !!scanQ.data?.progress?.stage;
  // Unified replay snapshot — fetched ONCE and shared by the pipeline panel,
  // Mission Map and Replay widget (no separate fetch of stage counts).
  const replayQ = useWidgetQuery<ReplayResp>({
    queryKey: ["mc", "replay-latest"], path: "/replay/sessions/latest",
    refetchInterval: R.replay, timeoutMs: 45_000,
  });

  // ── Responsive: compact mobile quick-dashboard by default on phones ───────
  const isMobile = useIsMobile();
  const [showFullOnMobile, setShowFullOnMobile] = useState(false);
  const compact = isMobile && !showFullOnMobile;

  // Shared /phase20/ledger query — fetched ONCE (desktop/full view only) and
  // passed to Throughput + LivePerformance so the ledger is never fetched twice.
  const ledgerToday = useLedgerToday();

  // Dashboard customization (Phase 25.1 Part 11): ordered, pin/hide-able sections.
  const layout = useLayoutManager(MC_SECTIONS);

  if (compact) {
    return (
      <div className="p-3 space-y-3" data-testid="page-mission-control-mobile">
        <div className="flex items-center gap-2">
          <Radio className="h-4 w-4 text-primary" />
          <h1 className="text-base font-semibold">Mission Control</h1>
          <Badge variant="outline" className="text-[9px]">PAPER</Badge>
          <button
            onClick={() => setShowFullOnMobile(true)}
            className="ml-auto inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[10px] text-muted-foreground"
            data-testid="mc-mobile-full-toggle"
          >
            <LayoutGrid className="w-3 h-3" /> Full dashboard
          </button>
        </div>
        <StatusBar portfolio={portfolioQ.data} portfolioErr={portfolioQ.isError} stream={stream} />
        <Suspense fallback={<WidgetFallback />}>
          <MarketSessionWidget market={stream.market ?? undefined} />
        </Suspense>
        <PortfolioSidebar q={portfolioQ} />
        <AlertCenterWidget />
      </div>
    );
  }

  // ── Section bodies (data-driven map so ordering is applied before render) ──
  const SECTION_BODY: Record<string, () => ReactElement> = {
    "market-session": () => (
      <Suspense fallback={<WidgetFallback />}>
        <MarketSessionWidget market={stream.market ?? undefined} />
      </Suspense>
    ),
    "mission-map": () => (
      <MissionMapWidget replayQ={replayQ} scanning={scanning} />
    ),
    "pipeline-row": () => (
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 items-start">
        <PipelinePanel scanning={scanning} replayQ={replayQ} scanQ={scanQ} />
        <div className="lg:col-span-2 space-y-3 min-w-0">
          <ScannerPanel scanQ={scanQ} />
          <PaperTradingPanel portfolio={portfolioQ.data} />
        </div>
        <PortfolioSidebar q={portfolioQ} />
      </div>
    ),
    "throughput-row": () => (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 items-start">
        <Suspense fallback={<WidgetFallback />}>
          <ThroughputWidget replay={replayQ.data} ledger={ledgerToday} />
        </Suspense>
        <Suspense fallback={<WidgetFallback />}>
          <LivePerformanceWidget portfolio={portfolioQ.data} ledger={ledgerToday} />
        </Suspense>
        <Suspense fallback={<WidgetFallback />}>
          <MarketBreadthWidget />
        </Suspense>
      </div>
    ),
    "stockwatch-row": () => (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
        <Suspense fallback={<WidgetFallback />}>
          <StockWatchWidget portfolio={portfolioQ.data} scan={scanQ.data} />
        </Suspense>
        <Suspense fallback={<WidgetFallback />}>
          <ExplainabilityWidget />
        </Suspense>
      </div>
    ),
    "intel-row": () => (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 items-start">
        <Suspense fallback={<WidgetFallback />}>
          <AiHealthWidget />
        </Suspense>
        <Suspense fallback={<WidgetFallback />}>
          <AiLearningWidget />
        </Suspense>
        <AlertCenterWidget />
      </div>
    ),
    "ops-row": () => (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 items-start">
        <Suspense fallback={<WidgetFallback />}>
          <ReplayWidget replayQ={replayQ} />
        </Suspense>
        <Suspense fallback={<WidgetFallback />}>
          <BacktestWidget />
        </Suspense>
        <Suspense fallback={<WidgetFallback />}>
          <BrokerWidget />
        </Suspense>
        <Suspense fallback={<WidgetFallback />}>
          <AgentMetricsWidget />
        </Suspense>
        <div className="md:col-span-2 xl:col-span-2">
          <Suspense fallback={<WidgetFallback />}>
            {/* SystemHealth2Widget is a superset of the old SystemHealthWidget. */}
            <SystemHealth2Widget portfolio={portfolioQ.data} replay={replayQ.data} />
          </Suspense>
        </div>
      </div>
    ),
    "timeline": () => (
      <Suspense fallback={<WidgetFallback h="h-28" />}>
        <MissionTimelineWidget />
      </Suspense>
    ),
    "event-feed": () => (
      <EventStreamPanel streamEvents={stream.pipelineEvents} />
    ),
  };

  return (
    <div className="p-4 space-y-3 max-w-[1700px] mx-auto" data-testid="page-mission-control">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Radio className="h-5 w-5 text-primary" />
        <h1 className="text-lg font-semibold">Mission Control</h1>
        <Badge variant="outline" className="text-[10px]">{LABEL}</Badge>
        <span className="text-[10px] text-muted-foreground ml-auto hidden md:inline">
          All data from the canonical pipeline event store, replay snapshot & phase20 ledger — no page-local calculations.
        </span>
        {isMobile && showFullOnMobile && (
          <button
            onClick={() => setShowFullOnMobile(false)}
            className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[10px] text-muted-foreground"
            data-testid="mc-mobile-compact-toggle"
          >
            <Smartphone className="w-3 h-3" /> Compact view
          </button>
        )}
      </div>

      {/* Operator command bar + layout customization toggle */}
      <div className="flex flex-wrap items-center gap-2">
        <CommandBar />
        <span className="ml-auto">
          <CustomizeControls mgr={layout} />
        </span>
      </div>

      {/* Canonical data freshness indicator (scan snapshot + staleness) */}
      <DataFreshnessBar variant="scan" />

      {/* Top status bar (always rendered — not part of customizable sections) */}
      <StatusBar portfolio={portfolioQ.data} portfolioErr={portfolioQ.isError} stream={stream} />

      {layout.customizing && (
        <p className="text-[10px] text-muted-foreground rounded-lg border border-teal-500/30 bg-teal-500/5 px-3 py-1.5" data-testid="mc-customize-hint">
          Customize mode — pin sections to the top, hide the ones you don't need, or reorder with the ↑/↓ controls. Your layout is saved to this browser.
        </p>
      )}

      {/* Sections render in the operator's saved order (pinned first). */}
      {layout.order.map((id) => {
        const label = MC_SECTIONS.find((s) => s.id === id)?.label ?? id;
        return (
          <SectionShell key={id} id={id} label={label} mgr={layout}>
            {SECTION_BODY[id]?.()}
          </SectionShell>
        );
      })}
    </div>
  );
}
