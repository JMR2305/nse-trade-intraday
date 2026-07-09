import { useState } from "react";
import { useRunStrategyLab } from "@workspace/api-client-react";
import type { StrategyLabEntry } from "@workspace/api-client-react";
import {
  FlaskConical, Trophy, Download, TrendingUp, TrendingDown,
  Minus, AlertCircle, Loader2, Play,
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
  const dt = new Date();
  dt.setDate(dt.getDate() + d);
  return dt.toISOString().split("T")[0];
}

// ── Strategy type badge colours ─────────────────────────────────────────────
const TYPE_COLOR: Record<string, string> = {
  TREND:          "text-primary border-primary/40 bg-primary/10",
  BREAKOUT:       "text-yellow-400 border-yellow-400/40 bg-yellow-400/10",
  MEAN_REVERSION: "text-purple-400 border-purple-400/40 bg-purple-400/10",
};

// ── Helpers ─────────────────────────────────────────────────────────────────
function fmt(v: number, dec = 2) { return v.toFixed(dec); }
function pct(v: number)          { return `${v >= 0 ? "+" : ""}${fmt(v)}%`; }
function inr(v: number)          { return `${v >= 0 ? "+" : ""}₹${fmt(v)}`; }

function colourPnl(v: number) {
  if (v > 0)  return "text-emerald-400";
  if (v < 0)  return "text-red-400";
  return "text-muted-foreground";
}

/** Pick the "best" row: highest Sharpe; break ties by net_pnl */
function pickBest(rows: StrategyLabEntry[]): string {
  const valid = rows.filter(r => !r.error && r.total_trades > 0);
  if (!valid.length) return "";
  const sorted = [...valid].sort((a, b) =>
    b.sharpe_ratio !== a.sharpe_ratio
      ? b.sharpe_ratio - a.sharpe_ratio
      : b.net_pnl - a.net_pnl
  );
  return sorted[0].strategy_id;
}

