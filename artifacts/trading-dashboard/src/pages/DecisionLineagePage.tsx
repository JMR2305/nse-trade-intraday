/**
 * DecisionLineagePage.tsx — Phase 10E
 * End-to-end decision lineage — 10 pipeline steps.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { GitCommit, CheckCircle2, XCircle } from "lucide-react";

export default function DecisionLineagePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["collab", "lineage"],
    queryFn:  () => apiJson("collab/lineage"),
    refetchInterval: 60_000,
    retry: 1,
  });

  const d     = data as any;
  const steps = (d?.lineage_steps || []) as any[];

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <GitCommit className="h-6 w-6 text-teal-400" />
            <h1 className="text-2xl font-bold">Decision Lineage</h1>
            <Badge variant="outline" className="text-violet-400 border-violet-600 text-xs">READ-ONLY</Badge>
            <Badge variant="outline" className="text-amber-400 border-amber-600 text-xs">ADVISORY</Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            End-to-end traceability from market data to knowledge
          </p>
        </div>
        {d && (
          <div className="text-right">
            <div className="text-2xl font-bold text-teal-400">{d.traceability_pct?.toFixed(0)}%</div>
            <div className="text-xs text-muted-foreground">Traceability</div>
          </div>
        )}
      </div>

      {/* Top recommendation */}
      {d?.top_recommendation && (
        <div className="bg-card border border-teal-800 rounded-xl p-4">
          <p className="text-xs text-muted-foreground mb-1">Latest Recommendation</p>
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold text-teal-300">{d.top_recommendation.symbol}</span>
            <Badge className="bg-teal-700 text-white text-xs">{d.top_recommendation.decision_type}</Badge>
            <span className="text-sm text-muted-foreground">
              {(d.top_recommendation.confidence * 100).toFixed(0)}% confidence
            </span>
          </div>
          {d.top_recommendation.explanation && (
            <p className="text-xs text-muted-foreground mt-1">{d.top_recommendation.explanation}</p>
          )}
        </div>
      )}

      {/* Summary */}
      {d && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Pipeline Steps",    value: d.step_count       ?? 0, color: "text-slate-300" },
            { label: "Available Sources", value: d.available_steps  ?? 0, color: "text-emerald-400" },
            { label: "Latency (ms)",      value: d.lineage_latency_ms?.toFixed(0) ?? "—", color: "text-blue-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-card border border-border rounded-xl p-3 text-center">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className={`text-2xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Lineage steps */}
      {isLoading && <div className="animate-pulse h-96 bg-muted rounded-xl" />}
      <div className="space-y-2">
        {steps.map((step: any) => {
          const ok = step.status === "AVAILABLE";
          return (
            <div key={step.step}
              className={`bg-card border rounded-xl p-4 flex gap-4 items-start ${ok ? "border-border" : "border-red-900/50"}`}>
              <div className="flex flex-col items-center gap-1">
                <span className="text-xs font-mono bg-slate-800 text-slate-400 w-6 h-6 flex items-center justify-center rounded-full shrink-0">
                  {step.step}
                </span>
                {step.step < steps.length && (
                  <div className="w-px h-4 bg-border" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  {ok
                    ? <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                    : <XCircle     className="h-4 w-4 text-red-400 shrink-0" />}
                  <span className="font-medium text-sm">{step.label}</span>
                  <span className="text-xs text-muted-foreground">· {step.source}</span>
                  <Badge
                    variant="outline"
                    className={`text-[10px] ${ok ? "text-emerald-400 border-emerald-700" : "text-red-400 border-red-700"}`}>
                    {step.status}
                  </Badge>
                </div>
                {ok && (
                  <div className="mt-1 flex gap-4 flex-wrap">
                    {Object.entries(step)
                      .filter(([k]) => !["step","label","source","status","agent"].includes(k))
                      .slice(0, 4)
                      .map(([k, v]) => (
                        <span key={k} className="text-[11px] text-muted-foreground">
                          {k.replace(/_/g, " ")}: <span className="text-foreground">{String(v)}</span>
                        </span>
                      ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        READ-ONLY · ADVISORY-ONLY · All outputs require operator review
      </p>
    </div>
  );
}
