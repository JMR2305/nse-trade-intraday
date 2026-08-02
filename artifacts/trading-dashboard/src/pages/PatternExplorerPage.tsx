/**
 * PatternExplorerPage.tsx — Phase 10D
 * Pattern Explorer — recurring market pattern observations.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Activity, Shield, AlertTriangle } from "lucide-react";

const q = (path: string) => ({
  queryKey:  ["pattern-explorer", path],
  queryFn:   () => apiJson("learning-layer/" + path),
  refetchInterval: 60_000,
  retry: 1,
  staleTime: 30_000,
});

const CAT_COLORS: Record<string, { border: string; bg: string; badge: string }> = {
  PRICE_ACTION: { border: "border-violet-500/40", bg: "bg-violet-500/5",  badge: "border-violet-500/50 text-violet-400" },
  VOLATILITY:   { border: "border-amber-500/40",  bg: "bg-amber-500/5",   badge: "border-amber-500/50 text-amber-400" },
  TIME_BASED:   { border: "border-blue-500/40",   bg: "bg-blue-500/5",    badge: "border-blue-500/50 text-blue-400" },
  SECTOR:       { border: "border-teal-500/40",   bg: "bg-teal-500/5",    badge: "border-teal-500/50 text-teal-400" },
  RISK:         { border: "border-red-500/40",    bg: "bg-red-500/5",     badge: "border-red-500/50 text-red-400" },
  META:         { border: "border-slate-500/40",  bg: "bg-slate-500/5",   badge: "border-slate-500/50 text-slate-400" },
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 45 ? "bg-amber-500" : "bg-slate-600";
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted-foreground">Confidence</span>
        <span className="text-xs font-mono">{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-border">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function PatternCard({ pattern }: { pattern: any }) {
  const c = CAT_COLORS[pattern.category] ?? CAT_COLORS.META;
  return (
    <div className={`rounded-xl border p-5 flex flex-col gap-2 ${c.border} ${c.bg}`}>
      <div className="flex items-start justify-between">
        <h3 className="font-semibold text-sm leading-snug">{pattern.name}</h3>
        <Badge variant="outline" className={`text-[10px] ${c.badge}`}>{pattern.category.replace(/_/g, " ")}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">{pattern.description}</p>
      <div className="flex items-center gap-2 mt-1">
        <Activity className="w-3 h-3 text-muted-foreground" />
        <span className="text-xs text-muted-foreground">{pattern.occurrences} occurrence{pattern.occurrences !== 1 ? "s" : ""}</span>
      </div>
      <ConfidenceBar value={pattern.confidence} />
      <div className="mt-2 rounded-lg bg-black/20 p-3">
        <p className="text-xs font-medium text-teal-400 mb-1">Advisory</p>
        <p className="text-xs text-muted-foreground">{pattern.advisory}</p>
      </div>
    </div>
  );
}

export default function PatternExplorerPage() {
  const patternsQ = useQuery(q("knowledge/patterns"));
  const data: any = patternsQ.data ?? {};
  const all = data.patterns ?? [];
  const active = all.filter((p: any) => p.pattern_id !== "BASELINE_OBSERVATION");
  const categories: string[] = Array.from(new Set(active.map((p: any) => p.category as string)));

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-6 h-6 text-violet-400" />
          <div>
            <h1 className="text-xl font-bold">Pattern Explorer</h1>
            <p className="text-sm text-muted-foreground">Recurring market pattern observations — advisory only</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs border-violet-500/50 text-violet-400">READ-ONLY</Badge>
          <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-400">ADVISORY</Badge>
          <Badge className="text-xs bg-violet-600">{active.length} Pattern{active.length !== 1 ? "s" : ""}</Badge>
        </div>
      </div>

      <Alert className="border-violet-500/30 bg-violet-500/10">
        <Shield className="h-4 w-4 text-violet-400" />
        <AlertDescription className="text-xs text-violet-300">
          All patterns are advisory observations. They do not trigger any automated action.
          Operator review is required before acting on any pattern.
        </AlertDescription>
      </Alert>

      {active.length === 0 ? (
        <div className="bg-card rounded-xl border border-border p-8 text-center">
          <Activity className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No recurring patterns detected yet. Complete more paper trades to enable pattern detection.
          </p>
        </div>
      ) : (
        <>
          {categories.map(cat => {
            const group = active.filter((p: any) => p.category === cat);
            if (!group.length) return null;
            return (
              <div key={cat}>
                <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
                  {cat.replace(/_/g, " ")}
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {group.map((p: any) => <PatternCard key={p.pattern_id} pattern={p} />)}
                </div>
              </div>
            );
          })}
        </>
      )}

      <p className="text-xs text-muted-foreground text-right">
        Updated {data.generated_at ?? "—"} · READ-ONLY · ADVISORY-ONLY
      </p>
    </div>
  );
}
