import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronDown, ChevronRight, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

const fmtPct = (v: number | undefined | null, signed = true) =>
  v === undefined || v === null ? "—" : `${signed && Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
const fmtNum = (v: number | undefined | null, d = 2) =>
  v === undefined || v === null ? "—" : Number(v).toFixed(d);
const fmtINR = (v: number | undefined | null) =>
  v === undefined || v === null ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pnlClass = (v: number | undefined | null) =>
  v === undefined || v === null ? "" : Number(v) > 0 ? "text-emerald-400" : Number(v) < 0 ? "text-red-400" : "";

const VERDICT_CLASS: Record<string, string> = {
  ACCEPTED: "text-emerald-400",
  REJECTED: "text-red-400",
  INSUFFICIENT_SAMPLE: "text-amber-400",
};
const VERDICT_LABEL: Record<string, string> = {
  ACCEPTED: "ACCEPTED",
  REJECTED: "REJECTED",
  INSUFFICIENT_SAMPLE: "TOO FEW TRADES",
};
const CATEGORY_LABEL: Record<string, string> = {
  entry_filter: "Entry filter",
  exit: "Exit rule",
  risk_management: "Risk rule",
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
        data-testid={`macd-sub-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
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

const metricCells = (m: any) => [
  m?.trades ?? "—",
  <span className={pnlClass(m?.net_return_pct)}>{fmtPct(m?.net_return_pct)}</span>,
  <span className={pnlClass(m?.expectancy_pct)}>{fmtPct(m?.expectancy_pct)}</span>,
  fmtNum(m?.profit_factor),
  `${fmtNum(m?.win_rate, 1)}%`,
  fmtNum(m?.sharpe_ratio),
  `${fmtNum(m?.max_drawdown_pct, 1)}%`,
  fmtINR(m?.total_costs),
];

const METRIC_COLS = ["Trades", "Net return", "Expectancy/trade", "PF", "Win rate", "Sharpe", "Max DD", "Txn costs"];

