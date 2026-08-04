import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

// API base URL chain (in priority order):
//   1. EXPO_PUBLIC_API_BASE_URL  — explicit full URL (recommended for production)
//   2. EXPO_PUBLIC_DOMAIN        — Replit dev domain (auto-set in package.json dev script)
//   3. /api                      — relative fallback
//
// A production build whose resolved URL contains localhost throws a
// ConfigurationError at startup (enforced in lib/apiConfig.ts).
import { API_BASE_URL } from "./apiConfig";
/** @deprecated Use API_BASE_URL from lib/apiConfig instead. */
export const BASE: string = API_BASE_URL;

// Per-request fetch timeout (ms) for standard data endpoints.
// NOTE: The mobile Scan button (signals tab) calls useRunScan which uses
// customFetch — that path has no AbortController timeout, so scans that
// take 30–90 s will complete without being aborted.  This constant applies
// only to the apiJson() calls in this file (health probes, settings, etc).
const FETCH_TIMEOUT_MS = 15_000;

// React Query hook defaults (applied per-hook where relevant):
//   retry: 1        — one automatic retry on transient network failures
//   refetchInterval: 60_000  — most health/status data refreshed every 60 s
//   refetchInterval: 120_000 — slower-changing data (broker/kite) refreshed every 2 min
// These values are intentionally conservative to avoid hammering the API during
// market hours while still surfacing stale data within an operator-acceptable window.

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError(`Request timed out after ${FETCH_TIMEOUT_MS / 1000}s`, 408);
    }
    throw err;
  }
  clearTimeout(timeoutId);
  const text = await res.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new ApiError(`Non-JSON response (${res.status})`, res.status);
    }
  }
  if (!res.ok) {
    const msg =
      typeof data === "object" && data !== null && "error" in data
        ? String((data as { error: unknown }).error)
        : `Request failed (${res.status})`;
    throw new ApiError(msg, res.status);
  }
  return data as T;
}

// ---------- Types (normalized) ----------

export interface LiveDataHealth {
  marketState: string;
  marketLabel?: string;
  provider?: string;
  circuitBreaker: string;
  consecutiveFailures: number;
  lastSuccessTs?: string | null;
  totalFetches?: number;
  totalErrors?: number;
  lastScanTs?: string | null;
  connectionStatus?: string;
  qualitySummary?: Record<string, number>;
  avgLatencyMs?: number;
}

export interface Phase20Settings {
  auto_scan_enabled?: boolean;
  scan_interval_minutes?: number;
  auto_paper_entries?: boolean;
  auto_paper_exits?: boolean;
  min_confidence?: number;
  max_trades_per_day?: number;
  [key: string]: unknown;
}

export interface SchedulerHealth {
  status?: string;
  detail?: string;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  next_due_at?: string | null;
  missed_count?: number;
  [key: string]: unknown;
}

export interface MonitorNotification {
  id: string;
  ts?: string;
  type?: string;
  severity?: string;
  title?: string;
  message?: string;
  read?: boolean;
}

export interface Phase20Position {
  symbol?: string;
  entry_ts?: string;
  qty?: number;
  quantity?: number;
  entry_price?: number;
  current_price?: number;
  pnl?: number;
  pnl_pct?: number;
  status?: string;
  stop_loss?: number;
  target?: number;
  [key: string]: unknown;
}

export interface Phase20Positions {
  positions: Phase20Position[];
  summary: { total_pnl: number; open_count: number };
}

export interface KiteStatus {
  provider?: string;
  credentials_present?: boolean;
  token_status?: string;
  token_age_hours?: number | null;
  token_expiry_note?: string;
  [key: string]: unknown;
}

export interface RiskKillSwitch {
  active?: boolean;
  triggered_at?: string | null;
  reason?: string | null;
}

export interface BrokerStatus {
  execution_mode?: string;
  broker?: {
    connected?: boolean;
    broker?: string;
    user_id?: string;
    token_status?: string;
    is_mock?: boolean;
    note?: string;
  };
  safety_controls?: { kill_switch?: boolean; [key: string]: unknown };
}

// ---------- AI Operations Centre types ----------

