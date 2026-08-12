import { useState, useEffect } from "react";
import { useGetStrategies, useRunBacktest } from "@workspace/api-client-react";
import type { BacktestResult, BacktestTrade } from "@workspace/api-client-react";
import { FlaskConical, TrendingUp, TrendingDown, AlertTriangle, BarChart2, CheckCircle2, XCircle, Clock } from "lucide-react";
import { Link } from "wouter";
import { cn } from "@/lib/utils";
import DataFreshnessBar from "@/components/DataFreshnessBar";

// ── Watchlist symbols for quick selection ──────────────────────────────────
const SYMBOLS = [
  "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
  "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
  "AXISBANK", "KOTAKBANK", "TMPV", "TMCV", "TITAN", "NESTLEIND",
];

const PERIODS: { label: string; start: () => string; end: () => string }[] = [
  {
    label: "3 Months",
    start: () => offset(-90),
    end: () => today(),
  },
  {
    label: "6 Months",
    start: () => offset(-180),
    end: () => today(),
  },
  {
    label: "1 Year",
    start: () => offset(-365),
    end: () => today(),
  },
  {
    label: "2 Years",
    start: () => offset(-730),
    end: () => today(),
  },
];

const INTERVALS = [
  { value: "1d", label: "Daily" },
  { value: "1h", label: "Hourly" },
];

function today() {
  return new Date().toISOString().split("T")[0];
}
function offset(days: number) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split("T")[0];
}

// ── Sub-components ─────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "red" | "yellow" | "neutral";
}) {
  const colors: Record<string, string> = {
    green:   "text-emerald-400",
    red:     "text-red-400",
    yellow:  "text-yellow-400",
    neutral: "text-foreground",
  };
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="text-xs font-mono text-muted-foreground uppercase tracking-widest mb-1">
        {label}
      </div>
      <div className={cn("text-2xl font-mono font-bold", colors[accent ?? "neutral"])}>
        {value}
      </div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5 font-mono">{sub}</div>}
    </div>
  );
}