export default function MacdOptimizationSection({ opt }: { opt: any }) {
  const [open, setOpen] = useState(true);

  const header = (
    <CardHeader
      className="cursor-pointer select-none py-3"
      onClick={() => setOpen(!open)}
      data-testid="section-macd-optimization-phase-3"
    >
      <CardTitle className="text-sm font-mono flex items-center gap-2">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <SlidersHorizontal className="h-4 w-4 text-cyan-400" />
        MACD Optimization Report (Phase 3 — analysis only)
      </CardTitle>
    </CardHeader>
  );

  if (opt?.error) {
    return (
      <Card className="bg-zinc-900 border-zinc-800">
        {header}
        {open && (
          <CardContent>
            <p className="text-xs font-mono text-red-400" data-testid="text-macd-error">{opt.error}</p>
          </CardContent>
        )}
      </Card>
    );
  }

  const base = opt?.baseline?.trade_level ?? {};
  const basePort = opt?.baseline?.portfolio ?? {};
  const table: any[] = opt?.comparison_table ?? [];
  const filters = table.filter((r) => r.category === "entry_filter");
  const exits = table.filter((r) => r.category === "exit");
  const risk = table.filter((r) => r.category === "risk_management");
  const combined = opt?.combined ?? {};
  const rc = opt?.recommended_config ?? {};
  const report = opt?.report ?? {};

  const variationRow = (r: any) => [
    <div>
      <div className="text-foreground">{r.name}</div>
      <div className="text-[10px] text-muted-foreground max-w-[260px] whitespace-normal">{r.description}</div>
    </div>,
    ...metricCells(r),
    <span className={pnlClass(r.vs_baseline_expectancy_diff)}>
      {r.vs_baseline_expectancy_diff === null || r.vs_baseline_expectancy_diff === undefined
        ? "—" : fmtPct(r.vs_baseline_expectancy_diff)}
    </span>,
    <div>
      <div className={cn("font-bold", VERDICT_CLASS[r.verdict] ?? "text-zinc-300")}>
        {VERDICT_LABEL[r.verdict] ?? r.verdict}
      </div>
      <div className="text-[10px] text-muted-foreground max-w-[280px] whitespace-normal">{r.reason}</div>
    </div>,
  ];

  const variationCols = ["Variation", ...METRIC_COLS, "vs baseline", "Verdict"];

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      {header}
      {open && (
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground font-mono" data-testid="text-macd-safety">
            {opt?.safety}
          </p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <Stat label="Baseline trades (unseen data)" value={String(base.trades ?? "—")} />
            <Stat label="Baseline expectancy / trade" value={fmtPct(base.expectancy_pct)} valueClass={pnlClass(base.expectancy_pct)} />
            <Stat label="Baseline profit factor" value={fmtNum(base.profit_factor)} />
            <Stat label="Baseline win rate" value={`${fmtNum(base.win_rate, 1)}%`} />
          </div>

          <div className="text-[11px] font-mono text-muted-foreground" data-testid="text-macd-baseline-summary">
            {report.baseline_summary}
          </div>

          <Sub title="1 · Entry filters (only remove trades — never add)" defaultOpen>
            <Tbl cols={variationCols} rows={filters.map(variationRow)} testId="table-macd-entry-filters" />
          </Sub>

          <Sub title="2 · Exit variations (same entries, different exits)" defaultOpen>
            <Tbl cols={variationCols} rows={exits.map(variationRow)} testId="table-macd-exits" />
          </Sub>

          <Sub title="3 · Risk management (portfolio replay)" defaultOpen>
            <div className="text-[11px] font-mono text-muted-foreground">
              Portfolio baseline for comparison: net return{" "}
              <span className={pnlClass(basePort.net_return_pct)}>{fmtPct(basePort.net_return_pct)}</span>, Sharpe {fmtNum(basePort.sharpe_ratio)},
              max drawdown {fmtNum(basePort.max_drawdown_pct, 1)}%, {basePort.trades ?? "—"} trades.
            </div>
            <Tbl cols={variationCols} rows={risk.map(variationRow)} testId="table-macd-risk" />
          </Sub>

          <Sub title="4 · Combined configuration vs baseline">
            <Tbl
              cols={["Configuration", ...METRIC_COLS]}
              rows={[
                ["Baseline (trade-level)", ...metricCells(base)],
                ["Combined (trade-level)", ...metricCells(combined.trade_level ?? {})],
                ["Baseline (portfolio)", ...metricCells(basePort)],
                ["Combined (portfolio)", ...metricCells(combined.portfolio ?? {})],
              ]}
              testId="table-macd-combined"
            />
            <div className="text-[11px] font-mono text-muted-foreground">{report.combined_vs_baseline}</div>
            {report.exit_note ? (
              <div className="text-[11px] font-mono text-amber-400">{report.exit_note}</div>
            ) : null}
            {combined.validation_caveat ? (
              <div className="text-[11px] font-mono text-amber-400" data-testid="text-macd-combined-caveat">
                ⚠ {combined.validation_caveat}
              </div>
            ) : null}
          </Sub>

          <Sub title="5 · Final recommended configuration" defaultOpen>
            <div
              className={cn(
                "text-xs font-mono font-bold",
                rc.adopted ? "text-emerald-400" : "text-amber-400",
              )}
              data-testid="text-macd-recommendation"
            >
              {rc.status}
            </div>
            <div className="text-[11px] font-mono text-muted-foreground">{rc.strategy}</div>
            <Tbl
              cols={["Component", "Setting", "Rule"]}
              rows={[
                ...(rc.entry_filters ?? []).map((f: any) => [
                  "Entry filter",
                  f.name,
                  f.rule ?? "",
                ]),
                ...(rc.exit ? [["Exit", rc.exit.name, rc.exit.rule ?? ""]] : []),
                ...(rc.risk_rules ?? []).map((rr: any) => ["Risk rule", rr.name, rr.rule]),
              ]}
              testId="table-macd-recommended-config"
            />
            <div className="text-[11px] font-mono text-muted-foreground">{rc.parameters_note}</div>
            {rc.validation_caveat ? (
              <div className="text-[11px] font-mono text-amber-400" data-testid="text-macd-recommendation-caveat">
                ⚠ {rc.validation_caveat}
              </div>
            ) : null}
          </Sub>

          <Sub title="6 · Everything that was rejected (and why)">
            <Tbl
              cols={["Variation", "Type", "Verdict", "Reason"]}
              rows={(report.rejected ?? []).map((r: any) => [
                r.name,
                CATEGORY_LABEL[r.category] ?? r.category,
                <span className={VERDICT_CLASS[r.verdict] ?? "text-zinc-300"}>{VERDICT_LABEL[r.verdict] ?? r.verdict}</span>,
                <span className="whitespace-normal max-w-[420px] block">{r.reason}</span>,
              ])}
              testId="table-macd-rejected"
            />
          </Sub>

          <Sub title="Methodology (how look-ahead bias was avoided)">
            <p className="text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">{opt?.methodology}</p>
          </Sub>
        </CardContent>
      )}
    </Card>
  );
}
