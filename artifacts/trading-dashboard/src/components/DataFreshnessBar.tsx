import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  Clock,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle2,
  Database,
  WifiOff,
} from "lucide-react";
import { type DataStatus, DATA_STATUS_COLOR, DATA_STATUS_DOT, isMarketOpen } from "@/lib/dataStatus";

// ── Phase 19C / Phase C — DataFreshnessBar ────────────────────────────────────
// Canonical data-truthfulness indicator for every data-driven page.
// Status vocabulary: LIVE | DELAYED | CACHED | STALE | DEMO | UNAVAILABLE.
// All values come from backend metadata — never from browser time.
// Paper trading / research only.

type Variant = "scan" | "quotes" | "historical" | "none";

interface HistoricalProps {
  /** e.g. "Trade history" / "Knowledge base" */
  datasetLabel?: string;
  /** ISO timestamp the dataset was last updated (backend metadata) */
  lastUpdated?: string | null;
  /** e.g. latest included trade date */
  latestRecord?: string | null;
  /** e.g. "142 trades" */
  sampleSize?: string | null;
}

interface DataFreshnessBarProps extends HistoricalProps {
  variant?: Variant;
  /** Extra provider label for quote pages (falls back to scan provider). */
  quoteProvider?: string | null;
  /** Latest quote/exchange timestamp for live-quote pages. */
  quoteTimestamp?: string | null;
  className?: string;
}

interface StalenessResponse {
  success?: boolean;
  current_time?: string;
  last_scan_time?: string;
  scan_age_seconds?: number;
  scan_age_human?: string;
  stale?: boolean;
  buy_recommendations_disabled?: boolean;
  warning?: string | null;
  label?: string;
}

interface ScanStatusResponse {
  success?: boolean;
  latest_scan?: {
    scan_id?: string;
    status?: string;
    started_at?: string;
    completed_at?: string;
    snapshot_ts?: string;
    provider?: string;
    symbols_requested?: number;
    symbols_received?: number;
    symbols_missing?: number;
    symbols_stale?: number;
    missing_symbols?: string[];
    stale_symbols?: string[];
    error?: string | null;
    updated_at?: string;
  } | null;
}

interface CoverageResponse {
  success?: boolean;
  ok?: boolean;
  in_session?: boolean;
  market_state?: string;
  coverage?: number | null;
  min_symbols_expected?: number;
  missing_symbols?: string[];
  scan_fresh_for_session?: boolean;
  warning?: string | null;
}

export const STALENESS_QUERY_KEY = ["/api/phase15/staleness"];
export const SCAN_STATUS_QUERY_KEY = ["/api/live-data/scan/status"];
export const COVERAGE_QUERY_KEY = ["/api/live-data/coverage"];

function useFreshness(enabled: boolean) {
  const staleness = useQuery<StalenessResponse>({
    queryKey: STALENESS_QUERY_KEY,
    queryFn: () => apiJson<StalenessResponse>("/phase15/staleness"),
    refetchInterval: 60_000,
    staleTime: 30_000,
    enabled,
  });
  const scanStatus = useQuery<ScanStatusResponse>({
    queryKey: SCAN_STATUS_QUERY_KEY,
    queryFn: () => apiJson<ScanStatusResponse>("/live-data/scan/status"),
    refetchInterval: 60_000,
    staleTime: 30_000,
    enabled,
  });
  // Canonical market-hours coverage verdict — ALL session/holiday/universe
  // logic is server-side (scanner_coverage.py); the browser only renders it.
  const coverage = useQuery<CoverageResponse>({
    queryKey: COVERAGE_QUERY_KEY,
    queryFn: () => apiJson<CoverageResponse>("/live-data/coverage"),
    refetchInterval: 60_000,
    staleTime: 30_000,
    enabled,
  });
  return { staleness, scanStatus, coverage };
}

function istTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
    timeZone: "Asia/Kolkata",
  }) + " IST";
}

function istDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
    timeZone: "Asia/Kolkata",
  }) + " IST";
}

