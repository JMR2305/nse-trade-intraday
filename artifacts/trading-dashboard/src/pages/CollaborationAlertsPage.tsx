/**
 * CollaborationAlertsPage.tsx — Phase 10E
 * Advisory collaboration alerts across the multi-agent platform.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Bell, AlertTriangle, Info } from "lucide-react";

const ALERT_TYPE_LABELS: Record<string, string> = {
  MISSING_SNAPSHOT:          "Missing Snapshot",
  AGENT_OFFLINE:             "Agent Offline",
  HEARTBEAT_MISSED:          "Heartbeat Missed",
  QUEUE_OVERLOAD:            "Queue Overload",
  SLOW_CONSUMER:             "Slow Consumer",
  STALE_RESEARCH:            "Stale Research",
  DATA_FRESHNESS:            "Data Freshness",
  CONFLICTING_RECOMMENDATIONS: "Conflicting Outputs",
};

function severityIcon(s: string) {
  if (s === "CRITICAL") return <AlertTriangle className="h-4 w-4 text-red-400" />;
  if (s === "WARNING")  return <AlertTriangle className="h-4 w-4 text-amber-400" />;
  return <Info className="h-4 w-4 text-blue-400" />;
}

export default function CollaborationAlertsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["collab", "alerts"],
    queryFn:  () => apiJson("collab/alerts"),
    refetchInterval: 30_000,
    retry: 1,
  });

  const d         = data as any;
  const alertList = (d?.alerts || []) as any[];

  const critical = alertList.filter((a: any) => a.severity === "CRITICAL");
  const warnings = alertList.filter((a: any) => a.severity === "WARNING");
  const info     = alertList.filter((a: any) => a.severity === "INFO");

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Bell className="h-6 w-6 text-amber-400" />
            <h1 className="text-2xl font-bold">Collaboration Alerts</h1>
            <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
            <Badge variant="outline" className="text-amber-400 border-amber-600 text-xs">ADVISORY</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Advisory alerts for missing snapshots, offline agents, data freshness issues
          </p>
        </div>
        {d && (
          <div className="text-right">
            <div className={`text-3xl font-bold ${critical.length > 0 ? "text-red-400" : "text-emerald-400"}`}>
              {d.alert_count ?? 0}
            </div>
            <div className="text-xs text-muted-foreground">Active Alerts</div>
          </div>
        )}
      </div>

      {/* Summary */}
      {d && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Critical", value: d.critical ?? 0, color: d.critical > 0 ? "text-red-400" : "text-slate-400" },
            { label: "Warning",  value: d.warnings ?? 0, color: d.warnings > 0 ? "text-amber-400" : "text-slate-400" },
            { label: "Info",     value: d.info     ?? 0, color: "text-blue-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-card border border-border rounded-xl p-3 text-center">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className={`text-3xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* All clear */}
      {!isLoading && alertList.length === 0 && (
        <div className="bg-emerald-950/30 border border-emerald-800 rounded-xl p-8 text-center">
          <p className="text-emerald-400 font-semibold">All Clear</p>
          <p className="text-sm text-muted-foreground mt-1">No collaboration alerts at this time.</p>
        </div>
      )}

      {isLoading && <div className="animate-pulse h-64 bg-muted rounded-xl" />}

      {/* Alert list */}
      <div className="space-y-3">
        {alertList.map((a: any) => (
          <div key={a.alert_id}
            className={`bg-card border rounded-xl p-4 ${
              a.severity === "CRITICAL" ? "border-red-800"  :
              a.severity === "WARNING"  ? "border-amber-800" :
              "border-border"}`}>
            <div className="flex items-start gap-3">
              {severityIcon(a.severity)}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <Badge variant="outline" className={`text-[10px] ${
                    a.severity === "CRITICAL" ? "text-red-400 border-red-700" :
                    a.severity === "WARNING"  ? "text-amber-400 border-amber-700" :
                    "text-blue-400 border-blue-700"}`}>
                    {a.severity}
                  </Badge>
                  <Badge variant="outline" className="text-[10px] text-slate-400 border-slate-600">
                    {ALERT_TYPE_LABELS[a.alert_type] || a.alert_type}
                  </Badge>
                  <span className="font-semibold text-sm">{a.title}</span>
                </div>
                <p className="text-xs text-muted-foreground mb-2">{a.description}</p>
                <p className="text-xs text-blue-300">
                  <span className="text-muted-foreground">Recommendation: </span>{a.recommendation}
                </p>
                <p className="text-[10px] text-muted-foreground mt-1">
                  Source: {a.source} · {a.generated_at}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · All alerts are advisory. No automated remediation.
      </p>
    </div>
  );
}
