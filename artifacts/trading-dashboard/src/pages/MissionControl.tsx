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
import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { Link } from "wouter";
import { useLiveStream, type PipelineStreamEvent } from "@/hooks/useLiveStream";
import { useIsMobile } from "@/hooks/use-mobile";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { Badge } from "@/components/ui/badge";
import {
  Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock, Cpu,
  HeartPulse, LayoutGrid, PieChart, Radar, Radio, Rocket, Search, Smartphone,
  RefreshCw, Timer, Wallet, Wifi, WifiOff, XCircle,
} from "lucide-react";
import { Widget, useWidgetQuery, fmtINR, timeAgo, PnlText } from "@/components/mission/Widget";
import { apiJson } from "@/lib/api";
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
const PRODUCT_VERSION = (import.meta.env.VITE_PRODUCT_VERSION as string | undefined) ?? "v1.0.0";
const UI_GIT_COMMIT = import.meta.env.VITE_UI_GIT_COMMIT as string | undefined;
const FRONTEND_BUILD_ID = import.meta.env.VITE_UI_BUILD_ID as string | undefined;

export type BuildIdentityState =
  | "loading"
  | "missing-ui"
  | "missing-api"
  | "match"
  | "mismatch";

export function buildIdsMatch(uiBuildId: string | null | undefined, apiBuildId: string | null | undefined): boolean {
  return Boolean(uiBuildId && apiBuildId && apiBuildId === uiBuildId);
}

export function getBuildIdentityState(
  uiBuildId: string | null | undefined,
  apiBuildId: string | null | undefined,
): BuildIdentityState {
  if (!uiBuildId?.trim() || uiBuildId === "production-unidentified") return "missing-ui";
  if (apiBuildId === undefined) return "loading";
  if (!apiBuildId?.trim() || apiBuildId === "production-unidentified") return "missing-api";
  return buildIdsMatch(uiBuildId, apiBuildId) ? "match" : "mismatch";
}

function formatIstRefreshTime(timestamp: number): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(timestamp));
}

export function ScanBuildIdentity({
  apiBuildId,
  lastRefreshedAt,
  uiBuildId,
  uiGitCommit,
  productVersion,
}: {
  apiBuildId: string | null | undefined;
  lastRefreshedAt: number;
  uiBuildId?: string | null;
  uiGitCommit?: string | null;
  productVersion?: string;
}) {
  const uiLabel = uiBuildId === undefined ? FRONTEND_BUILD_ID : uiBuildId;
  const commitLabel = uiGitCommit === undefined ? UI_GIT_COMMIT : uiGitCommit;
  const productLabel = productVersion ?? PRODUCT_VERSION;
  const state = getBuildIdentityState(uiLabel, apiBuildId);
  const statusLabel: Record<BuildIdentityState, string> = {
    loading: "CHECKING",
    "missing-ui": "UI IDENTITY UNAVAILABLE",
    "missing-api": "API IDENTITY UNAVAILABLE",
    match: "MATCH",
    mismatch: "MISMATCH",
  };
  const statusClass: Record<BuildIdentityState, string> = {
    loading: "text-muted-foreground",
    "missing-ui": "text-amber-400",
    "missing-api": "text-amber-400",
    match: "text-emerald-400",
    mismatch: "text-red-400",
  };
  const statusTitle: Record<BuildIdentityState, string> = {
    loading: "Waiting for the API deployment identity",
    "missing-ui": "The dashboard bundle has no source-derived UI identity; rebuild it from a captured commit",
    "missing-api": "The API did not provide a source-derived deployment identity",
    match: "UI and API deployment build IDs match exactly",
    mismatch: "UI and API deployment build IDs differ; coordinate a deployment or investigate the served asset",
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-[8px] font-mono text-muted-foreground" data-testid="mc-build-ids">
      <span data-testid="mc-product-version">Product Version {productLabel}</span>
      <span data-testid="mc-ui-build" title={commitLabel ? `Source commit: ${commitLabel}` : undefined}>
        UI Build {uiLabel ?? "unavailable"}
      </span>
      <span data-testid="mc-api-build">API Build {apiBuildId ?? "loading"}</span>
      <span
        className={statusClass[state]}
        data-testid="mc-build-match"
        title={statusTitle[state]}
        role={state === "mismatch" || state === "missing-ui" || state === "missing-api" ? "alert" : undefined}
      >
        {statusLabel[state]}
      </span>
      {lastRefreshedAt > 0 && (
        <span data-testid="mc-last-refreshed">· Last refreshed {formatIstRefreshTime(lastRefreshedAt)} IST</span>
      )}
    </span>
  );
}

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
interface CustomUniverseStatus {
  active_universe?: string;
  custom_universe_name?: string;
  price_filter?: { min?: number; max?: number };
  sectors?: string[];
  active_count?: number;
  excluded_count?: number;
  sector_counts?: Record<string, number>;
  last_refresh?: string | null;
  ohlcv_cache_hit_rate_pct?: number;
  kite_ltp?: { available_symbols?: number; status?: string };
  instrument_metadata?: {
    active_count?: number;
    complete_mapping_count?: number;
    oldest_cache_date?: string | null;
    newest_cache_date?: string | null;
    cache_age_days?: number | null;
    newest_cache_age_days?: number | null;
    oldest_mapping_at?: string | null;
    newest_mapping_at?: string | null;
    invalid_mapping_count?: number;
    stale_mapping_count?: number;
    refresh_required?: boolean;
    provenance?: string | null;
    approval_required?: boolean;
    confirmation_required?: string | null;
  };
}
interface CustomUniverseSymbol {
  symbol: string;
  company_name?: string | null;
  sector?: string | null;
  last_ltp?: number | null;
  last_ltp_source?: string | null;
  avg_volume_20d?: number | null;
  avg_turnover_20d?: number | null;
  is_active?: boolean;
  reason_included?: string | null;
  reason_excluded?: string | null;
  ohlcv_available?: boolean;
}
interface CustomUniverseSymbolsResponse { symbols?: CustomUniverseSymbol[] }
/** Task 857: latest job summary (market or system). */
interface LatestJobSummary {
  job_type?: string | null;        // "MARKET_SCAN" | "CACHE_REFRESH" | "SYSTEM_HEALTH" | …
  scan_type?: string | null;       // for market scans: "full" | "incremental" | …
  status?: string | null;          // "completed" | "running" | "failed" | …
  started_at?: string | null;
  completed_at?: string | null;
  started_at_ist?: string | null;  // pre-formatted IST string from backend
  completed_at_ist?: string | null;
  duration_s?: number | null;
  symbols_scanned?: number | null;
  source?: string | null;          // "scheduler" | "manual" | "api" | …
  market_state?: string | null;    // "open" | "pre_open" | "closed" | …
  entry_eligible?: boolean | null;
  execution_eligible?: boolean | null;
}

/** Task 857: upcoming scheduled job descriptor. */
interface NextJobInfo {
  job_type?: string | null;
  scheduled_at?: string | null;
  scheduled_at_ist?: string | null;
  source?: string | null;
}

interface ScanStatus {
  success?: boolean; status?: string; scan_id?: string; snapshot_ts?: string;
  age_minutes?: number | null;
  /** Legacy alias for completed_scans_today. Do not label as rotation. */
  scan_count_today?: number | null;
  completed_scans_today?: number | null;
  started_scans_today?: number | null;
  scheduler_ticks_today?: number | null;
  lock_busy_skips_today?: number | null;
  cadence_minutes?: number | null;    // expected minutes between scans
  api_build_id?: string;
  // ── Task 857 additive fields ──────────────────────────────────────────
  /** Market-scan jobs completed today (subset of all_system_jobs_today). */
  market_scans_today?: number | null;
  /** All system jobs (market + non-market) completed today. */
  all_system_jobs_today?: number | null;
  /** Summary of the latest market-scan job. */
  latest_market_job?: LatestJobSummary | null;
  /** Summary of the latest system job (could be non-market). */
  latest_system_job?: LatestJobSummary | null;
  /** Upcoming scheduled jobs. */
  next_jobs?: NextJobInfo[] | null;
  /** Current NSE market state as seen by the scanner. */
  market_state?: string | null;
  /** Whether new paper-entry executions are currently allowed. */
  entry_execution_allowed?: boolean | null;
  // ─────────────────────────────────────────────────────────────────────
  runtime?: {
    owner?: string | null; process_start_at?: string | null; status?: string | null;
    heartbeat_at?: string | null;
  } | null;
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
  // ── Task 857 enhanced history fields ─────────────────────────────────
  job_type?: string | null;           // "MARKET_SCAN" | "CACHE_REFRESH" | …
  scan_type?: string | null;          // "full" | "incremental" | …
  started_at_ist?: string | null;     // pre-formatted IST time string
  completed_at_ist?: string | null;   // pre-formatted IST time string
  source?: string | null;             // "scheduler" | "manual" | "api"
  market_state?: string | null;       // "open" | "pre_open" | "closed" | …
  entry_eligible?: boolean | null;
  execution_eligible?: boolean | null;
  // ─────────────────────────────────────────────────────────────────────
}
interface ScanHistoryResp {
  success?: boolean; history?: ScanHistoryEntry[]; count?: number;
  total_completed?: number; ist_date?: string;
}

export function normalizedJobValue(value?: string | null): string {
  return String(value ?? "").trim().toUpperCase();
}

