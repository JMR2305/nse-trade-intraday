/**
 * AgentCommMonitorPage.tsx — Phase 10E
 * Agent communication monitor — snapshot flow between agents.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Radio } from "lucide-react";

function edgeHealthColor(h: string) {
  const u = (h || "").toUpperCase();
  return u === "HEALTHY" ? "text-emerald-400" :
         u === "DEGRADED" ? "text-amber-400" :
         u === "DOWN" ? "text-red-400" : "text-slate-400";
}

export default function AgentCommMonitorPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["collab", "comm-monitor"],
    queryFn:  () => apiJson("collab/comm-monitor"),
    refetchInterval: 30_000,
    retry: 1,
  });

  const d       = data as any;
  const records = (d?.comm_records || []) as any[];

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Radio className="h-6 w-6 text-blue-400" />
            <h1 className="text-2xl font-bold">Agent Communication Monitor</h1>
            <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Snapshot publisher / consumer channels · Latency · Health
          </p>
        </div>
        {d && (
          <div className="text-right">
            <div className="text-2xl font-bold text-blue-400">{d.channel_count ?? 0}</div>
            <div className="text-xs text-muted-foreground">Channels</div>
          </div>
        )}
      </div>

      {/* Summary */}
      {d && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Channels",        value: d.channel_count       ?? 0, color: "text-blue-400" },
            { label: "Healthy Ch.",     value: d.healthy_channels    ?? 0, color: "text-emerald-400" },
            { label: "Avg Latency",     value: `${d.avg_latency_ms?.toFixed(0) ?? "—"}ms`, color: "text-violet-400" },
            { label: "Dropped Snaps.",  value: d.total_dropped       ?? 0, color: d.total_dropped > 0 ? "text-red-400" : "text-slate-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-card border border-border rounded-xl p-3">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className={`text-2xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Channel table */}
      {isLoading && <div className="animate-pulse h-64 bg-muted rounded-xl" />}
      {records.length > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground uppercase tracking-wide">
              <tr>
                <th className="p-3 text-left">Publisher</th>
                <th className="p-3 text-left">Consumer</th>
                <th className="p-3 text-left">Snapshot</th>
                <th className="p-3 text-center">Health</th>
                <th className="p-3 text-right">Latency</th>
                <th className="p-3 text-right">Pub Rate</th>
                <th className="p-3 text-right">Con Rate</th>
                <th className="p-3 text-right">Dropped</th>
                <th className="p-3 text-right">Errors</th>
                <th className="p-3 text-right">Warnings</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r: any, i: number) => (
                <tr key={i} className={`border-t border-border ${i % 2 === 0 ? "" : "bg-muted/10"}`}>
                  <td className="p-3 font-mono text-xs text-blue-300">{r.publisher}</td>
                  <td className="p-3 font-mono text-xs text-teal-300">{r.consumer}</td>
                  <td className="p-3 text-xs text-muted-foreground">{r.snapshot}</td>
                  <td className="p-3 text-center">
                    <span className={`text-xs font-semibold ${edgeHealthColor(r.edge_health)}`}>{r.edge_health}</span>
                  </td>
                  <td className="p-3 text-right text-xs">{r.latency_ms?.toFixed(0)}ms</td>
                  <td className="p-3 text-right text-xs text-muted-foreground">{r.publish_rate}</td>
                  <td className="p-3 text-right text-xs text-muted-foreground">{r.consumption_rate}</td>
                  <td className="p-3 text-right text-xs">{r.dropped_snapshots}</td>
                  <td className="p-3 text-right text-xs">{r.errors}</td>
                  <td className="p-3 text-right text-xs text-amber-400">{r.warnings}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · Communication metrics derived from graph edge data
      </p>
    </div>
  );
}