function ExitBadge({ reason }: { reason: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    TARGET:      { label: "TARGET",      cls: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30" },
    STOP:        { label: "STOP",        cls: "bg-red-500/10 text-red-400 border-red-500/30" },
    SIGNAL_EXIT: { label: "SIGNAL",      cls: "bg-blue-500/10 text-blue-400 border-blue-500/30" },
    END_OF_DATA: { label: "END",         cls: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30" },
  };
  const style = map[reason] ?? { label: reason, cls: "bg-muted text-muted-foreground border-border" };
  return (
    <span className={cn("text-xs font-mono px-2 py-0.5 rounded border", style.cls)}>
      {style.label}
    </span>
  );
}

function TradeRow({ trade, i }: { trade: BacktestTrade; i: number }) {
  const win = trade.pnl > 0;
  return (
    <tr className="border-b border-border/40 hover:bg-muted/30 transition-colors">
      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{trade.trade_no}</td>
      <td className="px-3 py-2 font-mono text-xs">{trade.entry_date.split("T")[0]}</td>
      <td className="px-3 py-2 font-mono text-xs">{trade.exit_date.split("T")[0]}</td>
      <td className="px-3 py-2 font-mono text-xs">₹{trade.entry_price.toFixed(2)}</td>
      <td className="px-3 py-2 font-mono text-xs">₹{trade.exit_price.toFixed(2)}</td>
      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{trade.quantity}</td>
      <td className={cn("px-3 py-2 font-mono text-xs font-bold", win ? "text-emerald-400" : "text-red-400")}>
        {win ? "+" : ""}₹{trade.pnl.toFixed(2)}
      </td>
      <td className={cn("px-3 py-2 font-mono text-xs", win ? "text-emerald-400" : "text-red-400")}>
        {win ? "+" : ""}{trade.pnl_pct.toFixed(2)}%
      </td>
      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{trade.duration_bars}d</td>
      <td className="px-3 py-2">
        <ExitBadge reason={trade.exit_reason} />
      </td>
    </tr>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function Backtest() {
  const [symbol, setSymbol]     = useState("RELIANCE");
  const [strategy, setStrategy] = useState("");
  const [periodIdx, setPeriodIdx] = useState(2);   // 1 Year default
  const [interval, setInterval] = useState("1d");
  const [capital, setCapital]   = useState(5000);
  const [result, setResult]     = useState<BacktestResult | null>(null);

  const { data: strategies = [], isLoading: loadingStrategies } = useGetStrategies();
  const runBacktest = useRunBacktest();

  // Auto-select first strategy once loaded
  useEffect(() => {
    if (strategies.length > 0 && strategy === "") {
      setStrategy(strategies[0].id);
    }
  }, [strategies]);

  const period = PERIODS[periodIdx];

  function handleRun() {
    if (!strategy) return;
    runBacktest.mutate(
      {
        data: {
          symbol,
          strategy,
          start_date: period.start(),
          end_date:   period.end(),
          initial_capital: capital,
          interval,
        },
      },
      {
        onSuccess: (data) => setResult(data as BacktestResult),
      },
    );
  }

  const running = runBacktest.isPending;

  // Derived metrics
  const pnlPos   = result && result.net_pnl >= 0;
  const ddBad    = result && result.max_drawdown_pct > 20;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <FlaskConical className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight font-mono">Backtest Engine — Single-Strategy Research</h1>
          <p className="text-sm text-muted-foreground font-mono">
            Walk-forward paper simulation · No real orders · ₹{capital.toLocaleString()} capital
          </p>
        </div>
        <Link href="/investigation-center"
          className="ml-auto text-xs text-primary underline underline-offset-2 whitespace-nowrap"
          data-testid="link-pipeline-backtest">
          Open Production Pipeline Backtest
        </Link>
      </div>

      <div className="bg-amber-500/10 border border-amber-500/40 rounded-lg px-4 py-3 text-xs text-amber-500 font-mono"
        data-testid="banner-not-canonical">
        This page runs a simple single-strategy simulator for quick research. It is NOT the canonical
        production-pipeline backtest — for &ldquo;what would the real system have done?&rdquo;, use the
        Production Pipeline Backtest (Investigation Center).
      </div>

      <DataFreshnessBar variant="historical" datasetLabel="Backtest dataset" />

      {/* ── Config form ─────────────────────────────────────────────────── */}
      <div className="bg-card border border-border rounded-lg p-5">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">

          {/* Symbol */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Stock</label>
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="bg-background border border-border rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {SYMBOLS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          {/* Strategy */}
          <div className="flex flex-col gap-1.5 col-span-2">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Strategy</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              disabled={loadingStrategies}
              className="bg-background border border-border rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          {/* Period */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Period</label>
            <select
              value={periodIdx}
              onChange={(e) => setPeriodIdx(Number(e.target.value))}
              className="bg-background border border-border rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {PERIODS.map((p, i) => (
                <option key={i} value={i}>{p.label}</option>
              ))}
            </select>
          </div>

          {/* Interval */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Interval</label>
            <select
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
              className="bg-background border border-border rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {INTERVALS.map((iv) => (
                <option key={iv.value} value={iv.value}>{iv.label}</option>
              ))}
            </select>
          </div>

          {/* Run button */}
          <div className="flex flex-col gap-1.5 justify-end">
            <button
              onClick={handleRun}
              disabled={running || !strategy}
              className={cn(
                "px-5 py-2 rounded-md font-mono text-sm font-bold transition-all",
                running
                  ? "bg-primary/50 text-primary-foreground cursor-wait"
                  : "bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95",
              )}
            >
              {running ? "Running…" : "▶ Run Backtest"}
            </button>
          </div>
        </div>

        {/* Strategy description */}
        {strategy && strategies.length > 0 && (() => {
          const s = strategies.find((x) => x.id === strategy);
          if (!s) return null;
          return (
            <div className="mt-4 pt-4 border-t border-border/50 flex flex-wrap gap-6">
              <div>
                <div className="text-xs text-muted-foreground font-mono mb-1">{s.description}</div>
                <div className="flex gap-2 mt-1">
                  <span className="text-xs bg-primary/10 text-primary border border-primary/20 rounded px-2 py-0.5 font-mono">{s.type}</span>
                  <span className="text-xs bg-muted text-muted-foreground border border-border rounded px-2 py-0.5 font-mono">{s.best_interval} bars</span>
                  <span className="text-xs bg-muted text-muted-foreground border border-border rounded px-2 py-0.5 font-mono">{(s.risk_pct * 100).toFixed(0)}% risk/trade</span>
                </div>
              </div>
              <div className="flex gap-6 text-xs font-mono">
                <div>
                  <div className="text-muted-foreground mb-1">ENTRY RULES</div>
                  {s.entry_rules.map((r, i) => (
                    <div key={i} className="text-foreground/80">· {r}</div>
                  ))}
                </div>
                <div>
                  <div className="text-muted-foreground mb-1">EXIT RULES</div>
                  {s.exit_rules.map((r, i) => (
                    <div key={i} className="text-foreground/80">· {r}</div>
                  ))}
                </div>
              </div>
            </div>
          );
        })()}
      </div>

      {/* ── Error ────────────────────────────────────────────────────────── */}
      {runBacktest.isError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 flex items-center gap-3 font-mono text-sm text-red-400">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {String(runBacktest.error)}
        </div>
      )}

      {/* ── Results ──────────────────────────────────────────────────────── */}
      {result && (
        <div className="space-y-5">
          {/* Engine error message */}
          {result.error && (
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 flex items-center gap-3 font-mono text-sm text-yellow-400">
              <AlertTriangle className="h-4 w-4 flex-shrink-0" />
              {result.error}
            </div>
          )}

          {/* Summary header */}
          <div className="flex items-center justify-between">
            <div className="font-mono text-sm text-muted-foreground">
              <span className="text-foreground font-bold">{result.symbol}</span>
              {" · "}{result.strategy_name}
              {" · "}{result.start_date.split("T")[0]} → {result.end_date.split("T")[0]}
              {" · "}<span className="text-xs">{result.data_source}</span>
            </div>
            <div className="text-xs font-mono text-muted-foreground">
              computed {new Date(result.computed_at).toLocaleTimeString()}
            </div>
          </div>

          {/* Metric cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <MetricCard
              label="Win Rate"
              value={`${result.win_rate.toFixed(1)}%`}
              sub={`${result.winning_trades}W / ${result.losing_trades}L`}
              accent={result.win_rate >= 50 ? "green" : "red"}
            />
            <MetricCard
              label="Net P&L"
              value={`${result.net_pnl >= 0 ? "+" : ""}₹${result.net_pnl.toFixed(0)}`}
              sub={`${result.net_pnl_pct >= 0 ? "+" : ""}${result.net_pnl_pct.toFixed(2)}%`}
              accent={result.net_pnl >= 0 ? "green" : "red"}
            />
            <MetricCard
              label="Profit Factor"
              value={result.profit_factor >= 99 ? "∞" : result.profit_factor.toFixed(2)}
              sub="gross profit / loss"
              accent={result.profit_factor >= 1.5 ? "green" : result.profit_factor >= 1 ? "yellow" : "red"}
            />
            <MetricCard
              label="Max Drawdown"
              value={`${result.max_drawdown_pct.toFixed(1)}%`}
              sub={`₹${result.max_drawdown.toFixed(0)}`}
              accent={result.max_drawdown_pct < 10 ? "green" : result.max_drawdown_pct < 20 ? "yellow" : "red"}
            />
            <MetricCard
              label="Total Trades"
              value={String(result.total_trades)}
              sub={`avg ${result.avg_duration_bars.toFixed(0)} bars`}
              accent="neutral"
            />
            <MetricCard
              label="Sharpe Ratio"
              value={result.sharpe_ratio.toFixed(2)}
              sub="per-trade"
              accent={result.sharpe_ratio >= 1 ? "green" : result.sharpe_ratio >= 0 ? "yellow" : "red"}
            />
          </div>

          {/* Secondary metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-card border border-border rounded-lg p-3 flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-emerald-400 flex-shrink-0" />
              <div>
                <div className="text-xs text-muted-foreground font-mono">Avg Profit</div>
                <div className="font-mono font-bold text-emerald-400">+₹{result.avg_profit.toFixed(2)}</div>
              </div>
            </div>
            <div className="bg-card border border-border rounded-lg p-3 flex items-center gap-3">
              <XCircle className="h-5 w-5 text-red-400 flex-shrink-0" />
              <div>
                <div className="text-xs text-muted-foreground font-mono">Avg Loss</div>
                <div className="font-mono font-bold text-red-400">-₹{result.avg_loss.toFixed(2)}</div>
              </div>
            </div>
            <div className="bg-card border border-border rounded-lg p-3 flex items-center gap-3">
              <TrendingUp className="h-5 w-5 text-emerald-400 flex-shrink-0" />
              <div>
                <div className="text-xs text-muted-foreground font-mono">Best Trade</div>
                <div className="font-mono font-bold text-emerald-400">+₹{result.best_trade.toFixed(2)}</div>
              </div>
            </div>
            <div className="bg-card border border-border rounded-lg p-3 flex items-center gap-3">
              <TrendingDown className="h-5 w-5 text-red-400 flex-shrink-0" />
              <div>
                <div className="text-xs text-muted-foreground font-mono">Worst Trade</div>
                <div className="font-mono font-bold text-red-400">₹{result.worst_trade.toFixed(2)}</div>
              </div>
            </div>
          </div>

          {/* Performance Analytics — expectancy, streaks */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <div className="bg-card border border-border rounded-lg p-3">
              <div className="text-xs text-muted-foreground font-mono">Expectancy / Trade</div>
              <div className={`font-mono font-bold ${result.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {result.expectancy >= 0 ? "+" : ""}₹{result.expectancy.toFixed(2)}
              </div>
            </div>
            <div className="bg-card border border-border rounded-lg p-3">
              <div className="text-xs text-muted-foreground font-mono">Max Consecutive Wins</div>
              <div className="font-mono font-bold text-emerald-400">{result.max_consecutive_wins}</div>
            </div>
            <div className="bg-card border border-border rounded-lg p-3">
              <div className="text-xs text-muted-foreground font-mono">Max Consecutive Losses</div>
              <div className="font-mono font-bold text-red-400">{result.max_consecutive_losses}</div>
            </div>
          </div>

          {/* Equity curve (simple bar chart using divs) */}
          {result.equity_curve.length > 1 && (
            <div className="bg-card border border-border rounded-lg p-4">
              <div className="text-xs font-mono text-muted-foreground uppercase tracking-widest mb-3 flex items-center gap-2">
                <BarChart2 className="h-3.5 w-3.5" />
                Equity Curve — ₹{result.initial_capital.toLocaleString()} → ₹{result.final_capital.toLocaleString()}
              </div>
              <EquityCurve curve={result.equity_curve} initial={result.initial_capital} />
            </div>
          )}

          {/* Trade list */}
          {result.trades.length > 0 && (
            <div className="bg-card border border-border rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-border flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-mono text-muted-foreground">
                  Trade History · {result.total_trades} trades
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      {["#", "Entry Date", "Exit Date", "Entry ₹", "Exit ₹", "Qty", "P&L", "P&L %", "Duration", "Exit"].map((h) => (
                        <th key={h} className="px-3 py-2 text-left text-xs font-mono text-muted-foreground uppercase tracking-widest whitespace-nowrap">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <TradeRow key={t.trade_no} trade={t} i={i} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {result.total_trades === 0 && !result.error && (
            <div className="bg-card border border-border rounded-lg p-8 text-center">
              <FlaskConical className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
              <div className="font-mono text-muted-foreground text-sm">
                No trades triggered for this period / strategy combination.
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Try a longer period or a different strategy.
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!result && !running && !runBacktest.isError && (
        <div className="bg-card border border-border border-dashed rounded-lg p-12 text-center">
          <FlaskConical className="h-12 w-12 text-muted-foreground/30 mx-auto mb-4" />
          <div className="font-mono text-muted-foreground">
            Configure a stock, strategy, and period above — then click <strong>Run Backtest</strong>.
          </div>
          <div className="text-xs text-muted-foreground mt-2">
            Walk-forward simulation · ₹1% risk/trade · No lookahead · Paper only
          </div>
        </div>
      )}
    </div>
  );
}

// ── Equity curve mini-chart ────────────────────────────────────────────────

function EquityCurve({ curve, initial }: { curve: number[]; initial: number }) {
  const min = Math.min(...curve);
  const max = Math.max(...curve);
  const range = max - min || 1;
  const h = 80;
  const w = 100;

  const pts = curve.map((v, i) => {
    const x = (i / (curve.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  });

  const last = curve[curve.length - 1];
  const gain = last >= initial;

  return (
    <div className="w-full h-20 relative">
      <svg
        viewBox={`0 0 100 ${h}`}
        preserveAspectRatio="none"
        className="w-full h-full"
      >
        {/* Fill area */}
        <polygon
          points={`0,${h} ${pts.join(" ")} ${w},${h}`}
          fill={gain ? "rgba(52,211,153,0.08)" : "rgba(248,113,113,0.08)"}
        />
        {/* Line */}
        <polyline
          points={pts.join(" ")}
          fill="none"
          stroke={gain ? "#34d399" : "#f87171"}
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        {/* Baseline (initial capital) */}
        {(() => {
          const baseY = h - ((initial - min) / range) * h;
          return (
            <line
              x1="0" y1={baseY} x2={w} y2={baseY}
              stroke="rgba(255,255,255,0.1)"
              strokeDasharray="2,2"
              strokeWidth="0.5"
              vectorEffect="non-scaling-stroke"
            />
          );
        })()}
      </svg>
    </div>
  );
}