export interface ScanPresentation {
  isScanning: boolean;
  isAfterHoursMonitoring: boolean;
  idleLabel: "IDLE" | "IDLE — MARKET CLOSED";
}

/**
 * A persisted progress payload is only evidence of an active full scan while
 * the scheduler itself says it is scanning. The progress key is intentionally
 * durable so it can briefly outlive a worker, and must not make after-hours
 * heartbeats look like a new market scan.
 */
export function getScanPresentation(scanData?: ScanStatus): ScanPresentation {
  const isScanning = normalizedJobValue(scanData?.runtime?.status) === "SCANNING";
  const marketState = normalizedJobValue(scanData?.market_state);
  const isAfterHours = ["POST_CLOSE", "CLOSED"].includes(marketState);
  const hasSchedulerHeartbeat = Boolean(
    scanData?.runtime?.heartbeat_at ?? scanData?.runtime?.owner,
  );

  return {
    isScanning,
    isAfterHoursMonitoring: !isScanning && isAfterHours && hasSchedulerHeartbeat,
    idleLabel: isAfterHours ? "IDLE — MARKET CLOSED" : "IDLE",
  };
}

export function jobStatusClass(status?: string | null): string {
  const normalized = normalizedJobValue(status);
  if (normalized === "SUCCESS" || normalized === "COMPLETED") return "text-emerald-400";
  if (normalized === "RUNNING" || normalized === "STARTED") return "text-blue-400";
  if (normalized === "FAILED" || normalized === "ERROR") return "text-red-400";
  return "text-muted-foreground";
}

export function istJobTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isNaN(date.getTime())) {
    return date.toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }
  // Preserve legacy pre-formatted values that cannot be parsed as ISO.
  const time = value.match(/(?:T|\s)(\d{2}:\d{2})/);
  return time?.[1] ?? value;
}

