import { useState } from "react";
import { useRunOptimizer } from "@workspace/api-client-react";
import type { OptimizerResult, MultiPeriodEntry } from "@workspace/api-client-react";
import {
  Settings2, Trophy, Download, AlertTriangle, AlertCircle,
  Loader2, Play, Info, ChevronDown, ChevronUp, CheckCircle2, XCircle,
  Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import DataFreshnessBar from "@/components/DataFreshnessBar";

// ── Constants ──────────────────────────────────────────────────────────────
const SYMBOLS = [
  "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
  "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
  "AXISBANK", "KOTAKBANK", "TATAMOTORS", "TITAN", "NESTLEIND",
];
const PERIODS = [
  { label: "1 Year",  days: -365 },
  { label: "2 Years", days: -730 },
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

// ── Badge config ─────────────────────────────────────────────────────────────
const BADGE_CFG: Record<string, { label: string; cls: string; dot: string }> = {
  A: { label: "A", cls: "text-emerald-400 border-emerald-400/50 bg-emerald-400/10", dot: "bg-emerald-400" },
  B: { label: "B", cls: "text-sky-400     border-sky-400/50     bg-sky-400/10",     dot: "bg-sky-400"     },
  C: { label: "C", cls: "text-yellow-400  border-yellow-400/50  bg-yellow-400/10",  dot: "bg-yellow-400"  },
  D: { label: "D", cls: "text-red-400     border-red-400/50     bg-red-400/10",     dot: "bg-red-400"     },
};
const BADGE_DESC: Record<string, string> = {
  A: "High trades + profitable across all time periods",
  B: "Medium reliability, profitable in most periods",
  C: "Low reliability, profitable in some periods",
  D: "Poor / unreliable — avoid live use",
};

// ── Reliability config ────────────────────────────────────────────────────────
const REL_CFG: Record<string, { cls: string; bar: string }> = {
  "HIGH":     { cls: "text-emerald-400", bar: "bg-emerald-500" },
  "MEDIUM":   { cls: "text-sky-400",     bar: "bg-sky-500"     },
  "LOW":      { cls: "text-yellow-400",  bar: "bg-yellow-500"  },
  "VERY LOW": { cls: "text-red-400",     bar: "bg-red-500"     },
};
const REL_MULT_PCT: Record<string, number> = {
  "HIGH": 100, "MEDIUM": 70, "LOW": 40, "VERY LOW": 10,
};

// ── Strategy colours ──────────────────────────────────────────────────────────
const STRAT_CLR: Record<string, string> = {
  ema_cross:         "text-sky-400   border-sky-400/40   bg-sky-400/10",
  mean_reversion:    "text-purple-400 border-purple-400/40 bg-purple-400/10",
  trend_rider:       "text-primary   border-primary/40   bg-primary/10",
  supertrend_follow: "text-amber-400  border-amber-400/40  bg-amber-400/10",
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmt = (v: number, d = 2) => v.toFixed(d);
const clrPnl  = (v: number) => v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-muted-foreground";
const clrWr   = (v: number) => v >= 50 ? "text-emerald-400" : v > 0 ? "text-yellow-400" : "text-muted-foreground";
const clrPf   = (v: number) => v >= 1.5 ? "text-emerald-400" : v >= 1 ? "text-yellow-400" : "text-red-400";
const clrSh   = (v: number) => v >= 1 ? "text-emerald-400" : v >= 0 ? "text-yellow-400" : "text-red-400";
const clrDd   = (v: number) => v > 10 ? "text-red-400" : v > 5 ? "text-yellow-400" : "text-emerald-400";
const clrStab = (v: number) => v >= 60 ? "text-emerald-400" : v >= 35 ? "text-yellow-400" : "text-red-400";

// ── Score bar ─────────────────────────────────────────────────────────────────
function ScoreBar({ score, max = 85, className }: { score: number; max?: number; className?: string }) {
  const pct = Math.max(0, Math.min(score / max * 100, 100));
  const clr = score / max >= 0.5 ? "bg-emerald-500" : score / max >= 0.25 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden min-w-[48px]">
        <div className={cn("h-full rounded-full", clr)} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-foreground w-8 text-right tabular-nums">{fmt(score, 1)}</span>
    </div>
  );
}

// ── Reliability bar ───────────────────────────────────────────────────────────
function ReliabilityBar({ label, multiplier }: { label: string; multiplier: number }) {
  const cfg = REL_CFG[label] ?? REL_CFG["VERY LOW"];
  const pct = REL_MULT_PCT[label] ?? 10;
  return (
    <div className="flex flex-col gap-0.5 min-w-[100px]">
      <div className="flex items-center justify-between">
        <span className={cn("text-xs font-mono font-semibold", cfg.cls)}>{label}</span>
        <span className="text-[10px] font-mono text-muted-foreground">×{multiplier}</span>
      </div>
      <div className="h-1 rounded-full bg-border overflow-hidden">
        <div className={cn("h-full rounded-full", cfg.bar)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── Badge pill ────────────────────────────────────────────────────────────────
function BadgePill({ badge, size = "md" }: { badge: string; size?: "sm" | "md" | "lg" }) {
  const cfg = BADGE_CFG[badge] ?? BADGE_CFG["D"];
  const sizeCls = size === "lg" ? "text-base font-bold h-8 w-8" : size === "sm" ? "text-[10px] h-5 w-5" : "text-xs font-bold h-6 w-6";
  return (
    <div className={cn(
      "inline-flex items-center justify-center rounded border font-mono shrink-0",
      sizeCls, cfg.cls,
    )}>
      {cfg.label}
    </div>
  );
}

// ── Warning badge ─────────────────────────────────────────────────────────────
function WarnBadge({ text }: { text: string }) {
  const isInsufficient = text.toLowerCase().includes("do not trust");
  const isInflated     = text.toLowerCase().includes("inflated");
  const cls = isInsufficient ? "text-red-400 border-red-400/40 bg-red-400/10"
            : isInflated     ? "text-orange-400 border-orange-400/40 bg-orange-400/10"
            : "text-yellow-400 border-yellow-400/40 bg-yellow-400/10";
  return (
    <span className={cn("inline-flex items-center gap-1 text-[10px] font-mono border rounded px-1.5 py-0.5 leading-tight", cls)}>
      <AlertTriangle className="h-2.5 w-2.5 shrink-0" />
      {text}
    </span>
  );
}

// ── Multi-period row ──────────────────────────────────────────────────────────
function MultiPeriodRow({ p }: { p: MultiPeriodEntry }) {
  if (p.skipped) {
    return (
      <tr className="border-b border-border/30">
        <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground font-semibold">{p.period}</td>
        <td colSpan={5} className="px-3 py-1.5 text-xs text-muted-foreground/50 font-mono italic">Insufficient data</td>
      </tr>
    );
  }
  return (
    <tr className="border-b border-border/30 hover:bg-accent/10">
      <td className="px-3 py-1.5 font-mono text-xs text-foreground font-semibold">{p.period}</td>
      <td className="px-3 py-1.5 text-right font-mono text-xs">{p.trades}</td>
      <td className={cn("px-3 py-1.5 text-right font-mono text-xs", clrWr(p.win_rate))}>
        {p.trades ? `${fmt(p.win_rate, 1)}%` : "—"}
      </td>
      <td className={cn("px-3 py-1.5 text-right font-mono text-xs", clrPnl(p.net_pnl_pct))}>
        {p.trades ? `${p.net_pnl_pct >= 0 ? "+" : ""}${fmt(p.net_pnl_pct, 1)}%` : "—"}
      </td>
      <td className={cn("px-3 py-1.5 text-right font-mono text-xs", clrDd(p.max_drawdown_pct))}>
        {p.trades ? `${fmt(p.max_drawdown_pct, 1)}%` : "—"}
      </td>
      <td className="px-3 py-1.5 text-center">
        {p.trades === 0
          ? <Minus className="h-3 w-3 text-muted-foreground/40 mx-auto" />
          : p.profitable
            ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mx-auto" />
            : <XCircle      className="h-3.5 w-3.5 text-red-400    mx-auto" />
        }
      </td>
    </tr>
  );
}

// ── CSV export ────────────────────────────────────────────────────────────────
function exportCsv(rows: OptimizerResult[], symbol: string) {
  const headers = [
    "Rank", "Badge", "Strategy", "Parameters",
    "Trades", "Win Rate%", "Net P&L ₹", "P&L%",
    "Profit Factor", "Max DD%", "Sharpe",
    "Reliability", "Rel. Multiplier", "Raw Score", "Final Score",
    "Stability", "Profitable Periods", "Total Periods",
    "Avg Win Rate (MP)", "Avg DD (MP)", "Warnings",
  ];
  const csv = [headers, ...rows.map(r => [
    r.rank, r.badge, r.strategy_name, `"${r.parameters_display}"`,
    r.total_trades, fmt(r.win_rate), fmt(r.net_pnl), fmt(r.net_pnl_pct),
    fmt(r.profit_factor), fmt(r.max_drawdown_pct), fmt(r.sharpe_ratio),
    r.reliability_label, r.reliability_multiplier, fmt(r.raw_score), fmt(r.final_score),
    fmt(r.stability_score), r.profitable_periods, r.total_periods,
    fmt(r.avg_win_rate_mp), fmt(r.avg_drawdown_mp),
    `"${r.warnings.join("; ")}"`,
  ])].map(row => row.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = `optimizer_${symbol}_robustness.csv`; a.click();
  URL.revokeObjectURL(url);
}

// ── Scoring legend tooltip ────────────────────────────────────────────────────
function ScoringInfo() {
  return (
    <div className="group relative inline-flex">
      <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
      <div className="absolute bottom-full left-0 mb-2 hidden group-hover:block z-50 w-80 rounded border border-border bg-card p-3 text-xs font-mono shadow-xl">
        <div className="font-semibold mb-2 text-foreground">v0.8 Scoring Pipeline</div>
        <div className="text-muted-foreground space-y-1">
          <div className="text-foreground/80 font-semibold text-[10px] uppercase tracking-wider mb-1">Raw Score (0–85)</div>
          <div>Win Rate (÷100)    × 0.25</div>
          <div>Profit Factor (÷5) × 0.25</div>
          <div>Net P&L% (÷30)    × 0.20</div>
          <div>Sharpe (÷3)        × 0.15</div>
          <div>− Max DD% (÷30)   × 0.15</div>
          <div className="border-t border-border/50 mt-2 pt-2 text-foreground/80 font-semibold text-[10px] uppercase tracking-wider">Reliability Multiplier</div>
          <div>HIGH   (≥50 trades)  × 1.00</div>
          <div>MEDIUM (20–49)       × 0.70</div>
          <div>LOW    (5–19)        × 0.40</div>
          <div>VERY LOW (&lt;5)     × 0.10</div>
          <div className="border-t border-border/50 mt-2 pt-2 font-semibold text-foreground">Final = Raw × Multiplier</div>
        </div>
      </div>
    </div>
  );
}

// ── Badge legend ──────────────────────────────────────────────────────────────
function BadgeLegend() {
  return (
    <div className="flex flex-wrap gap-3">
      {(["A","B","C","D"] as const).map(b => {
        const cfg = BADGE_CFG[b];
        return (
          <div key={b} className="flex items-center gap-2 text-xs font-mono">
            <BadgePill badge={b} size="sm" />
            <span className="text-muted-foreground">{BADGE_DESC[b]}</span>
          </div>
        );
      })}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Page
// ══════════════════════════════════════════════════════════════════════════════
export default function Optimizer() {
  const [symbol,    setSymbol]    = useState("RELIANCE");
  const [periodIdx, setPeriodIdx] = useState(0);
  const [interval,  setInterval]  = useState("1d");
  const [results,   setResults]   = useState<OptimizerResult[] | null>(null);
  const [expanded,  setExpanded]  = useState<Set<number>>(new Set());

  const runOpt = useRunOptimizer();
  const period     = PERIODS[periodIdx];
  const start_date = offset(period.days);
  const end_date   = today();

  function toggleExpand(rank: number) {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(rank) ? next.delete(rank) : next.add(rank);
      return next;
    });
  }

  function handleRun() {
    setResults(null);
    setExpanded(new Set());
    runOpt.mutate(
      { data: { symbol, start_date, end_date, initial_capital: 5000, interval, top_n: 10 } },
      { onSuccess: data => setResults(data) },
    );
  }

  const isLoading = runOpt.isPending;
  const hasError  = runOpt.isError;
  const best      = results?.[0];

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1500px]">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Settings2 className="mt-0.5 h-6 w-6 text-primary shrink-0" />
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold font-mono tracking-tight">Strategy Optimizer</h1>
            <span className="text-xs border border-primary/40 text-primary font-mono rounded px-1.5 py-0.5">v0.8</span>
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            51 combinations · 4-period stability testing · reliability-adjusted scoring · robustness badges A–D · ₹5,000 capital
          </p>
        </div>
      </div>

      <DataFreshnessBar variant="historical" datasetLabel="Optimization dataset" />

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
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Base Period</label>
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
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Range</label>
            <span className="text-sm font-mono text-muted-foreground py-1.5">{start_date} → {end_date}</span>
          </div>
          <button onClick={handleRun} disabled={isLoading}
            className="flex items-center gap-2 bg-primary text-primary-foreground font-mono text-sm px-5 py-1.5 rounded hover:bg-primary/90 disabled:opacity-60 disabled:cursor-not-allowed transition-colors ml-auto">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {isLoading ? "Optimizing…" : "Run Optimizer"}
          </button>
          {results && (
            <button onClick={() => exportCsv(results, symbol)}
              className="flex items-center gap-2 border border-border text-sm font-mono px-4 py-1.5 rounded hover:bg-accent transition-colors">
              <Download className="h-4 w-4" />
              Export CSV
            </button>
          )}
        </div>

        {/* Parameter grid info */}
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs font-mono text-muted-foreground">
          {[
            { name: "EMA Cross",         cls: "text-sky-400",    desc: "Fast: 9/10/20 · Slow: 21/30/50",              n: 9  },
            { name: "RSI Mean Reversion", cls: "text-purple-400", desc: "Oversold: 25/30/35 · Overbought: 65/70/75",   n: 9  },
            { name: "Trend Rider",        cls: "text-primary",    desc: "EMA pairs · RSI range · ATR stop/target",      n: 24 },
            { name: "Supertrend",         cls: "text-amber-400",  desc: "Period: 7/10/14 · Multiplier: 2/3/4",          n: 9  },
          ].map(s => (
            <div key={s.name} className="rounded border border-border px-2 py-1.5">
              <span className={s.cls}>{s.name}</span>
              <div className="mt-0.5 text-[10px] text-muted-foreground/70">{s.desc}</div>
              <div className="text-[10px] text-muted-foreground/50 mt-0.5">{s.n} combinations</div>
            </div>
          ))}
        </div>
      </div>

      {/* Error */}
      {hasError && (
        <div className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to run optimizer. Check the API server is running.
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="rounded border border-border bg-card p-10 flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <div className="text-sm font-mono text-muted-foreground text-center">
            <div className="text-foreground font-semibold">Testing 51 × 4 period combinations on {symbol}…</div>
            <div className="text-xs mt-1">Fetching 2 years of data · 3M / 6M / 1Y / 2Y stability slices</div>
            <div className="text-xs mt-0.5 text-muted-foreground/60">EMA Cross (9) · RSI Mean Rev (9) · Trend Rider (24) · Supertrend (9)</div>
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
              <div className="flex items-center gap-3 shrink-0">
                <Trophy className="h-5 w-5 text-primary" />
                <BadgePill badge={best.badge} size="lg" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono font-semibold text-primary text-base">
                    Best Setup — {best.strategy_name}
                  </span>
                  <span className={cn("text-xs border rounded px-1.5 py-0.5 font-mono", STRAT_CLR[best.strategy_id])}>
                    {best.strategy_id}
                  </span>
                </div>
                <div className="text-xs font-mono text-muted-foreground mt-0.5">{best.parameters_display}</div>
                <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2 text-xs font-mono">
                  <span>Final Score <span className="text-primary font-bold">{fmt(best.final_score, 1)}</span></span>
                  <span>Raw <span className="text-foreground">{fmt(best.raw_score, 1)}</span></span>
                  <span>Reliability <span className={REL_CFG[best.reliability_label]?.cls}>{best.reliability_label}</span> ×{best.reliability_multiplier}</span>
                  <span>Trades <span className="text-foreground">{best.total_trades}</span></span>
                  <span>Win Rate <span className={clrWr(best.win_rate)}>{fmt(best.win_rate, 1)}%</span></span>
                  <span>Net P&L <span className={clrPnl(best.net_pnl)}>₹{fmt(best.net_pnl)}</span></span>
                  <span>Stability <span className={clrStab(best.stability_score)}>{fmt(best.stability_score, 0)}/100</span></span>
                  <span>Profitable <span className="text-foreground">{best.profitable_periods}/{best.total_periods} periods</span></span>
                </div>
                {best.warnings.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {best.warnings.map((w, i) => <WarnBadge key={i} text={w} />)}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Main results table */}
          <div className="rounded border border-border bg-card overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-center px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider w-14">Rank</th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[140px]">Strategy</th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[220px]">Parameters</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Trades</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Win%</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Net P&L</th>
                  <th className="text-right  px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">PF</th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[120px]">Reliability</th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[120px]">
                    <span className="flex items-center gap-1">Final Score <ScoringInfo /></span>
                  </th>
                  <th className="text-left   px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[110px]">Stability</th>
                  <th className="text-center px-4 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider w-12"></th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, idx) => {
                  const isTop  = r.rank === 1;
                  const isOpen = expanded.has(r.rank);
                  const validMp = r.multi_period.filter(p => !p.skipped);
                  return (
                    <>
                      {/* Main row */}
                      <tr key={`row-${idx}`} className={cn(
                        "border-b border-border/50 transition-colors",
                        isTop  ? "bg-primary/5" : idx % 2 === 0 ? "bg-card" : "bg-background/20",
                        "hover:bg-accent/20 cursor-pointer",
                      )} onClick={() => toggleExpand(r.rank)}>

                        {/* Rank + Badge */}
                        <td className="px-3 py-3 text-center">
                          <div className="flex flex-col items-center gap-1">
                            <BadgePill badge={r.badge} size={isTop ? "md" : "sm"} />
                            {isTop
                              ? <Trophy className="h-3 w-3 text-primary" />
                              : <span className="text-[10px] font-mono text-muted-foreground">#{r.rank}</span>
                            }
                          </div>
                        </td>

                        {/* Strategy */}
                        <td className="px-4 py-3">
                          <div className="flex flex-col gap-1">
                            <span className="font-mono text-sm font-medium">{r.strategy_name}</span>
                            <span className={cn("text-[10px] border rounded px-1 w-fit font-mono", STRAT_CLR[r.strategy_id])}>
                              {r.strategy_id}
                            </span>
                          </div>
                        </td>

                        {/* Parameters + warnings */}
                        <td className="px-4 py-3">
                          <div className="font-mono text-xs text-foreground">{r.parameters_display}</div>
                          {r.warnings.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {r.warnings.map((w, wi) => <WarnBadge key={wi} text={w} />)}
                            </div>
                          )}
                        </td>

                        {/* Trades */}
                        <td className="px-4 py-3 text-right">
                          <span className={cn("font-mono text-sm", r.total_trades === 0 ? "text-muted-foreground" : "text-foreground")}>
                            {r.total_trades}
                          </span>
                          {r.total_trades > 0 && (
                            <div className="text-[10px] font-mono text-muted-foreground">{r.winning_trades}W/{r.losing_trades}L</div>
                          )}
                        </td>

                        {/* Win Rate */}
                        <td className="px-4 py-3 text-right">
                          <span className={cn("font-mono text-sm", r.total_trades ? clrWr(r.win_rate) : "text-muted-foreground")}>
                            {r.total_trades ? `${fmt(r.win_rate, 1)}%` : "—"}
                          </span>
                        </td>

                        {/* Net P&L */}
                        <td className="px-4 py-3 text-right">
                          <span className={cn("font-mono text-sm", r.total_trades ? clrPnl(r.net_pnl) : "text-muted-foreground")}>
                            {r.total_trades ? `₹${fmt(r.net_pnl)}` : "—"}
                          </span>
                          {r.total_trades > 0 && (
                            <div className={cn("text-[10px] font-mono", clrPnl(r.net_pnl_pct))}>
                              {r.net_pnl_pct >= 0 ? "+" : ""}{fmt(r.net_pnl_pct)}%
                            </div>
                          )}
                        </td>

                        {/* Profit Factor */}
                        <td className="px-4 py-3 text-right">
                          <span className={cn("font-mono text-sm", r.total_trades ? clrPf(r.profit_factor) : "text-muted-foreground")}>
                            {r.total_trades ? (r.profit_factor >= 999 ? "∞" : fmt(r.profit_factor)) : "—"}
                          </span>
                        </td>

                        {/* Reliability */}
                        <td className="px-4 py-3">
                          <ReliabilityBar label={r.reliability_label} multiplier={r.reliability_multiplier} />
                        </td>

                        {/* Final Score */}
                        <td className="px-4 py-3">
                          <ScoreBar score={r.final_score} max={85} />
                          <div className="text-[10px] font-mono text-muted-foreground mt-0.5">
                            raw {fmt(r.raw_score, 1)} × {r.reliability_multiplier}
                          </div>
                        </td>

                        {/* Stability */}
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden min-w-[40px]">
                              <div className={cn("h-full rounded-full",
                                r.stability_score >= 60 ? "bg-emerald-500" : r.stability_score >= 35 ? "bg-yellow-500" : "bg-red-500"
                              )} style={{ width: `${r.stability_score}%` }} />
                            </div>
                            <span className={cn("font-mono text-xs w-8 text-right", clrStab(r.stability_score))}>
                              {fmt(r.stability_score, 0)}
                            </span>
                          </div>
                          <div className="text-[10px] font-mono text-muted-foreground mt-0.5">
                            {r.profitable_periods}/{r.total_periods} profitable
                          </div>
                        </td>

                        {/* Expand toggle */}
                        <td className="px-4 py-3 text-center">
                          {isOpen
                            ? <ChevronUp   className="h-4 w-4 text-muted-foreground mx-auto" />
                            : <ChevronDown className="h-4 w-4 text-muted-foreground mx-auto" />
                          }
                        </td>
                      </tr>

                      {/* Expanded: multi-period detail */}
                      {isOpen && (
                        <tr key={`exp-${idx}`} className={cn(
                          "border-b border-border",
                          isTop ? "bg-primary/5" : idx % 2 === 0 ? "bg-card" : "bg-background/20",
                        )}>
                          <td colSpan={11} className="px-6 py-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                              {/* Multi-period table */}
                              <div>
                                <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider mb-2">
                                  Multi-Period Stability (3M / 6M / 1Y / 2Y)
                                </div>
                                <table className="w-full text-xs border border-border/50 rounded overflow-hidden">
                                  <thead>
                                    <tr className="border-b border-border/50 bg-background/40">
                                      <th className="px-3 py-2 text-left  font-mono text-muted-foreground">Period</th>
                                      <th className="px-3 py-2 text-right font-mono text-muted-foreground">Trades</th>
                                      <th className="px-3 py-2 text-right font-mono text-muted-foreground">Win%</th>
                                      <th className="px-3 py-2 text-right font-mono text-muted-foreground">P&L%</th>
                                      <th className="px-3 py-2 text-right font-mono text-muted-foreground">Max DD</th>
                                      <th className="px-3 py-2 text-center font-mono text-muted-foreground">Profitable</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {r.multi_period.map((p, pi) => (
                                      <MultiPeriodRow key={pi} p={p} />
                                    ))}
                                  </tbody>
                                </table>
                              </div>

                              {/* Detail metrics */}
                              <div className="flex flex-col gap-4">
                                {/* Full-period metrics */}
                                <div>
                                  <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider mb-2">
                                    Full-Period Metrics
                                  </div>
                                  <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs font-mono">
                                    {[
                                      ["Max Drawdown", `${fmt(r.max_drawdown_pct)}%`, clrDd(r.max_drawdown_pct)],
                                      ["Sharpe Ratio",  fmt(r.sharpe_ratio),           clrSh(r.sharpe_ratio)],
                                      ["Profit Factor", r.profit_factor >= 999 ? "∞ (no losses)" : fmt(r.profit_factor), clrPf(r.profit_factor)],
                                      ["Avg Hold",      `${r.avg_duration_bars} bars`, "text-foreground"],
                                      ["Avg Win Rate (MP)", r.avg_win_rate_mp ? `${fmt(r.avg_win_rate_mp)}%` : "—", clrWr(r.avg_win_rate_mp)],
                                      ["Avg DD (MP)",   r.avg_drawdown_mp ? `${fmt(r.avg_drawdown_mp)}%` : "—", clrDd(r.avg_drawdown_mp)],
                                    ].map(([label, val, cls]) => (
                                      <div key={label as string} className="flex justify-between gap-2">
                                        <span className="text-muted-foreground">{label}</span>
                                        <span className={cls as string}>{val}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>

                                {/* Score breakdown */}
                                <div>
                                  <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider mb-2">
                                    Score Breakdown
                                  </div>
                                  <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs font-mono">
                                    <div className="flex justify-between"><span className="text-muted-foreground">Raw Score</span><span className="text-foreground">{fmt(r.raw_score, 1)}</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground">Reliability</span><span className={REL_CFG[r.reliability_label]?.cls}>{r.reliability_label}</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground">Multiplier</span><span className="text-foreground">×{r.reliability_multiplier}</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground font-semibold">Final Score</span><span className="text-primary font-bold">{fmt(r.final_score, 1)}</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground">Stability</span><span className={clrStab(r.stability_score)}>{fmt(r.stability_score, 0)}/100</span></div>
                                    <div className="flex justify-between"><span className="text-muted-foreground">Badge</span><span><BadgePill badge={r.badge} size="sm" /></span></div>
                                  </div>
                                </div>

                                {/* Warnings */}
                                {r.warnings.length > 0 && (
                                  <div>
                                    <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider mb-2">Warnings</div>
                                    <div className="flex flex-col gap-1.5">
                                      {r.warnings.map((w, wi) => <WarnBadge key={wi} text={w} />)}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Badge legend */}
          <div className="rounded border border-border bg-card p-4">
            <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider mb-2">Robustness Badge Guide</div>
            <BadgeLegend />
          </div>

          {/* Footnotes */}
          <div className="flex flex-wrap items-start gap-x-6 gap-y-2 text-xs font-mono text-muted-foreground/70">
            <span>
              Final Score = Raw Score (0–85) × Reliability Multiplier (0.10–1.00)
            </span>
            <span className="ml-auto">
              ₹5,000 capital · paper trading only · {results.length} of 51 combinations shown · click row for details
            </span>
          </div>
        </>
      )}

      {/* Empty state */}
      {!isLoading && !results && !hasError && (
        <div className="rounded border border-border bg-card p-12 flex flex-col items-center gap-4 text-center">
          <div className="flex gap-2">
            {["A","B","C","D"].map(b => <BadgePill key={b} badge={b} size="lg" />)}
          </div>
          <p className="text-sm font-mono text-muted-foreground max-w-md">
            Click <span className="text-primary">Run Optimizer</span> to test{" "}
            <span className="text-foreground">51 parameter combinations</span> across 4 strategies,
            each tested across <span className="text-foreground">4 time windows</span> (3M / 6M / 1Y / 2Y).
          </p>
          <p className="text-xs text-muted-foreground/60">
            Reliability multiplier prevents 1-trade wonders from ranking #1.
            Robustness badge (A–D) shows overall trustworthiness.
          </p>
        </div>
      )}
    </div>
  );
}
