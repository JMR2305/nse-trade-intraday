/**
 * SupervisorExtendedPage.tsx — Phase 10E
 * Extended Supervisor capabilities — dependency validation, restart recommendations.
 *
 * READ-ONLY · ADVISORY-ONLY · No automatic recovery.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Shield, CheckCircle2, AlertTriangle, RefreshCw } from "lucide-react";

function SectionCard({ title, icon: Icon, children }: { title: string; icon: any; children: React.ReactNode }) {
  return (
    <div className="bg-card border border-border rounded-xl p-4">
      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-slate-400" />{title}
      </h2>
      {children}
    </div>
  );
}

export default function SupervisorExtendedPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["autonomous-ops", "supervisor-extended"],
    queryFn:  () => apiJson("autonomous-ops/supervisor-extended"),
    refetchInterval: 60_000,
    retry: 1,
  });

  const d   = data as any;
  const dv  = d?.dependency_validation  || {};
  const sf  = d?.snapshot_freshness     || {};
  const ch  = d?.collaboration_health   || {};
  const cs  = d?.capacity_score         || {};
  const rr  = (d?.restart_recommendations   || []) as any[];
  const rs  = (d?.recovery_suggestions      || []) as string[];
  const mr  = (d?.maintenance_recommendations || []) as string[];

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-2">
        <Shield className="h-6 w-6 text-indigo-400" />
        <h1 className="text-2xl font-bold">Extended Supervisor</h1>
        <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
        <Badge variant="outline" className="text-amber-400 border-amber-600 text-xs">ADVISORY</Badge>
      </div>

      <Alert className="border-slate-700 bg-slate-800/40">
        <AlertTriangle className="h-4 w-4 text-slate-400" />
        <AlertDescription className="text-slate-300 text-xs">
          No automatic recovery · All recommendations require operator action · Advisory only
        </AlertDescription>
      </Alert>

      {isLoading && <div className="animate-pulse h-96 bg-muted rounded-xl" />}

      {d && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { label: "Chain Intact",   value: dv.chain_intact ? "YES" : "NO",          color: dv.chain_intact ? "text-emerald-400" : "text-red-400" },
            { label: "Freshness",      value: `${sf.freshness_pct?.toFixed(0) ?? 0}%`, color: sf.freshness_pct >= 80 ? "text-emerald-400" : "text-amber-400" },
            { label: "Capacity",       value: `${cs.capacity_score?.toFixed(0) ?? 0}%`,color: cs.utilisation_pct < 60 ? "text-emerald-400" : "text-amber-400" },
            { label: "Overall Status", value: d.overall_status ?? "—",                  color: d.overall_status === "HEALTHY" ? "text-emerald-400" : "text-amber-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-card border border-border rounded-xl p-3 text-center">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className={`text-xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {d && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Dependency Validation */}
          <SectionCard title="Dependency Validation" icon={CheckCircle2}>
            <p className="text-sm mb-2">{dv.recommendation}</p>
            {(dv.missing_dependencies || []).length > 0 && (
              <ul className="space-y-1">
                {dv.missing_dependencies.map((m: string, i: number) => (
                  <li key={i} className="text-xs text-red-400">• {m}</li>
                ))}
              </ul>
            )}
            <p className="text-xs text-muted-foreground mt-2">
              Score: {dv.dependency_score?.toFixed(0)}%
            </p>
          </SectionCard>

          {/* Snapshot Freshness */}
          <SectionCard title="Snapshot Freshness" icon={CheckCircle2}>
            <div className="grid grid-cols-2 gap-2 mb-2 text-sm">
              <div><p className="text-xs text-muted-foreground">Fresh</p><p className="font-bold text-emerald-400">{sf.fresh_agents ?? 0}</p></div>
              <div><p className="text-xs text-muted-foreground">Stale</p><p className={`font-bold ${sf.stale_agents > 0 ? "text-red-400" : "text-slate-400"}`}>{sf.stale_agents ?? 0}</p></div>
            </div>
            <p className="text-sm text-muted-foreground">{sf.recommendation}</p>
          </SectionCard>

          {/* Collaboration Health */}
          <SectionCard title="Collaboration Health" icon={Shield}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-2xl font-bold ${ch.collaboration_health === "HEALTHY" ? "text-emerald-400" : "text-amber-400"}`}>
                {ch.collaboration_health}
              </span>
              <span className="text-sm text-muted-foreground">{ch.graph_health_pct?.toFixed(0)}%</span>
            </div>
            <p className="text-sm text-muted-foreground">{ch.recommendation}</p>
          </SectionCard>

          {/* Capacity */}
          <SectionCard title="System Capacity" icon={BarChart2Icon}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-2xl font-bold text-blue-400">{cs.capacity_score?.toFixed(0)}%</span>
              <span className="text-sm text-muted-foreground">available · {cs.utilisation_pct?.toFixed(0)}% used</span>
            </div>
            <p className="text-sm text-muted-foreground">{cs.recommendation}</p>
          </SectionCard>
        </div>
      )}

      {/* Restart Recommendations */}
      {rr.length > 0 && (
        <SectionCard title={`Restart Recommendations (${rr.length})`} icon={RefreshCw}>
          <div className="space-y-2">
            {rr.map((r: any, i: number) => (
              <div key={i} className={`rounded-lg p-3 border text-sm ${r.priority === "HIGH" ? "border-red-800 bg-red-950/20" : "border-border bg-muted/20"}`}>
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant="outline" className={`text-[10px] ${r.priority === "HIGH" ? "text-red-400 border-red-700" : "text-amber-400 border-amber-700"}`}>{r.priority}</Badge>
                  <span className="font-medium">{r.label}</span>
                  <span className="text-[10px] text-muted-foreground">{r.action}</span>
                </div>
                <p className="text-xs text-muted-foreground">{r.reason}</p>
                <p className="text-xs text-amber-300 mt-1">⚠ {r.note}</p>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {/* Recovery Suggestions */}
      {rs.length > 0 && (
        <SectionCard title="Recovery Suggestions" icon={RefreshCw}>
          <ul className="space-y-1">
            {rs.map((s: string, i: number) => (
              <li key={i} className="text-sm text-muted-foreground">• {s}</li>
            ))}
          </ul>
        </SectionCard>
      )}

      {/* Maintenance */}
      {mr.length > 0 && (
        <SectionCard title="Maintenance Recommendations" icon={Shield}>
          <ul className="space-y-1">
            {mr.map((m: string, i: number) => (
              <li key={i} className="text-sm text-muted-foreground">• {m}</li>
            ))}
          </ul>
        </SectionCard>
      )}

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · No automatic recovery · Operator action required
      </p>
    </div>
  );
}

function BarChart2Icon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={className}>
      <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
      <line x1="2" y1="20" x2="22" y2="20" />
    </svg>
  );
}