function ageLabel(seconds?: number): string {
  if (seconds == null || isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m ago`;
}

/**
 * Derive the canonical DataStatus from backend metadata.
 * Rules (in priority order):
 *  1. No scan has ever completed AND provider is unavailable → UNAVAILABLE
 *  2. Last scan FAILED but we have older cached snapshot → CACHED
 *  3. Last scan FAILED and no cached data → UNAVAILABLE
 *  4. Data exceeds staleness threshold AND market is closed → MARKET_CLOSED
 *     (stale during closed hours is expected — not a system error)
 *  5. Data exceeds staleness threshold AND market is open → STALE
 *  6. Some symbols missing or stale → DELAYED
 *  7. All symbols present, data fresh → LIVE
 *
 * Market-open determination uses `st.current_time` from the backend —
 * never from the browser clock.
 *
 * Exported for unit testing.
 */
export function deriveDataStatus(
  loading: boolean,
  failed: boolean,
  stale: boolean,
  meta: ScanStatusResponse["latest_scan"] | null,
  st: StalenessResponse | undefined,
): DataStatus {
  if (loading) return "LIVE"; // placeholder; spinner shown instead of badge
  // No data — provider has never delivered a snapshot
  if (!meta && !st?.last_scan_time) return "UNAVAILABLE";
  // Scan engine reported FAILED
  if (failed) {
    // If we still have a previous snapshot (staleness endpoint has a last_scan_time),
    // the server is returning CACHED data from the previous good scan.
    return st?.last_scan_time ? "CACHED" : "UNAVAILABLE";
  }
  // Data exceeds the platform's staleness threshold
  if (stale) {
    // MARKET_CLOSED is more informative than STALE when outside trading hours:
    // stale data during weekends / post-close is expected, not a system problem.
    return isMarketOpen(st?.current_time) ? "STALE" : "MARKET_CLOSED";
  }
  // Provider connected but some symbols are missing or individually stale
  const partialCoverage =
    (meta?.symbols_missing ?? 0) > 0 || (meta?.symbols_stale ?? 0) > 0;
  if (partialCoverage) return "DELAYED";
  return "LIVE";
}

/** Small animated connection dot. */
function ConnectionDot({ status }: { status: DataStatus }) {
  const color = DATA_STATUS_DOT[status];
  const pulse = status === "LIVE";
  return (
    <span className="relative inline-flex h-2 w-2 flex-shrink-0">
      {pulse && (
        <span
          className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
          style={{ backgroundColor: color }}
        />
      )}
      <span
        className="relative inline-flex h-2 w-2 rounded-full"
        style={{ backgroundColor: color }}
      />
    </span>
  );
}

export default function DataFreshnessBar({
  variant = "scan",
  quoteProvider,
  quoteTimestamp,
  datasetLabel,
  lastUpdated,
  latestRecord,
  sampleSize,
  className = "",
}: DataFreshnessBarProps) {
  const [open, setOpen] = useState(false);
  const isLive = variant === "scan" || variant === "quotes";
  const { staleness, scanStatus, coverage } = useFreshness(isLive);

  // ── Static / config-only pages ──────────────────────────────────────────
  if (variant === "none") {
    return (
      <div
        data-testid="data-freshness-bar"
        className={`flex items-center gap-2 rounded-md border border-border/60 bg-card/40 px-3 py-1.5 text-xs font-mono text-muted-foreground ${className}`}
      >
        <Database className="h-3.5 w-3.5 flex-shrink-0" />
        No live dataset used on this page
      </div>
    );
  }

  // ── Historical / dataset pages ──────────────────────────────────────────
  if (variant === "historical") {
    return (
      <div
        data-testid="data-freshness-bar"
        className={`rounded-md border border-border/60 bg-card/40 px-3 py-1.5 text-xs font-mono text-muted-foreground ${className}`}
      >
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left"
          data-testid="button-freshness-toggle"
        >
          <span className="flex items-center gap-1.5">
            <Database className="h-3.5 w-3.5 flex-shrink-0 text-sky-400" />
            <span className="text-sky-400">HISTORICAL</span>
          </span>
          <span>{datasetLabel ?? "Dataset"}</span>
          <span>Updated: {istDateTime(lastUpdated)}</span>
          {latestRecord ? <span>Latest: {latestRecord}</span> : null}
          {sampleSize ? <span>Sample: {sampleSize}</span> : null}
          {open ? <ChevronUp className="ml-auto h-3.5 w-3.5" /> : <ChevronDown className="ml-auto h-3.5 w-3.5" />}
        </button>
        {open && (
          <div className="mt-2 space-y-1 border-t border-border/40 pt-2">
            <div>Dataset: {datasetLabel ?? "Historical dataset"}</div>
            <div>Last updated: {istDateTime(lastUpdated)}</div>
            <div>Latest included record: {latestRecord ?? "—"}</div>
            <div>Sample size: {sampleSize ?? "—"}</div>
            <div className="text-muted-foreground/70">
              Historical analysis — not live market data. Paper trading / research only.
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Live scan / quote pages ─────────────────────────────────────────────
  const st = staleness.data;
  const meta = scanStatus.data?.latest_scan ?? null;
  const loading = staleness.isLoading || scanStatus.isLoading;

  const failed = meta?.status === "FAILED";
  const stale = st?.stale === true;

  const dataStatus = deriveDataStatus(loading, failed, stale, meta, st);
  const statusColorCls = DATA_STATUS_COLOR[dataStatus];

  // Keep STALE/FAILED strings visible for stale-data protection logic
  // and downstream test assertions (freshness-coverage.test.ts).
  const legacyStatusText = loading
    ? "LOADING"
    : failed
      ? "FAILED"
      : stale
        ? "STALE"
        : "FRESH";

  const StatusIcon =
    dataStatus === "UNAVAILABLE" ? WifiOff
    : dataStatus === "MARKET_CLOSED" ? Clock
    : dataStatus === "STALE" || dataStatus === "DELAYED" || dataStatus === "CACHED" ? AlertTriangle
    : CheckCircle2;

  // Market-hours coverage warning: a weekend data gap (e.g. 48/50) is
  // expected to self-resolve at Monday open — if coverage is still below
  // the expected universe DURING today's session (incl. pre-open, holiday
  // aware), the server verdict flags it. Rendered verbatim from the server.
  const cov = coverage.data;
  const coverageWarning = !loading && cov?.ok === false && !!cov?.warning;

  const scanTs = meta?.completed_at ?? st?.last_scan_time;
  const provider = quoteProvider ?? meta?.provider ?? "yfinance";
  // Source label: "yfinance / NSE" style
  const sourceLabel = provider && provider !== "—" ? `${provider} / NSE` : "NSE";
  const shortId = meta?.scan_id ? meta.scan_id.slice(0, 8) : "—";

  return (
    <div
      data-testid="data-freshness-bar"
      className={`rounded-md border px-3 py-1.5 text-xs font-mono ${
        dataStatus === "UNAVAILABLE"
          ? "border-red-500/40 bg-red-500/10"
          : dataStatus === "STALE" || dataStatus === "CACHED"
            ? "border-warn bg-warn-surface"
            : dataStatus === "DELAYED"
              ? "border-warn/60 bg-warn-surface/60"
              : dataStatus === "MARKET_CLOSED"
                ? "border-slate-500/40 bg-slate-500/10"
                : "border-border/60 bg-card/40"
      } ${className}`}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left text-muted-foreground"
        data-testid="button-freshness-toggle"
      >
        {/* Canonical status badge with connection dot */}
        <span className={`flex items-center gap-1.5 ${statusColorCls}`}>
          {loading
            ? <StatusIcon className="h-3.5 w-3.5 flex-shrink-0 animate-pulse" />
            : <ConnectionDot status={dataStatus} />}
          {loading ? "Loading…" : dataStatus}
        </span>

        {/* Source name */}
        <span className="flex items-center gap-1 text-muted-foreground/70">
          <Database className="h-3 w-3" />
          {sourceLabel}
        </span>

        {/* Last update age (human-readable) */}
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {st?.scan_age_seconds != null
            ? ageLabel(st.scan_age_seconds)
            : scanTs
              ? `Scan: ${istTime(scanTs)}`
              : "—"}
        </span>

        {variant === "quotes" && (
          <span>Quotes: {istTime(quoteTimestamp ?? meta?.updated_at)}</span>
        )}

        <span>ID: {shortId}</span>
        {open ? <ChevronUp className="ml-auto h-3.5 w-3.5" /> : <ChevronDown className="ml-auto h-3.5 w-3.5" />}
      </button>

      {coverageWarning && (
        <div
          data-testid="warning-market-hours-coverage"
          className="mt-1.5 flex items-start gap-1.5 rounded border border-warn/60 bg-warn-surface px-2 py-1 text-warn"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
          <span>{cov?.warning}</span>
        </div>
      )}

      {open && (
        <div className="mt-2 space-y-1 border-t border-border/40 pt-2 text-muted-foreground">
          {/* Internal status preserved for stale-data protection */}
          <div>Status: {legacyStatusText}{meta?.error ? ` — ${meta.error}` : ""} · Scan: {meta?.status ?? "—"}</div>
          <div>Scan ID: {meta?.scan_id ?? "—"}</div>
          <div>Started: {istDateTime(meta?.started_at)}</div>
          <div>Completed: {istDateTime(meta?.completed_at)}</div>
          <div>Snapshot: {istDateTime(meta?.snapshot_ts)}</div>
          <div>Source: {sourceLabel} (provider: {provider})</div>
          <div>
            Coverage: {meta?.symbols_received ?? "—"}/{meta?.symbols_requested ?? "—"} symbols
            {meta?.symbols_missing ? ` · ${meta.symbols_missing} unavailable` : ""}
            {meta?.symbols_stale ? ` · ${meta.symbols_stale} STALE` : ""}
          </div>
          {meta?.missing_symbols?.length ? (
            <div>Unavailable: {meta.missing_symbols.join(", ")}</div>
          ) : null}
          {stale && st?.warning ? (
            <div className="text-warn">{st.warning}</div>
          ) : null}
          {st?.buy_recommendations_disabled ? (
            <div className="text-warn">BUY recommendations disabled until data is fresh.</div>
          ) : null}
          <div className="text-muted-foreground/70">{st?.label ?? "PAPER / RESEARCH ONLY"}</div>
        </div>
      )}
    </div>
  );
}
