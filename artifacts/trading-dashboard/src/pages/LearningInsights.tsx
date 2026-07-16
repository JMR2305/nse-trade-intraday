import React from "react";
import {
  useGetLearningInsights,
  getGetLearningInsightsQueryKey,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Brain, TrendingUp, TrendingDown, ShieldCheck, ShieldAlert,
  Building2, Activity, Grid3X3, RefreshCcw,
} from "lucide-react";
import DataFreshnessBar from "@/components/DataFreshnessBar";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrColor(wr: number): string {
  if (wr >= 60) return "text-emerald-400";
  if (wr >= 50) return "text-green-400";
  if (wr >= 45) return "text-yellow-400";
  return "text-red-400";
}

function heatCellColor(wr: number): string {
  if (wr >= 65) return "bg-emerald-500/60";
  if (wr >= 55) return "bg-emerald-500/35";
  if (wr >= 50) return "bg-yellow-500/30";
  if (wr >= 45) return "bg-orange-500/35";
  return "bg-red-500/45";
}

function titleize(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PatternTable({ title, icon, patterns, dims, extraCols = [] }: {
  title: string;
  icon: React.ReactNode;
  patterns: any[];
  dims: { key: string; label: string }[];
  extraCols?: { key: string; label: string; fmt?: (v: number) => string }[];
}) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardHeader className="py-3 px-4 border-b border-border/50">
        <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border/50 text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
              {dims.map((d) => (
                <th key={d.key} className="py-2 px-3">{d.label}</th>
              ))}
              <th className="py-2 px-3">Trades</th>
              <th className="py-2 px-3">Win Rate</th>
              <th className="py-2 px-3">Avg Return</th>
              <th className="py-2 px-3">PF</th>
              <th className="py-2 px-3">Expectancy</th>
              {extraCols.map((c) => (
                <th key={c.key} className="py-2 px-3">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {patterns.map((p, i) => (
              <tr key={i} className="border-b border-border/30 hover:bg-muted/10">
                {dims.map((d) => (
                  <td key={d.key} className="py-2 px-3 text-xs font-mono">{titleize(String(p[d.key] ?? "—"))}</td>
                ))}
                <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{p.trades}</td>
                <td className={`py-2 px-3 text-xs font-mono font-bold ${wrColor(p.win_rate)}`}>{p.win_rate.toFixed(1)}%</td>
                <td className={`py-2 px-3 text-xs font-mono ${p.average_return >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {p.average_return >= 0 ? "+" : ""}{p.average_return.toFixed(2)}%
                </td>
                <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{p.profit_factor.toFixed(2)}</td>
                <td className={`py-2 px-3 text-xs font-mono ${p.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {p.expectancy >= 0 ? "+" : ""}{p.expectancy.toFixed(2)}%
                </td>
                {extraCols.map((c) => (
                  <td key={c.key} className="py-2 px-3 text-xs font-mono text-muted-foreground">
                    {c.fmt ? c.fmt(Number(p[c.key] ?? 0)) : Number(p[c.key] ?? 0).toFixed(2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {patterns.length === 0 && (
          <div className="py-6 text-center text-muted-foreground text-sm font-mono">
            Not enough historical data yet
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Heatmap({ title, data }: { title: string; data: any }) {
  if (!data || !data.rows?.length) {
    return (
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="py-3 px-4 border-b border-border/50">
          <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <Grid3X3 className="h-3.5 w-3.5" />
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className="py-6 text-center text-muted-foreground text-sm font-mono">
          No data
        </CardContent>
      </Card>
    );
  }
  const cellMap = new Map<string, any>();
  for (const c of data.cells ?? []) cellMap.set(`${c.row}|${c.col}`, c);
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardHeader className="py-3 px-4 border-b border-border/50">
        <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
          <Grid3X3 className="h-3.5 w-3.5" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3 overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="py-1 px-2" />
              {data.cols.map((c: string) => (
                <th key={c} className="py-1 px-2 text-[10px] font-mono uppercase text-muted-foreground text-center">
                  {titleize(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r: string) => (
              <tr key={r}>
                <td className="py-1 px-2 text-[10px] font-mono uppercase text-muted-foreground whitespace-nowrap">
                  {titleize(r)}
                </td>
                {data.cols.map((c: string) => {
                  const cell = cellMap.get(`${r}|${c}`);
                  return (
                    <td key={c} className="p-0.5">
                      {cell ? (
                        <div
                          className={`rounded text-center py-1.5 ${heatCellColor(cell.win_rate)}`}
                          title={`${titleize(r)} × ${titleize(c)} — ${cell.trades} trades, ${cell.win_rate.toFixed(1)}% win rate, ${cell.average_return >= 0 ? "+" : ""}${cell.average_return.toFixed(2)}% avg return`}
                        >
                          <div className="text-[11px] font-mono font-bold">{cell.win_rate.toFixed(0)}%</div>
                          <div className="text-[9px] font-mono text-foreground/60">{cell.trades}</div>
                        </div>
                      ) : (
                        <div className="rounded text-center py-1.5 bg-muted/20 text-[10px] font-mono text-muted-foreground">—</div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-2 text-[10px] font-mono text-muted-foreground">
          Cell = win rate % over N historical trades
        </div>
      </CardContent>
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LearningInsights() {
  const { data, isLoading, refetch, isFetching } = useGetLearningInsights({
    query: { queryKey: getGetLearningInsightsQueryKey() },
  });

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">ANALYSING HISTORICAL KNOWLEDGE...</p>
        </div>
      </div>
    );
  }

  const heatmaps: any = data?.heatmaps ?? {};

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-primary" />
            Learning Insights
          </h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Deterministic patterns from {data?.knowledge_trades ?? 0} simulated historical trades — research only, paper trading
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded border border-border hover:bg-muted/40 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
          data-testid="button-refresh-insights"
        >
          <RefreshCcw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <DataFreshnessBar
        variant="historical"
        datasetLabel="Learning insights dataset"
        sampleSize={data?.knowledge_trades ? `${data.knowledge_trades} trades` : undefined}
      />

      {(data?.knowledge_trades ?? 0) === 0 ? (
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="py-10 text-center text-muted-foreground font-mono text-sm">
            Historical Knowledge Base is empty — build it from the Historical Knowledge page first.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid lg:grid-cols-2 gap-4">
            <PatternTable
              title="Top Performing Patterns"
              icon={<TrendingUp className="h-3.5 w-3.5 text-emerald-400" />}
              patterns={data?.top_patterns ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "sector", label: "Sector" },
                { key: "regime", label: "Regime" },
              ]}
            />
            <PatternTable
              title="Worst Performing Patterns"
              icon={<TrendingDown className="h-3.5 w-3.5 text-red-400" />}
              patterns={data?.worst_patterns ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "sector", label: "Sector" },
                { key: "regime", label: "Regime" },
              ]}
            />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <PatternTable
              title="Best Strategy by Sector"
              icon={<Building2 className="h-3.5 w-3.5 text-primary" />}
              patterns={data?.best_strategy_by_sector ?? []}
              dims={[
                { key: "sector", label: "Sector" },
                { key: "strategy", label: "Best Strategy" },
              ]}
            />
            <PatternTable
              title="Best Strategy by Market Regime"
              icon={<Activity className="h-3.5 w-3.5 text-primary" />}
              patterns={data?.best_strategy_by_regime ?? []}
              dims={[
                { key: "regime", label: "Regime" },
                { key: "strategy", label: "Best Strategy" },
              ]}
            />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <PatternTable
              title="Most Reliable Setups (30+ trades)"
              icon={<ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />}
              patterns={data?.most_reliable_setups ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "rsi_band", label: "RSI Band" },
                { key: "adx_band", label: "ADX Band" },
              ]}
            />
            <PatternTable
              title="Least Reliable Setups (30+ trades)"
              icon={<ShieldAlert className="h-3.5 w-3.5 text-red-400" />}
              patterns={data?.least_reliable_setups ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "rsi_band", label: "RSI Band" },
                { key: "adx_band", label: "ADX Band" },
              ]}
            />
          </div>

          {/* ── Expectancy Engine (Sprint 4) ── */}
          <div className="grid lg:grid-cols-2 gap-4">
            <PatternTable
              title="Top 20 by Expectancy"
              icon={<TrendingUp className="h-3.5 w-3.5 text-emerald-400" />}
              patterns={data?.top_expectancy_patterns ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "sector", label: "Sector" },
                { key: "regime", label: "Regime" },
              ]}
            />
            <PatternTable
              title="Bottom 20 by Expectancy"
              icon={<TrendingDown className="h-3.5 w-3.5 text-red-400" />}
              patterns={data?.lowest_expectancy_patterns ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "sector", label: "Sector" },
                { key: "regime", label: "Regime" },
              ]}
            />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <PatternTable
              title="Highest Sharpe (Most Consistent)"
              icon={<ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />}
              patterns={data?.highest_sharpe_patterns ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "sector", label: "Sector" },
                { key: "regime", label: "Regime" },
              ]}
              extraCols={[{ key: "sharpe", label: "Sharpe" }]}
            />
            <PatternTable
              title="Highest Kelly (Strongest Edge)"
              icon={<TrendingUp className="h-3.5 w-3.5 text-primary" />}
              patterns={data?.highest_kelly_patterns ?? []}
              dims={[
                { key: "strategy", label: "Strategy" },
                { key: "sector", label: "Sector" },
                { key: "regime", label: "Regime" },
              ]}
              extraCols={[{ key: "kelly_percent", label: "Kelly", fmt: (v) => `${v.toFixed(0)}%` }]}
            />
          </div>

          <PatternTable
            title="Largest Historical Drawdowns (Riskiest Patterns)"
            icon={<ShieldAlert className="h-3.5 w-3.5 text-red-400" />}
            patterns={data?.largest_drawdown_patterns ?? []}
            dims={[
              { key: "strategy", label: "Strategy" },
              { key: "sector", label: "Sector" },
              { key: "regime", label: "Regime" },
            ]}
            extraCols={[{ key: "max_drawdown", label: "Max DD", fmt: (v) => `${v.toFixed(1)}%` }]}
          />

          <div className="grid lg:grid-cols-3 gap-4">
            <PatternTable
              title="Best Risk-Adjusted Strategies"
              icon={<ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />}
              patterns={data?.best_risk_adjusted_strategies ?? []}
              dims={[{ key: "strategy", label: "Strategy" }]}
              extraCols={[{ key: "sharpe", label: "Sharpe" }]}
            />
            <PatternTable
              title="Best Long-Term Strategies (10+ days)"
              icon={<Activity className="h-3.5 w-3.5 text-primary" />}
              patterns={data?.best_long_term_strategies ?? []}
              dims={[{ key: "strategy", label: "Strategy" }]}
              extraCols={[{ key: "avg_holding_days", label: "Avg Hold", fmt: (v) => `${v.toFixed(0)}d` }]}
            />
            <PatternTable
              title="Best Swing Strategies (3-10 days)"
              icon={<Activity className="h-3.5 w-3.5 text-primary" />}
              patterns={data?.best_swing_strategies ?? []}
              dims={[{ key: "strategy", label: "Strategy" }]}
              extraCols={[{ key: "avg_holding_days", label: "Avg Hold", fmt: (v) => `${v.toFixed(0)}d` }]}
            />
          </div>

          <Heatmap title="Sector × Strategy" data={heatmaps.sector_strategy} />
          <Heatmap title="Regime × Strategy" data={heatmaps.regime_strategy} />
          <div className="grid lg:grid-cols-2 gap-4">
            <Heatmap title="RSI Band × Strategy" data={heatmaps.rsi_strategy} />
            <Heatmap title="ADX Band × Strategy" data={heatmaps.adx_strategy} />
          </div>

          {data?.warning && (
            <p className="text-[11px] font-mono text-muted-foreground/70">{data.warning}</p>
          )}
        </>
      )}
    </div>
  );
}
