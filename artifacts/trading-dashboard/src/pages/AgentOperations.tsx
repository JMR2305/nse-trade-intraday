/**
 * AgentOperations.tsx — Phase 10A
 * Agent Operations Dashboard
 *
 * Displays all registered agents, supervisor health, snapshot bus stats,
 * scalability estimates, and per-agent metrics.
 *
 * READ-ONLY · ADVISORY-ONLY
 * No orders, no portfolio modification, no agent restart from this page.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  Bot, Activity, Radio, CheckCircle2, Zap, Database, BookOpen, Gauge, RefreshCw, X,
} from "lucide-react";
import {
  PageHeader, SectionHeader, StatusBadge, KpiCard, HealthCard,
  MetricTile, AlertCard, EmptyState, KpiCardSkeleton, CardSkeleton, TableSkeleton,
  StatCard, DataTable, SectionHeader as SH,
} from "@/components/ds";
import type { TableColumn } from "@/components/ds/DataTable";
import { scoreColor } from "@/lib/designTokens";

// ── Query helpers ──────────────────────────────────────────────────────────────
const REFETCH = 30_000;
const q = (path: string) => ({
  queryKey:  ["agent-fw", path],
  queryFn:   () => apiJson("agent-framework/" + path),
  refetchInterval: REFETCH,
  retry: 1,
  staleTime: 15_000,
});

// ── Agent state colour ─────────────────────────────────────────────────────────
const STATE_COLOR: Record<string, string> = {
  RUNNING:      "text-emerald-400",
  IDLE:         "text-teal-400",
  BUSY:         "text-blue-400",
  PAUSED:       "text-amber-400",
  WARNING:      "text-amber-400",
  ERROR:        "text-red-400",
  STOPPED:      "text-slate-400",
  INITIALIZING: "text-slate-300",
  STARTING:     "text-slate-300",
};

const HB_COLOR: Record<string, string> = {
  OK:      "text-emerald-400",
  LATE:    "text-amber-400",
  MISSED:  "text-orange-400",
  STALLED: "text-red-400",
  NEVER:   "text-slate-400",
};

// ── Agent table columns ────────────────────────────────────────────────────────
type AgentRow = {
  agent_id:            string;
  name:                string;
  state:               string;
  health_score:        number;
  heartbeat_status:    string;
  heartbeat_elapsed_s: number | null;
  queue_depth:         number;
  processing_time_ms:  number;
  snapshots_published: number;
  snapshots_consumed:  number;
  dependencies:        string[];
  last_heartbeat:      string | null;
  version:             string;
  priority:            number;
  [key: string]:       unknown;
};

const AGENT_COLUMNS: TableColumn<AgentRow>[] = [
  {
    key: "name", label: "Agent", sortable: true,
    render: (_v, row) => (
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
          row.state === "RUNNING" || row.state === "IDLE" ? "bg-emerald-400" :
          row.state === "ERROR" ? "bg-red-500" : "bg-amber-400"
        }`} />
        <span className="font-medium text-sm">{row.name}</span>
      </div>
    ),
  },
  {
    key: "state", label: "State", sortable: true,
    render: (_v, row) => (
      <span className={`text-xs font-semibold ${STATE_COLOR[row.state] ?? "text-slate-400"}`}>
        {row.state}
      </span>
    ),
  },
  {
    key: "health_score", label: "Health", sortable: true,
    render: (_v, row) => (
      <div className="flex items-center gap-1.5">
        <span className={`text-sm font-bold ${scoreColor(row.health_score)}`}>
          {row.health_score.toFixed(0)}
        </span>
        <span className="text-xs text-muted-foreground">/100</span>
      </div>
    ),
  },
  {
    key: "heartbeat_status", label: "Heartbeat", sortable: true,
    render: (_v, row) => (
      <div className="flex flex-col">
        <span className={`text-xs font-medium ${HB_COLOR[row.heartbeat_status] ?? ""}`}>
          {row.heartbeat_status}
        </span>
        {row.heartbeat_elapsed_s != null && (
          <span className="text-xs text-muted-foreground">
            {((row.heartbeat_elapsed_s ?? 0) as number).toFixed(0)}s ago
          </span>
        )}
      </div>
    ),
  },
  {
    key: "queue_depth", label: "Queue", sortable: true,
    render: (_v, row) => <span className="text-sm">{row.queue_depth}</span>,
  },
  {
    key: "processing_time_ms", label: "Latency", sortable: true,
    render: (_v, row) => (
      <span className={`text-sm ${row.processing_time_ms > 5000 ? "text-amber-400" : ""}`}>
        {(row.processing_time_ms ?? 0).toFixed(0)} ms
      </span>
    ),
  },
  {
    key: "snapshots_published", label: "Published", sortable: true,
    render: (_v, row) => (
      <span className="text-sm text-teal-400">{row.snapshots_published}</span>
    ),
  },
  {
    key: "dependencies", label: "Deps",
    render: (_v, row) => {
      const deps = row.dependencies as string[];
      return deps.length === 0
        ? <span className="text-xs text-muted-foreground">None</span>
        : <span className="text-xs">{deps.join(", ")}</span>;
    },
  },
];

// ── Supervisor summary strip ───────────────────────────────────────────────────
function SupervisorSummary({ snap }: { snap: any }) {
  if (!snap?.available) return null;
  const fw  = snap.framework_metrics ?? {};
  const hb  = snap.heartbeat_summary ?? {};
  const bus = snap.snapshot_bus ?? {};

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
      <MetricTile label="Agents"     value={fw.agent_count ?? 0} />
      <MetricTile label="Active"     value={fw.active_agents ?? 0}  color="text-emerald-400" />
      <MetricTile label="Warnings"   value={fw.warning_agents ?? 0} color={(fw.warning_agents ?? 0) > 0 ? "text-amber-400" : undefined} />
      <MetricTile label="Errors"     value={fw.error_agents ?? 0}   color={(fw.error_agents ?? 0) > 0 ? "text-red-400" : undefined} />
      <MetricTile label="HB OK"      value={hb.ok ?? 0}             color="text-emerald-400" />
      <MetricTile label="HB Missed"  value={hb.missed ?? 0}         color={(hb.missed ?? 0) > 0 ? "text-red-400" : undefined} />
      <MetricTile label="Snapshots"  value={fw.total_snapshots_published ?? 0} color="text-teal-400" />
      <MetricTile label="Bus Topics" value={bus.topic_count ?? 0} />
    </div>
  );
}

// ── Overall health card ────────────────────────────────────────────────────────
function OverallHealthCard({ health }: { health: any }) {
  if (!health) return null;
  const score  = health.score ?? 0;
  const rawStatus = (health.status ?? "UNKNOWN").toLowerCase() as
    "healthy" | "degraded" | "critical" | "unknown" | "disabled";
  const details = [
    `Critical: ${health.critical_agents ?? 0}`,
    `Warning: ${health.warning_agents ?? 0}`,
  ].join(" · ");
  return (
    <HealthCard
      label="Agent Framework Health"
      score={score}
      status={rawStatus}
      details={details}
    />
  );
}

// ── Supervisor alerts panel ────────────────────────────────────────────────────
function AlertsPanel({ alerts }: { alerts: any[] }) {
  if (!alerts?.length) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="No active alerts"
        description="All agents are operating normally."
      />
    );
  }
  return (
    <div className="space-y-2">
      {alerts.slice(0, 10).map((a: any, i: number) => (
        <AlertCard
          key={i}
          severity={a.severity?.toLowerCase() as
            "critical" | "high" | "medium" | "low" | "info" | "success"}
          title={a.title}
          body={a.recommendation ? `${a.body ?? ""} — ${a.recommendation}` : a.body}
          timestamp={a.generated_at}
        />
      ))}
    </div>
  );
}

// ── Scalability estimator ─────────────────────────────────────────────────────
function ScalabilityPanel({ snap }: { snap: any }) {
  if (!snap?.available) return null;
  const util = snap.utilisation_pct ?? 0;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <StatCard label="Monitored Symbols" value={snap.current_monitored_symbols ?? 0} />
      <StatCard label="Safe Capacity"     value={snap.safe_capacity_symbols ?? 0} />
      <StatCard label="Max Capacity"      value={snap.estimated_max_capacity ?? 0} />
      <StatCard
        label="Utilisation"
        value={`${(util as number).toFixed(1)}%`}
        changeLabel={util > 80 ? "High" : util > 60 ? "Medium" : "Low"}
      />
      <StatCard label="Current Agents"    value={snap.current_agent_count ?? 0} />
      <StatCard label="Future Agents"     value={snap.future_agents_supported ?? 0} />
      <StatCard label="Scan Interval"     value={`${snap.current_scan_interval_s ?? 0}s`} />
      <StatCard label="Rec. Interval"     value={`${snap.recommended_scan_interval_s ?? 0}s`} />
    </div>
  );
}

// ── Snapshot info card ────────────────────────────────────────────────────────
function SnapshotInfoCard({ title, icon: Icon, data, fields }: {
  title: string;
  icon: any;
  data: any;
  fields: { label: string; key: string; color?: string }[];
}) {
  if (!data?.available) {
    return (
      <div className="bg-card border border-border rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Icon className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm font-medium">{title}</span>
          <StatusBadge variant="offline" size="sm" />
        </div>
        <p className="text-xs text-muted-foreground">{data?.message ?? "Feature disabled or unavailable."}</p>
      </div>
    );
  }
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-teal-400" />
          <span className="text-sm font-medium">{title}</span>
          <StatusBadge variant="live" size="sm" />
        </div>
        {data.generated_at && (
          <span className="text-xs text-muted-foreground">
            {String(data.generated_at).slice(11, 19)} UTC
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {fields.map(({ label, key, color }) => {
          const val = data[key];
          return (
            <div key={key} className="bg-muted/30 rounded p-2">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className={`text-sm font-semibold ${color ?? ""}`}>
                {val == null ? "—" : typeof val === "number" ? (val as number).toFixed(1) : String(val)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Agent registry table ──────────────────────────────────────────────────────
export function AgentDetailPanel({ agentId, onClose }: {
  agentId: string;
  onClose: () => void;
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["agent-fw", "agent-detail", agentId],
    queryFn: () => apiJson(`agent-framework/agents/${encodeURIComponent(agentId)}`, undefined, 30_000),
    refetchInterval: 5_000,
    retry: 1,
    staleTime: 0,
  });
  const detail = data as Record<string, any> | undefined;
  const isRecoverable = detail?.recoverable === true || detail?.status === "INITIALIZING";
  const isStale = detail?.stale === true;

  return (
    <div
      className="mt-3 rounded-xl border border-border bg-card p-4"
      data-testid="agent-detail-panel"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Agent detail</p>
          <h3 className="text-base font-semibold">{detail?.name ?? agentId}</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close agent detail"
          className="rounded-md p-1 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <RefreshCw className="h-4 w-4 animate-spin" />
          Loading agent details…
        </div>
      )}

      {(isError || isRecoverable) && (
        <div
          className={`rounded-lg border p-3 ${
            isStale
              ? "border-orange-500/30 bg-orange-500/5"
              : "border-amber-500/25 bg-amber-500/5"
          }`}
          data-testid={isStale ? "agent-detail-stale" : "agent-detail-recoverable"}
          role="status"
        >
          <div className={`flex items-center gap-2 text-sm font-medium ${
            isStale ? "text-orange-300" : "text-amber-300"
          }`}>
            <RefreshCw className="h-4 w-4 animate-spin" />
            {isStale ? "Agent details are stale — retrying" : "Agent details are retrying"}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {detail?.message ?? (error as Error)?.message ??
              "The Agent Framework is still initialising this agent. Retrying automatically."}
          </p>
        </div>
      )}

      {!isLoading && !isError && detail?.available && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            ["State", detail.state],
            ["Health", detail.health_status ?? detail.health_score],
            ["Heartbeat", detail.heartbeat_status],
            ["Queue", detail.queue_depth],
            ["Last heartbeat", detail.last_heartbeat],
            ["Latest snapshot", detail.latest_snapshot_ts],
            ["Published", detail.snapshots_published],
            ["Dependencies", Array.isArray(detail.dependencies) ? detail.dependencies.join(", ") || "None" : detail.dependencies],
          ].map(([label, value]) => (
            <div key={label} className="rounded bg-muted/30 p-2">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="truncate text-sm font-semibold">{value == null ? "—" : String(value)}</p>
            </div>
          ))}
        </div>
      )}

      {!isLoading && !isError && !isRecoverable && detail && !detail.available && (
        <p className="text-sm text-muted-foreground" role="status">
          {detail.message ?? "Agent detail is unavailable."}
        </p>
      )}
    </div>
  );
}

function AgentRegistryTable() {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  // The canonical agent_list backend calls 12 agents in parallel — cold-start ~25 s.
  // Without an explicit timeout, apiJson's 15 s default kills the first call.
  const { data, isLoading, isError, error } = useQuery({
    queryKey:        ["agent-fw", "agents"],
    queryFn:         () => apiJson("agent-framework/agents", undefined, 45_000),
    refetchInterval: REFETCH,
    retry: 2,
    retryDelay:      (n) => Math.min(2000 * 2 ** n, 10_000),
    staleTime: 15_000,
  });
  const r      = data as any;
  const agents = (r?.agents ?? []) as AgentRow[];

  if (isLoading) return <TableSkeleton rows={4} cols={6} />;

  if (isError || (r?.recoverable && agents.length === 0)) {
    return (
      <EmptyState
        icon={Bot}
        title="Agent status temporarily unavailable"
        description={r?.message ?? (error as Error)?.message ?? "The Agent Framework is starting up. This page will retry automatically."}
        why="The live scanner remains available while agent status recovers."
        actions={[]}
      />
    );
  }

  if (!r?.available || agents.length === 0) {
    return (
      <EmptyState
        icon={Bot}
        title="No agents registered"
        description="The Agent Framework is starting up or no agents have been initialised."
        why="Feature flags must be set to true."
        actions={[]}
      />
    );
  }

  return (
    <>
      {r?.recoverable && (
        <p
          className="text-xs text-amber-300/90 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 mb-3"
          data-testid="agent-registry-recoverable"
          role="status"
        >
          {r.message ?? "Showing the last known agent state while the Agent Framework recovers. Retrying automatically."}
        </p>
      )}
      <DataTable
        columns={AGENT_COLUMNS}
        data={agents}
        rowKey={(row: AgentRow) => row.agent_id}
        pageSize={20}
        exportName="agent_registry"
        onRowClick={(row: AgentRow) => setSelectedAgentId(row.agent_id)}
      />
      {selectedAgentId && (
        <AgentDetailPanel
          agentId={selectedAgentId}
          onClose={() => setSelectedAgentId(null)}
        />
      )}
    </>
  );
}

// ── Backend Diagnostics panel ─────────────────────────────────────────────────
function BackendDiagnosticsPanel() {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey:        ["agent-fw", "diagnostics"],
    queryFn:         () => apiJson("agent-framework/diagnostics", undefined, 15_000),
    refetchInterval: 60_000,
    staleTime:       30_000,
    retry: 1,
  });
  const d = data as any;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen((o: boolean) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/30 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-teal-400" />
          <span className="text-sm font-medium">Backend Diagnostics</span>
          <span className="text-xs text-muted-foreground">— subprocess model · registry · snapshot bus</span>
        </div>
        <span className="text-xs text-muted-foreground">{open ? "▲ hide" : "▼ show"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-4">
          {/* Subprocess model explanation */}
          <div className="rounded-lg bg-amber-950/20 border border-amber-700/30 p-3 text-xs text-amber-200/80">
            <p className="font-semibold mb-1">ℹ️ Why is Agent Registry count 0?</p>
            <p>
              Each API call spawns a fresh Python subprocess. <code className="font-mono text-amber-300">AgentRegistry</code> is
              an in-process singleton that starts <em>empty</em> on every call. A count of 0 is <strong>expected
              behaviour</strong> — it is NOT a configuration error. Active agent count is derived from live
              snapshot data, not the registry.
            </p>
          </div>

          {isLoading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="bg-muted/30 rounded-lg p-3 animate-pulse h-14" />
              ))}
            </div>
          ) : d ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                {/* Registry status */}
                <div className="bg-muted/30 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">Agent Registry</p>
                  <p className={`text-sm font-semibold ${d.registry_connected ? "text-emerald-400" : "text-red-400"}`}>
                    {d.registry_connected ? "Connected" : "Error"}
                  </p>
                  <p className="text-xs text-muted-foreground">Model: subprocess</p>
                </div>
                {/* Registry count */}
                <div className="bg-muted/30 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">Registered (in-process)</p>
                  <p className="text-sm font-semibold text-amber-400">{d.registry_count ?? 0}</p>
                  <p className="text-xs text-muted-foreground">Expected: 0</p>
                </div>
                {/* Active from snapshots */}
                <div className="bg-muted/30 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">Active (from snapshot)</p>
                  <p className="text-sm font-semibold text-emerald-400">
                    {d.active_agents_from_snapshot > 0 ? d.active_agents_from_snapshot : "—"}
                  </p>
                  <p className="text-xs text-muted-foreground">KV cache derived</p>
                </div>
                {/* Snapshot Bus */}
                <div className="bg-muted/30 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">Snapshot Bus</p>
                  <p className={`text-sm font-semibold ${d.bus_connected ? "text-emerald-400" : "text-red-400"}`}>
                    {d.bus_connected ? "Connected" : "Error"}
                  </p>
                  <p className="text-xs text-muted-foreground">{d.bus_topic_count ?? 0} topics</p>
                </div>
                {/* Last snapshot */}
                <div className="bg-muted/30 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">Last Snapshot</p>
                  <p className="text-sm font-semibold font-mono">
                    {d.last_snapshot_ts ? String(d.last_snapshot_ts).slice(11, 19) + " UTC" : "—"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {d.last_health_pct ? `${d.last_health_pct}% health` : "No scan yet"}
                  </p>
                </div>
                {/* Scan ID */}
                <div className="bg-muted/30 rounded-lg p-3">
                  <p className="text-xs text-muted-foreground">Scan ID / Version</p>
                  <p className="text-xs font-semibold font-mono text-teal-400 truncate">
                    {d.scan_id ? String(d.scan_id).slice(0, 12) + "…" : "—"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {d.flags_enabled ?? 0}/{d.flags_total ?? 0} flags enabled
                  </p>
                </div>
              </div>

              {/* Connected pages */}
              <div className="flex flex-wrap gap-2">
                <span className="text-xs text-muted-foreground">Pages reading canonical source:</span>
                {(d.connected_pages ?? []).map((pg: string) => (
                  <span key={pg} className="text-xs px-2 py-0.5 rounded-full bg-teal-950/40 border border-teal-700/40 text-teal-300">
                    {pg}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">Diagnostics unavailable.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function AgentOperations() {
  const { data: snapData,  isLoading: snapLoading  } = useQuery(q("supervisor/snapshot"));
  const { data: alertData, isLoading: alertLoading } = useQuery(q("supervisor/alerts"));
  const { data: scalData,  isLoading: scalLoading  } = useQuery(q("scalability"));
  const { data: mdSnap,    isLoading: mdLoading    } = useQuery(q("market-data/snapshot"));
  const { data: resSnap,   isLoading: resLoading   } = useQuery(q("research/snapshot"));

  // Canonical agent count — same source as AI Operations Centre & AI Paper Trader
  const { data: canonical } = useQuery({
    queryKey:        ["ops-centre", "agents"],
    queryFn:         () => apiJson("/ops-centre/agents", undefined, 30_000),
    refetchInterval: 30_000,
    staleTime:       20_000,
    retry: 1,
  });
  const ca = canonical as any;
  const canonicalSubtitle = ca?.agent_count
    ? `${ca.agent_count.active}/${ca.agent_count.total} agents ACTIVE · ${ca.health_pct ?? 0}% health · canonical snapshot`
    : "Multi-agent framework — status, health, snapshot bus, scalability";

  const snap   = snapData  as any;
  const alerts = alertData as any;
  const scal   = scalData  as any;
  const md     = mdSnap    as any;
  const res    = resSnap   as any;

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      <PageHeader
        icon={Bot}
        title="Agent Operations"
        subtitle={canonicalSubtitle}
        agentId="operations"
        agentName="Operations Agent"
        status="live"
        readOnly
        advisory
        helpTitle="Agent Operations Dashboard"
        faqs={[
          {
            q: "Why can't I restart agents from here?",
            a: "All agents are READ-ONLY and ADVISORY-ONLY. The Supervisor NEVER auto-restarts agents — operator action is required.",
          },
          {
            q: "What is the Snapshot Bus?",
            a: "Agents publish snapshots to named topics on the bus. No direct agent-to-agent calls. Consumers subscribe to receive updates.",
          },
          {
            q: "What do the health scores mean?",
            a: "70+ = Healthy, 40–69 = Degraded, <40 = Critical. Scores combine state, heartbeat, processing time, and snapshot activity.",
          },
        ]}
        relatedPages={[
          { href: "/command-center",    label: "Command Centre" },
          { href: "/observability",     label: "Observability" },
          { href: "/operations-center", label: "Operations Centre" },
        ]}
      />

      {/* Loading skeleton */}
      {snapLoading && !ca && <KpiCardSkeleton count={8} />}

      {/* Overall health + summary strip
          Prefer canonical agent counts (from ops-centre) when the supervisor
          snapshot shows 0 agents — that happens whenever AgentRegistry is
          empty in the fresh subprocess, which is always. The supervisor's
          overall_health object is also overridden so the HealthCard shows
          the real score rather than "Unknown 0/100". */}
      {(snap || ca) && (() => {
        // Build a synthetic supervisor view from canonical data
        const canonicalAgents = ca?.agent_count;
        const useCa = canonicalAgents && (snap?.framework_metrics?.agent_count ?? 0) === 0;
        const displayHealth = useCa
          ? {
              score:          ca.health_pct ?? 0,
              status:         ca.health_pct >= 80 ? "healthy" : ca.health_pct >= 50 ? "degraded" : "critical",
              critical_agents: canonicalAgents.error ?? 0,
              warning_agents:  0,
            }
          : snap?.overall_health;
        const displaySnap = useCa
          ? {
              ...snap,
              available:       true,
              framework_metrics: {
                ...(snap?.framework_metrics ?? {}),
                agent_count:     canonicalAgents.total,
                active_agents:   canonicalAgents.active,
                error_agents:    canonicalAgents.error ?? 0,
                warning_agents:  0,
                total_snapshots_published: snap?.framework_metrics?.total_snapshots_published ?? 0,
              },
              heartbeat_summary: snap?.heartbeat_summary ?? { ok: canonicalAgents.active, missed: 0 },
              snapshot_bus:      snap?.snapshot_bus ?? { topic_count: 0 },
            }
          : snap;
        return (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-1">
              <OverallHealthCard health={displayHealth} />
            </div>
            <div className="lg:col-span-2 flex flex-col justify-center">
              {displaySnap && <SupervisorSummary snap={displaySnap} />}
            </div>
          </div>
        );
      })()}

      {/* Agent registry table */}
      <div>
        <SectionHeader icon={Database} title="Agent Registry" />
        <AgentRegistryTable />
      </div>

      {/* Supervisor alerts */}
      {!alertLoading && (
        <div>
          <SectionHeader
            icon={Activity}
            title="Supervisor Alerts"
            badge={alerts?.alert_count > 0
              ? <span className={alerts?.critical_count > 0 ? "text-red-400" : "text-amber-400"}>{alerts.alert_count}</span>
              : undefined}
          />
          <AlertsPanel alerts={alerts?.alerts ?? []} />
          {(alerts?.alert_count ?? 0) > 0 && (
            <p className="text-xs text-muted-foreground mt-2 italic">
              ⚠ Supervisor NEVER auto-restarts agents. All alerts are advisory only.
            </p>
          )}
        </div>
      )}

      {/* Market Data + Research snapshots */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <SectionHeader icon={Radio} title="Market Data Snapshot" />
          {mdLoading
            ? <CardSkeleton />
            : <SnapshotInfoCard
                title="Market Data Agent"
                icon={Radio}
                data={md}
                fields={[
                  { label: "Regime",    key: "market_regime" },
                  { label: "Symbols",   key: "symbols_count" },
                  { label: "Coverage",  key: "coverage_pct",  color: "text-teal-400" },
                  { label: "VIX",       key: "india_vix" },
                  { label: "Freshness", key: "data_freshness_s" },
                  { label: "Provider",  key: "data_provider" },
                ]}
              />
          }
        </div>
        <div>
          <SectionHeader icon={BookOpen} title="Research Snapshot" />
          {resLoading
            ? <CardSkeleton />
            : <SnapshotInfoCard
                title="Research Agent"
                icon={BookOpen}
                data={res}
                fields={[
                  { label: "Announcements", key: "announcement_count" },
                  { label: "Earnings",      key: "earnings_count" },
                  { label: "Macro Events",  key: "macro_event_count" },
                  { label: "Sector News",   key: "sector_news_count" },
                  { label: "Total Items",   key: "total_research_items", color: "text-teal-400" },
                  { label: "Macro Regime",  key: "macro_regime" },
                ]}
              />
          }
        </div>
      </div>

      {/* Scalability estimator */}
      {!scalLoading && scal?.available && (
        <div>
          <SectionHeader icon={Gauge} title="Scalability Estimator" />
          <ScalabilityPanel snap={scal} />
          <p className="text-xs text-muted-foreground mt-2 italic">
            Advisory-only capacity estimates. Actual limits depend on data provider and infrastructure.
          </p>
        </div>
      )}

      {/* Snapshot bus stats */}
      {!snapLoading && snap?.snapshot_bus && (
        <div>
          <SectionHeader icon={Zap} title="Snapshot Bus" />
          <div className="bg-card border border-border rounded-xl p-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <MetricTile label="Topics"      value={snap.snapshot_bus.topic_count ?? 0} />
              <MetricTile label="Subscribers" value={snap.snapshot_bus.subscriber_count ?? 0} />
              {Object.entries(snap.snapshot_bus.sequences ?? {}).map(([topic, seq]) => (
                <MetricTile key={topic} label={`${topic} seq`} value={seq as number} color="text-teal-400" />
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-3">
              No direct agent-to-agent calls. All communication is mediated by the bus.
            </p>
          </div>
        </div>
      )}

      {/* Backend Diagnostics — subprocess model explanation + registry / bus stats */}
      <div>
        <SectionHeader icon={Database} title="Backend Diagnostics" />
        <BackendDiagnosticsPanel />
      </div>

      {/* ── Phase 10B: Analysis Layer ─────────────────────────────────────── */}
      <AnalysisLayerSection />

      {/* Advisory footer */}
      <p className="text-xs text-center text-muted-foreground pb-2">
        READ-ONLY · ADVISORY-ONLY · No agent restart from this page · Supervisor never auto-restarts
      </p>
    </div>
  );
}

// ── Analysis Layer Section (Phase 10B) ────────────────────────────────────────

const aa = (path: string) => ({
  queryKey:  ["analysis-agents", path],
  queryFn:   () => apiJson("analysis-agents/" + path),
  refetchInterval: 45_000,
  retry: 1,
  staleTime: 20_000,
});

const RISK_COLOR: Record<string, string> = {
  LOW:      "text-emerald-400",
  MODERATE: "text-amber-400",
  HIGH:     "text-orange-400",
  CRITICAL: "text-red-400",
  UNKNOWN:  "text-slate-400",
};

function AnalysisLayerSection() {
  const { data: summary, isLoading: sumLoading } = useQuery(aa("summary"));
  const { data: perf,    isLoading: perfLoading } = useQuery(aa("performance"));

  const agentStatusRows: Array<{
    agent_id: string;
    state: string;
    health_score: number;
    processing_time_ms: number;
    snapshots_published: number;
    heartbeat_status: string;
    registered: boolean;
  }> = (perf?.agent_metrics ?? []);

  const agentCols: TableColumn<Record<string, unknown>>[] = [
    {
      key: "agent_id", label: "Agent",
      render: (v) => <span className="font-mono text-xs">{String(v)}</span>,
    },
    {
      key: "state", label: "State",
      render: (v, row) => (
        <span className={STATE_COLOR[String(v)] ?? "text-slate-400"}>
          {row["registered"] ? String(v) : "NOT_REGISTERED"}
        </span>
      ),
    },
    {
      key: "health_score", label: "Health",
      render: (v) => <span className={scoreColor(Number(v))}>{Number(v).toFixed(1)}</span>,
    },
    {
      key: "processing_time_ms", label: "Latency",
      render: (v) => `${Number(v).toFixed(0)} ms`,
    },
    {
      key: "snapshots_published", label: "Published",
      render: (v) => String(v),
    },
    {
      key: "heartbeat_status", label: "Heartbeat",
      render: (v) => <span className={HB_COLOR[String(v)] ?? "text-slate-400"}>{String(v)}</span>,
    },
  ];

  return (
    <div>
      <SH icon={Activity} title="Phase 10B — Analysis Layer" />

      {(sumLoading || perfLoading) ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[0,1,2,3].map(i => <KpiCardSkeleton key={i} />)}
        </div>
      ) : (
        <>
          {/* Summary KPIs */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3 mb-4">
            <div className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
              <p className="text-xs text-muted-foreground">Market Regime</p>
              <p className="text-lg font-bold text-teal-400">{summary?.market_regime ?? "—"}</p>
              <p className="text-xs text-muted-foreground">{summary?.momentum_state ?? ""}</p>
            </div>
            <div className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
              <p className="text-xs text-muted-foreground">Symbols Monitored</p>
              <p className="text-lg font-bold">{summary?.symbols_monitored ?? 0}</p>
              <p className="text-xs text-muted-foreground">Priority queue</p>
            </div>
            <div className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
              <p className="text-xs text-muted-foreground">Breakouts Found</p>
              <p className="text-lg font-bold text-emerald-400">{summary?.breakouts_found ?? 0}</p>
              <p className="text-xs text-muted-foreground">This cycle</p>
            </div>
            <div className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
              <p className="text-xs text-muted-foreground">Top Strategy</p>
              <p className="text-base font-bold text-blue-400 truncate">{summary?.top_strategy ?? "—"}</p>
              <p className="text-xs text-muted-foreground">Score {summary?.highest_score?.toFixed(0) ?? "—"}</p>
            </div>
            <div className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
              <p className="text-xs text-muted-foreground">Portfolio Risk</p>
              <p className={`text-lg font-bold ${RISK_COLOR[summary?.risk_level] ?? "text-slate-400"}`}>
                {summary?.risk_level ?? "—"}
              </p>
              <p className="text-xs text-muted-foreground">Score {summary?.risk_score?.toFixed(0) ?? "—"}/100</p>
            </div>
          </div>

          {/* Agent performance table */}
          {agentStatusRows.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-4">
              <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                Analysis Agent Health
              </p>
              <DataTable
                data={agentStatusRows as Array<Record<string, unknown>>}
                columns={agentCols}
              />
              <p className="text-xs text-muted-foreground mt-2 italic">
                {perf?.symbols_monitored ?? 0} symbols monitored ·{" "}
                {perf?.strategy_evaluations ?? 0} strategy evaluations ·{" "}
                {perf?.strategies_registered ?? 0} strategies registered
              </p>
            </div>
          )}
          {agentStatusRows.length === 0 && (
            <EmptyState
              title="Analysis Agents Not Running"
              description="No Phase 10B analysis agents have been registered yet. Trigger a snapshot to initialise."
            />
          )}
          <p className="text-xs text-muted-foreground mt-2 italic">
            READ-ONLY · ADVISORY-ONLY · 4 analysis agents · 6 strategies · 9 risk dimensions · 12 event types
          </p>
        </>
      )}
    </div>
  );
}
