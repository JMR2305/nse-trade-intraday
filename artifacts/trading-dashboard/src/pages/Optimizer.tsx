import { useState } from "react";
import { useRunOptimizer } from "@workspace/api-client-react";
import type { OptimizerResult } from "@workspace/api-client-react";
import {
  Settings2, Trophy, Download, AlertTriangle, AlertCircle,
  Loader2, Play, Info,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Constants ──────────────────────────────────────────────────────────────
const SYMBOLS = [
  "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
  "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
  "AXISBANK", "KOTAKBANK", "TATAMOTORS", "TITAN", "NESTLEIND",
];
const PERIODS = [
  { label: "3 Months", days: -90  },
  { label: "6 Months", days: -180 },
  { label: "1 Year",   days: -365 },
  { label: "2 Years",  days: -730 },
];
const INTERVALS = [
  { value: "1d", label: "Daily"  },
  { value: "1h", label: "Hourly" },
];

function today()           { return new Date().toISOString().split("T")[0]; }
function offset(d: number) {
  const dt = new Date(); dt.setDate(dt.getDate() + d);
  return dt.toISOString().split("T")[0];
}

// ── Strategy colours ────────────────────────────────────────────────────────
const STRAT_COLOR: Record<string, string> = {
  ema_cross:         "text-sky-400   border-sky-400/40   bg-sky-400/10",
  mean_reversion:    "text-purple-400 border-purple-400/40 bg-purple-400/10",
  trend_rider:       "text-primary   border-primary/40   bg-primary/10",
  supertrend_follow: "text-amber-400  border-amber-400/40  bg-amber-400/10",
};

// ── Helpers ─────────────────────────────────────────────────────────────────
function fmt(v: number, d = 2) { return v.toFixed(d); }
function colourPnl(v: number)  {
  return v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-muted-foreground";
}
function colourWr(v: number) {
  return v >= 50 ? "text-emerald-400" : v > 0 ? "text-yellow-400" : "text-muted-foreground";
}
function colourPf(v: number) {
  return v >= 1.5 ? "text-emerald-400" : v >= 1 ? "text-yellow-400" : "text-red-400";
}
function colourDd(v: number) {
  return v > 10 ? "text-red-400" : v > 5 ? "text-yellow-400" : "text-muted-foreground";
}
function colourSharpe(v: number) {
  return v >= 1 ? "text-emerald-400" : v >= 0 ? "text-yellow-400" : "text-red-400";
}

// ── Score bar ────────────────────────────────────────────────────────────────
function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(score / 85 * 100, 100));
  const clr = score >= 40 ? "bg-emerald-500" : score >= 20 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2 min-w-[90px]">
      <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", clr)} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-foreground w-8 text-right">{fmt(score, 1)}</span>
    </div>
  );
}

// ── Warning badge ─────────────────────────────────────────────────────────────
function WarnBadge({ warning }: { warning: string | null | undefined }) {
  if (!warning) return null;
  const isUnreliable = warning.toLowerCase().includes("reliable");
  return (
    <span className={cn(
      "inline-flex items-center gap-1 text-[10px] font-mono border rounded px-1.5 py-0.5 whitespace-nowrap",
      isUnreliable
        ? "text-orange-400 border-orange-400/40 bg-orange-400/10"
        : "text-yellow-400 border-yellow-400/40 bg-yellow-400/10",
    )}>
      <AlertTriangle className="h-2.5 w-2.5" />
      {warning}
    </span>
  );
}

