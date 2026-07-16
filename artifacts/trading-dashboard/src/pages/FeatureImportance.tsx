import React from "react";
import {
  useGetFeatureImportance,
  getGetFeatureImportanceQueryKey,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart3,
  RefreshCcw,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  ShieldCheck,
} from "lucide-react";
import DataFreshnessBar from "@/components/DataFreshnessBar";

function SummaryCard({ label, value, color, sub }: {
  label: string; value: string | number; color?: string; sub?: string;
}) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">{label}</div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
        {sub && <div className="text-[11px] font-mono text-muted-foreground mt-0.5">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function TrendBadge({ trend }: { trend: string }) {
  if (trend === "GAINING") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-mono font-bold text-emerald-400">
        <TrendingUp className="h-3 w-3" /> GAINING
      </span>
    );
  }
  if (trend === "LOSING") {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-red-500/30 bg-red-500/10 px-1.5 py-0.5 text-[10px] font-mono font-bold text-red-400">
        <TrendingDown className="h-3 w-3" /> LOSING
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded border border-border bg-muted/30 px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
      <Minus className="h-3 w-3" /> STABLE
    </span>
  );
}

export default function FeatureImportance() {
  const { data, isLoading, refetch, isFetching } = useGetFeatureImportance(
    undefined,
    { query: { queryKey: getGetFeatureImportanceQueryKey() } },
  );

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">ANALYZING FEATURE IMPORTANCE...</p>
        </div>
      </div>
    );
  }

  const features = data?.features ?? [];
  const maxImportance = Math.max(0.0001, ...features.map((f) => f.importance));
  const mostValuable = features[0];
  const mostHarmfulShift = [...features]
    .filter((f) => f.worst_value && f.worst_value_lift < 0)
    .sort((a, b) => a.worst_value_lift - b.worst_value_lift)[0];
  const gaining = features.filter((f) => f.trend === "GAINING").length;
  const losing = features.filter((f) => f.trend === "LOSING").length;

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BarChart3 className="h-6 w-6 text-primary" />
            Feature Importance
          </h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Which market conditions consistently predicted success across {data?.total_trades ?? 0} completed historical trades — research only
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded border border-border hover:bg-muted/40 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
          data-testid="button-refresh-feature-importance"
        >
          <RefreshCcw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <DataFreshnessBar
        variant="historical"
        datasetLabel="Feature importance dataset"
        sampleSize={data?.total_trades ? `${data.total_trades} trades` : undefined}
      />

      {features.length === 0 ? (
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="py-10 text-center text-muted-foreground font-mono text-sm">
            No feature-importance data yet — build the Historical Knowledge Base first.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SummaryCard
              label="Most valuable indicator"
              value={mostValuable?.label ?? "—"}
              color="text-emerald-400"
              sub={mostValuable ? `${mostValuable.contribution_pct.toFixed(1)}% of predictive power` : undefined}
            />
            <SummaryCard
              label="Strongest warning sign"
              value={mostHarmfulShift?.worst_value ?? "None found"}
              color="text-red-400"
              sub={mostHarmfulShift ? `${Math.abs(mostHarmfulShift.worst_value_lift).toFixed(1)}% more common among losers` : undefined}
            />
            <SummaryCard label="Gaining importance" value={gaining} color="text-emerald-400" sub="indicators trending up" />
            <SummaryCard label="Losing importance" value={losing} color="text-red-400" sub="indicators trending down" />
          </div>

          <Card className="bg-card/50 backdrop-blur border-border/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-mono uppercase text-muted-foreground">
                Ranked predictive importance
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {features.map((f, i) => (
                  <div key={f.feature} data-testid={`row-feature-${f.feature}`}>
                    <div className="flex items-center justify-between gap-2 mb-1 flex-wrap">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-muted-foreground w-5">#{i + 1}</span>
                        <span className="text-sm font-semibold">{f.label}</span>
                        <TrendBadge trend={f.trend} />
                      </div>
                      <div className="flex items-center gap-3 text-[11px] font-mono text-muted-foreground">
                        <span>contribution <span className="text-foreground font-bold">{f.contribution_pct.toFixed(1)}%</span></span>
                        <span>weight <span className="text-foreground font-bold">{f.current_weight.toFixed(1)}</span>{f.current_weight.toFixed(1) !== f.static_weight.toFixed(1) && <span> (was {f.static_weight.toFixed(1)})</span>}</span>
                        <span>{f.sample_size.toLocaleString()} trades</span>
                        <span>confidence {(f.confidence * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                    <div className="h-2 rounded bg-muted/40 overflow-hidden">
                      <div
                        className={`h-full rounded ${f.direction === "HARMFUL" ? "bg-red-500/70" : "bg-emerald-500/70"}`}
                        style={{ width: `${(f.importance / maxImportance) * 100}%` }}
                      />
                    </div>
                    <div className="text-[11px] font-mono text-muted-foreground mt-0.5 flex flex-wrap gap-x-4">
                      {f.best_value && (
                        <span>
                          Best signal: <span className="text-emerald-400">{f.best_value}</span>
                          {" "}(+{f.best_value_lift.toFixed(1)}% among winners)
                        </span>
                      )}
                      {f.worst_value && f.worst_value_lift < 0 && (
                        <span>
                          Warning sign: <span className="text-red-400">{f.worst_value}</span>
                          {" "}({Math.abs(f.worst_value_lift).toFixed(1)}% more among losers)
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card/50 backdrop-blur border-border/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-mono uppercase text-muted-foreground flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-primary" />
                Dynamic weight safety
              </CardTitle>
            </CardHeader>
            <CardContent className="text-xs font-mono space-y-1.5 text-muted-foreground">
              <div className="flex justify-between">
                <span>Similarity weights</span>
                <span className="text-foreground font-bold" data-testid="text-weights-status">
                  {data?.weights_dynamic ? "EVIDENCE-ADJUSTED" : "STATIC BASELINE"}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Last recomputed</span>
                <span className="text-foreground">{data?.updated_at ?? "—"}</span>
              </div>
              <div className="flex justify-between">
                <span>Completed trades until next weight update</span>
                <span className="text-foreground font-bold">{data?.trades_until_next_update ?? "—"}</span>
              </div>
              <div className="flex justify-between">
                <span>Minimum new trades per update</span>
                <span className="text-foreground">{data?.min_new_trades_per_update ?? 50}</span>
              </div>
              <p className="text-[11px] text-foreground/70 pt-1">
                Weights rebalance gradually (80% previous + 20% evidence, capped at ±15% per
                feature per update, always totalling 100). No single trade can significantly
                alter the model.
              </p>
            </CardContent>
          </Card>

          <p className="text-[11px] text-yellow-400/80 flex items-start gap-1 font-mono">
            <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
            {data?.safety}
          </p>
        </>
      )}
    </div>
  );
}
