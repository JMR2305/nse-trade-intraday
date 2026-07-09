import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetHistoricalKnowledgeSummary,
  getGetHistoricalKnowledgeSummaryQueryKey,
  useBuildHistoricalKnowledge,
  useGetHistoricalKnowledgeTrades,
  getGetHistoricalKnowledgeTradesQueryKey,
  type HistoricalKnowledgeGroupStat,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  BookOpenText, Loader2, Play, AlertTriangle, TrendingUp, TrendingDown,
  Database, Layers, Target,
} from "lucide-react";
import { cn } from "@/lib/utils";

const STRATEGY_LABELS: Record<string, string> = {
  ema_cross: "EMA Cross",
  macd_cross: "MACD Cross",
  mean_reversion: "RSI Mean Reversion",
  trend_rider: "Trend Rider",
  breakout_hunter: "Breakout",
  supertrend_follow: "Supertrend",
};

function Stat({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="bg-zinc-800/50 rounded-md p-3">
      <div className="text-[10px] text-muted-foreground font-mono mb-1 uppercase tracking-wide">{label}</div>
      <div className={cn("text-lg font-mono font-bold", valueClass ?? "text-foreground")}>{value}</div>
    </div>
  );
}

function GroupCard({ title, stat, positive }: {
  title: string;
  stat: HistoricalKnowledgeGroupStat | undefined;
  positive: boolean;
}) {
  return (
    <div className="bg-zinc-800/50 rounded-md p-3">
      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground font-mono mb-1 uppercase tracking-wide">
        {positive ? <TrendingUp className="h-3 w-3 text-emerald-400" /> : <TrendingDown className="h-3 w-3 text-red-400" />}
        {title}
      </div>
      {stat ? (
        <>
          <div className="text-sm font-mono font-bold">{STRATEGY_LABELS[stat.name] ?? stat.name}</div>
          <div className="text-xs font-mono text-muted-foreground mt-0.5">
            {stat.trades} trades · WR {stat.win_rate.toFixed(0)}% ·{" "}
            <span className={stat.avg_return >= 0 ? "text-emerald-400" : "text-red-400"}>
              {stat.avg_return > 0 ? "+" : ""}{stat.avg_return.toFixed(2)}%
            </span>{" "}
            avg
          </div>
        </>
      ) : (
        <div className="text-xs font-mono text-muted-foreground">Not enough data yet</div>
      )}
    </div>
  );
}

