/**
 * ScalabilityDashboardPage.tsx — Phase 10E
 * Scalability and capacity planning dashboard.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { BarChart2 } from "lucide-react";

function UsageBar({ pct }: { pct: number }) {
  const color = pct < 60 ? "bg-emerald-500" : pct < 80 ? "bg-amber-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-xs text-muted-foreground mb-1">
        <span>Utilisation</span><span>{pct.toFixed(1)}%</span>
      </div>
      <div className="w-full bg-muted rounded-full h-2">
        <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

export default function ScalabilityDashboardPage() {
  const { data: scal, isLoading: sl } = useQuery({
    queryKey: ["autonomous-ops", "scalability"],
    queryFn:  () => apiJson("autonomous-ops/scalability"),
    refetchInterval: 60_000, retry: 1,
  });
  const { data: cap } = useQuery({
    queryKey: ["autonomous-ops", "capacity"],
    queryFn:  () => apiJson("autonomous-ops/capacity"),
    refetchInterval: 60_000, retry: 1,
  });

  const s = scal as any;
  const c = cap  as any;

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-2">
        <BarChart2 className="h-6 w-6 text-green-400" />
        <h1 className="text-2xl font-bold">Scalability Dashboard</h1>
        <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
        <Badge variant="outline" className="text-amber-400 border-amber-600 text-xs">ADVISORY</Badge>
      </div>
      <p className="text-sm text-muted-foreground">Capacity planning · Symbol limits · Agent growth · Resource estimates</p>

      {sl && <div className="animate-pulse h-64 bg-muted rounded-xl" />}

      {s && (
        <>
          {/* Current metrics */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {[
              { label: "Agents",             value: s.current_agents,             color: "text-slate-300" },
              { label: "Monitored Symbols",  value: s.current_monitored_symbols,  color: "text-teal-400" },
              { label: "Snapshots/min",      value: s.snapshots_per_minute,       color: "text-blue-400" },
              { label: "Recs/hour",          value: s.recommendations_per_hour,   color: "text-violet-400" },
              { label: "KB Entries",         value: s.knowledge_base_size,        color: "text-indigo-400" },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-card border border-border rounded-xl p-3">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className={`text-2xl font-bold ${color}`}>{value ?? "—"}</p>
              </div>
            ))}
          </div>

          {/* Capacity metrics */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="bg-card border border-border rounded-xl p-4 space-y-3">
              <h2 className="text-sm font-semibold">Symbol Capacity</h2>
              <UsageBar pct={s.utilisation_pct ?? 0} />
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div><p className="text-xs text-muted-foreground">Safe Capacity</p><p className="font-semibold text-emerald-400">{s.safe_capacity_symbols}</p></div>
                <div><p className="text-xs text-muted-foreground">Max Capacity</p><p className="font-semibold text-amber-400">{s.max_capacity_symbols}</p></div>
                <div><p className="text-xs text-muted-foreground">Remaining</p><p className="font-semibold text-blue-400">{s.remaining_capacity}</p></div>
                <div><p className="text-xs text-muted-foreground">Future Agents</p><p className="font-semibold text-slate-300">{s.future_agents_supported}</p></div>
              </div>
            </div>
            <div className="bg-card border border-border rounded-xl p-4 space-y-3">
              <h2 className="text-sm font-semibold">Resource Estimates (Advisory)</h2>
              <div className="space-y-2">
                <div>
                  <div className="flex justify-between text-xs text-muted-foreground mb-1"><span>CPU</span><span>{s.estimated_cpu_pct?.toFixed(1)}%</span></div>
                  <div className="w-full bg-muted rounded-full h-2">
                    <div className="h-2 rounded-full bg-blue-500" style={{ width: `${Math.min(100, s.estimated_cpu_pct ?? 0)}%` }} />
                  </div>
                </div>
                <div>
                  <div className="flex justify-between text-xs text-muted-foreground mb-1"><span>Memory</span><span>{s.estimated_memory_mb?.toFixed(0)} MB</span></div>
                  <div className="w-full bg-muted rounded-full h-2">
                    <div className="h-2 rounded-full bg-indigo-500" style={{ width: `${Math.min(100, (s.estimated_memory_mb ?? 0) / 2048 * 100)}%` }} />
                  </div>
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                <p>Learning: {s.learning_throughput || "—"}</p>
                <p>Knowledge: {s.knowledge_growth || "—"}</p>
              </div>
            </div>
          </div>

          {/* Scaling advisory */}
          <div className="bg-card border border-border rounded-xl p-4">
            <h2 className="text-sm font-semibold mb-2">Scaling Advisory</h2>
            <p className="text-sm text-muted-foreground">{s.scaling_estimate}</p>
          </div>
        </>
      )}

      {/* Capacity forecast */}
      {c && (
        <div className="bg-card border border-border rounded-xl p-4 space-y-2">
          <h2 className="text-sm font-semibold">Capacity Forecast</h2>
          <p className="text-sm text-muted-foreground">{c.forecast_30d}</p>
          <p className="text-sm text-muted-foreground">{c.forecast_90d}</p>
          <div className="grid grid-cols-2 gap-3 mt-2 text-sm">
            <div><p className="text-xs text-muted-foreground">CPU Headroom</p><p className="font-semibold text-emerald-400">{c.cpu_headroom_pct?.toFixed(1)}%</p></div>
            <div><p className="text-xs text-muted-foreground">Memory Headroom</p><p className="font-semibold text-emerald-400">{c.memory_headroom_mb?.toFixed(0)} MB</p></div>
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · Estimates based on current configuration. Future scaling requires no architectural redesign.
      </p>
    </div>
  );
}
