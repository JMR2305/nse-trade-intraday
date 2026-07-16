import { useState, useEffect } from "react";
import { useGetStrategies, useRunBacktest } from "@workspace/api-client-react";
import type {
  BacktestResult,
  ValidationSummary,
  DebugCandle,
  RejectedTrade,
  RuleCheck,
} from "@workspace/api-client-react";
import {
  ShieldCheck, AlertTriangle, CheckCircle2, XCircle, ChevronLeft,
  ChevronRight, FileText, BarChart2, TrendingUp, Activity,
  Layers, Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import DataFreshnessBar from "@/components/DataFreshnessBar";

// ── Shared form constants ──────────────────────────────────────────────────
const SYMBOLS = [
  "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
  "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
  "AXISBANK", "KOTAKBANK", "TATAMOTORS", "TITAN", "NESTLEIND",
];

const PERIODS = [
  { label: "3 Months",  days: -90  },
  { label: "6 Months",  days: -180 },
  { label: "1 Year",    days: -365 },
  { label: "2 Years",   days: -730 },
];

const INTERVALS = [
  { value: "1d", label: "Daily"  },
  { value: "1h", label: "Hourly" },
];

function today()          { return new Date().toISOString().split("T")[0]; }
function offset(d: number){ const dt = new Date(); dt.setDate(dt.getDate() + d); return dt.toISOString().split("T")[0]; }

// ── Sub-components ────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: "green" | "red" | "yellow" | "blue" }) {
  const colors = {
    green:  "border-emerald-500/30 text-emerald-400",
    red:    "border-red-500/30     text-red-400",
    yellow: "border-yellow-500/30  text-yellow-400",
    blue:   "border-primary/30     text-primary",
  };
  return (
    <div className={cn("rounded border bg-card p-4", accent ? colors[accent] : "border-border text-foreground")}>
      <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider mb-1">{label}</div>
      <div className={cn("text-2xl font-mono font-bold", accent ? colors[accent].split(" ")[1] : "")}>{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-1 font-mono">{sub}</div>}
    </div>
  );
}

function PassBadge({ passed }: { passed: boolean }) {
  return passed
    ? <span className="inline-flex items-center gap-1 text-emerald-400 font-mono text-xs"><CheckCircle2 className="h-3.5 w-3.5" />PASS</span>
    : <span className="inline-flex items-center gap-1 text-red-400 font-mono text-xs"><XCircle className="h-3.5 w-3.5" />FAIL</span>;
}

function SectionHeader({ icon: Icon, title, count }: { icon: React.ElementType; title: string; count?: number }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="h-4 w-4 text-primary" />
      <h3 className="font-mono font-semibold text-sm text-foreground">{title}</h3>
      {count !== undefined && (
        <span className="ml-auto text-xs font-mono text-muted-foreground">{count} item{count !== 1 ? "s" : ""}</span>
      )}
    </div>
  );
}

