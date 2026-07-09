import React from "react";
import {
  useGetMarketReplay,
  getGetMarketReplayQueryKey,
  type GetMarketReplayHoldingPeriod,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  RefreshCcw, Flame, TrendingUp, TrendingDown, Eye, Ban,
  CheckCircle2, XCircle, MinusCircle, Clock3, ListOrdered,
} from "lucide-react";

// ── Config maps ───────────────────────────────────────────────────────────────

const ACTION_CONFIG: Record<string, { color: string; bg: string; icon: React.ReactNode }> = {
  "STRONG BUY": { color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30", icon: <Flame className="h-3.5 w-3.5" /> },
  "BUY":        { color: "text-green-400",   bg: "bg-green-500/10 border-green-500/30",     icon: <TrendingUp className="h-3.5 w-3.5" /> },
  "WATCH":      { color: "text-yellow-400",  bg: "bg-yellow-500/10 border-yellow-500/30",   icon: <Eye className="h-3.5 w-3.5" /> },
  "IGNORE":     { color: "text-muted-foreground", bg: "bg-muted/20 border-border/30",       icon: <Ban className="h-3.5 w-3.5" /> },
};

const OUTCOME_CONFIG: Record<string, { color: string; icon: React.ReactNode }> = {
  Correct: { color: "text-emerald-400", icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
  Wrong:   { color: "text-red-400",     icon: <XCircle className="h-3.5 w-3.5" /> },
  Neutral: { color: "text-yellow-400",  icon: <MinusCircle className="h-3.5 w-3.5" /> },
  Pending: { color: "text-muted-foreground", icon: <Clock3 className="h-3.5 w-3.5" /> },
};

const OUTCOME_LABEL_COLOR: Record<string, string> = {
  Excellent:    "text-emerald-400 bg-emerald-400/10 border-emerald-500/30",
  Good:         "text-lime-400 bg-lime-400/10 border-lime-500/30",
  Weak:         "text-yellow-400 bg-yellow-400/10 border-yellow-500/30",
  "Small Loss": "text-orange-400 bg-orange-400/10 border-orange-500/30",
  Failed:       "text-red-400 bg-red-400/10 border-red-500/30",
  Pending:      "text-muted-foreground bg-muted/20 border-border/30",
};

const HOLDING_PERIODS = [1, 3, 5, 10] as const;
const INTERVALS = ["daily", "hourly"] as const;

function defaultScanDate(): string {
  // Default to ~3 weeks ago so a 10-day holding period always has a settled outcome.
  const d = new Date();
  d.setDate(d.getDate() - 21);
  return d.toISOString().slice(0, 10);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SummaryCard({
  label, value, sub, color,
}: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">{label}</div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground mt-1 font-mono">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function ReplayRow({ item }: { item: any }) {
  const actionCfg = ACTION_CONFIG[item.historical_action] ?? ACTION_CONFIG["IGNORE"];
  const outcomeCfg = OUTCOME_CONFIG[item.outcome] ?? OUTCOME_CONFIG["Pending"];
  const returnPositive = (item.return_pct ?? 0) >= 0;

  return (
    <tr className="border-b border-border/30 hover:bg-muted/10 transition-colors align-top">
      <td className="py-2 px-3">
        <div className="font-mono font-bold text-sm">{item.stock}</div>
        <div className="text-[10px] text-muted-foreground font-mono">{item.sector}</div>
      </td>
      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{item.best_strategy_name || "—"}</td>
      <td className="py-2 px-3">
        <Badge variant="outline" className={`font-mono text-[10px] gap-1 ${actionCfg.bg} ${actionCfg.color}`}>
          {actionCfg.icon}
          {item.historical_action}
        </Badge>
      </td>
      <td className="py-2 px-3 text-sm font-mono">
        {item.price_on_scan_date ? `₹${item.price_on_scan_date.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "—"}
      </td>
      <td className="py-2 px-3 text-sm font-mono">
        {item.price_after_holding != null ? `₹${item.price_after_holding.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : "—"}
      </td>
      <td className="py-2 px-3">
        {item.return_pct != null ? (
          <span className={`text-sm font-mono font-bold flex items-center gap-1 ${returnPositive ? "text-emerald-400" : "text-red-400"}`}>
            {returnPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {returnPositive ? "+" : ""}{item.return_pct.toFixed(2)}%
          </span>
        ) : (
          <span className="text-xs text-muted-foreground font-mono">—</span>
        )}
      </td>
      <td className="py-2 px-3">
        <span className={`text-xs font-mono font-bold flex items-center gap-1 ${outcomeCfg.color}`}>
          {outcomeCfg.icon}
          {item.outcome}
        </span>
      </td>
      <td className="py-2 px-3">
        <Badge variant="outline" className={`font-mono text-[10px] ${OUTCOME_LABEL_COLOR[item.outcome_label] ?? OUTCOME_LABEL_COLOR.Pending}`}>
          {item.outcome_label}
        </Badge>
      </td>
      <td className="py-2 px-3 text-xs text-muted-foreground max-w-xs">
        <div className="font-mono">{item.why_signal}</div>
        {item.what_happened && (
          <div className="font-mono mt-1 text-muted-foreground/70">{item.what_happened}</div>
        )}
        {item.error && (
          <div className="font-mono mt-1 text-red-400/80">{item.error}</div>
        )}
      </td>
    </tr>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MarketReplay() {
  const [scanDate, setScanDate] = React.useState(defaultScanDate());
  const [holdingPeriod, setHoldingPeriod] = React.useState<GetMarketReplayHoldingPeriod>(5);
  const [interval, setInterval] = React.useState<"daily" | "hourly">("daily");

  const params = { scan_date: scanDate, holding_period: holdingPeriod, interval };
  const { data, isLoading, isFetching, refetch, error } = useGetMarketReplay(
    params,
    { query: { queryKey: getGetMarketReplayQueryKey(params), enabled: Boolean(scanDate) } },
  );

  const summary = data?.summary;
  const items = data?.items ?? [];

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Market Replay</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Historical scan on a past date, compared against real outcomes — paper trading only, no lookahead bias
          </p>
        </div>
      </div>

      {/* Controls */}
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardContent className="p-4 flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Scan date</label>
            <input
              type="date"
              value={scanDate}
              max={new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
              onChange={(e) => setScanDate(e.target.value)}
              className="bg-background border border-border rounded px-2 py-1.5 text-sm font-mono"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Holding period</label>
            <div className="flex gap-1">
              {HOLDING_PERIODS.map((hp) => (
                <button
                  key={hp}
                  onClick={() => setHoldingPeriod(hp)}
                  className={`px-3 py-1.5 rounded text-xs font-mono border transition-colors ${
                    holdingPeriod === hp
                      ? "bg-primary text-primary-foreground border-primary"
                      : "border-border text-muted-foreground hover:bg-muted/40"
                  }`}
                >
                  {hp}d
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Interval</label>
            <div className="flex gap-1">
              {INTERVALS.map((iv) => (
                <button
                  key={iv}
                  onClick={() => setInterval(iv)}
                  className={`px-3 py-1.5 rounded text-xs font-mono border capitalize transition-colors ${
                    interval === iv
                      ? "bg-primary text-primary-foreground border-primary"
                      : "border-border text-muted-foreground hover:bg-muted/40"
                  }`}
                >
                  {iv}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded border border-border hover:bg-muted/40 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50 ml-auto"
          >
            <RefreshCcw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
            Run Replay
          </button>
        </CardContent>
      </Card>

      {error && (
        <Card className="bg-red-500/10 border-red-500/30">
          <CardContent className="p-4 text-sm font-mono text-red-400">
            {(error as any)?.message ?? "Failed to run market replay"}
          </CardContent>
        </Card>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-4">
            <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
            <p className="text-muted-foreground font-mono text-sm">REPLAYING SCAN ON {scanDate}...</p>
            <p className="text-muted-foreground/60 text-xs">Fetching historical data and comparing signals with actual outcomes — may take ~20-30s</p>
          </div>
        </div>
      )}

      {!isLoading && data && (
        <>
          {/* Accuracy summary */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <SummaryCard label="Scanned" value={summary?.total_scanned ?? 0} sub="stocks" />
            <SummaryCard label="Accuracy" value={`${summary?.accuracy_pct ?? 0}%`} sub={`${summary?.correct_calls ?? 0} correct / ${summary?.wrong_calls ?? 0} wrong`} color="text-emerald-400" />
            <SummaryCard label="Avg Return" value={`${(summary?.avg_return_pct ?? 0) >= 0 ? "+" : ""}${summary?.avg_return_pct ?? 0}%`} color={(summary?.avg_return_pct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"} />
            <SummaryCard label="Buy Signals" value={summary?.buy_signals ?? 0} color="text-green-400" />
            <SummaryCard label="Watch Signals" value={summary?.watch_signals ?? 0} color="text-yellow-400" />
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <Card className="bg-card/50 backdrop-blur border-border/50">
              <CardContent className="p-4">
                <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">Best Signal</div>
                <div className="text-xl font-bold font-mono text-emerald-400">{summary?.best_signal ?? "—"}</div>
                <div className="text-xs text-muted-foreground font-mono mt-1">
                  {(summary?.best_signal_return ?? 0) >= 0 ? "+" : ""}{summary?.best_signal_return ?? 0}% over {summary?.holding_period}d
                </div>
              </CardContent>
            </Card>
            <Card className="bg-card/50 backdrop-blur border-border/50">
              <CardContent className="p-4">
                <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">Worst Signal</div>
                <div className="text-xl font-bold font-mono text-red-400">{summary?.worst_signal ?? "—"}</div>
                <div className="text-xs text-muted-foreground font-mono mt-1">
                  {(summary?.worst_signal_return ?? 0) >= 0 ? "+" : ""}{summary?.worst_signal_return ?? 0}% over {summary?.holding_period}d
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Performance Analytics */}
          {summary && (
            <Card className="bg-card/50 backdrop-blur border-border/50">
              <CardHeader className="py-3 px-4 border-b border-border/50">
                <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                  Performance Analytics — simulated equal-weighted paper trades on taken signals
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 space-y-4">
                {summary.reliability_warning && (
                  <div className="text-xs font-mono text-yellow-400/90 bg-yellow-400/5 border border-yellow-500/20 rounded px-3 py-2">
                    {summary.reliability_warning}
                  </div>
                )}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <SummaryCard label="Starting Capital" value={`₹${summary.starting_capital.toLocaleString("en-IN")}`} />
                  <SummaryCard
                    label="Ending Capital"
                    value={`₹${summary.ending_capital.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`}
                    sub={`${summary.total_return_pct >= 0 ? "+" : ""}${summary.total_return_pct.toFixed(2)}%`}
                    color={summary.total_return_pct >= 0 ? "text-emerald-400" : "text-red-400"}
                  />
                  <SummaryCard
                    label="Expectancy / Trade"
                    value={`₹${summary.expectancy.toFixed(0)}`}
                    color={summary.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}
                  />
                  <SummaryCard label="Max Drawdown" value={`${summary.max_drawdown_pct.toFixed(2)}%`} color="text-red-400" />
                  <SummaryCard label="Max Consecutive Wins" value={summary.max_consecutive_wins} color="text-emerald-400" />
                  <SummaryCard label="Max Consecutive Losses" value={summary.max_consecutive_losses} color="text-red-400" />
                </div>
              </CardContent>
            </Card>
          )}

          {/* Outcome comparison table */}
          <Card className="bg-card/50 backdrop-blur border-border/50">
            <CardHeader className="py-3 px-4 border-b border-border/50">
              <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                <ListOrdered className="h-3.5 w-3.5" />
                Outcome Comparison — {scanDate} + {holdingPeriod}d ({interval})
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0 overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-border/50 text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
                    <th className="py-2 px-3">Stock</th>
                    <th className="py-2 px-3">Strategy</th>
                    <th className="py-2 px-3">Historical Signal</th>
                    <th className="py-2 px-3">Price on scan date</th>
                    <th className="py-2 px-3">Price after {holdingPeriod}d</th>
                    <th className="py-2 px-3">Return</th>
                    <th className="py-2 px-3">Outcome</th>
                    <th className="py-2 px-3">Grade</th>
                    <th className="py-2 px-3">Explanation</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <ReplayRow key={item.stock} item={item} />
                  ))}
                </tbody>
              </table>
              {items.length === 0 && (
                <div className="py-8 text-center text-muted-foreground text-sm font-mono">
                  No results for this date
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
