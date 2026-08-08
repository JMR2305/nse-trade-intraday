/**
 * Widget.tsx — Phase 25A Mission Control widget framework.
 *
 * Every Mission Control panel is wrapped in <Widget>, which renders a common
 * chrome (title, live/stale pill, last-updated timestamp) and handles the
 * three data states honestly:
 *   - loading  → skeleton pulse
 *   - error    → inline error with the message (widget never blanks the page)
 *   - data     → children render; a stale pill appears when the data is older
 *                than 2× its refresh cadence.
 *
 * Each widget owns its own React Query (own key, own refresh cadence, own
 * timeout) via useWidgetQuery, so one slow endpoint never blocks the others.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { AlertTriangle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

// ── Query hook ────────────────────────────────────────────────────────────────

export interface WidgetQueryOpts {
  /** Unique query key parts, e.g. ["mc", "scan-status"] */
  queryKey: (string | number | null)[];
  /** API path relative to API_BASE (no /api prefix — apiJson prepends it) */
  path: string;
  /** Refresh cadence in ms */
  refetchInterval: number;
  /** Explicit request timeout (slow aggregate endpoints need > 15 s default) */
  timeoutMs?: number;
  enabled?: boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function useWidgetQuery<T = any>(opts: WidgetQueryOpts): UseQueryResult<T> {
  return useQuery<T>({
    queryKey: opts.queryKey,
    queryFn: () => apiJson<T>(opts.path, undefined, opts.timeoutMs),
    refetchInterval: opts.refetchInterval,
    retry: 2,
    retryDelay: (attempt: number) => Math.min(1500 * 2 ** attempt, 10_000),
    staleTime: Math.min(opts.refetchInterval / 2, 15_000),
    enabled: opts.enabled ?? true,
  });
}

// ── Last-updated / staleness pill ─────────────────────────────────────────────

function UpdatedPill({ dataUpdatedAt, staleAfterMs }: { dataUpdatedAt: number; staleAfterMs: number }) {
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1_000);
    return () => clearInterval(id);
  }, []);
  if (!dataUpdatedAt) return null;
  const age = Math.max(0, Date.now() - dataUpdatedAt);
  const secs = Math.round(age / 1000);
  const label = secs < 60 ? `${secs}s` : `${Math.round(secs / 60)}m`;
  const stale = age > staleAfterMs;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-medium border ${
        stale
          ? "bg-amber-950/60 border-amber-700/40 text-amber-300"
          : "bg-emerald-950/60 border-emerald-700/40 text-emerald-300"
      }`}
      title={stale ? "Data is older than expected — endpoint may be slow" : "Fresh data"}
    >
      <span className={`w-1 h-1 rounded-full inline-block ${stale ? "bg-amber-400" : "bg-emerald-400 animate-pulse"}`} />
      {stale ? "Stale" : "Live"} · {label}
    </span>
  );
}

// ── Widget chrome ─────────────────────────────────────────────────────────────

export interface WidgetProps {
  title: string;
  icon: LucideIcon;
  /** The query that drives this widget (for state + last-updated) */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  query: UseQueryResult<any>;
  /** Refresh cadence — stale threshold is 2× this */
  refreshMs: number;
  /** Extra header content (badges, counts) */
  headerExtra?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
  /** Skeleton height while loading */
  skeletonClass?: string;
}

export function Widget({
  title, icon: Icon, query, refreshMs, headerExtra, children, className = "", testId, skeletonClass = "h-32",
}: WidgetProps) {
  return (
    <div className={`bg-card border border-border rounded-xl p-3 flex flex-col min-w-0 ${className}`} data-testid={testId}>
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <Icon className="w-3.5 h-3.5 text-teal-400 shrink-0" />
        <h2 className="text-[11px] font-semibold tracking-wide uppercase text-muted-foreground">{title}</h2>
        {headerExtra}
        <span className="ml-auto">
          <UpdatedPill dataUpdatedAt={query.dataUpdatedAt} staleAfterMs={refreshMs * 2} />
        </span>
      </div>
      {query.isLoading ? (
        <div className={`animate-pulse rounded-lg bg-muted/30 ${skeletonClass}`} />
      ) : query.isError ? (
        <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/5 border border-red-500/20 rounded-lg p-2.5">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium">Failed to load</p>
            <p className="text-red-400/70 break-words">{(query.error as Error)?.message ?? "Unknown error"}</p>
          </div>
        </div>
      ) : (
        <div className="min-w-0 flex-1">{children}</div>
      )}
    </div>
  );
}

// ── Small shared bits ─────────────────────────────────────────────────────────

export function fmtINR(v: unknown, digits = 0): string {
  const n = typeof v === "number" ? v : null;
  if (n === null || !isFinite(n)) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: digits });
}

export function timeAgo(ts: string | null | undefined): string {
  if (!ts) return "—";
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${(s / 3600).toFixed(1)}h ago`;
}

export function PnlText({ value, digits = 0, className = "" }: { value: number | null | undefined; digits?: number; className?: string }) {
  const v = typeof value === "number" && isFinite(value) ? value : null;
  if (v === null) return <span className={`text-muted-foreground ${className}`}>—</span>;
  return (
    <span className={`${v >= 0 ? "text-emerald-400" : "text-red-400"} ${className}`}>
      {v >= 0 ? "+" : ""}{fmtINR(v, digits)}
    </span>
  );
}