// Rule Inspector table from a list of rule_checks
function RuleInspectorTable({ rules }: { rules: RuleCheck[] }) {
  if (!rules.length) return <p className="text-xs text-muted-foreground font-mono">No rule data available.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono border-collapse">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="text-left py-2 pr-4 font-medium">RULE</th>
            <th className="text-left py-2 pr-4 font-medium">CURRENT VALUE</th>
            <th className="text-left py-2 pr-4 font-medium">REQUIRED</th>
            <th className="text-left py-2 font-medium">RESULT</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((rc, idx) => (
            <tr
              key={idx}
              className={cn(
                "border-b border-border/40",
                rc.passed ? "bg-emerald-500/5" : "bg-red-500/5"
              )}
            >
              <td className="py-2 pr-4 text-foreground/90">{rc.rule}</td>
              <td className={cn("py-2 pr-4", rc.passed ? "text-emerald-400" : "text-red-400")}>{rc.current_value}</td>
              <td className="py-2 pr-4 text-muted-foreground">{rc.required_value}</td>
              <td className="py-2"><PassBadge passed={rc.passed} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Debug Candles paginated table
const DEBUG_PAGE_SIZE = 25;

function DebugTable({ candles }: { candles: DebugCandle[] }) {
  const [page, setPage] = useState(0);
  const totalPages = Math.ceil(candles.length / DEBUG_PAGE_SIZE);
  const slice = candles.slice(page * DEBUG_PAGE_SIZE, (page + 1) * DEBUG_PAGE_SIZE);

  useEffect(() => { setPage(0); }, [candles]);

  if (!candles.length) return <p className="text-xs text-muted-foreground font-mono">No debug candle data (only available when debug mode is on).</p>;

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded border border-border">
        <table className="w-full text-xs font-mono border-collapse min-w-[900px]">
          <thead className="bg-muted/40">
            <tr className="text-muted-foreground">
              {["DATE","CLOSE","EMA9","EMA20","EMA50","RSI","MACD","VWAP","ADX","POS","BUY","SELL","FAILED RULES"].map(h => (
                <th key={h} className="text-left px-2 py-2 font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((c, idx) => (
              <tr
                key={idx}
                className={cn(
                  "border-b border-border/30 hover:bg-muted/20",
                  c.buy_signal  && !c.in_position ? "bg-emerald-500/5" : "",
                  c.sell_signal && c.in_position  ? "bg-red-500/5"     : "",
                  c.in_position && !c.sell_signal ? "bg-primary/5"     : "",
                )}
              >
                <td className="px-2 py-1.5 text-muted-foreground whitespace-nowrap">{String(c.date).split("T")[0]}</td>
                <td className="px-2 py-1.5">{c.close.toFixed(1)}</td>
                <td className="px-2 py-1.5">{c.ema9.toFixed(1)}</td>
                <td className="px-2 py-1.5">{c.ema20.toFixed(1)}</td>
                <td className="px-2 py-1.5">{c.ema50.toFixed(1)}</td>
                <td className={cn("px-2 py-1.5", c.rsi < 30 ? "text-red-400" : c.rsi > 70 ? "text-yellow-400" : "")}>{c.rsi.toFixed(1)}</td>
                <td className={cn("px-2 py-1.5", c.macd_line > c.macd_signal ? "text-emerald-400" : "text-red-400")}>{c.macd_line.toFixed(3)}</td>
                <td className="px-2 py-1.5">{c.vwap.toFixed(1)}</td>
                <td className={cn("px-2 py-1.5", c.adx > 25 ? "text-primary" : "text-muted-foreground")}>{c.adx.toFixed(1)}</td>
                <td className="px-2 py-1.5">{c.in_position ? <span className="text-primary">IN</span> : <span className="text-muted-foreground">—</span>}</td>
                <td className="px-2 py-1.5">{c.buy_signal ? <span className="text-emerald-400">BUY</span> : <span className="text-muted-foreground">—</span>}</td>
                <td className="px-2 py-1.5">{c.sell_signal ? <span className="text-red-400">EXIT</span> : <span className="text-muted-foreground">—</span>}</td>
                <td className="px-2 py-1.5 text-red-400/80 max-w-[200px] truncate" title={c.failed_rules.join(", ")}>
                  {c.failed_rules.length ? c.failed_rules.join(", ") : <span className="text-emerald-400/60">✓ all pass</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between font-mono text-xs text-muted-foreground">
          <span>Page {page + 1} / {totalPages} · {candles.length} bars total</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="flex items-center gap-1 px-2 py-1 rounded border border-border hover:bg-muted disabled:opacity-40"
            >
              <ChevronLeft className="h-3 w-3" /> Prev
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
              className="flex items-center gap-1 px-2 py-1 rounded border border-border hover:bg-muted disabled:opacity-40"
            >
              Next <ChevronRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Rejected trade card
function RejectedTradeCard({ rt, index }: { rt: RejectedTrade; index: number }) {
  const [open, setOpen] = useState(false);
  const typeColor = rt.rejection_type === "bad_stop" ? "text-yellow-400" : "text-red-400";
  return (
    <div className="rounded border border-border bg-card p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">#{index + 1}</span>
            <span className="font-mono text-xs font-semibold">{String(rt.date).split("T")[0]}</span>
            <span className="font-mono text-xs text-muted-foreground">close=₹{rt.close.toFixed(1)}</span>
          </div>
          <span className={cn("font-mono text-xs font-bold uppercase tracking-wide", typeColor)}>
            {rt.rejection_type.replace("_", " ")}
          </span>
          <p className="font-mono text-xs text-muted-foreground">{rt.explanation}</p>
        </div>
        <button
          onClick={() => setOpen(o => !o)}
          className="text-xs font-mono text-primary hover:underline whitespace-nowrap"
        >
          {open ? "Hide rules" : "Show rules"}
        </button>
      </div>
      {open && (
        <div className="pt-2 border-t border-border/40">
          <p className="text-xs font-mono text-muted-foreground mb-2">All entry rules passed — trade rejected AFTER signal:</p>
          <RuleInspectorTable rules={rt.rule_checks} />
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Validate() {
  const [symbol,    setSymbol]    = useState("RELIANCE");
  const [strategy,  setStrategy]  = useState("");
  const [periodIdx, setPeriodIdx] = useState(2);   // 1 Year default
  const [interval,  setInterval]  = useState("1d");
  const [result,    setResult]    = useState<BacktestResult | null>(null);

  const { data: strategies = [], isLoading: loadingStrategies } = useGetStrategies();
  const runBacktest = useRunBacktest();

  useEffect(() => {
    if (strategies.length > 0 && strategy === "") {
      setStrategy(strategies[0].id);
    }
  }, [strategies]);

  // Build period with callable start/end
  const currentPeriod = { ...PERIODS[periodIdx], start: () => offset(PERIODS[periodIdx].days), end: () => today() };

  function handleRunWithFns() {
    if (!strategy) return;
    runBacktest.mutate(
      {
        data: {
          symbol,
          strategy,
          start_date:      currentPeriod.start(),
          end_date:        currentPeriod.end(),
          initial_capital: 5000,
          interval,
          debug:           true,
        },
      },
      { onSuccess: (data) => setResult(data) },
    );
  }

  const validation = result?.validation as ValidationSummary | undefined;
  const debugCandles: DebugCandle[] = (result?.debug_candles ?? []) as DebugCandle[];
  const rejectedTrades: RejectedTrade[] = (result?.rejected_trades_detail ?? []) as RejectedTrade[];

  // Last candle's rule_checks → Rule Inspector
  const lastRuleChecks: RuleCheck[] = debugCandles.length > 0
    ? (debugCandles[debugCandles.length - 1].rule_checks as RuleCheck[])
    : [];

  // Rule failure frequency (for bar chart)
  const ruleFailures: { rule: string; count: number }[] = validation
    ? Object.entries(validation.rule_failure_counts ?? {})
        .sort((a, b) => (b[1] as number) - (a[1] as number))
        .map(([rule, count]) => ({ rule, count: count as number }))
    : [];

  const maxFailures = ruleFailures[0]?.count ?? 1;

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ShieldCheck className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-mono font-bold tracking-tight">Strategy Validation</h1>
          <p className="text-sm text-muted-foreground font-mono mt-0.5">
            Debug mode · Per-candle rule analysis · No real orders · ₹5,000 capital
          </p>
        </div>
      </div>

      <DataFreshnessBar variant="historical" datasetLabel="Validation dataset" />

      {/* Form */}
      <div className="rounded-lg border border-border bg-card/50 p-4">
        <div className="flex flex-wrap gap-3 items-end">
          {/* Stock */}
          <div className="space-y-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Stock</label>
            <select
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              className="bg-background border border-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          {/* Strategy */}
          <div className="space-y-1 min-w-[220px]">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Strategy</label>
            <select
              value={strategy}
              onChange={e => setStrategy(e.target.value)}
              className="w-full bg-background border border-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
              disabled={loadingStrategies}
            >
              {strategies.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          {/* Period */}
          <div className="space-y-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Period</label>
            <select
              value={periodIdx}
              onChange={e => setPeriodIdx(Number(e.target.value))}
              className="bg-background border border-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {PERIODS.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
            </select>
          </div>

          {/* Interval */}
          <div className="space-y-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Interval</label>
            <select
              value={interval}
              onChange={e => setInterval(e.target.value)}
              className="bg-background border border-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {INTERVALS.map(iv => <option key={iv.value} value={iv.value}>{iv.label}</option>)}
            </select>
          </div>

          {/* Run button */}
          <button
            onClick={handleRunWithFns}
            disabled={runBacktest.isPending || !strategy}
            className="flex items-center gap-2 px-5 py-2 rounded bg-primary text-primary-foreground font-mono text-sm font-semibold hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            <Search className="h-4 w-4" />
            {runBacktest.isPending ? "Validating…" : "Run Validation"}
          </button>
        </div>

        {/* Strategy info */}
        {strategy && strategies.find(s => s.id === strategy) && (() => {
          const s = strategies.find(st => st.id === strategy)!;
          return (
            <div className="mt-3 pt-3 border-t border-border/40 text-xs font-mono text-muted-foreground flex flex-wrap gap-x-6 gap-y-1">
              <span>{s.description}</span>
              <span className="text-primary/70">{s.type}</span>
              <span>1% risk/trade</span>
            </div>
          );
        })()}
      </div>

      {/* Error */}
      {runBacktest.isError && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 font-mono text-sm">
          ⚠ {runBacktest.error instanceof Error ? runBacktest.error.message : "Validation failed"}
        </div>
      )}

      {/* Loading */}
      {runBacktest.isPending && (
        <div className="rounded-lg border border-border bg-card/50 p-8 text-center">
          <div className="animate-pulse text-primary font-mono text-sm">
            Running debug backtest · evaluating every candle…
          </div>
        </div>
      )}

      {/* Results */}
      {result && validation && !runBacktest.isPending && (
        <div className="space-y-6">

          {/* ── 1. Validation Summary ─────────────────────────────────── */}
          <section className="rounded-lg border border-border bg-card/50 p-5">
            <SectionHeader icon={BarChart2} title="Validation Summary" />
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              <StatCard
                label="Candles Analysed"
                value={validation.active_candles}
                sub={`${validation.warmup_candles} warmup discarded`}
                accent="blue"
              />
              <StatCard
                label="Buy Opportunities"
                value={validation.buy_signals_fired}
                sub={`${validation.buy_signals_while_flat} while flat`}
                accent={validation.buy_signals_fired > 0 ? "green" : "red"}
              />
              <StatCard
                label="Sell / Exit Events"
                value={validation.sell_signals_fired}
                sub="total exit events"
              />
              <StatCard
                label="Executed Trades"
                value={validation.executed_trades}
                accent={validation.executed_trades > 0 ? "green" : "red"}
              />
              <StatCard
                label="Rejected Trades"
                value={validation.rejected_trades}
                sub={
                  Object.entries(validation.rejection_breakdown ?? {})
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(", ") || undefined
                }
                accent={validation.rejected_trades > 0 ? "yellow" : undefined}
              />
              <StatCard
                label="Skipped (Invested)"
                value={validation.skipped_while_invested}
                sub="signal fired while in position"
              />
            </div>
          </section>

          {/* ── 2. Zero-Trade Diagnosis ───────────────────────────────── */}
          {validation.executed_trades === 0 && validation.zero_trade_diagnosis.length > 0 && (
            <section className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
              <SectionHeader icon={AlertTriangle} title="Zero-Trade Diagnosis" />
              <p className="text-xs font-mono text-muted-foreground mb-3">
                No trades were executed. Here is exactly what prevented entries:
              </p>
              <ul className="space-y-2">
                {validation.zero_trade_diagnosis.map((d, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm font-mono text-red-300">
                    <XCircle className="h-4 w-4 mt-0.5 flex-shrink-0 text-red-400" />
                    {d}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* ── 3. Rule Inspector ─────────────────────────────────────── */}
          <section className="rounded-lg border border-border bg-card/50 p-5">
            <SectionHeader icon={Layers} title="Rule Inspector (Last Bar)" />
            <p className="text-xs font-mono text-muted-foreground mb-3">
              Entry rule state for the most recent active bar ({String(debugCandles[debugCandles.length - 1]?.date ?? "").split("T")[0]}).
            </p>
            <RuleInspectorTable rules={lastRuleChecks} />

            {/* Rule failure frequency bar chart */}
            {ruleFailures.length > 0 && (
              <div className="mt-5">
                <div className="text-xs font-mono text-muted-foreground mb-2 uppercase tracking-wider">
                  Rule Failure Frequency (when flat &amp; no signal)
                </div>
                <div className="space-y-2">
                  {ruleFailures.map(({ rule, count }) => {
                    const pct = Math.round((count / (validation.active_candles || 1)) * 100);
                    const barPct = Math.round((count / maxFailures) * 100);
                    return (
                      <div key={rule} className="space-y-0.5">
                        <div className="flex justify-between text-xs font-mono text-muted-foreground">
                          <span className="truncate max-w-[400px]">{rule}</span>
                          <span className="ml-4 whitespace-nowrap">{count}× ({pct}% of active bars)</span>
                        </div>
                        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full bg-red-500/60 rounded-full"
                            style={{ width: `${barPct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </section>

          {/* ── 4. Rejected Trades ─────────────────────────────────────── */}
          <section className="rounded-lg border border-border bg-card/50 p-5">
            <SectionHeader icon={XCircle} title="Rejected Trades" count={rejectedTrades.length} />
            {rejectedTrades.length === 0 ? (
              <p className="text-xs font-mono text-muted-foreground">
                No trades were rejected. All signals that passed the entry rules were successfully executed.
              </p>
            ) : (
              <div className="space-y-2">
                {rejectedTrades.map((rt, i) => (
                  <RejectedTradeCard key={i} rt={rt} index={i} />
                ))}
              </div>
            )}
          </section>

          {/* ── 5. Debug Candle Table ──────────────────────────────────── */}
          <section className="rounded-lg border border-border bg-card/50 p-5">
            <SectionHeader icon={Activity} title="Per-Candle Debug Log" count={debugCandles.length} />
            <div className="flex flex-wrap gap-x-6 gap-y-1 mb-3 text-xs font-mono text-muted-foreground">
              <span><span className="text-emerald-400">■</span> BUY signal (flat)</span>
              <span><span className="text-red-400">■</span> EXIT signal (invested)</span>
              <span><span className="text-primary">■</span> In position</span>
            </div>
            <DebugTable candles={debugCandles} />
          </section>

          {/* ── 6. Log file ───────────────────────────────────────────── */}
          <section className="rounded-lg border border-border bg-card/50 p-5">
            <SectionHeader icon={FileText} title="Backtest Log" />
            <p className="text-xs font-mono text-muted-foreground">
              Detailed log written to server at:
            </p>
            <code className="block mt-1 text-xs font-mono bg-muted/40 rounded px-3 py-2 text-primary/80 break-all">
              {validation.log_file_path || "(log write failed)"}
            </code>
            <p className="text-xs font-mono text-muted-foreground mt-2">
              The log contains per-candle indicator values, rejected trades, and a full summary.
              Access via the API server's /tmp/ directory.
            </p>
          </section>

        </div>
      )}

      {/* Empty state */}
      {!result && !runBacktest.isPending && (
        <div className="rounded-lg border border-border bg-card/50 p-12 text-center space-y-3">
          <ShieldCheck className="h-10 w-10 text-muted-foreground/30 mx-auto" />
          <p className="font-mono text-muted-foreground text-sm">
            Configure a stock, strategy, and period above — then click{" "}
            <span className="text-primary font-semibold">Run Validation</span>.
          </p>
          <p className="text-xs font-mono text-muted-foreground/60">
            Debug mode enabled · Per-candle rule checks · Rejected trade analysis · Log file generated
          </p>
        </div>
      )}
    </div>
  );
}
