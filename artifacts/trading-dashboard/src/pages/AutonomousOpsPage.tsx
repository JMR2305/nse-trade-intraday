/**
 * AutonomousOpsPage.tsx — Phase 10E
 * Autonomous Operations Dashboard — full platform visibility.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Monitor, CheckCircle2, AlertTriangle, XCircle, Activity,
  Clock, Brain, BookOpen, Zap,
} from "lucide-react";

const REFETCH = 30_000;

function KpiCard({ label, value, color = "text-foreground", sub }: {
  label: string; value: string | number; color?: string; sub?: string
}) {
  return (
    <div className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

function healthBadge(h: string) {
  const upper = (h || "").toUpperCase();
  const cls = upper === "HEALTHY" ? "bg-emerald-600" :
              upper === "DEGRADED" ? "bg-amber-500" :
              upper === "CRITICAL" ? "bg-red-600" : "bg-slate-600";
  return <span className={`inline-flex px-2 py-0.5 rounded-full text-white text-[10px] font-semibold ${cls}`}>{h || "—"}</span>;
}

export default function AutonomousOpsPage() {
  const opsQuery  = useQuery({ queryKey: ["autonomous-ops", "snapshot"], queryFn: () => apiJson("autonomous-ops/snapshot"), refetchInterval: REFETCH, retry: 1 });
  const healthQ   = useQuery({ queryKey: ["autonomous-ops", "health"],   queryFn: () => apiJson("autonomous-ops/system-health"), refetchInterval: REFETCH, retry: 1 });
  const alertsQ   = useQuery({ queryKey: ["collab", "alerts"],           queryFn: () => apiJson("collab/alerts"), refetchInterval: REFETCH, retry: 1 });

  const ops    = opsQuery.data  as any;
  const health = healthQ.data   as any;
  const alerts = alertsQ.data   as any;
  const alertList = (alerts?.alerts || []) as any[];
  const components = (health?.components || {}) as Record<string, any>;

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Monitor className="h-6 w-6 text-cyan-400" />
            <h1 className="text-2xl font-bold">Autonomous Operations</h1>
            <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
            <Badge variant="outline" className="text-amber-400 border-amber-600 text-xs">ADVISORY</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Platform-wide operational visibility · 11 agents monitored
          </p>
        </div>
        {health && (
          <div className="text-right">
            <div className="text-3xl font-bold text-cyan-400">{health.overall_score?.toFixed(0)}%</div>
            <div className="text-xs text-muted-foreground">Platform Health</div>
          </div>
        )}
      </div>

      <Alert className="border-slate-700 bg-slate-800/40">
        <AlertTriangle className="h-4 w-4 text-slate-400" />
        <AlertDescription className="text-slate-300 text-xs">
          No autonomous execution · No automatic recovery · All recommendations require operator approval
        </AlertDescription>
      </Alert>

      {/* KPI Grid */}
      {ops && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard label="Registered"      value={ops.registered_agents ?? "—"}  color="text-slate-300" />
          <KpiCard label="Healthy"         value={ops.healthy_agents    ?? "—"}  color="text-emerald-400" />
          <KpiCard label="Warning"         value={ops.warning_agents    ?? "—"}  color={ops.warning_agents > 0 ? "text-amber-400" : "text-slate-400"} />
          <KpiCard label="Failed"          value={ops.failed_agents     ?? "—"}  color={ops.failed_agents  > 0 ? "text-red-400"   : "text-slate-400"} />
          <KpiCard label="Snapshot Thru."  value={ops.snapshot_throughput ?? "—"} color="text-blue-400" sub="total published" />
          <KpiCard label="Queue Depth"     value={ops.queue_depth       ?? "—"}  color="text-indigo-400" />
        </div>
      )}
      {ops && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <KpiCard label="Heartbeat"       value={ops.heartbeat_status  ?? "—"}  color={ops.heartbeat_status === "HEALTHY" ? "text-emerald-400" : "text-amber-400"} />
          <KpiCard label="Data Freshness"  value={ops.data_freshness_s ? `${ops.data_freshness_s}s` : "—"} color="text-teal-400" />
          <KpiCard label="Avg Decision Lat" value={ops.avg_decision_latency_ms ? `${ops.avg_decision_latency_ms?.toFixed(0)}ms` : "—"} color="text-violet-400" />
          <KpiCard label="Avg Snap Lat"    value={ops.avg_snapshot_latency_ms ? `${ops.avg_snapshot_latency_ms?.toFixed(0)}ms` : "—"} color="text-pink-400" />
          <KpiCard label="Learning Queue"  value={ops.learning_queue    ?? "—"}  color="text-cyan-400" sub="trades pending" />
          <KpiCard label="Knowledge Queue" value={ops.knowledge_queue   ?? "—"}  color="text-indigo-400" sub="entries indexed" />
          <KpiCard label="Overall Health"  value={ops.overall_health    ?? "—"}  color={ops.overall_health === "HEALTHY" ? "text-emerald-400" : "text-amber-400"} />
          <KpiCard label="Health Score"    value={`${ops.overall_health_score?.toFixed(0)}%`} color="text-cyan-400" />
        </div>
      )}

      {/* 8-Component Health Breakdown */}
      {health && Object.keys(components).length > 0 && (
        <div className="bg-card border border-border rounded-xl p-4">
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Activity className="h-4 w-4 text-cyan-400" />
            8-Component Health Score
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Object.entries(components).map(([name, comp]: [string, any]) => (
              <div key={name} className="bg-muted/30 rounded-lg p-3">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{name.replace(/_/g, " ")}</p>
                <p className="text-xl font-bold text-slate-200">{comp.score?.toFixed(0)}%</p>
                <div className="flex items-center justify-between mt-1">
                  {healthBadge(comp.health)}
                  <span className="text-[10px] text-muted-foreground">w={comp.weight}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Collaboration Alerts */}
      {alertList.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-4">
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            Collaboration Alerts ({alertList.length})
          </h2>
          <div className="space-y-2">
            {alertList.slice(0, 6).map((a: any) => (
              <div key={a.alert_id}
                className={`rounded-lg p-3 border text-sm ${
                  a.severity === "CRITICAL" ? "border-red-800 bg-red-950/20" :
                  a.severity === "WARNING"  ? "border-amber-800 bg-amber-950/20" :
                  "border-border bg-muted/20"}`}>
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline"
                    className={`text-[10px] ${a.severity === "CRITICAL" ? "text-red-400 border-red-700" : a.severity === "WARNING" ? "text-amber-400 border-amber-700" : "text-slate-400 border-slate-600"}`}>
                    {a.severity}
                  </Badge>
                  <span className="font-medium text-sm">{a.title}</span>
                </div>
                <p className="text-xs text-muted-foreground">{a.description}</p>
                <p className="text-xs text-blue-300 mt-1">→ {a.recommendation}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · No autonomous execution · No automatic recovery
      </p>
    </div>
  );
}