export interface AgentState {
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

export interface OpsSnapshot {
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
  pipeline_nodes: Array<{
    id: string;
    label: string;
    agent_key: string;
    status: string;
    health_pct: number;
    stocks_out: number;
  }>;
  agents: Record<string, AgentState>;
}

// The ops-centre snapshot aggregates 12 agents and typically takes 30–40 s.
// We use a custom fetch with a 60 s timeout instead of the default 15 s apiJson.
async function fetchOpsSnapshot(): Promise<OpsSnapshot> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60_000);
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/ops-centre/snapshot`, {
      signal: controller.signal,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === "AbortError") {
      throw new ApiError("Ops snapshot timed out after 60 s", 408);
    }
    throw err;
  }
  clearTimeout(timeoutId);
  const text = await res.text();
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const d = JSON.parse(text) as Record<string, unknown>;
      if (d.error) msg = String(d.error);
    } catch { /* ignore */ }
    throw new ApiError(msg, res.status);
  }
  return JSON.parse(text) as OpsSnapshot;
}

export function useOpsSnapshot() {
  return useQuery({
    queryKey: ["ops-centre", "snapshot"],
    queryFn: fetchOpsSnapshot,
    refetchInterval: 30_000,
    retry: 1,
    staleTime: 20_000,
  });
}

// ---------- Hooks ----------

export function useLiveDataHealth() {
  return useQuery({
    queryKey: ["monitor", "live-data-health-v2"],
    queryFn: async (): Promise<LiveDataHealth> => {
      const raw = await apiJson<{
        market?: { state?: string; label?: string };
        quote_provider?: {
          provider?: string;
          circuit_breaker?: string;
          consecutive_failures?: number;
          last_success_ts?: string | null;
          total_fetches?: number;
          total_errors?: number;
        };
        scan_provider_health?: {
          snapshot_ts?: string | null;
          connection_status?: string;
          quality_summary?: Record<string, number>;
          avg_latency_ms?: number;
        };
      }>("/live-data/health-v2");
      const qp = raw.quote_provider;
      const sp = raw.scan_provider_health;
      return {
        marketState: raw.market?.state ?? "UNKNOWN",
        marketLabel: raw.market?.label,
        provider: qp?.provider,
        circuitBreaker: qp?.circuit_breaker ?? "UNKNOWN",
        consecutiveFailures: qp?.consecutive_failures ?? 0,
        lastSuccessTs: qp?.last_success_ts,
        totalFetches: qp?.total_fetches,
        totalErrors: qp?.total_errors,
        lastScanTs: sp?.snapshot_ts,
        connectionStatus: sp?.connection_status,
        qualitySummary: sp?.quality_summary,
        avgLatencyMs: sp?.avg_latency_ms,
      };
    },
    refetchInterval: 60_000,
  });
}

export function usePhase20Settings() {
  return useQuery({
    queryKey: ["monitor", "phase20-settings"],
    queryFn: async (): Promise<Phase20Settings> => {
      const raw = await apiJson<{ settings?: Phase20Settings }>("/phase20/settings");
      return raw.settings ?? {};
    },
  });
}

export function useDisableAutoPaperEntries() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson("/phase20/settings", {
        method: "PUT",
        body: JSON.stringify({ patch: { auto_paper_entries: false } }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["monitor", "phase20-settings"] });
    },
  });
}

export function useSchedulerHealth() {
  return useQuery({
    queryKey: ["monitor", "scheduler-health"],
    queryFn: async (): Promise<SchedulerHealth> => {
      const raw = await apiJson<{ scheduler?: SchedulerHealth }>("/phase20/scheduler/health");
      return raw.scheduler ?? {};
    },
    refetchInterval: 60_000,
  });
}

export function useNotifications() {
  return useQuery({
    queryKey: ["monitor", "notifications"],
    queryFn: async (): Promise<MonitorNotification[]> => {
      const raw = await apiJson<{
        notifications?: {
          id?: number | string;
          kind?: string;
          severity?: string;
          title?: string;
          body?: string;
          created_at?: string;
          read?: boolean;
        }[];
      }>("/phase20/notifications?limit=100");
      return (raw.notifications ?? []).map((n) => ({
        id: String(n.id ?? ""),
        ts: n.created_at,
        type: n.kind,
        severity: n.severity,
        title: n.title,
        message: n.body,
        read: n.read,
      }));
    },
    refetchInterval: 60_000,
  });
}

export function useMarkNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids: string[] | null) =>
      apiJson("/phase20/notifications/read", {
        method: "POST",
        body: JSON.stringify({ ids: ids ? ids.map((i) => Number(i)) : null }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["monitor", "notifications"] });
    },
  });
}

export function usePhase20Positions() {
  return useQuery({
    queryKey: ["monitor", "phase20-positions"],
    queryFn: async (): Promise<Phase20Positions> => {
      const raw = await apiJson<{ positions?: Phase20Position[] }>("/phase20/positions");
      const positions = Array.isArray(raw.positions) ? raw.positions : [];
      const total_pnl = positions.reduce((sum, p) => sum + (typeof p.pnl === "number" ? p.pnl : 0), 0);
      return { positions, summary: { total_pnl, open_count: positions.length } };
    },
    refetchInterval: 60_000,
  });
}

export function useKiteStatus() {
  return useQuery({
    queryKey: ["monitor", "kite-status"],
    queryFn: () => apiJson<KiteStatus>("/kite/status"),
    refetchInterval: 120_000,
  });
}

export function useRiskKillSwitch() {
  return useQuery({
    queryKey: ["monitor", "risk-kill-switch"],
    queryFn: async (): Promise<RiskKillSwitch> => {
      const raw = await apiJson<{ kill_switch?: RiskKillSwitch }>("/risk/kill-switch");
      return raw.kill_switch ?? {};
    },
    refetchInterval: 60_000,
  });
}

export function useWatchlist() {
  return useQuery({
    queryKey: ["monitor", "watchlist"],
    queryFn: async (): Promise<string[]> => {
      const raw = await apiJson<{ watchlist?: string[] }>("/watchlist");
      return Array.isArray(raw.watchlist) ? raw.watchlist : [];
    },
  });
}

export function useAddWatchlistSymbol() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) =>
      apiJson("/watchlist", {
        method: "POST",
        body: JSON.stringify({ symbol: symbol.trim().toUpperCase() }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["monitor", "watchlist"] });
    },
  });
}

export function useRemoveWatchlistSymbol() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) =>
      apiJson(`/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["monitor", "watchlist"] });
    },
  });
}

export function useBrokerStatus() {
  return useQuery({
    queryKey: ["monitor", "broker-status"],
    queryFn: () => apiJson<BrokerStatus>("/broker/status"),
    refetchInterval: 120_000,
  });
}
