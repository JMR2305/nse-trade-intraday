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
} from "lucide-react";

// ── Phase 19C — DataFreshnessBar ──────────────────────────────────────────────
// One reusable freshness indicator rendered near the top of every data-driven
// page. All values come from backend metadata (canonical durable scan state +
// staleness engine) — never from browser time. Paper trading / research only.

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

export const STALENESS_QUERY_KEY = ["/api/phase15/staleness"];
export const SCAN_STATUS_QUERY_KEY = ["/api/live-data/scan/status"];

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
  return { staleness, scanStatus };
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
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
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
  const { staleness, scanStatus } = useFreshness(isLive);

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
  const statusText = loading
    ? "LOADING"
    : failed
      ? "FAILED"
      : stale
        ? "STALE"
        : "FRESH";
  const statusColor = loading
    ? "text-muted-foreground"
    : failed
      ? "text-red-400"
      : stale
        ? "text-warn"
        : "text-emerald-400";
  const StatusIcon = failed || stale ? AlertTriangle : CheckCircle2;

  const scanTs = meta?.completed_at ?? st?.last_scan_time;
  const provider = quoteProvider ?? meta?.provider ?? "—";
  const shortId = meta?.scan_id ? meta.scan_id.slice(0, 8) : "—";

  return (
    <div
      data-testid="data-freshness-bar"
      className={`rounded-md border px-3 py-1.5 text-xs font-mono ${
        failed
          ? "border-red-500/40 bg-red-500/10"
          : stale
            ? "border-warn bg-warn-surface"
            : "border-border/60 bg-card/40"
      } ${className}`}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left text-muted-foreground"
        data-testid="button-freshness-toggle"
      >
        <span className={`flex items-center gap-1.5 ${statusColor}`}>
          <StatusIcon className="h-3.5 w-3.5 flex-shrink-0" />
          Data: {statusText}
        </span>
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" /> Scan: {istTime(scanTs)}
        </span>
        {variant === "quotes" && (
          <span>Quotes: {istTime(quoteTimestamp ?? meta?.updated_at)}</span>
        )}
        <span>Age: {ageLabel(st?.scan_age_seconds)}</span>
        <span>ID: {shortId}</span>
        {open ? <ChevronUp className="ml-auto h-3.5 w-3.5" /> : <ChevronDown className="ml-auto h-3.5 w-3.5" />}
      </button>

      {open && (
        <div className="mt-2 space-y-1 border-t border-border/40 pt-2 text-muted-foreground">
          <div>Scan ID: {meta?.scan_id ?? "—"}</div>
          <div>Status: {meta?.status ?? "—"}{meta?.error ? ` — ${meta.error}` : ""}</div>
          <div>Started: {istDateTime(meta?.started_at)}</div>
          <div>Completed: {istDateTime(meta?.completed_at)}</div>
          <div>Snapshot: {istDateTime(meta?.snapshot_ts)}</div>
          <div>Provider: {provider}</div>
          <div>
            Coverage: {meta?.symbols_received ?? "—"}/{meta?.symbols_requested ?? "—"} symbols
            {meta?.symbols_missing ? ` · ${meta.symbols_missing} unavailable` : ""}
            {meta?.symbols_stale ? ` · ${meta.symbols_stale} stale` : ""}
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