// ── CSV export ───────────────────────────────────────────────────────────────
function exportCsv(rows: OptimizerResult[], symbol: string, period: string) {
  const headers = [
    "Rank", "Strategy", "Parameters",
    "Trades", "Win Rate %", "Net P&L (₹)", "P&L %",
    "Profit Factor", "Max Drawdown %", "Sharpe", "Score", "Warning",
  ];
  const csv = [headers, ...rows.map(r => [
    r.rank, r.strategy_name, r.parameters_display,
    r.total_trades, fmt(r.win_rate), fmt(r.net_pnl), fmt(r.net_pnl_pct),
    fmt(r.profit_factor), fmt(r.max_drawdown_pct), fmt(r.sharpe_ratio),
    fmt(r.score), r.warning ?? "",
  ])].map(row => row.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `optimizer_${symbol}_${period}.csv`; a.click();
  URL.revokeObjectURL(url);
}

// ── Scoring explanation tooltip ───────────────────────────────────────────────
function ScoreInfo() {
  return (
    <div className="group relative inline-flex">
      <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
      <div className="absolute bottom-full left-0 mb-1.5 hidden group-hover:block z-50 w-72 rounded border border-border bg-card p-3 text-xs font-mono shadow-lg">
        <div className="font-semibold mb-2 text-foreground">Score formula (0–85)</div>
        <div className="text-muted-foreground space-y-0.5">
          <div>Win Rate (÷100)    × 0.25</div>
          <div>Profit Factor (÷5) × 0.25</div>
          <div>Net P&L% (÷30)    × 0.20</div>
          <div>Sharpe (÷3)        × 0.15</div>
          <div>− Max DD% (÷30)   × 0.15</div>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page
// ══════════════════════════════════════════════════════════════════════════════
export default function Optimizer() {
  const [symbol,    setSymbol]    = useState("RELIANCE");
  const [periodIdx, setPeriodIdx] = useState(2);
  const [interval,  setInterval]  = useState("1d");
  const [results,   setResults]   = useState<OptimizerResult[] | null>(null);

  const runOpt = useRunOptimizer();

  const period     = PERIODS[periodIdx];
  const start_date = offset(period.days);
  const end_date   = today();

  function handleRun() {
    setResults(null);
    runOpt.mutate(
      { data: { symbol, start_date, end_date, initial_capital: 5000, interval, top_n: 10 } },
      { onSuccess: data => setResults(data) },
    );
  }

  const isLoading = runOpt.isPending;
  const hasError  = runOpt.isError;
  const best      = results?.[0];

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1400px]">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Settings2 className="mt-0.5 h-6 w-6 text-primary shrink-0" />
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold font-mono tracking-tight">Strategy Optimizer</h1>
            <span className="text-xs border border-primary/40 text-primary font-mono rounded px-1.5 py-0.5">v0.7</span>
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            51 parameter combinations · 4 strategies · composite scoring · top 10 ranked · ₹5,000 capital
          </p>
        </div>
      </div>

      {/* Controls */}
      <div className="rounded border border-border bg-card p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Stock</label>
            <select value={symbol} onChange={e => setSymbol(e.target.value)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary min-w-[140px]">
              {SYMBOLS.map(s => <option key={s}>{s}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Period</label>
            <select value={periodIdx} onChange={e => setPeriodIdx(Number(e.target.value))}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary">
              {PERIODS.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Interval</label>
            <select value={interval} onChange={e => setInterval(e.target.value)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary">
              {INTERVALS.map(iv => <option key={iv.value} value={iv.value}>{iv.label}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Date Range</label>
            <span className="text-sm font-mono text-muted-foreground py-1.5">{start_date} → {end_date}</span>
          </div>
          <button onClick={handleRun} disabled={isLoading}
            className="flex items-center gap-2 bg-primary text-primary-foreground font-mono text-sm px-5 py-1.5 rounded hover:bg-primary/90 disabled:opacity-60 disabled:cursor-not-allowed transition-colors ml-auto">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {isLoading ? "Optimizing…" : "Run Optimizer"}
          </button>
          {results && (
            <button onClick={() => exportCsv(results, symbol, period.label.replace(" ", "_"))}
              className="flex items-center gap-2 border border-border text-sm font-mono px-4 py-1.5 rounded hover:bg-accent transition-colors">
              <Download className="h-4 w-4" />
              Export CSV
            </button>
          )}
        </div>

        {/* Strategies being tested */}
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs font-mono text-muted-foreground">
          <div className="rounded border border-border px-2 py-1.5">
            <span className="text-sky-400">EMA Cross</span>
            <div className="mt-0.5 text-[10px]">Fast: 9/10/20 · Slow: 21/30/50</div>
            <div className="text-[10px]">9 combinations</div>
          </div>
          <div className="rounded border border-border px-2 py-1.5">
            <span className="text-purple-400">RSI Mean Reversion</span>
            <div className="mt-0.5 text-[10px]">Oversold: 25/30/35 · OB: 65/70/75</div>
            <div className="text-[10px]">9 combinations</div>
          </div>
          <div className="rounded border border-border px-2 py-1.5">
            <span className="text-primary">Trend Rider</span>
            <div className="mt-0.5 text-[10px]">EMA pairs · RSI range · ATR stop/target</div>
            <div className="text-[10px]">24 combinations</div>
          </div>
          <div className="rounded border border-border px-2 py-1.5">
            <span className="text-amber-400">Supertrend</span>
            <div className="mt-0.5 text-[10px]">Period: 7/10/14 · Multiplier: 2/3/4</div>
            <div className="text-[10px]">9 combinations</div>
          </div>
        </div>
      </div>

      {/* Error */}
      {hasError && (
        <div className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to run optimizer. Check API server is running.
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="rounded border border-border bg-card p-10 flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <div className="text-sm font-mono text-muted-foreground text-center">
            <div>Testing 51 parameter combinations on {symbol}…</div>
            <div className="text-xs mt-1 text-muted-foreground/60">
              EMA Cross (9) · RSI Mean Rev (9) · Trend Rider (24) · Supertrend (9)
            </div>
          </div>
          <div className="w-48 h-1 rounded-full bg-border overflow-hidden">
            <div className="h-full bg-primary rounded-full animate-pulse" style={{ width: "60%" }} />
          </div>
        </div>
      )}

      {/* Results */}
      {!isLoading && results && results.length > 0 && (
        <>
          {/* Best setup banner */}
          {best && (
            <div className="rounded border border-primary/40 bg-primary/5 p-4 flex items-start gap-4">
              <Trophy className="h-5 w-5 text-primary mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono font-semibold text-primary">
                    Best Setup — {best.strategy_name}
                  </span>
                  <span className={cn(
                    "text-xs border rounded px-1.5 py-0.5 font-mono",
                    STRAT_COLOR[best.strategy_id] ?? "text-muted-foreground",
                  )}>
                    {best.strategy_id}
                  </span>
                  {best.warning && <WarnBadge warning={best.warning} />}
                </div>
                <div className="text-xs font-mono text-muted-foreground mt-1 break-words">
                  {best.parameters_display}
                </div>
                <div className="flex flex-wrap gap-4 mt-2 text-xs font-mono">
                  <span>Score <span className="text-primary">{fmt(best.score, 1)}</span></span>
                  <span>Trades <span className="text-foreground">{best.total_trades}</span></span>
                  <span>Win Rate <span className={colourWr(best.win_rate)}>{fmt(best.win_rate, 1)}%</span></span>
                  <span>Net P&L <span className={colourPnl(best.net_pnl)}>₹{fmt(best.net_pnl)}</span></span>
                  <span>Profit Factor <span className={colourPf(best.profit_factor)}>{fmt(best.profit_factor)}</span></span>
                  <span>Sharpe <span className={colourSharpe(best.sharpe_ratio)}>{fmt(best.sharpe_ratio)}</span></span>
                </div>
              </div>
            </div>
          )}

          {/* Main table */}
          <div className="rounded border border-border bg-card overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-center px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider w-10">Rank</th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[140px]">Strategy</th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[220px]">Parameters</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Trades</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Win Rate</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Net P&L</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Prof. Factor</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Max DD</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Sharpe</th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[120px]">
                    <span className="flex items-center gap-1">Score <ScoreInfo /></span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, idx) => {
                  const isTop = r.rank === 1;
                  return (
                    <tr key={idx} className={cn(
                      "border-b border-border/50 transition-colors hover:bg-accent/20",
                      isTop ? "bg-primary/5" : idx % 2 === 0 ? "bg-card" : "bg-background/20",
                    )}>
                      {/* Rank */}
                      <td className="px-3 py-3 text-center">
                        {isTop ? (
                          <span className="inline-flex items-center justify-center h-6 w-6 rounded-full bg-primary/20 text-primary">
                            <Trophy className="h-3.5 w-3.5" />
                          </span>
                        ) : (
                          <span className="font-mono text-xs text-muted-foreground">#{r.rank}</span>
                        )}
                      </td>

                      {/* Strategy */}
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-1">
                          <span className="font-mono text-sm font-medium">{r.strategy_name}</span>
                          <span className={cn(
                            "text-[10px] border rounded px-1 w-fit font-mono",
                            STRAT_COLOR[r.strategy_id] ?? "text-muted-foreground",
                          )}>
                            {r.strategy_id}
                          </span>
                        </div>
                      </td>

                      {/* Parameters */}
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-1">
                          <span className="font-mono text-xs text-foreground">{r.parameters_display}</span>
                          {r.warning && <WarnBadge warning={r.warning} />}
                        </div>
                      </td>

                      {/* Trades */}
                      <td className="px-4 py-3 text-right font-mono text-sm">
                        <span className={r.total_trades === 0 ? "text-muted-foreground" : "text-foreground"}>
                          {r.total_trades}
                        </span>
                        {r.total_trades > 0 && (
                          <div className="text-[10px] text-muted-foreground">
                            {r.winning_trades}W/{r.losing_trades}L
                          </div>
                        )}
                      </td>

                      {/* Win Rate */}
                      <td className="px-4 py-3 text-right">
                        <span className={cn("font-mono text-sm", r.total_trades ? colourWr(r.win_rate) : "text-muted-foreground")}>
                          {r.total_trades ? `${fmt(r.win_rate, 1)}%` : "—"}
                        </span>
                      </td>

                      {/* Net P&L */}
                      <td className="px-4 py-3 text-right">
                        <span className={cn("font-mono text-sm", r.total_trades ? colourPnl(r.net_pnl) : "text-muted-foreground")}>
                          {r.total_trades ? `₹${fmt(r.net_pnl)}` : "—"}
                        </span>
                        {r.total_trades > 0 && (
                          <div className={cn("text-[10px]", colourPnl(r.net_pnl_pct))}>
                            {r.net_pnl_pct >= 0 ? "+" : ""}{fmt(r.net_pnl_pct)}%
                          </div>
                        )}
                      </td>

                      {/* Profit Factor */}
                      <td className="px-4 py-3 text-right">
                        <span className={cn("font-mono text-sm", r.total_trades ? colourPf(r.profit_factor) : "text-muted-foreground")}>
                          {r.total_trades ? fmt(r.profit_factor) : "—"}
                        </span>
                      </td>

                      {/* Max DD */}
                      <td className="px-4 py-3 text-right">
                        <span className={cn("font-mono text-sm", r.total_trades ? colourDd(r.max_drawdown_pct) : "text-muted-foreground")}>
                          {r.total_trades ? `${fmt(r.max_drawdown_pct, 1)}%` : "—"}
                        </span>
                      </td>

                      {/* Sharpe */}
                      <td className="px-4 py-3 text-right">
                        <span className={cn("font-mono text-sm", r.total_trades ? colourSharpe(r.sharpe_ratio) : "text-muted-foreground")}>
                          {r.total_trades ? fmt(r.sharpe_ratio) : "—"}
                        </span>
                      </td>

                      {/* Score bar */}
                      <td className="px-4 py-3">
                        <ScoreBar score={r.score} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Score formula footnote */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-mono text-muted-foreground/70">
            <span>Score (0–85) = Win Rate×0.25 + Profit Factor×0.25 + Net P&L×0.20 + Sharpe×0.15 − Max DD×0.15</span>
            <span className="ml-auto">₹5,000 capital · paper trading only · {results.length} of 51 combinations shown</span>
          </div>

          {/* Warning legend */}
          <div className="flex flex-wrap gap-4 text-xs font-mono text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1 border border-yellow-400/40 bg-yellow-400/10 text-yellow-400 rounded px-1.5 py-0.5">
                <AlertTriangle className="h-2.5 w-2.5" />Low sample size
              </span>
              &lt; 5 trades — results may not be statistically significant
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1 border border-orange-400/40 bg-orange-400/10 text-orange-400 rounded px-1.5 py-0.5">
                <AlertTriangle className="h-2.5 w-2.5" />Not reliable yet
              </span>
              100% win rate with &lt; 5 trades — may be overfitted
            </span>
          </div>
        </>
      )}

      {/* Empty state */}
      {!isLoading && !results && !hasError && (
        <div className="rounded border border-border bg-card p-12 flex flex-col items-center gap-3 text-center">
          <Settings2 className="h-10 w-10 text-muted-foreground/40" />
          <p className="text-sm font-mono text-muted-foreground max-w-md">
            Select a stock, period, and interval — then click{" "}
            <span className="text-primary">Run Optimizer</span> to test{" "}
            <span className="text-foreground">51 parameter combinations</span> across 4 strategies.
          </p>
          <p className="text-xs text-muted-foreground/60 font-mono">
            EMA Cross · RSI Mean Reversion · Trend Rider · Supertrend · all on the same data
          </p>
        </div>
      )}
    </div>
  );
}