// ── CSV export ───────────────────────────────────────────────────────────────
function exportCsv(rows: StrategyLabEntry[], symbol: string, period: string) {
  const headers = [
    "Strategy", "Type", "Best Regime",
    "Trades", "Win Rate %", "Net P&L (₹)", "P&L %",
    "Profit Factor", "Max Drawdown (₹)", "Max Drawdown %",
    "Sharpe Ratio", "Avg Hold (bars)", "Best Trade (₹)", "Worst Trade (₹)",
  ];
  const csvRows = rows.map(r => [
    r.strategy_name, r.strategy_type, r.best_regime,
    r.total_trades, fmt(r.win_rate), fmt(r.net_pnl), fmt(r.net_pnl_pct),
    fmt(r.profit_factor), fmt(r.max_drawdown), fmt(r.max_drawdown_pct),
    fmt(r.sharpe_ratio), fmt(r.avg_duration_bars), fmt(r.best_trade), fmt(r.worst_trade),
  ]);
  const csv = [headers, ...csvRows].map(row => row.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `strategy_lab_${symbol}_${period}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Column definitions ───────────────────────────────────────────────────────
interface Col {
  key:   string;
  label: string;
  title: string;
  render: (r: StrategyLabEntry) => React.ReactNode;
  better: "higher" | "lower" | "none";
}

const COLS: Col[] = [
  {
    key: "total_trades", label: "Trades", title: "Total number of completed trades",
    render: r => <span className="font-mono">{r.total_trades}</span>,
    better: "none",
  },
  {
    key: "win_rate", label: "Win Rate", title: "Winning trades ÷ total trades",
    render: r => (
      <span className={cn("font-mono", r.win_rate >= 50 ? "text-emerald-400" : r.win_rate > 0 ? "text-yellow-400" : "text-muted-foreground")}>
        {r.total_trades ? `${fmt(r.win_rate, 1)}%` : "—"}
      </span>
    ),
    better: "higher",
  },
  {
    key: "net_pnl", label: "Net P&L", title: "Net profit / loss for the period",
    render: r => (
      <span className={cn("font-mono", colourPnl(r.net_pnl))}>
        {r.total_trades ? inr(r.net_pnl) : "—"}
      </span>
    ),
    better: "higher",
  },
  {
    key: "profit_factor", label: "Profit Factor", title: "Gross profit ÷ gross loss (>1 = profitable)",
    render: r => {
      const pf = r.profit_factor;
      const cls = pf >= 1.5 ? "text-emerald-400" : pf >= 1 ? "text-yellow-400" : "text-red-400";
      return (
        <span className={cn("font-mono", r.total_trades ? cls : "text-muted-foreground")}>
          {r.total_trades ? fmt(pf) : "—"}
        </span>
      );
    },
    better: "higher",
  },
  {
    key: "max_drawdown_pct", label: "Max DD", title: "Maximum peak-to-trough drawdown as % of peak equity",
    render: r => (
      <span className={cn("font-mono", r.max_drawdown_pct > 5 ? "text-red-400" : r.max_drawdown_pct > 2 ? "text-yellow-400" : "text-muted-foreground")}>
        {r.total_trades ? `${fmt(r.max_drawdown_pct, 1)}%` : "—"}
      </span>
    ),
    better: "lower",
  },
  {
    key: "sharpe_ratio", label: "Sharpe", title: "Annualised Sharpe ratio (trade-level returns)",
    render: r => {
      const s = r.sharpe_ratio;
      const cls = s >= 1 ? "text-emerald-400" : s >= 0 ? "text-yellow-400" : "text-red-400";
      return (
        <span className={cn("font-mono", r.total_trades ? cls : "text-muted-foreground")}>
          {r.total_trades ? fmt(s) : "—"}
        </span>
      );
    },
    better: "higher",
  },
  {
    key: "avg_duration_bars", label: "Avg Hold", title: "Average trade duration in bars",
    render: r => (
      <span className="font-mono text-muted-foreground">
        {r.total_trades ? `${fmt(r.avg_duration_bars, 1)} bars` : "—"}
      </span>
    ),
    better: "none",
  },
  {
    key: "best_regime", label: "Best Regime", title: "Market conditions this strategy works best in",
    render: r => (
      <span className="text-xs text-muted-foreground whitespace-nowrap">{r.best_regime || "—"}</span>
    ),
    better: "none",
  },
];

// ── Sort header ──────────────────────────────────────────────────────────────
function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <span className="ml-1 opacity-20">↕</span>;
  return <span className="ml-1 text-primary">{dir === "asc" ? "↑" : "↓"}</span>;
}

// ══════════════════════════════════════════════════════════════════════════════
// Page
// ══════════════════════════════════════════════════════════════════════════════

export default function StrategyLab() {
  const [symbol,    setSymbol]    = useState("RELIANCE");
  const [periodIdx, setPeriodIdx] = useState(2);   // 1 Year
  const [interval,  setInterval]  = useState("1d");
  const [results,   setResults]   = useState<StrategyLabEntry[] | null>(null);
  const [sortCol,   setSortCol]   = useState("net_pnl");
  const [sortDir,   setSortDir]   = useState<"asc" | "desc">("desc");

  const runLab = useRunStrategyLab();

  const period     = PERIODS[periodIdx];
  const start_date = offset(period.days);
  const end_date   = today();

  function handleRun() {
    setResults(null);
    runLab.mutate(
      { data: { symbol, start_date, end_date, initial_capital: 5000, interval } },
      { onSuccess: (data) => setResults(data) },
    );
  }

  function handleSort(col: string) {
    if (sortCol === col) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  }

  const bestId = results ? pickBest(results) : "";

  const sorted = results ? [...results].sort((a, b) => {
    const colDef = COLS.find(c => c.key === sortCol);
    if (!colDef) return 0;
    const va = ((a as unknown) as Record<string, number>)[sortCol] ?? 0;
    const vb = ((b as unknown) as Record<string, number>)[sortCol] ?? 0;
    return sortDir === "asc" ? va - vb : vb - va;
  }) : [];

  // Summary cards for the best strategy
  const best = results?.find(r => r.strategy_id === bestId);

  const isLoading = runLab.isPending;
  const hasError  = runLab.isError;

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1400px]">
      {/* ── Header ── */}
      <div className="flex items-start gap-3">
        <FlaskConical className="mt-0.5 h-6 w-6 text-primary shrink-0" />
        <div>
          <h1 className="text-2xl font-bold font-mono tracking-tight">Strategy Lab</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Run all 6 strategies on the same data · side-by-side comparison · ₹5,000 capital
          </p>
        </div>
      </div>

      {/* ── Controls ── */}
      <div className="rounded border border-border bg-card p-4">
        <div className="flex flex-wrap items-end gap-4">
          {/* Stock */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Stock</label>
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary min-w-[140px]"
            >
              {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          {/* Period */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Period</label>
            <select
              value={periodIdx}
              onChange={e => setPeriodIdx(Number(e.target.value))}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary"
            >
              {PERIODS.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
            </select>
          </div>

          {/* Interval */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Interval</label>
            <select
              value={interval}
              onChange={e => setInterval(e.target.value)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary"
            >
              {INTERVALS.map(iv => <option key={iv.value} value={iv.value}>{iv.label}</option>)}
            </select>
          </div>

          {/* Date range display */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Date Range</label>
            <span className="text-sm font-mono text-muted-foreground py-1.5">
              {start_date} → {end_date}
            </span>
          </div>

          {/* Run button */}
          <button
            onClick={handleRun}
            disabled={isLoading}
            className="flex items-center gap-2 bg-primary text-primary-foreground font-mono text-sm px-5 py-1.5 rounded hover:bg-primary/90 disabled:opacity-60 disabled:cursor-not-allowed transition-colors ml-auto"
          >
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {isLoading ? "Running…" : "Run Lab"}
          </button>

          {/* Export CSV */}
          {results && (
            <button
              onClick={() => exportCsv(results, symbol, period.label.replace(" ", "_"))}
              className="flex items-center gap-2 border border-border text-sm font-mono px-4 py-1.5 rounded hover:bg-accent transition-colors"
            >
              <Download className="h-4 w-4" />
              Export CSV
            </button>
          )}
        </div>

        {/* Strategy pill list */}
        <div className="mt-3 flex flex-wrap gap-2">
          {["EMA Cross", "MACD Cross", "Mean Reversion", "Trend Rider", "Breakout Hunter", "Supertrend"].map(s => (
            <span key={s} className="text-xs font-mono border border-border rounded px-2 py-0.5 text-muted-foreground">
              {s}
            </span>
          ))}
        </div>
      </div>

      {/* ── Error ── */}
      {hasError && (
        <div className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to run Strategy Lab. Check API server is running.
        </div>
      )}

      {/* ── Loading skeleton ── */}
      {isLoading && (
        <div className="rounded border border-border bg-card p-8 flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm font-mono text-muted-foreground">
            Fetching {symbol} · computing indicators · running 6 strategies…
          </p>
          <div className="flex gap-2 mt-1">
            {["EMA Cross", "MACD Cross", "Mean Rev.", "Trend Rider", "Breakout", "Supertrend"].map((s, i) => (
              <span key={s} className="text-xs font-mono text-muted-foreground animate-pulse" style={{ animationDelay: `${i * 150}ms` }}>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Results ── */}
      {!isLoading && results && (
        <>
          {/* Best performer banner */}
          {best && (
            <div className="rounded border border-primary/30 bg-primary/5 p-4 flex items-center gap-4">
              <Trophy className="h-5 w-5 text-primary shrink-0" />
              <div>
                <div className="text-sm font-mono font-semibold text-primary">
                  Best Strategy — {best.strategy_name}
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  Sharpe {fmt(best.sharpe_ratio)} · Net P&L {inr(best.net_pnl)} ({pct(best.net_pnl_pct)}) · {best.total_trades} trades · Win Rate {fmt(best.win_rate, 1)}% · Best Regime: {best.best_regime}
                </div>
              </div>
            </div>
          )}

          {/* Comparison mini-cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {results.map(r => {
              const isBest = r.strategy_id === bestId;
              return (
                <div
                  key={r.strategy_id}
                  className={cn(
                    "rounded border bg-card p-3 flex flex-col gap-1",
                    isBest ? "border-primary/50 ring-1 ring-primary/20" : "border-border",
                  )}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-mono font-semibold truncate">{r.strategy_name}</span>
                    {isBest && <Trophy className="h-3 w-3 text-primary shrink-0" />}
                  </div>
                  <span className={cn(
                    "text-xs border rounded px-1 w-fit font-mono",
                    TYPE_COLOR[r.strategy_type] ?? "text-muted-foreground",
                  )}>
                    {r.strategy_type}
                  </span>
                  {r.error ? (
                    <span className="text-xs text-red-400 font-mono mt-1">Error</span>
                  ) : (
                    <>
                      <div className={cn("text-sm font-mono font-bold mt-1", colourPnl(r.net_pnl))}>
                        {r.total_trades ? inr(r.net_pnl) : "No trades"}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono">
                        {r.total_trades} trades · {fmt(r.win_rate, 0)}% WR
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          {/* Full comparison table */}
          <div className="rounded border border-border bg-card overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider sticky left-0 bg-card min-w-[160px]">
                    Strategy
                  </th>
                  {COLS.map(col => (
                    <th
                      key={col.key}
                      title={col.title}
                      onClick={() => handleSort(col.key)}
                      className="text-right px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider whitespace-nowrap cursor-pointer select-none hover:text-foreground transition-colors"
                    >
                      {col.label}
                      <SortIcon active={sortCol === col.key} dir={sortDir} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((r, idx) => {
                  const isBest = r.strategy_id === bestId;
                  return (
                    <tr
                      key={r.strategy_id}
                      className={cn(
                        "border-b border-border/50 transition-colors",
                        isBest   ? "bg-primary/5"  : idx % 2 === 0 ? "bg-card" : "bg-background/30",
                        "hover:bg-accent/30",
                      )}
                    >
                      {/* Strategy name cell */}
                      <td className="px-4 py-3 sticky left-0 bg-inherit">
                        <div className="flex items-center gap-2">
                          {isBest && <Trophy className="h-3.5 w-3.5 text-primary shrink-0" />}
                          <div>
                            <div className="font-mono font-semibold text-sm">{r.strategy_name}</div>
                            <div className="flex items-center gap-1 mt-0.5">
                              <span className={cn(
                                "text-[10px] border rounded px-1 font-mono",
                                TYPE_COLOR[r.strategy_type] ?? "text-muted-foreground",
                              )}>
                                {r.strategy_type}
                              </span>
                              {r.error && (
                                <span className="text-[10px] text-red-400 font-mono">ERROR</span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Metric cells */}
                      {COLS.map(col => (
                        <td key={col.key} className="text-right px-4 py-3">
                          {r.error
                            ? <span className="text-xs text-red-400 font-mono">—</span>
                            : col.render(r)
                          }
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-4 text-xs font-mono text-muted-foreground">
            <span className="flex items-center gap-1">
              <TrendingUp className="h-3 w-3 text-emerald-400" /> Profitable
            </span>
            <span className="flex items-center gap-1">
              <TrendingDown className="h-3 w-3 text-red-400" /> Loss
            </span>
            <span className="flex items-center gap-1">
              <Minus className="h-3 w-3 text-muted-foreground" /> No trades / neutral
            </span>
            <span className="ml-auto">Click column headers to sort · ₹5,000 initial capital · paper trading only</span>
          </div>
        </>
      )}

      {/* ── Empty state ── */}
      {!isLoading && !results && !hasError && (
        <div className="rounded border border-border bg-card p-12 flex flex-col items-center gap-3 text-center">
          <FlaskConical className="h-10 w-10 text-muted-foreground/40" />
          <p className="text-sm font-mono text-muted-foreground max-w-sm">
            Select a stock, period, and interval above — then click{" "}
            <span className="text-primary">Run Lab</span> to compare all 6 strategies side-by-side.
          </p>
          <p className="text-xs text-muted-foreground/60 font-mono">
            Data fetched once · indicators computed once · 6 strategies run sequentially
          </p>
        </div>
      )}
    </div>
  );
}