function scanSnapshotTime(status: ScanStatus | undefined): number | null {
  const raw = status?.progress?.started_at
    ?? status?.latest_scan?.snapshot_ts
    ?? status?.snapshot_ts
    ?? null;
  if (!raw) return null;
  const parsed = new Date(raw).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Preserve the newest verified status within this browser session. A response
 * that regresses the scan timestamp/count is never rendered over it; instead a
 * no-store refetch is requested and the scanner shows an explicit warning.
 */
export function isScanStatusOlder(candidate: ScanStatus, displayed: ScanStatus): boolean {
  const candidateTs = scanSnapshotTime(candidate);
  const displayedTs = scanSnapshotTime(displayed);
  const candidateCount = candidate.completed_scans_today ?? candidate.scan_count_today;
  const displayedCount = displayed.completed_scans_today ?? displayed.scan_count_today;
  if (candidateTs != null && displayedTs != null && candidateTs < displayedTs) return true;
  const equalOrMissingTimestamp = candidateTs == null || displayedTs == null || candidateTs === displayedTs;
  return Boolean(
    equalOrMissingTimestamp
    && candidateCount != null
    && displayedCount != null
    && candidateCount < displayedCount,
  );
}

export function useMonotonicScanStatus(scanQ: UseQueryResult<ScanStatus>) {
  const [displayed, setDisplayed] = useState<ScanStatus | undefined>(undefined);
  const [staleResponse, setStaleResponse] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(0);
  const lastRefetchKey = useRef<string | null>(null);

  useEffect(() => {
    const candidate = scanQ.data;
    if (!candidate) return;
    if (!displayed) {
      setDisplayed(candidate);
      setStaleResponse(false);
      setLastRefreshedAt(scanQ.dataUpdatedAt || Date.now());
      return;
    }

    if (isScanStatusOlder(candidate, displayed)) {
      setStaleResponse(true);
      const key = [
        candidate.latest_scan?.scan_id ?? candidate.scan_id ?? "unknown",
        scanSnapshotTime(candidate) ?? "unknown",
        candidate.completed_scans_today ?? candidate.scan_count_today ?? "unknown",
      ].join("|");
      if (lastRefetchKey.current !== key) {
        lastRefetchKey.current = key;
        void scanQ.refetch({ cancelRefetch: true });
      }
      return;
    }

    lastRefetchKey.current = null;
    setDisplayed(candidate);
    setStaleResponse(false);
    setLastRefreshedAt(scanQ.dataUpdatedAt || Date.now());
  }, [displayed, scanQ.data, scanQ.dataUpdatedAt, scanQ.refetch]);

  return { data: displayed ?? scanQ.data, staleResponse, lastRefreshedAt };
}
interface OhlcvCacheStatus {
  success?: boolean;
  cache_enabled?: boolean;
  ohlcv_source?: string;            // "local_yfinance_cache" | "yfinance_fallback"
  cache_hit_rate_pct?: number;      // 0-100
  total_symbols?: number;
  live_symbols?: number;
  uncached_symbols?: string[];      // symbols not in the local cache
  stale_symbols?: string[];
  missing_required_bars?: string[];
  latest_cached_date?: string | null;
  last_postmarket_refresh?: {
    refresh_date?: string | null;
    refresh_type?: string | null;
    status?: string | null;
    symbols_requested?: number | null;
    symbols_updated?: number | null;
    failed_symbols?: string[] | null;
    duration_seconds?: number | null;
    end_time?: string | null;
  } | null;
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
interface BootstrapCandidate {
  symbol: string; confidence: number; opportunity_score: number;
  rr_ratio: number; bootstrap_eligible: boolean; entry_price: number;
  action?: string; ineligibility_reason?: string | null;
}
interface BootstrapWatchCandidate {
  symbol: string; confidence: number; opportunity_score: number;
  rr_ratio: number; action: string; ineligibility_reason?: string | null;
}
interface BootstrapStatus {
  success?: boolean;
  bootstrap_paper_enabled?: boolean;
  auto_paper_entries?: boolean;
  circuit_breaker_tripped?: boolean;
  circuit_breaker_detail?: string;
  kite_verified?: boolean;
  bootstrap_cutoff_reached?: boolean;
  bootstrap_eligible_count?: number;
  watch_count?: number;
  snapshot_ts?: string | null;
  top_candidates?: BootstrapCandidate[];
  top_watch_candidate?: BootstrapWatchCandidate | null;
}
interface EodForceCloseResult {
  symbol: string | null; exit_rule: string; exit_price: number | null;
  realized_pnl: number | null; exit_price_source: string | null;
  fallback_used: boolean; ts: string;
}
interface EodBlockedEvent {
  symbol: string | null; trade_id: string | null; reason: string | null; ts: string;
}
interface EodStatus {
  success?: boolean;
  time_to_squareoff_sec?: number;
  squareoff_time_ist?: string;
  in_squareoff_window?: boolean;
  past_post_close?: boolean;
  show_countdown?: boolean;
  eod_ran_today?: boolean;
  force_close_results?: EodForceCloseResult[];
  blocked_events?: EodBlockedEvent[];
  now_ist?: string;
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

export function ScanInfoChips({ scanData, summaryData, cacheData }: {
  scanData: ScanStatus | undefined;
  summaryData?: PipelineSummary;
  cacheData?: OhlcvCacheStatus;
}) {
  const meta     = scanData?.latest_scan ?? {};
  const presentation = getScanPresentation(scanData);
  const progress = presentation.isScanning ? scanData?.progress : null;
  const scanId   = (progress?.scan_id ?? (meta as {scan_id?: string}).scan_id ?? scanData?.scan_id) ?? null;
  const universeSize =
    progress?.symbols_total ??
    (meta as { universe_size?: number; symbols_total?: number }).universe_size ??
    (meta as { universe_size?: number; symbols_total?: number }).symbols_total ?? null;
  const ageMin     = scanData?.age_minutes ?? null;
  const durationS  = (meta as { duration_s?: number | null }).duration_s ?? null;
  const startedAt  = progress?.started_at ?? null;
  const completedToday = scanData?.completed_scans_today ?? scanData?.scan_count_today ?? null;
  const startedToday = scanData?.started_scans_today ?? null;
  const schedulerTicksToday = scanData?.scheduler_ticks_today ?? null;
  const busySkipsToday = scanData?.lock_busy_skips_today ?? null;
  const cadence    = scanData?.cadence_minutes ?? null;
  const runtimeOwner = scanData?.runtime?.owner ?? null;

  // Cache provenance from /ohlcv-cache/status
  const hitRate    = cacheData?.cache_hit_rate_pct ?? null;
  const ohlcvSrc   = cacheData?.ohlcv_source ?? null;
  const sourceLabel =
    ohlcvSrc === "local_yfinance_cache" ? "Local cache"
    : ohlcvSrc === "yfinance_fallback"  ? "yfinance fallback"
    : null;

  // Task 857: prefer market_scans_today / all_system_jobs_today when present.
  const marketScansToday = scanData?.market_scans_today ?? null;
  const allSystemJobsToday = scanData?.all_system_jobs_today ?? null;

  type Chip = { label: string; value: string; cls?: string; mono?: boolean };
  const chips: Chip[] = [];

  if (marketScansToday != null) {
    chips.push({ label: "Market Scans Today", value: String(marketScansToday) });
  } else if (completedToday != null) {
    chips.push({ label: "Completed", value: `${completedToday} today` });
  }
  if (allSystemJobsToday != null && allSystemJobsToday !== (marketScansToday ?? completedToday)) {
    chips.push({ label: "All System Jobs Today", value: String(allSystemJobsToday) });
  }
  if (startedToday != null)    chips.push({ label: "Started", value: `${startedToday} today` });
  if (schedulerTicksToday != null) chips.push({ label: "Scheduler ticks", value: `${schedulerTicksToday} today` });
  if (busySkipsToday != null)  chips.push({
    label: "Lock-busy skips",
    value: `${busySkipsToday} today`,
    cls: busySkipsToday > 0 ? "text-amber-400" : undefined,
  });
  if (runtimeOwner)            chips.push({ label: "Runtime", value: runtimeOwner, mono: true });
  if (cadence != null)         chips.push({ label: "Cadence", value: `${cadence} min` });
  if (universeSize != null)    chips.push({ label: "Universe", value: `${universeSize} symbols` });
  if (scanId)                  chips.push({ label: "Scan ID", value: scanId.slice(0, 10) + (scanId.length > 10 ? "…" : ""), mono: true });
  if (startedAt)               chips.push({ label: "Current scan started", value: timeAgo(startedAt) });
  if (durationS != null)       chips.push({ label: "Duration", value: `${durationS.toFixed(0)}s` });
  if (ageMin != null)          chips.push({ label: "Age", value: `${Math.round(ageMin)}m`, cls: ageMin > 30 ? "text-amber-400" : "" });
  // Cache source chip — shown alongside duration so operators see both at a glance
  if (sourceLabel != null)     chips.push({
    label: "Source",
    value: sourceLabel,
    cls: ohlcvSrc === "local_yfinance_cache" ? "text-teal-300" : "text-amber-400",
  });
  if (hitRate != null)         chips.push({
    label: "Cache",
    value: `${hitRate.toFixed(0)}%`,
    cls: hitRate >= 80 ? "text-teal-300" : hitRate >= 50 ? "text-amber-400" : "text-red-400",
  });

  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1 mb-2">
      {chips.map((c) => (
        <span
          key={`${c.label}:${c.value}`}
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

export function PipelinePanel({ scanning, afterHoursMonitoring = false, replayQ, scanQ }: {
  scanning: boolean;
  afterHoursMonitoring?: boolean;
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
  const currentSym   = scanning
    ? (scanQ.data?.progress?.current_symbol ?? scanQ.data?.progress?.symbol ?? null)
    : null;

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
  const progressStage = scanning ? scanQ.data?.progress?.stage ?? null : null;
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
          {!scanning && afterHoursMonitoring && (
            <Badge variant="secondary" className="text-[9px] px-1.5 py-0" data-testid="mc-pipeline-after-hours-status">
              IDLE — MARKET CLOSED
            </Badge>
          )}
        </>
      }
    >
      {/* Scan metadata strip */}
      <ScanInfoChips scanData={scanQ.data} summaryData={summaryQ.data} />
      {afterHoursMonitoring && (
        <p className="mb-2 text-[10px] text-muted-foreground" data-testid="mc-pipeline-after-hours-note">
          After-hours monitoring only — execution disabled.
        </p>
      )}

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

function ScannerPanel({
  scanQ,
  staleDisplay = false,
}: {
  scanQ: ReturnType<typeof useWidgetQuery<ScanStatus>>;
  staleDisplay?: boolean;
}) {
  const d = scanQ.data;
  const meta = d?.latest_scan ?? d ?? {};
  const presentation = getScanPresentation(d);
  const scanning = presentation.isScanning;
  const progress = scanning ? d?.progress ?? null : null;
  const done  = progress?.symbols_done ?? 0;
  const total = progress?.symbols_total ??
    (meta as { symbols_total?: number; universe_size?: number }).universe_size ??
    (meta as { symbols_total?: number }).symbols_total ?? 0;
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  const currentSymbol = progress?.current_symbol ?? progress?.symbol ?? null;
  const ageMin = d?.age_minutes;
  const scanId = (meta as { scan_id?: string }).scan_id ?? d?.scan_id ?? null;
  const durationS = (meta as { duration_s?: number | null }).duration_s ?? null;

  // Explicit durable observability labels. Never show the legacy "rotation"
  // alias: completed scans, scheduler ticks, and history rows are different.
  const completedToday = d?.completed_scans_today ?? d?.scan_count_today ?? null;
  const startedToday = d?.started_scans_today ?? null;
  const schedulerTicksToday = d?.scheduler_ticks_today ?? null;
  const busySkipsToday = d?.lock_busy_skips_today ?? null;
  const cadence    = d?.cadence_minutes ?? null;

  // ── Task 857 additive fields (with legacy fallbacks) ─────────────────────
  // market_scans_today: market-scan completions only; falls back to completed_scans_today.
  const marketScansToday = d?.market_scans_today ?? completedToday;
  // all_system_jobs_today: total system jobs; shown only when distinct from market count.
  const allSystemJobsToday = d?.all_system_jobs_today ?? null;
  const latestMarketJob = d?.latest_market_job ?? null;
  const latestSystemJob = d?.latest_system_job ?? null;
  const nextJobs = d?.next_jobs ?? null;
  const marketState = d?.market_state ?? null;
  const entryExecutionAllowed = d?.entry_execution_allowed ?? null;

  // OHLCV cache status — 60 s cadence (slow route; Python spawns a DB query)
  const cacheQ = useWidgetQuery<OhlcvCacheStatus>({
    queryKey: ["mc", "ohlcv-cache-status"],
    path: "/ohlcv-cache/status",
    requestInit: { cache: "no-store" },
    cacheBust: true,
    refetchInterval: 60_000,
    timeoutMs: 35_000,
  });
  const cache = cacheQ.data;
  const uncachedCount = cache?.uncached_symbols?.length ?? 0;
  const yfinanceFallbackAlert = uncachedCount > 5;

  // Today's scan history — 30 s cache, same TTL as the backend route.
  const historyQ = useWidgetQuery<ScanHistoryResp>({
    queryKey: ["mc", "scan-history"], path: "/live-data/scan/history",
    requestInit: { cache: "no-store" }, cacheBust: true, refetchInterval: 30_000,
  });
  const [showHistory, setShowHistory] = useState(false);

  // Derive max gap (minutes) across today's scan history entries.
  // If the largest gap exceeds 2× the configured cadence a missed scan likely occurred.
  const maxGapMin = useMemo(() => {
    const entries = historyQ.data?.history ?? [];
    const gaps = entries
      .map((e) => e.gap_from_prev_s)
      .filter((g): g is number => g != null);
    if (gaps.length === 0) return null;
    return Math.max(...gaps) / 60;
  }, [historyQ.data?.history]);
  const gapAlert = cadence != null && maxGapMin != null && maxGapMin > cadence * 2;

  // Format the last post-market refresh timestamp for display.
  const lastRefresh = cache?.last_postmarket_refresh ?? null;
  const lastRefreshLabel = useMemo(() => {
    if (!lastRefresh?.end_time) return null;
    const dt = new Date(lastRefresh.end_time);
    if (isNaN(dt.getTime())) return null;
    return dt.toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit", month: "short",
      hour: "2-digit", minute: "2-digit",
      hour12: false,
    }) + " IST";
  }, [lastRefresh]);

  return (
    <Widget
      title="Live Scanner" icon={Radar} query={scanQ} refreshMs={R.scan} testId="mc-scanner"
      headerExtra={
        <div className="flex items-center gap-2 flex-wrap">
          {/* Task 857: separate market-scan vs all-system-job counts */}
          {marketScansToday != null && (
            <span
              className="text-[9px] font-semibold text-teal-300"
              data-testid="mc-market-scans-today-chip"
            >
              {marketScansToday} market scans today
            </span>
          )}
          {allSystemJobsToday != null && allSystemJobsToday !== marketScansToday && (
            <span
              className="text-[9px] text-muted-foreground"
              data-testid="mc-all-system-jobs-today-chip"
            >
              {allSystemJobsToday} system jobs
            </span>
          )}
          {/* Legacy chip retained when market_scans_today is absent (fallback path) */}
          {d?.market_scans_today == null && completedToday != null && (
            <span
              className="text-[9px] font-semibold text-teal-300"
              data-testid="mc-completed-scans-chip"
            >
              {completedToday} completed today
            </span>
          )}
          {startedToday != null && (
            <span className="text-[9px] text-muted-foreground" data-testid="mc-started-scans-chip">
              {startedToday} started
            </span>
          )}
          {schedulerTicksToday != null && (
            <span className="text-[9px] text-muted-foreground" data-testid="mc-scheduler-ticks-chip">
              {schedulerTicksToday} scheduler ticks
            </span>
          )}
          {busySkipsToday != null && (
            <span
              className={`text-[9px] ${busySkipsToday > 0 ? "text-amber-400" : "text-muted-foreground"}`}
              data-testid="mc-lock-busy-skips-chip"
            >
              {busySkipsToday} lock-busy skips
            </span>
          )}
          {gapAlert && (
            <span
              className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 bg-amber-500/20 border border-amber-500/50 text-[9px] font-semibold text-amber-400"
              data-testid="mc-scan-gap-badge"
              title={`Gap between scans (${Math.round(maxGapMin!)}m) exceeds 2× cadence (${cadence}m). A missed scan may have occurred.`}
            >
              ⚠ Gap
            </span>
          )}
          {yfinanceFallbackAlert && (
            <span
              className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 bg-amber-500/20 border border-amber-500/50 text-[9px] font-semibold text-amber-400"
              data-testid="mc-yfinance-fallback-badge"
              title={`${uncachedCount} symbols not in local cache — yfinance is being called for these symbols, which slows scans significantly.`}
            >
              ⚠ {uncachedCount} yfinance
            </span>
          )}
          {cadence != null && (
            <span className="text-[9px] text-muted-foreground">{cadence} min cadence</span>
          )}
          {scanning
            ? <Badge className="animate-pulse text-[9px] px-1.5 py-0">RUNNING · {progress?.stage}</Badge>
            : <Badge
                variant="secondary"
                className="text-[9px] px-1.5 py-0"
                data-testid={presentation.isAfterHoursMonitoring ? "mc-scanner-after-hours-status" : undefined}
              >
                {presentation.idleLabel}
              </Badge>}
        </div>
      }
    >
      {/* Scan info chips — includes cache source + hit rate when available */}
      <ScanInfoChips scanData={d} cacheData={cache} />
      {presentation.isAfterHoursMonitoring && (
        <p className="mb-2 text-[10px] text-muted-foreground" data-testid="mc-scanner-after-hours-note">
          After-hours monitoring only — execution disabled.
        </p>
      )}

      {/* ── Task 857: Market state + entry-execution allowance ──────────────── */}
      {(marketState != null || entryExecutionAllowed != null) && (
        <div
          className="mb-2 flex flex-wrap items-center gap-2 text-[10px]"
          data-testid="mc-market-entry-status"
        >
          {marketState != null && (
            <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 bg-muted/30 border border-border/50">
              <span className="text-muted-foreground">Market state</span>
              <span
                className={`font-semibold ${
                  normalizedJobValue(marketState) === "OPEN" ? "text-emerald-400"
                  : normalizedJobValue(marketState) === "PRE_OPEN" ? "text-amber-400"
                  : "text-muted-foreground"
                }`}
                data-testid="mc-market-state-label"
              >
                {marketState}
              </span>
            </span>
          )}
          {entryExecutionAllowed != null && (
            <span
              className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 border text-[10px] font-semibold ${
                entryExecutionAllowed
                  ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400"
                  : "bg-slate-500/10 border-slate-500/40 text-muted-foreground"
              }`}
              data-testid="mc-entry-execution-allowed"
              title={entryExecutionAllowed ? "New paper entries are currently allowed" : "New paper entries are currently blocked"}
            >
              {entryExecutionAllowed ? "✓ Entries allowed" : "✗ Entries blocked"}
            </span>
          )}
        </div>
      )}

      {/* ── Task 857: Latest market job status ──────────────────────────────── */}
      {latestMarketJob != null && (
        <div
          className="mb-2 rounded border border-border/40 bg-muted/10 px-2 py-1.5 text-[10px] space-y-0.5"
          data-testid="mc-latest-market-job"
        >
          <p className="text-muted-foreground font-medium flex items-center gap-1.5">
            <Radar className="w-3 h-3 shrink-0" />
            Latest market scan
            {latestMarketJob.status != null && (
              <span
                className={`ml-1 font-semibold ${jobStatusClass(latestMarketJob.status)}`}
              >
                {latestMarketJob.status}
              </span>
            )}
            {latestMarketJob.scan_type != null && (
              <span className="text-muted-foreground/60 text-[9px]">({latestMarketJob.scan_type})</span>
            )}
          </p>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
            {(latestMarketJob.completed_at_ist ?? latestMarketJob.completed_at) != null && (
              <span>
                Completed{" "}
                <span className="text-foreground font-mono">
                  {istJobTime(latestMarketJob.completed_at_ist ?? latestMarketJob.completed_at)}
                </span>
              </span>
            )}
            {latestMarketJob.duration_s != null && (
              <span>Duration <span className="text-foreground">{latestMarketJob.duration_s.toFixed(0)}s</span></span>
            )}
            {latestMarketJob.symbols_scanned != null && (
              <span>Symbols <span className="text-foreground">{latestMarketJob.symbols_scanned}</span></span>
            )}
            {latestMarketJob.source != null && (
              <span>Source <span className="text-foreground">{latestMarketJob.source}</span></span>
            )}
          </div>
        </div>
      )}

      {/* ── Task 857: Latest system (non-market) job status ─────────────────── */}
      {latestSystemJob != null && latestSystemJob.job_type !== "MARKET_SCAN" && (
        <div
          className="mb-2 rounded border border-border/40 bg-muted/10 px-2 py-1.5 text-[10px] space-y-0.5"
          data-testid="mc-latest-system-job"
        >
          <p className="text-muted-foreground font-medium flex items-center gap-1.5">
            <Cpu className="w-3 h-3 shrink-0" />
            Latest system job
            {latestSystemJob.job_type != null && (
              <span className="font-mono text-[9px] text-foreground/70">{latestSystemJob.job_type}</span>
            )}
            {latestSystemJob.status != null && (
              <span
                className={`ml-1 font-semibold ${jobStatusClass(latestSystemJob.status)}`}
              >
                {latestSystemJob.status}
              </span>
            )}
          </p>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
            {(latestSystemJob.completed_at_ist ?? latestSystemJob.completed_at) != null && (
              <span>
                Completed{" "}
                <span className="text-foreground font-mono">
                  {istJobTime(latestSystemJob.completed_at_ist ?? latestSystemJob.completed_at)}
                </span>
              </span>
            )}
            {latestSystemJob.duration_s != null && (
              <span>Duration <span className="text-foreground">{latestSystemJob.duration_s.toFixed(0)}s</span></span>
            )}
            {latestSystemJob.source != null && (
              <span>Source <span className="text-foreground">{latestSystemJob.source}</span></span>
            )}
          </div>
        </div>
      )}

      {/* ── Task 857: Upcoming scheduled jobs ───────────────────────────────── */}
      {nextJobs != null && nextJobs.length > 0 && (
        <div
          className="mb-2 flex flex-wrap gap-1.5 text-[9px]"
          data-testid="mc-next-jobs"
        >
          <span className="text-muted-foreground shrink-0">Next jobs:</span>
          {nextJobs.slice(0, 3).map((j, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 bg-muted/30 border border-border/50"
              title={`${j.job_type ?? "job"} — ${j.source ?? ""}`}
            >
              <span className="text-foreground font-mono">{j.job_type ?? "job"}</span>
              {(j.scheduled_at_ist ?? j.scheduled_at) != null && (
                <span className="text-muted-foreground">
                  @{istJobTime(j.scheduled_at_ist ?? j.scheduled_at)}
                </span>
              )}
            </span>
          ))}
        </div>
      )}

      {staleDisplay && (
        <div
          className="mb-2 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[10px] text-amber-300"
          data-testid="mc-stale-display-warning"
        >
          Displayed scan status is newer than the latest response. Keeping the newer canonical value and refreshing.
        </div>
      )}

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

      {/* ── Live Data Health ──────────────────────────────────────────────── */}
      {/* Shows OHLCV cache health, hit rate and last post-market refresh.   */}
      {/* Only rendered once the cache status query has resolved.             */}
      {cache != null && (
        <div
          className="mt-3 border-t border-border/40 pt-2 space-y-1"
          data-testid="mc-live-data-health"
        >
          <p className="text-[10px] text-muted-foreground font-medium flex items-center gap-1.5">
            <HeartPulse className="w-3 h-3 shrink-0" />
            Live Data Health
          </p>

          {/* Cache summary row */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px]">
            <span className="text-muted-foreground">OHLCV source:</span>
            <span
              className={`font-semibold ${
                cache.ohlcv_source === "local_yfinance_cache"
                  ? "text-teal-300"
                  : "text-amber-400"
              }`}
              data-testid="mc-ohlcv-source-label"
            >
              {cache.ohlcv_source === "local_yfinance_cache"
                ? "Local cache"
                : cache.ohlcv_source === "yfinance_fallback"
                ? "yfinance fallback"
                : cache.ohlcv_source ?? "Unknown"}
            </span>
            {cache.cache_hit_rate_pct != null && (
              <span
                className={`font-semibold ${
                  cache.cache_hit_rate_pct >= 80
                    ? "text-teal-300"
                    : cache.cache_hit_rate_pct >= 50
                    ? "text-amber-400"
                    : "text-red-400"
                }`}
                data-testid="mc-cache-hit-rate"
              >
                {cache.cache_hit_rate_pct.toFixed(0)}% cache
              </span>
            )}
            {cache.live_symbols != null && cache.total_symbols != null && (
              <span className="text-muted-foreground">
                {cache.live_symbols}/{cache.total_symbols} live
              </span>
            )}
          </div>

          {/* Uncached symbols warning */}
          {yfinanceFallbackAlert && (
            <p
              className="text-[10px] text-amber-400/80 leading-snug"
              data-testid="mc-uncached-symbols-note"
            >
              ⚠ {uncachedCount} symbol{uncachedCount !== 1 ? "s" : ""} not in local cache —
              yfinance is being called for these, slowing scans. Run a backfill to restore speed.
            </p>
          )}

          {/* Last post-market refresh */}
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[10px]">
            <span className="text-muted-foreground shrink-0">Last refresh:</span>
            {lastRefreshLabel ? (
              <>
                <span
                  className="font-semibold text-foreground"
                  data-testid="mc-last-refresh-time"
                >
                  {lastRefreshLabel}
                </span>
                {lastRefresh?.status && (
                  <span
                    className={`text-[9px] ${
                      lastRefresh.status === "SUCCESS"
                        ? "text-teal-400"
                        : "text-amber-400"
                    }`}
                  >
                    {lastRefresh.status}
                  </span>
                )}
                {lastRefresh?.symbols_updated != null && (
                  <span className="text-muted-foreground text-[9px]">
                    {lastRefresh.symbols_updated} symbols
                  </span>
                )}
                {lastRefresh?.duration_seconds != null && (
                  <span className="text-muted-foreground text-[9px]">
                    {lastRefresh.duration_seconds.toFixed(0)}s
                  </span>
                )}
              </>
            ) : (
              <span
                className="text-muted-foreground/60 italic"
                data-testid="mc-last-refresh-time"
              >
                {cacheQ.isLoading ? "Loading…" : "Not yet run"}
              </span>
            )}
          </div>
        </div>
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
            <span>History rows shown</span>
            {historyQ.data?.count != null && (
              <span className="font-semibold text-foreground ml-0.5">
                {historyQ.data.count}
                {historyQ.data.total_completed != null ? ` of ${historyQ.data.total_completed}` : ""}
              </span>
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
          // Detect whether any Task 857 enhanced fields are present in this
          // history batch so we can render the richer layout when available.
          const hasEnhancedFields = history.some(
            (e) => e.job_type != null || e.scan_type != null || e.started_at_ist != null ||
                   e.market_state != null || e.entry_eligible != null || e.execution_eligible != null ||
                   e.source != null,
          );

          return (
            <div className="mt-1.5" data-testid="mc-scan-history-list">
              {hasEnhancedFields ? (
                // ── Task 857 enhanced history layout ─────────────────────────
                <div className="space-y-1">
                  {history.map((entry, i) => {
                    // Prefer pre-formatted IST strings from backend; fall back to
                    // client-side formatting from the raw UTC timestamps.
                    const timeIST = istJobTime(entry.completed_at_ist ?? entry.completed_at);
                    const startedIST = istJobTime(entry.started_at_ist ?? entry.started_at);
                    const dur = entry.duration_s != null ? `${entry.duration_s}s` : "—";
                    const syms = entry.symbols_scanned != null ? String(entry.symbols_scanned) : null;
                    const gapMin = entry.gap_from_prev_s != null
                      ? Math.round(entry.gap_from_prev_s / 60)
                      : null;
                    const gapLabel = gapMin != null ? `${gapMin}m` : (i === history.length - 1 ? "first" : "—");
                    const gapCls = gapMin != null && gapMin > 10 ? "text-amber-400 font-semibold" : "";
                    // Non-market rows get a visible label; market rows use compact display.
                    const isMarketScan = !entry.job_type || normalizedJobValue(entry.job_type) === "MARKET_SCAN";

                    return (
                      <div
                        key={i}
                        className={`rounded px-1.5 py-1 text-[10px] hover:bg-muted/20 font-mono ${
                          isMarketScan ? "" : "border border-border/40 bg-muted/10"
                        }`}
                        data-testid={`mc-scan-history-row-${i}`}
                        data-job-type={entry.job_type ?? "MARKET_SCAN"}
                      >
                        {/* Row header: time + type label + status */}
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                          <span className="text-foreground">{timeIST ?? "—"}</span>
                          {startedIST && startedIST !== timeIST && (
                            <span className="text-muted-foreground/60 text-[9px]">started {startedIST}</span>
                          )}
                          <span className="text-muted-foreground">{dur}</span>
                          {!isMarketScan && (
                            <span
                              className="rounded bg-muted/40 border border-border/60 px-1 text-[9px] text-foreground/70 font-semibold shrink-0"
                              data-testid={`mc-history-job-type-${i}`}
                            >
                              {entry.job_type}
                            </span>
                          )}
                          {entry.scan_type != null && (
                            <span className="text-muted-foreground/60 text-[9px]">{entry.scan_type}</span>
                          )}
                          {entry.status != null && (
                            <span
                              className={`text-[9px] ${jobStatusClass(entry.status)}`}
                            >
                              {entry.status}
                            </span>
                          )}
                          <span className={`ml-auto ${gapCls || "text-muted-foreground"} shrink-0`}
                                title="Gap from previous job">
                            gap {gapLabel}
                          </span>
                        </div>
                        {/* Row detail: market state, execution eligibility, symbols, source */}
                        {(!isMarketScan || entry.market_state != null || entry.entry_eligible != null || entry.execution_eligible != null || syms != null || entry.source != null) && (
                          <div className="flex flex-wrap gap-x-2 gap-y-0 mt-0.5 text-[9px] text-muted-foreground">
                            {syms != null && <span>{syms} symbols</span>}
                            {entry.market_state != null && (
                              <span
                                className={
                                  normalizedJobValue(entry.market_state) === "OPEN" ? "text-emerald-400/70"
                                  : normalizedJobValue(entry.market_state) === "PRE_OPEN" ? "text-amber-400/70"
                                  : ""
                                }
                                data-testid={`mc-history-market-state-${i}`}
                              >
                                mkt:{entry.market_state}
                              </span>
                            )}
                            {entry.entry_eligible != null && (
                              <span
                                className={entry.entry_eligible ? "text-emerald-400/70" : "text-muted-foreground/50"}
                                data-testid={`mc-history-entry-eligible-${i}`}
                              >
                                {entry.entry_eligible ? "entry✓" : "entry✗"}
                              </span>
                            )}
                            {entry.execution_eligible != null && (
                              <span
                                className={entry.execution_eligible ? "text-emerald-400/70" : "text-muted-foreground/50"}
                                data-testid={`mc-history-execution-eligible-${i}`}
                              >
                                {entry.execution_eligible ? "exec✓" : "exec✗"}
                              </span>
                            )}
                            {entry.source != null && (
                              <span data-testid={`mc-history-source-${i}`}>{entry.source}</span>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                // ── Legacy compact history layout (no Task 857 fields) ─────────
                <>
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
                </>
              )}
            </div>
          );
        })()}
      </div>
    </Widget>
  );
}

// ── Bootstrap eligibility banner (inside PaperTradingPanel) ─────────────────
// Shown when all bootstrap gates pass but bootstrap_eligible_count=0, so the
// operator knows EXACTLY which stock was closest and why it didn't qualify.

function BootstrapStatusBanner({ d }: { d: BootstrapStatus | undefined }) {
  if (!d) return null;
  // Only show when the feature is on and auto-entries are armed.
  if (!d.bootstrap_paper_enabled || !d.auto_paper_entries) return null;
  // Don't show when circuit-breaker is tripped or cutoff reached — those have
  // their own prominent indicators elsewhere.
  if (d.circuit_breaker_tripped || d.bootstrap_cutoff_reached) return null;

  const eligCount = d.bootstrap_eligible_count ?? 0;
  const watchTop  = d.top_watch_candidate ?? null;

  if (eligCount > 0) {
    // Eligible candidates exist — show a quiet positive note.
    return (
      <div
        className="mt-2 rounded-lg border border-teal-500/30 bg-teal-500/10 px-2.5 py-1.5 text-[10px]"
        data-testid="mc-bootstrap-banner-eligible"
      >
        <span className="text-teal-300 font-semibold">{eligCount} bootstrap-eligible</span>
        {" "}candidate{eligCount !== 1 ? "s" : ""} in last scan.
        {(d.top_candidates ?? []).length > 0 && (
          <span className="text-muted-foreground ml-1">
            Top: <span className="font-mono font-semibold text-foreground">
              {d.top_candidates![0].symbol}
            </span>
            {" "}({d.top_candidates![0].confidence.toFixed(0)}% conf)
          </span>
        )}
      </div>
    );
  }

  // No bootstrap-eligible candidates. Show the top WATCH candidate with reason.
  return (
    <div
      className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[10px] space-y-0.5"
      data-testid="mc-bootstrap-banner-none"
    >
      <p className="text-amber-300 font-semibold flex items-center gap-1">
        <AlertTriangle className="w-3 h-3 shrink-0" />
        No bootstrap-eligible candidates in last scan
      </p>
      {watchTop ? (
        <p className="text-muted-foreground leading-snug">
          Top candidate:{" "}
          <span className="font-mono font-semibold text-foreground">{watchTop.symbol}</span>
          {" "}(<span className="text-amber-300">{watchTop.action}</span>, {watchTop.confidence.toFixed(0)}% conf)
          {watchTop.ineligibility_reason && (
            <span className="text-muted-foreground/70"> — {watchTop.ineligibility_reason}</span>
          )}
        </p>
      ) : (
        <p className="text-muted-foreground">
          Scanner found {d.watch_count ?? 0} WATCH symbol{(d.watch_count ?? 0) !== 1 ? "s" : ""} —
          none cleared bootstrap thresholds.
        </p>
      )}
    </div>
  );
}

// ── EOD square-off countdown banner ──────────────────────────────────────────
// Shown inside PaperTradingPanel whenever the squareoff window is approaching
// or active, or today's force-close has already produced results/blocks.

function EodSquareoffBanner({ d }: { d: EodStatus | undefined }) {
  // Local per-second countdown so the display is smooth between 30 s query
  // refreshes.  Seeded from `time_to_squareoff_sec` whenever the query returns
  // fresh data; counts down independently between refreshes.
  const [localSec, setLocalSec] = useState<number | null>(null);
  const seedRef = useRef<number | null>(null);

  useEffect(() => {
    if (d?.time_to_squareoff_sec === undefined) return;
    const fresh = d.time_to_squareoff_sec;
    if (seedRef.current !== fresh) {
      seedRef.current = fresh;
      setLocalSec(fresh);
    }
    const id = setInterval(() => {
      setLocalSec((prev) => (prev !== null && prev > 0 ? prev - 1 : prev));
    }, 1_000);
    return () => clearInterval(id);
  }, [d?.time_to_squareoff_sec]);

  if (!d) return null;

  const sqTime = d.squareoff_time_ist ?? "15:20 IST";
  const blocked = d.blocked_events ?? [];
  const closed = d.force_close_results ?? [];

  // ── 1. MARKET_CLOSE_EXIT_BLOCKED — prominent red banner ─────────────────
  if (blocked.length > 0) {
    return (
      <div className="mt-2 space-y-1" data-testid="mc-eod-blocked-banner">
        <div className="rounded-lg border border-red-500/50 bg-red-500/10 px-2.5 py-2 text-[10px]">
          <p className="text-red-400 font-semibold flex items-center gap-1 mb-1">
            <XCircle className="w-3 h-3 shrink-0" />
            EOD square-off blocked — position{blocked.length !== 1 ? "s" : ""} may carry overnight
          </p>
          {blocked.map((b, i) => (
            <p key={i} className="text-muted-foreground leading-snug">
              <span className="font-mono font-semibold text-foreground">{b.symbol ?? "—"}</span>
              {b.reason ? `: ${b.reason}` : " — no price available"}
            </p>
          ))}
          <p className="text-red-300/70 mt-1">Manual review required.</p>
        </div>
        {/* Also show any successful closes alongside the block */}
        {closed.length > 0 && (
          <EodCloseResults results={closed} />
        )}
      </div>
    );
  }

  // ── 2. After-close results (force-close ran, no blocks) ──────────────────
  if ((d.eod_ran_today || closed.length > 0) && d.past_post_close) {
    if (closed.length === 0) {
      return (
        <div
          className="mt-2 rounded-lg border border-border/40 bg-muted/10 px-2.5 py-1.5 text-[10px] text-muted-foreground"
          data-testid="mc-eod-ran-no-positions"
        >
          <span className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
            EOD square-off completed — no open positions to close.
          </span>
        </div>
      );
    }
    return <EodCloseResults results={closed} className="mt-2" />;
  }

  // ── 3. Active square-off window (15:20–15:30 IST) ───────────────────────
  if (d.in_squareoff_window) {
    return (
      <div
        className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-[10px]"
        data-testid="mc-eod-active-banner"
      >
        <p className="text-amber-300 font-semibold flex items-center gap-1">
          <Timer className="w-3 h-3 shrink-0 animate-pulse" />
          EOD square-off active — positions will close on next scan
        </p>
        <p className="text-muted-foreground mt-0.5">
          All open paper positions will be force-closed at {sqTime}.
        </p>
      </div>
    );
  }

  // ── 4. Countdown (within 30 min of 15:20 IST) ───────────────────────────
  if (d.show_countdown && localSec !== null && localSec > 0) {
    const mins = Math.floor(localSec / 60);
    const secs = localSec % 60;
    const urgency = localSec <= 5 * 60; // last 5 minutes
    return (
      <div
        className={`mt-2 rounded-lg border px-2.5 py-1.5 text-[10px] ${
          urgency
            ? "border-orange-500/50 bg-orange-500/10"
            : "border-amber-500/30 bg-amber-500/5"
        }`}
        data-testid="mc-eod-countdown-banner"
      >
        <p className={`font-semibold flex items-center gap-1 ${urgency ? "text-orange-300" : "text-amber-300"}`}>
          <Timer className="w-3 h-3 shrink-0" />
          EOD square-off in {mins}m {String(secs).padStart(2, "0")}s ({sqTime})
        </p>
        <p className="text-muted-foreground mt-0.5">
          Open positions will be auto-closed at market end.
        </p>
      </div>
    );
  }

  return null;
}

/** Compact table of today's force-close results. */
function EodCloseResults({
  results, className = "",
}: {
  results: EodForceCloseResult[];
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-teal-500/30 bg-teal-500/5 px-2.5 py-1.5 text-[10px] ${className}`}
      data-testid="mc-eod-close-results"
    >
      <p className="text-teal-300 font-semibold flex items-center gap-1 mb-1">
        <CheckCircle2 className="w-3 h-3 shrink-0" />
        EOD square-off complete — {results.length} position{results.length !== 1 ? "s" : ""} closed
      </p>
      <div className="space-y-0.5">
        {results.map((r, i) => (
          <div key={i} className="flex items-center gap-2 text-[10px]">
            <span className="font-mono font-semibold w-20 truncate">{r.symbol ?? "—"}</span>
            <span className="text-muted-foreground">@ {fmtINR(r.exit_price, 2)}</span>
            {r.realized_pnl != null && (
              <PnlText value={r.realized_pnl} className="ml-auto" />
            )}
            {r.fallback_used && (
              <span className="text-amber-400/80 shrink-0" title="Exit price used fill-price fallback">⚠</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Panel 3 — Live Paper Trading ─────────────────────────────────────────────

function PaperTradingPanel({ portfolio }: { portfolio: PortfolioSnapshot | undefined }) {
  // Single canonical ledger query shared with Throughput/LivePerformance
  // (same key/path as useLedgerToday — React Query dedupes to one fetch).
  const ledgerQ = useLedgerToday();

  // Bootstrap status — queried here to add the eligibility banner without a
  // separate page-level fetch. 30 s cadence matches scan cadence; 10 s timeout.
  const bootstrapQ = useWidgetQuery<BootstrapStatus>({
    queryKey: ["mc", "bootstrap-status"],
    path: "/phase20/bootstrap-status",
    requestInit: { cache: "no-store" },
    cacheBust: true,
    refetchInterval: 30_000,
    timeoutMs: 10_000,
  });

  // EOD square-off status — lightweight read-only endpoint; no yfinance calls.
  // Polled every 30 s; 10 s timeout. Shown only when approaching 15:20 IST.
  const eodQ = useWidgetQuery<EodStatus>({
    queryKey: ["mc", "eod-status"],
    path: "/phase20/eod-status",
    requestInit: { cache: "no-store" },
    cacheBust: true,
    refetchInterval: 30_000,
    timeoutMs: 10_000,
  });

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
      {/* Bootstrap eligibility status banner */}
      <BootstrapStatusBanner d={bootstrapQ.data} />

      {/* EOD square-off countdown / result banner */}
      <EodSquareoffBanner d={eodQ.data} />

      {/* Recent fills */}
      <p className="text-[10px] text-muted-foreground mb-1 mt-2">Recent trades</p>
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

export function EventStreamPanel({ streamEvents }: { streamEvents: PipelineStreamEvent[] }) {
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

            // Phase 20 Allocation Extraction
            const allocTier = (
              e.payload?.allocation_tier ?? e.payload?.tier
            ) as string | undefined;
            const isAllocEvent = e.event_type.includes("ALLOCATION") || !!allocTier;
            const requestedMult = (
              e.payload?.allocation_requested_multiplier
              ?? e.payload?.requested_multiplier
            ) as number | undefined;
            const effMult = (
              e.payload?.allocation_multiplier
              ?? e.payload?.allocation_effective_multiplier
              ?? e.payload?.effective_multiplier
            ) as number | undefined;
            const notional = (
              e.payload?.allocation_final_notional
              ?? e.payload?.final_notional
            ) as number | undefined;
            const caps = (
              e.payload?.allocation_limiting_caps
              ?? e.payload?.limiting_caps
            ) as string[] | undefined;
            const hasCaps = caps && caps.length > 0;

            return (
              <div key={e.id} style={{ height: EVENT_ROW_H }} className="flex items-center gap-2 border-b border-border/30 last:border-0 group">
                <Icon className={`h-3 w-3 shrink-0 ${toneClass[tone]}`} />
                <span className="text-muted-foreground w-14 shrink-0">{timeAgo(e.ts)}</span>
                <span className="w-24 shrink-0 truncate text-muted-foreground/70">{e.stage}</span>
                <span className={`w-40 shrink-0 truncate ${toneClass[tone]}`} title={e.event_type}>{e.event_type}</span>
                <span className="w-20 shrink-0 font-semibold truncate">{e.symbol ?? ""}</span>

                {/* Custom payload display */}
                <div className="flex items-center gap-1.5 flex-1 min-w-0 truncate text-muted-foreground">
                  <span className="truncate min-w-0">
                    {String(e.payload?.rejection_reason ?? e.payload?.reason ?? e.payload?.action ?? e.payload?.strategy_name ?? e.payload?.trade_id ?? "")}
                  </span>

                  {isAllocEvent && allocTier && (
                    <Badge variant="outline" className={`text-[8px] h-3.5 px-1 py-0 leading-none shrink-0 ${
                      allocTier === "EXCEPTIONAL_QUALITY_3X"
                        ? "border-fuchsia-800 text-fuchsia-400 bg-fuchsia-950/40"
                        : "border-blue-800 text-blue-400 bg-blue-950/40"
                    }`} data-testid={`mc-allocation-tier-${e.id}`}>
                      {allocTier === "EXCEPTIONAL_QUALITY_3X"
                        ? "3X"
                        : allocTier === "HIGH_QUALITY_2X"
                          ? "2X"
                          : "1X"}
                    </Badge>
                  )}
                  {isAllocEvent && effMult !== undefined && (
                    <span className="text-[9px] font-mono shrink-0 text-slate-400">
                      {effMult}x
                      {requestedMult !== undefined && requestedMult !== effMult
                        ? `/${requestedMult}x req`
                        : ""}
                    </span>
                  )}
                  {isAllocEvent && notional !== undefined && (
                    <span className="text-[9px] font-mono shrink-0 text-slate-400">₹{(notional / 1000).toFixed(1)}k</span>
                  )}
                  {isAllocEvent && hasCaps && (
                    <span className="text-[9px] shrink-0 text-amber-500/80 truncate max-w-[80px]" title={`Capped by: ${caps.join(", ")}`}>
                      [cap: {caps[0]}]
                    </span>
                  )}
                </div>

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

const METADATA_HYDRATION_CONFIRMATION = "HYDRATE_INSTRUMENT_METADATA_ONLY";

export function LowPriceUniverseCard({
  statusQ,
  symbolsQ,
}: {
  statusQ: UseQueryResult<CustomUniverseStatus>;
  symbolsQ: UseQueryResult<CustomUniverseSymbolsResponse>;
}) {
  const queryClient = useQueryClient();
  const [adminToken, setAdminToken] = useState("");
  const [metadataConfirmation, setMetadataConfirmation] = useState("");
  const refresh = useMutation({
    mutationFn: () => apiJson("/universe/custom/refresh", { method: "POST" }, 180_000),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mc", "custom-universe-status"] });
      void queryClient.invalidateQueries({ queryKey: ["mc", "custom-universe-symbols"] });
    },
  });
  const hydrateMetadata = useMutation({
    mutationFn: (request: { token: string; confirmation: string }) => apiJson(
      "/universe/custom/hydrate-instruments",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-token": request.token,
        },
        body: JSON.stringify({ confirmation: request.confirmation }),
      },
      60_000,
    ),
    onSuccess: () => {
      setAdminToken("");
      setMetadataConfirmation("");
      void queryClient.invalidateQueries({ queryKey: ["mc", "custom-universe-status"] });
      void queryClient.invalidateQueries({ queryKey: ["mc", "custom-universe-symbols"] });
    },
  });
  const status = statusQ.data;
  if (!status) return null;
  const customModeActive = status.active_universe === "CUSTOM_LOW_PRICE_SECTOR";
  const symbols = symbolsQ.data?.symbols ?? [];
  const included = symbols.filter((symbol) => symbol.is_active);
  const excluded = symbols.filter((symbol) => !symbol.is_active);
  const band = status.price_filter ?? {};
  const metadata = status.instrument_metadata;
  const confirmationRequired = metadata?.confirmation_required ?? METADATA_HYDRATION_CONFIRMATION;
  const canHydrateMetadata = Boolean(
    adminToken.trim() && metadataConfirmation.trim() === confirmationRequired,
  );

  return (
    <Widget
      title={customModeActive ? "Low Price Universe Builder" : "Custom Universe Mapping Review"}
      icon={PieChart}
      query={statusQ}
      refreshMs={15_000}
      testId="mc-low-price-universe"
      headerExtra={<Badge variant="outline" className="text-[9px] border-teal-700/50 text-teal-300">PAPER ONLY</Badge>}
      skeletonClass="h-48"
    >
      <div className="space-y-3 text-[10px]">
        {customModeActive ? (
          <>
            <div className="flex flex-wrap gap-2 items-center">
              <Badge className="text-[9px] bg-teal-950 text-teal-300 border border-teal-800">
                {status.custom_universe_name ?? "CUSTOM_LOW_PRICE_SECTOR"}
              </Badge>
              <span className="text-muted-foreground">Price ₹{band.min ?? 20}–₹{band.max ?? 200}</span>
              <span className="text-muted-foreground">Sectors: {(status.sectors ?? ["IT", "INFRA", "BANK"]).join(" · ")}</span>
              <button
                type="button"
                className="ml-auto inline-flex items-center gap-1 rounded-md border border-teal-700/60 px-2 py-1 text-[10px] text-teal-300 hover:bg-teal-950/50 disabled:opacity-50"
                onClick={() => refresh.mutate()}
                disabled={refresh.isPending}
                data-testid="mc-refresh-low-price-universe"
              >
                <RefreshCw className={`h-3 w-3 ${refresh.isPending ? "animate-spin" : ""}`} />
                {refresh.isPending ? "Refreshing membership…" : "Refresh membership"}
              </button>
            </div>
            {refresh.isError && <p className="text-red-400">Refresh failed: {(refresh.error as Error).message}</p>}
            {refresh.isSuccess && <p className="text-emerald-400">Membership refresh completed. Stored instrument mappings were not changed.</p>}
          </>
        ) : (
          <p className="rounded-md border border-border/50 bg-muted/10 px-2 py-1.5 text-muted-foreground" data-testid="mc-custom-universe-inactive-note">
            Custom universe is inactive. Review its mapping freshness here before switching modes or approving a metadata-only refresh.
          </p>
        )}

        {metadata && (
          <div
            className={`rounded-lg border px-2.5 py-2 space-y-2 ${
              metadata.refresh_required
                ? "border-amber-700/60 bg-amber-950/20"
                : "border-border/50 bg-muted/10"
            }`}
            data-testid="mc-custom-universe-mapping-status"
          >
            <div className="flex flex-wrap items-start gap-2">
              <div className="min-w-0">
                <p className="font-medium text-foreground flex items-center gap-1.5">
                  <RefreshCw className="h-3 w-3 shrink-0 text-teal-300" />
                  Instrument mapping freshness
                </p>
                <p className="text-muted-foreground leading-snug mt-0.5">
                  The instrument cache and stored custom-universe mappings are separate.
                  Refreshing the cache does not update these mappings automatically.
                </p>
              </div>
              <Badge
                variant="outline"
                className={`ml-auto text-[9px] ${
                  metadata.refresh_required
                    ? "border-amber-600/60 text-amber-300"
                    : "border-emerald-700/50 text-emerald-300"
                }`}
                data-testid="mc-custom-universe-mapping-refresh-status"
              >
                {metadata.refresh_required ? "REFRESH REQUIRED" : "MAPPING CURRENT"}
              </Badge>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-muted-foreground">Complete coverage</p>
                <p className="font-semibold text-foreground" data-testid="mc-custom-universe-mapping-coverage">
                  {metadata.complete_mapping_count ?? 0} / {metadata.active_count ?? status.active_count ?? 0} active
                </p>
              </div>
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-muted-foreground">Newest mapping date</p>
                <p className="font-semibold text-foreground" data-testid="mc-custom-universe-newest-mapping-date">
                  {metadata.newest_cache_date ?? "—"}
                </p>
              </div>
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-muted-foreground">Mapping age</p>
                <p
                  className={`font-semibold ${
                    metadata.refresh_required ? "text-amber-300" : "text-foreground"
                  }`}
                  data-testid="mc-custom-universe-mapping-age"
                >
                  {metadata.cache_age_days != null ? `${metadata.cache_age_days} day${metadata.cache_age_days === 1 ? "" : "s"} (oldest)` : "—"}
                </p>
              </div>
              <div className="rounded-md bg-muted/30 p-2">
                <p className="text-muted-foreground">Provenance</p>
                <p className="font-semibold text-foreground break-words" data-testid="mc-custom-universe-mapping-provenance">
                  {metadata.provenance ?? "Unknown"}
                </p>
              </div>
            </div>

            {(metadata.invalid_mapping_count || metadata.stale_mapping_count) ? (
              <p className="text-amber-300 leading-snug" data-testid="mc-custom-universe-mapping-issues">
                {metadata.invalid_mapping_count ?? 0} incomplete and {metadata.stale_mapping_count ?? 0} stale active mapping{(metadata.invalid_mapping_count ?? 0) + (metadata.stale_mapping_count ?? 0) === 1 ? "" : "s"}.
              </p>
            ) : null}

            <form
              className="border-t border-border/40 pt-2 space-y-1.5"
              onSubmit={(event) => {
                event.preventDefault();
                if (canHydrateMetadata) {
                  hydrateMetadata.mutate({
                    token: adminToken.trim(),
                    confirmation: metadataConfirmation.trim(),
                  });
                }
              }}
            >
              <p className="font-medium text-foreground">Metadata-only approval</p>
              <p className="text-muted-foreground leading-snug">
                This does not refresh membership or choose symbols. It only hydrates NSE instrument metadata
                for the existing active membership. Administrator credential and exact confirmation are required.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <label className="space-y-1">
                  <span className="text-muted-foreground">Administrator credential</span>
                  <input
                    type="password"
                    value={adminToken}
                    onChange={(event) => setAdminToken(event.target.value)}
                    placeholder="Enter admin token"
                    autoComplete="off"
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[10px] text-foreground placeholder:text-muted-foreground/50"
                    data-testid="mc-custom-universe-admin-token"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-muted-foreground">
                    Type <code className="font-mono text-teal-300">{confirmationRequired}</code>
                  </span>
                  <input
                    type="text"
                    value={metadataConfirmation}
                    onChange={(event) => setMetadataConfirmation(event.target.value)}
                    placeholder="Exact confirmation"
                    autoComplete="off"
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-[10px] font-mono text-foreground placeholder:text-muted-foreground/50"
                    data-testid="mc-custom-universe-metadata-confirmation"
                  />
                </label>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="submit"
                  className="inline-flex items-center gap-1 rounded-md border border-amber-700/60 px-2 py-1 text-[10px] text-amber-300 hover:bg-amber-950/40 disabled:opacity-50"
                  disabled={!canHydrateMetadata || hydrateMetadata.isPending}
                  data-testid="mc-approve-metadata-only-hydration"
                >
                  <RefreshCw className={`h-3 w-3 ${hydrateMetadata.isPending ? "animate-spin" : ""}`} />
                  {hydrateMetadata.isPending ? "Hydrating metadata…" : "Approve metadata-only refresh"}
                </button>
                <span className="text-muted-foreground">
                  {metadata.approval_required === false ? "Approval not currently required." : "Approval required"}
                </span>
              </div>
              {hydrateMetadata.isError && (
                <p className="text-red-400" data-testid="mc-custom-universe-metadata-error">
                  Metadata refresh failed: {(hydrateMetadata.error as Error).message}
                </p>
              )}
              {hydrateMetadata.isSuccess && (
                <p className="text-emerald-400" data-testid="mc-custom-universe-metadata-success">
                  Metadata-only refresh completed. Review the updated mapping date and coverage above.
                </p>
              )}
            </form>
          </div>
        )}

        {customModeActive && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="rounded-md bg-muted/30 p-2"><p className="text-muted-foreground">Active</p><p className="font-semibold text-teal-300">{status.active_count ?? 0}</p></div>
              <div className="rounded-md bg-muted/30 p-2"><p className="text-muted-foreground">OHLCV cache</p><p className="font-semibold">{status.ohlcv_cache_hit_rate_pct ?? 0}%</p></div>
              <div className="rounded-md bg-muted/30 p-2"><p className="text-muted-foreground">Kite LTP</p><p className="font-semibold">{status.kite_ltp?.status ?? "UNKNOWN"}</p></div>
              <div className="rounded-md bg-muted/30 p-2"><p className="text-muted-foreground">Last refresh</p><p className="font-semibold">{timeAgo(status.last_refresh)}</p></div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(status.sector_counts ?? {}).map(([sector, count]) => (
                <Badge key={sector} variant="outline" className="text-[9px]">{sector}: {count}</Badge>
              ))}
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              <div className="min-w-0">
                <p className="mb-1 font-medium text-emerald-300">Included ({included.length})</p>
                <div className="max-h-44 overflow-auto rounded-md border border-border/60">
                  <table className="w-full text-left">
                    <thead className="sticky top-0 bg-card text-muted-foreground"><tr><th className="p-1.5">Symbol</th><th>LTP</th><th>Sector</th><th>20D vol</th><th>20D turnover</th></tr></thead>
                    <tbody>{included.map((row) => <tr key={row.symbol} className="border-t border-border/40">
                      <td className="p-1.5 font-mono">{row.symbol}</td><td>{fmtINR(row.last_ltp, 2)}</td><td>{row.sector ?? "—"}</td>
                      <td>{(row.avg_volume_20d ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}</td><td>{fmtINR(row.avg_turnover_20d)}</td>
                    </tr>)}{!included.length && <tr><td className="p-2 text-muted-foreground" colSpan={5}>No active symbols yet.</td></tr>}</tbody>
                  </table>
                </div>
              </div>
              <div className="min-w-0">
                <p className="mb-1 font-medium text-amber-300">Excluded ({excluded.length})</p>
                <div className="max-h-44 overflow-auto rounded-md border border-border/60">
                  <table className="w-full text-left"><thead className="sticky top-0 bg-card text-muted-foreground"><tr><th className="p-1.5">Symbol</th><th>Reason</th></tr></thead>
                    <tbody>{excluded.map((row) => <tr key={row.symbol} className="border-t border-border/40"><td className="p-1.5 font-mono">{row.symbol}</td><td className="text-muted-foreground">{row.reason_excluded ?? "Not eligible"}</td></tr>)}
                    {!excluded.length && <tr><td className="p-2 text-muted-foreground" colSpan={2}>No exclusions recorded.</td></tr>}</tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </Widget>
  );
}

function UniverseModeControl({ statusQ }: { statusQ: UseQueryResult<CustomUniverseStatus> }) {
  const queryClient = useQueryClient();
  const active = statusQ.data?.active_universe ?? "NIFTY_50";
  const updateMode = useMutation({
    mutationFn: (active_intraday_universe: string) => apiJson(
      "/universe/active",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active_intraday_universe }),
      },
      30_000,
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mc", "custom-universe-status"] });
      void queryClient.invalidateQueries({ queryKey: ["mc", "custom-universe-symbols"] });
      void queryClient.invalidateQueries({ queryKey: ["mc", "scan-status"] });
    },
  });

  return (
    <div className="rounded-lg border border-teal-800/50 bg-teal-950/20 px-3 py-2 flex flex-wrap items-center gap-3"
      data-testid="mc-universe-mode-control">
      <div className="min-w-44">
        <p className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Active intraday universe</p>
        <p className="text-[10px] text-teal-300">Paper-only scan selection · risk caps unchanged</p>
      </div>
      <select
        value={active}
        onChange={(event) => updateMode.mutate(event.target.value)}
        disabled={statusQ.isLoading || updateMode.isPending}
        className="rounded-md border border-teal-700/60 bg-background px-2 py-1.5 text-xs font-mono text-foreground disabled:opacity-50"
        data-testid="mc-select-intraday-universe"
      >
        <option value="NIFTY_50">NIFTY 50</option>
        <option value="CUSTOM_LOW_PRICE_SECTOR">Low-price IT / Infra / Bank</option>
      </select>
      <Badge variant="outline" className="text-[9px] border-teal-700/50 text-teal-300">
        {active === "CUSTOM_LOW_PRICE_SECTOR" ? "CUSTOM MODE ACTIVE" : "NIFTY 50 ACTIVE"}
      </Badge>
      {statusQ.isError && <span className="text-xs text-red-400">Unable to read active universe.</span>}
      {updateMode.isError && <span className="text-xs text-red-400">Selection failed: {(updateMode.error as Error).message}</span>}
      {updateMode.isSuccess && <span className="text-xs text-emerald-400">Saved — the next scan uses this universe.</span>}
    </div>
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
  // Also refresh the OHLCV cache status on scan completion so the hit-rate chip
  // reflects the actual source used by the completed scan.
  useEffect(() => {
    if (!scanEvent) return;
    void queryClient.invalidateQueries({ queryKey: ["mc", "scan-status"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "replay-latest"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "pipeline-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "portfolio"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "ohlcv-cache-status"] });
  }, [scanEvent, queryClient]);

  // Shared queries used by multiple regions (fetched ONCE each).
  const portfolioQ = useWidgetQuery<PortfolioSnapshot>({
    queryKey: ["mc", "portfolio"], path: "/portfolio/snapshot", refetchInterval: R.portfolio, timeoutMs: 30_000,
  });
  const scanQ = useWidgetQuery<ScanStatus>({
    queryKey: ["mc", "scan-status"],
    path: "/live-data/scan/status",
    requestInit: { cache: "no-store" },
    cacheBust: true,
    refetchInterval: R.scan,
  });
  const monotonicScan = useMonotonicScanStatus(scanQ);
  const scanQForDisplay = {
    ...scanQ,
    data: monotonicScan.data,
  } as UseQueryResult<ScanStatus>;
  const customUniverseStatusQ = useWidgetQuery<CustomUniverseStatus>({
    queryKey: ["mc", "custom-universe-status"],
    path: "/universe/custom/status",
    refetchInterval: 15_000,
    timeoutMs: 30_000,
  });
  const customUniverseSymbolsQ = useWidgetQuery<CustomUniverseSymbolsResponse>({
    queryKey: ["mc", "custom-universe-symbols"],
    path: "/universe/custom/symbols",
    refetchInterval: 30_000,
    timeoutMs: 30_000,
    enabled: customUniverseStatusQ.data?.active_universe === "CUSTOM_LOW_PRICE_SECTOR",
  });
  const scanPresentation = getScanPresentation(monotonicScan.data);
  const scanning = scanPresentation.isScanning;
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
          <ScanBuildIdentity
            apiBuildId={monotonicScan.data?.api_build_id}
            lastRefreshedAt={monotonicScan.lastRefreshedAt}
          />
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
        <PipelinePanel
          scanning={scanning}
          afterHoursMonitoring={scanPresentation.isAfterHoursMonitoring}
          replayQ={replayQ}
          scanQ={scanQForDisplay}
        />
        <div className="lg:col-span-2 space-y-3 min-w-0">
          <ScannerPanel scanQ={scanQForDisplay} staleDisplay={monotonicScan.staleResponse} />
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
          <StockWatchWidget portfolio={portfolioQ.data} scan={monotonicScan.data} />
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
        <ScanBuildIdentity
          apiBuildId={monotonicScan.data?.api_build_id}
          lastRefreshedAt={monotonicScan.lastRefreshedAt}
        />
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

      <UniverseModeControl statusQ={customUniverseStatusQ} />

      {customUniverseStatusQ.data && (
        <LowPriceUniverseCard statusQ={customUniverseStatusQ} symbolsQ={customUniverseSymbolsQ} />
      )}

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
