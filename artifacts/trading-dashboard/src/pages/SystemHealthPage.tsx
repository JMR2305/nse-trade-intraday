/**
 * SystemHealthPage.tsx — Phase 10E
 * 8-component platform health score with history trend.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Activity } from "lucide-react";

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "bg-emerald-500" : score >= 55 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="w-full bg-muted rounded-full h-2">
      <div className={`h-2 rounded-full ${color}`} style={{ width: `${Math.min(100, score)}%` }} />
    </div>
  );
}

function healthCls(h: string) {
  const u = (h || "").toUpperCase();
  return u === "HEALTHY" ? "text-emerald-400" :
         u === "DEGRADED" ? "text-amber-400" :
         u === "CRITICAL" ? "text-red-400" : "text-slate-400";
}

export default function SystemHealthPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["autonomous-ops", "health"],
    queryFn:  () => apiJson("autonomous-ops/system-health"),
    refetchInterval: 30_000,
    retry: 1,
  });

  const d          = data as any;
  const components = (d?.components || {}) as Record<string, any>;
  const history    = (d?.history    || []) as any[];

  const COMPONENT_LABELS: Record<string, string> = {
    agent_health:         "Agent Health",
    snapshot_health:      "Snapshot Health",
    heartbeat_health:     "Heartbeat Health",
    timeline_health:      "Timeline Health",
    knowledge_health:     "Knowledge Health",
    learning_health:      "Learning Health",
    performance_health:   "Performance Health",
    collaboration_health: "Collaboration Health",
  };

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-6 w-6 text-cyan-400" />
            <h1 className="text-2xl font-bold">System Health Score</h1>
            <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            8-component weighted health score · Historical trend
          </p>
        </div>
        {d && (
          <div className="text-right">
            <div className={`text-4xl font-bold ${healthCls(d.overall_health)}`}>
              {d.overall_score?.toFixed(0)}%
            </div>
            <div className="text-sm text-muted-foreground">{d.overall_health}</div>
          </div>
        )}
      </div>

      {isLoading && <div className="animate-pulse h-64 bg-muted rounded-xl" />}

      {/* 8 Components */}
      {!isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {Object.entries(components).map(([key, comp]: [string, any]) => (
            <div key={key} className="bg-card border border-border rounded-xl p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{COMPONENT_LABELS[key] || key}</span>
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-semibold ${healthCls(comp.health)}`}>{comp.health}</span>
                  <span className="text-lg font-bold text-slate-200">{comp.score?.toFixed(0)}%</span>
                </div>
              </div>
              <ScoreBar score={comp.score ?? 0} />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>Weight: {(comp.weight * 100).toFixed(0)}%</span>
                <span>Contribution: {comp.contribution?.toFixed(1)}pts</span>
              </div>
              {key === "performance_health" && comp.avg_latency_ms > 0 && (
                <p className="text-[10px] text-muted-foreground">
                  Avg latency: {comp.avg_latency_ms?.toFixed(0)}ms
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* History trend */}
      {history.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-4">
          <h2 className="text-sm font-semibold mb-3">Health History (last {history.length} samples)</h2>
          <div className="flex items-end gap-1 h-16">
            {history.map((h: any, i: number) => {
              const pct = Math.max(5, h.score);
              const color = h.score >= 80 ? "bg-emerald-500" : h.score >= 55 ? "bg-amber-500" : "bg-red-500";
              return (
                <div key={i} className="flex-1 flex flex-col justify-end gap-1" title={`${h.score}% — ${h.timestamp}`}>
                  <div className={`rounded-sm ${color}`} style={{ height: `${pct}%` }} />
                  <span className="text-[9px] text-muted-foreground text-center">{h.score?.toFixed(0)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · Scores derived from existing agent snapshots · No new computation
      </p>
    </div>
  );
}