export default function HistoricalKnowledge() {
  const [years, setYears] = useState<1 | 3 | 5>(5);
  // Poll aggressively for a short window after a build is kicked off, even if
  // the status file hasn't flipped to "running" yet (the build process takes
  // a few seconds to boot).
  const [pollUntil, setPollUntil] = useState(0);
  const queryClient = useQueryClient();

  const { data: summary, isLoading } = useGetHistoricalKnowledgeSummary({
    query: {
      queryKey: getGetHistoricalKnowledgeSummaryQueryKey(),
      refetchInterval: (q) =>
        q.state.data?.build?.status === "running" || Date.now() < pollUntil
          ? 3000
          : false,
    },
  });

  const build = summary?.build;
  const running = build?.status === "running";

  const buildMutation = useBuildHistoricalKnowledge({
    mutation: {
      onSuccess: () => {
        setPollUntil(Date.now() + 30_000);
        queryClient.invalidateQueries({ queryKey: getGetHistoricalKnowledgeSummaryQueryKey() });
      },
    },
  });

  const { data: tradesPage } = useGetHistoricalKnowledgeTrades(
    { limit: 25 },
    {
      query: {
        queryKey: getGetHistoricalKnowledgeTradesQueryKey({ limit: 25 }),
        enabled: (summary?.total_trades ?? 0) > 0,
      },
    },
  );

  const hasData = (summary?.total_trades ?? 0) > 0;

  return (
    <div className="p-6 space-y-4 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BookOpenText className="h-6 w-6 text-primary" />
            Historical Knowledge
          </h1>
          <p className="text-sm text-muted-foreground font-mono mt-1">
            Simulated strategy history from Yahoo Finance · NIFTY 50 · research dataset
          </p>
        </div>
        <div className="flex items-center gap-2">
          {([1, 3, 5] as const).map((y) => (
            <button
              key={y}
              onClick={() => setYears(y)}
              disabled={running}
              className={cn(
                "px-2.5 py-1 rounded-md text-xs font-mono border",
                years === y
                  ? "border-primary text-primary bg-primary/10"
                  : "border-zinc-700 text-muted-foreground hover:text-foreground",
              )}
              data-testid={`button-years-${y}`}
            >
              {y}Y
            </button>
          ))}
          <Button
            size="sm"
            onClick={() => buildMutation.mutate({ data: { years } })}
            disabled={running || buildMutation.isPending}
            data-testid="button-build-knowledge"
          >
            {running || buildMutation.isPending
              ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              : <Play className="h-4 w-4 mr-1.5" />}
            {running ? "Building…" : "Build Knowledge Base"}
          </Button>
        </div>
      </div>

      {/* Research warning */}
      <div className="flex items-center gap-2 text-xs font-mono text-orange-400 bg-orange-400/10 border border-orange-400/20 rounded-md px-3 py-2">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        This is historical simulation using Yahoo Finance data. It is for research only and not investment advice.
      </div>

      {/* Build status */}
      {build && build.status !== "idle" && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-mono flex items-center gap-2">
              <Database className="h-4 w-4 text-primary" />
              Build Status
              <Badge variant="outline" className={cn("font-mono text-[10px]",
                running ? "text-yellow-400 border-yellow-400/40" : "text-emerald-400 border-emerald-400/40")}>
                {build.status?.toUpperCase()}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              <Stat label="Stocks Processed" value={`${build.stocks_processed ?? 0} / ${build.stocks_total ?? 0}`} />
              <Stat label="Strategies" value={String(build.strategies?.length ?? 6)} />
              <Stat label="Trades Simulated" value={String(build.trades_generated ?? 0)} />
              <Stat label="New Trades Added" value={String(build.new_trades_inserted ?? 0)}
                valueClass={(build.new_trades_inserted ?? 0) > 0 ? "text-emerald-400" : undefined} />
              <Stat label="Symbols Skipped" value={String(build.skipped_symbols?.length ?? 0)}
                valueClass={(build.skipped_symbols?.length ?? 0) > 0 ? "text-orange-400" : undefined} />
            </div>
            {running && (
              <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${((build.stocks_processed ?? 0) / Math.max(1, build.stocks_total ?? 50)) * 100}%` }}
                />
              </div>
            )}
            {(build.logs?.length ?? 0) > 0 && (
              <details className="text-xs font-mono">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                  Build log ({build.logs!.length} entries)
                </summary>
                <div className="mt-2 max-h-48 overflow-y-auto space-y-0.5 bg-zinc-900/60 rounded-md p-2">
                  {build.logs!.slice().reverse().map((l, i) => (
                    <div key={i} className={cn(
                      l.startsWith("SKIP") || l.startsWith("ERROR") || l.startsWith("WARNING")
                        ? "text-orange-400" : "text-muted-foreground")}>
                      {l}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </CardContent>
        </Card>
      )}

      {/* Summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-mono flex items-center gap-2">
            <Layers className="h-4 w-4 text-primary" />
            Knowledge Base Summary
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm font-mono text-muted-foreground py-4">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : !hasData ? (
            <div className="text-sm font-mono text-muted-foreground py-4">
              No knowledge base yet. Choose a period and press "Build Knowledge Base" to
              simulate all 6 strategies across the NIFTY 50 using Yahoo Finance history.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2">
                <Stat label="Total Trades" value={String(summary!.total_trades)} />
                <Stat label="Winning" value={String(summary!.winning_trades)} valueClass="text-emerald-400" />
                <Stat label="Losing" value={String(summary!.losing_trades)} valueClass="text-red-400" />
                <Stat label="Win Rate" value={`${summary!.win_rate.toFixed(1)}%`}
                  valueClass={summary!.win_rate >= 50 ? "text-emerald-400" : "text-red-400"} />
                <Stat label="Avg Return" value={`${summary!.average_return > 0 ? "+" : ""}${summary!.average_return.toFixed(2)}%`}
                  valueClass={summary!.average_return >= 0 ? "text-emerald-400" : "text-red-400"} />
                <Stat label="Profit Factor" value={summary!.profit_factor.toFixed(2)}
                  valueClass={summary!.profit_factor >= 1 ? "text-emerald-400" : "text-red-400"} />
                <Stat label="Stocks Covered" value={String(summary!.stocks_covered)} />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                <GroupCard title="Best Strategy" stat={summary!.best_strategy} positive />
                <GroupCard title="Worst Strategy" stat={summary!.worst_strategy} positive={false} />
                <GroupCard title="Best Sector" stat={summary!.best_sector} positive />
                <GroupCard title="Worst Sector" stat={summary!.worst_sector} positive={false} />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent simulated trades */}
      {hasData && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-mono flex items-center gap-2">
              <Target className="h-4 w-4 text-primary" />
              Recent Simulated Trades
              <span className="text-muted-foreground font-normal">
                ({tradesPage?.total ?? 0} total)
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-muted-foreground border-b border-border/40 text-left">
                  <th className="py-1.5 px-2">SYMBOL</th>
                  <th className="py-1.5 px-2">STRATEGY</th>
                  <th className="py-1.5 px-2">ENTRY</th>
                  <th className="py-1.5 px-2">EXIT</th>
                  <th className="py-1.5 px-2 text-right">DAYS</th>
                  <th className="py-1.5 px-2 text-right">RETURN</th>
                  <th className="py-1.5 px-2">REGIME</th>
                  <th className="py-1.5 px-2">EXIT REASON</th>
                </tr>
              </thead>
              <tbody>
                {(tradesPage?.trades ?? []).map((t) => (
                  <tr key={t.id ?? `${t.symbol}-${t.strategy}-${t.entry_date}`}
                      className="border-b border-border/20">
                    <td className="py-1.5 px-2 font-bold">{t.symbol}</td>
                    <td className="py-1.5 px-2">{STRATEGY_LABELS[t.strategy] ?? t.strategy}</td>
                    <td className="py-1.5 px-2 text-muted-foreground">{t.entry_date}</td>
                    <td className="py-1.5 px-2 text-muted-foreground">{t.exit_date}</td>
                    <td className="py-1.5 px-2 text-right">{t.holding_days}</td>
                    <td className={cn("py-1.5 px-2 text-right font-bold",
                      (t.return_percent ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                      {(t.return_percent ?? 0) > 0 ? "+" : ""}{(t.return_percent ?? 0).toFixed(2)}%
                    </td>
                    <td className="py-1.5 px-2 text-muted-foreground">{t.market_regime}</td>
                    <td className="py-1.5 px-2 text-muted-foreground">{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
