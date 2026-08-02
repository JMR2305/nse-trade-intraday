/**
 * CollaborationGraphPage.tsx — Phase 10E
 * Agent collaboration graph — 11 nodes, 10 edges, live health.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertTriangle, GitBranch, CheckCircle2, XCircle, Minus } from "lucide-react";

const REFETCH = 60_000;

function healthColor(health: string): string {
  const h = (health || "").toUpperCase();
  if (h === "HEALTHY" || h === "ACTIVE")     return "text-emerald-400";
  if (h === "DEGRADED" || h === "WARNING")   return "text-amber-400";
  if (h === "UNAVAILABLE" || h === "DOWN")   return "text-red-400";
  return "text-slate-400";
}
function healthBg(health: string): string {
  const h = (health || "").toUpperCase();
  if (h === "HEALTHY" || h === "ACTIVE")     return "border-l-4 border-emerald-500";
  if (h === "DEGRADED" || h === "WARNING")   return "border-l-4 border-amber-500";
  if (h === "UNAVAILABLE" || h === "DOWN")   return "border-l-4 border-red-500";
  return "border-l-4 border-slate-600";
}
function layerColor(layer: string): string {
  const l = (layer || "").toUpperCase();
  if (l === "ORCHESTRATION") return "bg-violet-900/40 text-violet-300";
  if (l === "DATA")          return "bg-blue-900/40 text-blue-300";
  if (l === "ANALYSIS")      return "bg-teal-900/40 text-teal-300";
  if (l === "DECISION")      return "bg-orange-900/40 text-orange-300";
  if (l === "LEARNING")      return "bg-indigo-900/40 text-indigo-300";
  return "bg-slate-800 text-slate-300";
}

export default function CollaborationGraphPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["collab", "graph"],
    queryFn:  () => apiJson("collab/graph"),
    refetchInterval: REFETCH,
    retry: 1,
  });

  const d = data as any;
  const nodes     = (d?.nodes     || []) as any[];
  const missing   = (d?.missing_dependencies || []) as string[];
  const conflicts = (d?.conflicting_outputs  || []) as string[];
  const stale     = (d?.stale_nodes          || []) as string[];

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch className="h-6 w-6 text-violet-400" />
            <h1 className="text-2xl font-bold">Agent Collaboration Graph</h1>
            <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
            <Badge variant="outline" className="text-amber-400 border-amber-600 text-xs">ADVISORY</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            11-agent dependency chain · Snapshot flow · Health monitoring
          </p>
        </div>
        {d && (
          <div className="text-right">
            <div className="text-2xl font-bold text-emerald-400">{d.graph_health_pct?.toFixed(0)}%</div>
            <div className="text-xs text-muted-foreground">Graph Health</div>
          </div>
        )}
      </div>

      {/* Warnings */}
      {missing.length > 0 && (
        <Alert className="border-red-800 bg-red-950/30">
          <AlertTriangle className="h-4 w-4 text-red-400" />
          <AlertDescription className="text-red-300 text-sm">
            {missing.length} missing dependency(ies): {missing.slice(0, 2).join("; ")}
          </AlertDescription>
        </Alert>
      )}
      {conflicts.length > 0 && (
        <Alert className="border-amber-800 bg-amber-950/30">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <AlertDescription className="text-amber-300 text-sm">
            {conflicts[0]}
          </AlertDescription>
        </Alert>
      )}

      {/* Summary row */}
      {d && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Total Agents",   value: d.node_count        ?? 0, color: "text-slate-300" },
            { label: "Healthy",        value: d.healthy_agents    ?? 0, color: "text-emerald-400" },
            { label: "Stale / Offline",value: stale.length,            color: stale.length ? "text-red-400" : "text-slate-400" },
            { label: "Edges",          value: d.edge_count        ?? 0, color: "text-blue-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-card border border-border rounded-xl p-3">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className={`text-2xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Agent nodes */}
      <div className="space-y-2">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Agent Pipeline ({nodes.length} nodes)
        </h2>
        {isLoading && <div className="animate-pulse h-64 bg-muted rounded-xl" />}
        <div className="space-y-2">
          {nodes.map((node: any) => (
            <div key={node.agent_id}
              className={`bg-card rounded-xl p-3 flex items-center gap-3 ${healthBg(node.health)}`}>
              <span className={`text-lg ${healthColor(node.health)}`}>
                {node.available ? <CheckCircle2 className="h-5 w-5 inline" /> : <XCircle className="h-5 w-5 inline" />}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm">{node.label}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${layerColor(node.layer)}`}>{node.layer}</span>
                  {stale.includes(node.agent_id) && (
                    <span className="text-[10px] px-1.5 py-0.5 bg-red-900/40 text-red-400 rounded">STALE</span>
                  )}
                </div>
                <div className="flex gap-3 mt-1 text-[11px] text-muted-foreground">
                  {node.produces?.length > 0 && <span>↑ {node.produces.join(", ")}</span>}
                  {node.consumes?.length  > 0 && <span>↓ {node.consumes.join(", ")}</span>}
                </div>
              </div>
              <div className="text-right shrink-0">
                <p className={`text-xs font-semibold ${healthColor(node.health)}`}>{node.health}</p>
                <p className="text-[10px] text-muted-foreground">{node.latency_ms?.toFixed(0)}ms</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · All outputs require operator review
      </p>
    </div>
  );
}
