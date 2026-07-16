import React, { useState } from "react";
import {
  useGetPatternQuality,
  getGetPatternQualityQueryKey,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Gauge, RefreshCcw, ListOrdered } from "lucide-react";
import DataFreshnessBar from "@/components/DataFreshnessBar";

const RATING_COLOR: Record<string, string> = {
  Excellent: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  Good:      "text-green-400 bg-green-500/10 border-green-500/30",
  Neutral:   "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  Poor:      "text-orange-400 bg-orange-500/10 border-orange-500/30",
  Negative:  "text-red-400 bg-red-500/10 border-red-500/30",
};

const RATING_FILTERS = ["All", "Excellent", "Good", "Neutral", "Poor", "Negative"];

function titleize(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function RatingBadge({ rating }: { rating?: string }) {
  const r = rating ?? "Neutral";
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-mono font-bold ${RATING_COLOR[r] ?? RATING_COLOR.Neutral}`}>
      {r}
    </span>
  );
}

function SummaryCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">{label}</div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

export default function PatternQuality() {
  const { data, isLoading, refetch, isFetching } = useGetPatternQuality({
    query: { queryKey: getGetPatternQualityQueryKey() },
  });
  const [filter, setFilter] = useState("All");

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">COMPUTING PATTERN QUALITY...</p>
        </div>
      </div>
    );
  }

  const patterns = data?.patterns ?? [];
  const shown = filter === "All"
    ? patterns
    : patterns.filter((p) => p.expectancy_rating === filter);

  const counts: Record<string, number> = {};
  for (const p of patterns) {
    counts[p.expectancy_rating] = (counts[p.expectancy_rating] ?? 0) + 1;
  }

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Gauge className="h-6 w-6 text-primary" />
            Pattern Quality
          </h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Every strategy × sector × regime pattern ranked by expectancy — from {data?.knowledge_trades ?? 0} simulated historical trades, research only
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded border border-border hover:bg-muted/40 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
          data-testid="button-refresh-pattern-quality"
        >
          <RefreshCcw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <DataFreshnessBar
        variant="historical"
        datasetLabel="Pattern quality dataset"
        sampleSize={data?.knowledge_trades ? `${data.knowledge_trades} trades` : undefined}
      />

      {patterns.length === 0 ? (
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="py-10 text-center text-muted-foreground font-mono text-sm">
            Historical Knowledge Base is empty — build it from the Historical Knowledge page first.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <SummaryCard label="Excellent" value={counts["Excellent"] ?? 0} color="text-emerald-400" />
            <SummaryCard label="Good" value={counts["Good"] ?? 0} color="text-green-400" />
            <SummaryCard label="Neutral" value={counts["Neutral"] ?? 0} color="text-yellow-400" />
            <SummaryCard label="Poor" value={counts["Poor"] ?? 0} color="text-orange-400" />
            <SummaryCard label="Negative" value={counts["Negative"] ?? 0} color="text-red-400" />
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            {RATING_FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`text-xs font-mono px-2.5 py-1 rounded border transition-colors ${
                  filter === f
                    ? "border-primary text-primary bg-primary/10"
                    : "border-border text-muted-foreground hover:text-foreground hover:bg-muted/40"
                }`}
                data-testid={`filter-rating-${f.toLowerCase()}`}
              >
                {f}{f !== "All" ? ` (${counts[f] ?? 0})` : ` (${patterns.length})`}
              </button>
            ))}
          </div>

          <Card className="bg-card/50 backdrop-blur border-border/50">
            <CardHeader className="py-3 px-4 border-b border-border/50">
              <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                <ListOrdered className="h-3.5 w-3.5" />
                Patterns Ranked by Expectancy — {shown.length} shown
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0 overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-border/50 text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
                    <th className="py-2 px-3">Rank</th>
                    <th className="py-2 px-3">Strategy</th>
                    <th className="py-2 px-3">Sector</th>
                    <th className="py-2 px-3">Regime</th>
                    <th className="py-2 px-3">Trades</th>
                    <th className="py-2 px-3">Win Rate</th>
                    <th className="py-2 px-3">PF</th>
                    <th className="py-2 px-3">Expectancy</th>
                    <th className="py-2 px-3">Sharpe</th>
                    <th className="py-2 px-3">Kelly</th>
                    <th className="py-2 px-3">Rating</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((p) => (
                    <tr key={p.rank} className="border-b border-border/30 hover:bg-muted/10" data-testid={`row-pattern-${p.rank}`}>
                      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">#{p.rank}</td>
                      <td className="py-2 px-3 text-xs font-mono">{titleize(String(p.strategy ?? "—"))}</td>
                      <td className="py-2 px-3 text-xs font-mono">{titleize(String(p.sector ?? "—"))}</td>
                      <td className="py-2 px-3 text-xs font-mono">{titleize(String(p.regime ?? "—"))}</td>
                      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{p.trades}</td>
                      <td className="py-2 px-3 text-xs font-mono">{p.win_rate.toFixed(1)}%</td>
                      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{p.profit_factor.toFixed(2)}</td>
                      <td className={`py-2 px-3 text-xs font-mono font-bold ${p.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {p.expectancy >= 0 ? "+" : ""}{p.expectancy.toFixed(2)}%
                      </td>
                      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{p.sharpe.toFixed(2)}</td>
                      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{p.kelly_percent.toFixed(0)}%</td>
                      <td className="py-2 px-3"><RatingBadge rating={p.expectancy_rating} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {shown.length === 0 && (
                <div className="py-6 text-center text-muted-foreground text-sm font-mono">
                  No patterns with this rating
                </div>
              )}
            </CardContent>
          </Card>

          {data?.warning && (
            <p className="text-[11px] font-mono text-muted-foreground/70">{data.warning}</p>
          )}
        </>
      )}
    </div>
  );
}
