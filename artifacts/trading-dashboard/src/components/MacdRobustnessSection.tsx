import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronDown, ChevronRight, ShieldCheck, ShieldAlert, ShieldX } from "lucide-react";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

const fmtPct = (v: any, signed = true) =>
  v === undefined || v === null ? "—" : `${signed && Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
const fmtNum = (v: any, d = 2) =>
  v === undefined || v === null ? "—" : Number(v).toFixed(d);
const fmtINR = (v: any) =>
  v === undefined || v === null ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pnlClass = (v: any) =>
  v === undefined || v === null ? "" : Number(v) > 0 ? "text-emerald-400" : Number(v) < 0 ? "text-red-400" : "";

const VERDICT_META = {
  KEEP:     { icon: ShieldCheck, color: "text-emerald-400", bg: "bg-emerald-900/30 border-emerald-700" },
  RESTRICT: { icon: ShieldAlert, color: "text-amber-400",   bg: "bg-amber-900/30 border-amber-700" },
  REJECT:   { icon: ShieldX,     color: "text-red-400",     bg: "bg-red-900/30 border-red-700" },
};

const ACTION_CLASS: Record<string, string> = {
  ENABLE: "text-emerald-400",
  MONITOR: "text-amber-400",
  DISABLE: "text-red-400",
  "INSUFFICIENT DATA": "text-zinc-400",
};

function Sub({ title, children, defaultOpen = false }: {
  title: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-zinc-800 rounded-md">
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-mono uppercase tracking-wide text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {title}
      </button>
      {open && <div className="px-3 pb-3 space-y-3">{children}</div>}
    </div>
  );
}

function Tbl({ cols, rows, testId }: { cols: string[]; rows: (string | number | React.ReactNode)[][]; testId?: string }) {
  return (
    <div className="overflow-x-auto" data-testid={testId}>
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-zinc-800">
            {cols.map((c) => <th key={c} className="py-1.5 pr-3 font-normal uppercase text-[10px] tracking-wide whitespace-nowrap">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-zinc-800/50">
              {row.map((cell, j) => <td key={j} className="py-1.5 pr-3 whitespace-nowrap">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="bg-zinc-800/50 rounded-md p-3">
      <div className="text-[10px] text-muted-foreground font-mono mb-1 uppercase tracking-wide">{label}</div>
      <div className={cn("text-base font-mono font-bold", valueClass ?? "text-foreground")}>{value}</div>
    </div>
  );
}

const METRIC_COLS = ["Trades", "Net return", "Expectancy/trade", "PF", "Win rate", "Sharpe", "Max DD", "Profit contrib"];

const metricCells = (r: any) => [
  r?.trades ?? "—",
  <span className={pnlClass(r?.net_return_pct)}>{fmtPct(r?.net_return_pct)}</span>,
  <span className={pnlClass(r?.expectancy_pct)}>{fmtPct(r?.expectancy_pct)}</span>,
  fmtNum(r?.profit_factor),
  `${fmtNum(r?.win_rate, 1)}%`,
  fmtNum(r?.sharpe_ratio),
  `${fmtNum(r?.max_drawdown_pct, 1)}%`,
  r?.profit_contribution_pct !== undefined
    ? `${fmtNum(r?.profit_contribution_pct, 1)}%`
    : "—",
];

const STRESS_COLS = ["Test", "Trades", "Net return", "Expectancy/trade", "PF", "Sharpe", "Max DD", "vs baseline exp", "Still profitable"];

function stressRow(r: any, label?: string) {
  return [
    <div>
      <div className="text-foreground">{label ?? r.label}</div>
      <div className="text-[10px] text-muted-foreground max-w-[260px] whitespace-normal">{r.description}</div>
    </div>,
    r.trades ?? "—",
    <span className={pnlClass(r.net_return_pct)}>{fmtPct(r.net_return_pct)}</span>,
    <span className={pnlClass(r.expectancy_pct)}>{fmtPct(r.expectancy_pct)}</span>,
    fmtNum(r.profit_factor),
    fmtNum(r.sharpe_ratio),
    `${fmtNum(r.max_drawdown_pct, 1)}%`,
    <span className={pnlClass(r.vs_base_expectancy)}>{fmtPct(r.vs_base_expectancy)}</span>,
    <span className={r.still_profitable ? "text-emerald-400" : "text-red-400"}>
      {r.still_profitable ? "YES" : "NO"}
    </span>,
  ];
}

export default function MacdRobustnessSection({ rob }: { rob: any }) {
  const [open, setOpen] = useState(true);

  const verdict = rob?.verdict ?? {};
  const vm = VERDICT_META[verdict.verdict as keyof typeof VERDICT_META] ?? VERDICT_META.RESTRICT;
  const VerdictIcon = vm.icon;

  const header = (
    <CardHeader
      className="cursor-pointer select-none py-3"
      onClick={() => setOpen(!open)}
      data-testid="section-macd-robustness-phase-4"
    >
      <CardTitle className="text-sm font-mono flex items-center gap-2">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <VerdictIcon className={cn("h-4 w-4", vm.color)} />
        MACD Robustness Analysis (Phase 4 — analysis only)
        {verdict.verdict && (
          <span className={cn("ml-2 text-xs font-bold px-2 py-0.5 rounded border", vm.bg, vm.color)}>
            {verdict.verdict}
          </span>
        )}
      </CardTitle>
    </CardHeader>
  );

  if (rob?.error) {
    return (
      <Card className="bg-zinc-900 border-zinc-800">
        {header}
        {open && (
          <CardContent>
            <p className="text-xs font-mono text-red-400">{rob.error}</p>
          </CardContent>
        )}
      </Card>
    );
  }

  const base = rob?.baseline ?? {};
  const breakdowns = rob?.breakdowns ?? {};
  const stress = rob?.stress_tests ?? {};
  const concentration = rob?.concentration ?? {};
  const regimeRecs = rob?.regime_recommendations ?? [];
  const roadmap = rob?.roadmap ?? [];
  const checks = verdict.checks ?? [];
  const windowPerf: any[] = rob?.window_performance ?? [];

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      {header}
      {open && (
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground font-mono">{rob?.safety}</p>

          {/* ── Verdict banner ── */}
          <div className={cn("rounded-md border p-3", vm.bg)}>
            <div className={cn("text-sm font-mono font-bold mb-1", vm.color)}>
              {verdict.verdict}: {verdict.passed_count}/{checks.length} robustness checks passed
            </div>
            <p className="text-xs font-mono text-muted-foreground">{verdict.rationale}</p>
          </div>

          {/* ── Verdict checklist ── */}
          <Sub title="Stability checklist" defaultOpen>
            <Tbl
              cols={["Check", "Threshold", "Observed", "Result"]}
              rows={checks.map((c: any) => [
                <div>
                  <div className={c.passed ? "text-foreground" : "text-red-300"}>{c.name}</div>
                  <div className="text-[10px] text-muted-foreground whitespace-normal max-w-[340px]">{c.description}</div>
                </div>,
                <span className="font-mono text-zinc-400">{c.threshold}</span>,
                <span className={cn("font-mono", c.passed ? "text-foreground" : "text-red-300")}>{c.observed}</span>,
                <span className={c.passed ? "text-emerald-400 font-bold" : "text-red-400 font-bold"}>
                  {c.passed ? "PASS" : "FAIL"}
                  {c.critical && !c.passed ? " ⚠ critical" : ""}
                </span>,
              ])}
              testId="table-robustness-verdict"
            />
          </Sub>

          {/* ── Baseline summary ── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <Stat label="Total OOS trades" value={String(base.trades ?? "—")} />
            <Stat label="Expectancy / trade" value={fmtPct(base.expectancy_pct)} valueClass={pnlClass(base.expectancy_pct)} />
            <Stat label="Profit factor" value={fmtNum(base.profit_factor)} />
            <Stat label="Max drawdown" value={`${fmtNum(base.max_drawdown_pct, 1)}%`}
              valueClass={Number(base.max_drawdown_pct) >= 40 ? "text-red-400" : "text-foreground"} />
          </div>

          {/* ── Concentration summary ── */}
          <Sub title="Concentration summary" defaultOpen>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              <Stat label="Top stock" value={`${concentration.top_stock ?? "—"}: ${fmtNum(concentration.top_stock_share_pct, 1)}%`}
                valueClass={Number(concentration.top_stock_share_pct) > 35 ? "text-red-400" : "text-foreground"} />
              <Stat label="Top sector" value={`${concentration.top_sector ?? "—"}: ${fmtNum(concentration.top_sector_share_pct, 1)}%`}
                valueClass={Number(concentration.top_sector_share_pct) > 35 ? "text-red-400" : "text-foreground"} />
              <Stat label="Top month" value={`${concentration.top_month ?? "—"}: ${fmtNum(concentration.top_month_share_pct, 1)}%`} />
              <Stat label="Top 1 trade" value={`${fmtNum(concentration.top1_trade_share_pct, 1)}% of profit`} />
              <Stat label="Top 5 trades" value={`${fmtNum(concentration.top5_trade_share_pct, 1)}% of profit`}
                valueClass={Number(concentration.top5_trade_share_pct) > 50 ? "text-red-400" : "text-foreground"} />
              <Stat label="Top 10 trades" value={`${fmtNum(concentration.top10_trade_share_pct, 1)}% of profit`} />
            </div>
          </Sub>

          {/* ── Performance breakdowns ── */}
          <Sub title="1 · Performance by stock" defaultOpen>
            <Tbl cols={["Stock", ...METRIC_COLS]} testId="table-robustness-by-stock"
              rows={(breakdowns.by_stock ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          <Sub title="2 · Performance by sector" defaultOpen>
            <Tbl cols={["Sector", ...METRIC_COLS]} testId="table-robustness-by-sector"
              rows={(breakdowns.by_sector ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          <Sub title="3 · Performance by market regime" defaultOpen>
            <Tbl cols={["Regime", ...METRIC_COLS]} testId="table-robustness-by-regime"
              rows={(breakdowns.by_regime ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          <Sub title="4 · Performance by month">
            <Tbl cols={["Month", ...METRIC_COLS]} testId="table-robustness-by-month"
              rows={(breakdowns.by_month ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          <Sub title="5 · Performance by holding period">
            <Tbl cols={["Holding period", ...METRIC_COLS]} testId="table-robustness-by-holding"
              rows={(breakdowns.by_holding_period ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          <Sub title="6 · Performance by volatility band (ATR%)">
            <Tbl cols={["Volatility band", ...METRIC_COLS]}
              rows={(breakdowns.by_volatility_band ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          <Sub title="7 · Performance by ADX band (trend strength)">
            <Tbl cols={["ADX band", ...METRIC_COLS]}
              rows={(breakdowns.by_adx_band ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          <Sub title="8 · Performance by entry sub-type">
            <Tbl cols={["Entry type", ...METRIC_COLS]}
              rows={(breakdowns.by_entry_subtype ?? []).map((r: any) => [r.group, ...metricCells(r)])} />
          </Sub>

          {/* ── Walk-forward window performance ── */}
          <Sub title="Performance by walk-forward window">
            <Tbl
              cols={["Window", "Test period", "Trades", "Net return", "Expectancy/trade", "PF", "Sharpe", "Max DD"]}
              rows={windowPerf.map((w: any) => [
                w.label,
                `${String(w.test_start ?? "").slice(0, 10)} → ${String(w.test_end ?? "").slice(0, 10)}`,
                w.trades ?? "—",
                <span className={pnlClass(w.net_return_pct)}>{fmtPct(w.net_return_pct)}</span>,
                <span className={pnlClass(w.expectancy_pct)}>{fmtPct(w.expectancy_pct)}</span>,
                fmtNum(w.profit_factor),
                fmtNum(w.sharpe_ratio),
                `${fmtNum(w.max_drawdown_pct, 1)}%`,
              ])}
              testId="table-robustness-windows"
            />
          </Sub>

          {/* ── Stress tests ── */}
          <Sub title="Stress test: leave-one-stock-out" defaultOpen>
            <div className="text-[11px] font-mono text-muted-foreground mb-2">
              Each row shows performance after removing all trades from that stock.
              Rows where "still profitable = NO" are concentration risks.
            </div>
            <Tbl cols={STRESS_COLS}
              rows={(stress.leave_one_stock_out ?? []).map((r: any) => stressRow(r))}
              testId="table-stress-stock-out" />
          </Sub>

          <Sub title="Stress test: leave-one-sector-out" defaultOpen>
            <div className="text-[11px] font-mono text-muted-foreground mb-2">
              Removes all trades from one sector at a time.
            </div>
            <Tbl cols={STRESS_COLS}
              rows={(stress.leave_one_sector_out ?? []).map((r: any) => stressRow(r))}
              testId="table-stress-sector-out" />
          </Sub>

          <Sub title="Stress test: leave-one-month-out">
            <Tbl cols={STRESS_COLS}
              rows={(stress.leave_one_month_out ?? []).map((r: any) => stressRow(r))}
              testId="table-stress-month-out" />
          </Sub>

          <Sub title="Stress test: top-5 trades removed" defaultOpen>
            <div className="text-[11px] font-mono text-amber-400 mb-2">
              Top-5 trades by P&amp;L removed: {stress.top5_trades_removed?.removed_label}.
              They account for{" "}
              <strong>{fmtNum(stress.top5_trades_removed?.top5_share_of_profit_pct, 1)}%</strong> of total profit.
            </div>
            <Tbl cols={STRESS_COLS}
              rows={stress.top5_trades_removed ? [stressRow(stress.top5_trades_removed)] : []}
              testId="table-stress-top5" />
          </Sub>

          <Sub title="Stress test: winsorized returns (±2σ)" defaultOpen>
            <div className="text-[11px] font-mono text-muted-foreground mb-2">
              {stress.winsorized_returns?.description}
            </div>
            <Tbl cols={STRESS_COLS}
              rows={stress.winsorized_returns ? [stressRow(stress.winsorized_returns)] : []}
              testId="table-stress-winsor" />
          </Sub>

          {/* ── Regime recommendations ── */}
          <Sub title="Regime-specific recommendations" defaultOpen>
            <Tbl
              cols={["Regime", "Trades", "Expectancy/trade", "PF", "Win rate", "Max DD", "Action", "Reason"]}
              rows={regimeRecs.map((r: any) => [
                r.regime,
                r.trades,
                <span className={pnlClass(r.expectancy_pct)}>{fmtPct(r.expectancy_pct)}</span>,
                fmtNum(r.profit_factor),
                `${fmtNum(r.win_rate, 1)}%`,
                `${fmtNum(r.max_drawdown_pct, 1)}%`,
                <span className={cn("font-bold", ACTION_CLASS[r.action] ?? "text-zinc-300")}>{r.action}</span>,
                <span className="text-[10px] text-muted-foreground max-w-[300px] whitespace-normal block">{r.reason}</span>,
              ])}
              testId="table-robustness-regimes"
            />
          </Sub>

          {/* ── Improvement roadmap ── */}
          <Sub title="Improvement roadmap" defaultOpen>
            <div className="space-y-2">
              {roadmap.map((item: any, i: number) => (
                <div key={i} className="border border-zinc-800 rounded-md p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-mono text-muted-foreground uppercase">
                      Priority {item.priority}
                    </span>
                    <span className="text-xs font-mono font-bold text-cyan-400">{item.area}</span>
                  </div>
                  <p className="text-xs font-mono text-foreground">{item.action}</p>
                  <p className="text-[11px] font-mono text-muted-foreground mt-1">Target: {item.target}</p>
                </div>
              ))}
            </div>
          </Sub>
        </CardContent>
      )}
    </Card>
  );
}
