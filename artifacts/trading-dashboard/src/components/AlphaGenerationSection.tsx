import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChevronDown, ChevronRight, FlaskConical,
  ShieldCheck, ShieldAlert, ShieldX, CheckCircle2, XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ── Formatters ────────────────────────────────────────────────────────────────
const fmtPct = (v: any, signed = true) =>
  v === undefined || v === null ? "—"
    : `${signed && Number(v) > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
const fmtNum = (v: any, d = 2) =>
  v === undefined || v === null ? "—" : Number(v).toFixed(d);
const pnlClass = (v: any) =>
  v === undefined || v === null ? ""
    : Number(v) > 0 ? "text-emerald-400"
    : Number(v) < 0 ? "text-red-400" : "";

// ── Verdict meta ──────────────────────────────────────────────────────────────
const VERDICT_META = {
  KEEP_FOR_FURTHER_TESTING: {
    icon: ShieldCheck,
    color: "text-emerald-400",
    bg: "bg-emerald-900/30 border-emerald-700",
    short: "KEEP",
  },
  INCONCLUSIVE: {
    icon: ShieldAlert,
    color: "text-warn",
    bg: "bg-warn-surface border-warn",
    short: "INCONCLUSIVE",
  },
  REJECT: {
    icon: ShieldX,
    color: "text-red-400",
    bg: "bg-red-900/30 border-red-700",
    short: "REJECT",
  },
};

function verdictMeta(v: string) {
  return (
    VERDICT_META[v as keyof typeof VERDICT_META] ?? VERDICT_META.INCONCLUSIVE
  );
}

// ── Sub-section (collapsible) ─────────────────────────────────────────────────
function Sub({
  title, children, defaultOpen = false,
}: {
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

// ── Table ─────────────────────────────────────────────────────────────────────
function Tbl({
  cols, rows, testId,
}: {
  cols: string[];
  rows: (string | number | React.ReactNode)[][];
  testId?: string;
}) {
  return (
    <div className="overflow-x-auto" data-testid={testId}>
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-zinc-800">
            {cols.map((c) => (
              <th key={c} className="py-1.5 pr-3 font-normal uppercase text-[10px] tracking-wide whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-zinc-800/50">
              {row.map((cell, j) => (
                <td key={j} className="py-1.5 pr-3 whitespace-nowrap">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Stat tile ─────────────────────────────────────────────────────────────────
function Stat({
  label, value, valueClass,
}: {
  label: string; value: string; valueClass?: string;
}) {
  return (
    <div className="bg-zinc-800/50 rounded-md p-3">
      <div className="text-[10px] text-muted-foreground font-mono mb-1 uppercase tracking-wide">
        {label}
      </div>
      <div className={cn("text-base font-mono font-bold", valueClass ?? "text-foreground")}>
        {value}
      </div>
    </div>
  );
}

// ── Candidate card ────────────────────────────────────────────────────────────
function CandidateCard({ cand }: { cand: any }) {
  const [open, setOpen] = useState(false);
  const vm = verdictMeta(cand.verdict);
  const VIcon = vm.icon;
  const m = cand.metrics ?? {};
  const cons = cand.window_consistency ?? {};
  const conc = cand.concentration ?? {};
  const checks: any[] = cand.verdict_checks ?? [];
  const regimes: any[] = cand.regime_breakdown ?? [];
  const sectors: any[] = cand.sector_breakdown ?? [];

  return (
    <div className="border border-zinc-800 rounded-md">
      <button
        type="button"
        className="w-full flex items-start gap-2 px-3 py-2.5 text-left hover:bg-zinc-800/30"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
              : <ChevronRight className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-mono font-bold text-zinc-300">
              {cand.id}: {cand.name}
            </span>
            <span className={cn("text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border", vm.bg, vm.color)}>
              {vm.short}
            </span>
            <span className="text-[10px] text-muted-foreground font-mono">
              {m.trades ?? 0} trades · {cand.pct_of_baseline?.toFixed(0) ?? "?"}% of baseline
            </span>
          </div>
          <div className="flex gap-4 mt-1 text-[11px] font-mono">
            <span className={pnlClass(m.expectancy_pct)}>
              exp {fmtPct(m.expectancy_pct)} / trade
            </span>
            <span>PF {fmtNum(m.profit_factor)}</span>
            <span>DD {fmtNum(m.max_drawdown_pct, 1)}%</span>
            <span className="text-zinc-500">
              {cons.positive_windows ?? 0}/{cons.total_windows ?? 0} windows ✓
            </span>
          </div>
          <div className="mt-1 flex gap-1 flex-wrap">
            {(cand.filters ?? []).map((f: string, i: number) => (
              <span key={i} className="text-[10px] bg-zinc-800 rounded px-1.5 py-0.5 font-mono text-zinc-400">
                {f}
              </span>
            ))}
          </div>
        </div>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-3">
          <p className="text-xs text-muted-foreground font-mono">{cand.description}</p>

          {/* Strategy components */}
          {cand.components?.length > 0 && (
            <div className="flex gap-1 flex-wrap">
              {cand.components.map((c: string, i: number) => (
                <span key={i} className="text-[10px] bg-blue-900/30 border border-blue-800/50 rounded px-1.5 py-0.5 font-mono text-blue-300">
                  {c}
                </span>
              ))}
            </div>
          )}

          {/* Verdict banner */}
          <div className={cn("rounded-md border p-3", vm.bg)}>
            <div className={cn("text-xs font-mono font-bold mb-1", vm.color)}>
              {cand.verdict}: {cand.verdict_passed}/{checks.length} gates passed
            </div>
            <p className="text-[11px] font-mono text-muted-foreground">{cand.verdict_rationale}</p>
          </div>

          {/* Quality gate checklist */}
          <Sub title={`Quality gates (${cand.verdict_passed}/${checks.length} passed)`} defaultOpen>
            <div className="space-y-1">
              {checks.map((c: any, i: number) => (
                <div key={i} className="flex items-start gap-2 text-[11px] font-mono">
                  {c.passed
                    ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
                    : <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />}
                  <span className={c.passed ? "text-foreground" : "text-red-300"}>
                    {c.check}
                  </span>
                  {c.detail && (
                    <span className="text-muted-foreground ml-1">({c.detail})</span>
                  )}
                </div>
              ))}
            </div>
          </Sub>

          {/* Key metrics */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Trades" value={String(m.trades ?? "—")} />
            <Stat label="Expectancy" value={fmtPct(m.expectancy_pct)}
              valueClass={pnlClass(m.expectancy_pct)} />
            <Stat label="Profit factor" value={fmtNum(m.profit_factor)} />
            <Stat label="Win rate" value={`${fmtNum(m.win_rate, 1)}%`} />
            <Stat label="Net return" value={fmtPct(m.net_return_pct)}
              valueClass={pnlClass(m.net_return_pct)} />
            <Stat label="Sharpe" value={fmtNum(m.sharpe_ratio)} />
            <Stat label="Max drawdown" value={`${fmtNum(m.max_drawdown_pct, 1)}%`}
              valueClass={m.max_drawdown_pct > 60 ? "text-red-400"
                : m.max_drawdown_pct > 40 ? "text-warn" : ""} />
            <Stat label="Windows +" value={`${cons.pct_positive ?? 0}%`}
              valueClass={
                (cons.pct_positive ?? 0) >= 50 ? "text-emerald-400" : "text-warn"
              } />
          </div>

          {/* Per-window breakdown */}
          {(cons.per_window ?? []).length > 0 && (
            <Sub title="Per-window consistency">
              <Tbl
                cols={["Window", "Test period", "Trades", "Exp/trade", "PF", "Max DD", "+"]}
                rows={(cons.per_window ?? []).map((w: any) => [
                  w.label,
                  `${w.test_start?.slice(0, 10) ?? ""} → ${w.test_end?.slice(0, 10) ?? ""}`,
                  w.trades,
                  <span className={pnlClass(w.expectancy_pct)}>{fmtPct(w.expectancy_pct)}</span>,
                  fmtNum(w.profit_factor),
                  `${fmtNum(w.max_drawdown_pct, 1)}%`,
                  w.positive
                    ? <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                    : <XCircle className="h-3 w-3 text-red-400" />,
                ])}
              />
            </Sub>
          )}

          {/* Regime breakdown */}
          {regimes.length > 0 && (
            <Sub title="By market regime">
              <Tbl
                cols={["Regime", "Trades", "Exp/trade", "PF", "Win rate"]}
                rows={regimes.map((r: any) => [
                  r.regime,
                  r.trades,
                  <span className={pnlClass(r.expectancy_pct)}>{fmtPct(r.expectancy_pct)}</span>,
                  fmtNum(r.profit_factor),
                  `${fmtNum(r.win_rate, 1)}%`,
                ])}
              />
            </Sub>
          )}

          {/* Sector breakdown */}
          {sectors.length > 0 && (
            <Sub title="By sector">
              <Tbl
                cols={["Sector", "Trades", "Exp/trade", "PF", "Win rate"]}
                rows={sectors.slice(0, 8).map((r: any) => [
                  r.sector,
                  r.trades,
                  <span className={pnlClass(r.expectancy_pct)}>{fmtPct(r.expectancy_pct)}</span>,
                  fmtNum(r.profit_factor),
                  `${fmtNum(r.win_rate, 1)}%`,
                ])}
              />
            </Sub>
          )}

          {/* Concentration */}
          {(conc.top_stock || conc.top5_trade_share_pct !== undefined) && (
            <Sub title="Concentration">
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Top stock" value={`${conc.top_stock ?? "—"} (${fmtNum(conc.top_stock_share_pct, 1)}%)`}
                  valueClass={conc.top_stock_share_pct > 35 ? "text-warn" : ""} />
                <Stat label="Top sector" value={`${conc.top_sector ?? "—"} (${fmtNum(conc.top_sector_share_pct, 1)}%)`}
                  valueClass={conc.top_sector_share_pct > 35 ? "text-warn" : ""} />
                <Stat label="Top-5 trade share" value={`${fmtNum(conc.top5_trade_share_pct, 1)}%`}
                  valueClass={conc.top5_trade_share_pct > 70 ? "text-red-400"
                    : conc.top5_trade_share_pct > 50 ? "text-warn" : ""} />
              </div>
            </Sub>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function AlphaGenerationSection({ alpha }: { alpha: any }) {
  const [open, setOpen] = useState(true);

  const candidates: any[] = alpha?.candidates ?? [];
  const base = alpha?.baseline ?? {};
  const table: any[] = alpha?.comparison_table ?? [];
  const recs: any[] = alpha?.recommendation_summary ?? [];

  const keepCount = candidates.filter((c) => c.verdict === "KEEP_FOR_FURTHER_TESTING").length;
  const inconclusiveCount = candidates.filter((c) => c.verdict === "INCONCLUSIVE").length;
  const rejectCount = candidates.filter((c) => c.verdict === "REJECT").length;

  const header = (
    <CardHeader
      className="cursor-pointer select-none py-3"
      onClick={() => setOpen(!open)}
      data-testid="section-alpha-generation-phase-5"
    >
      <CardTitle className="text-sm font-mono flex items-center gap-2 flex-wrap">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <FlaskConical className="h-4 w-4 text-blue-400" />
        Phase 3 — Alpha Generation Engine
        <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border bg-blue-900/30 border-blue-700 text-blue-300">
          RESEARCH ONLY
        </span>
        {candidates.length > 0 && (
          <span className="text-xs text-muted-foreground font-mono ml-1">
            {keepCount > 0 && (
              <span className="text-emerald-400">{keepCount} keep </span>
            )}
            <span className="text-warn">{inconclusiveCount} inconclusive </span>
            <span className="text-red-400">{rejectCount} reject</span>
          </span>
        )}
      </CardTitle>
    </CardHeader>
  );

  if (alpha?.error) {
    return (
      <Card className="bg-zinc-900 border-zinc-800">
        {header}
        {open && (
          <CardContent>
            <p className="text-xs font-mono text-red-400">{alpha.error}</p>
          </CardContent>
        )}
      </Card>
    );
  }

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      {header}
      {open && (
        <CardContent className="space-y-4">
          {/* Safety notice */}
          <div className="rounded-md border border-blue-800/50 bg-blue-900/20 p-3">
            <p className="text-xs font-mono text-blue-300">{alpha?.safety}</p>
          </div>

          {/* Summary stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="OOS trades (baseline)" value={String(alpha?.total_oos_trades ?? "—")} />
            <Stat label="Windows evaluated" value={String(alpha?.windows_evaluated ?? "—")} />
            <Stat label="Baseline exp/trade" value={fmtPct(base.expectancy_pct)}
              valueClass={pnlClass(base.expectancy_pct)} />
            <Stat label="Baseline PF" value={fmtNum(base.profit_factor)} />
          </div>

          {/* Recommendation summary table */}
          {recs.length > 0 && (
            <Sub title={`Candidate ranking (${candidates.length} candidates)`} defaultOpen>
              <Tbl
                testId="alpha-recommendation-table"
                cols={["Candidate", "Trades", "Exp/trade", "PF", "Windows +", "Status"]}
                rows={recs.map((r: any) => {
                  const vm = verdictMeta(r.status);
                  const VIcon = vm.icon;
                  return [
                    <span className="text-zinc-300">{r.candidate_id}: {r.name?.replace(/^MACD × /, "")}</span>,
                    r.trades,
                    <span className={pnlClass(r.expectancy_pct)}>{fmtPct(r.expectancy_pct)}</span>,
                    fmtNum(r.profit_factor),
                    `${fmtNum(r.pct_positive_windows, 0)}%`,
                    <span className={cn("flex items-center gap-1 text-[10px] font-bold", vm.color)}>
                      <VIcon className="h-3 w-3" />
                      {vm.short}
                    </span>,
                  ];
                })}
              />
            </Sub>
          )}

          {/* Comparison table vs baseline */}
          {table.length > 0 && (
            <Sub title="Metrics comparison vs unfiltered MACD baseline">
              <Tbl
                testId="alpha-comparison-table"
                cols={["Name", "Trades", "Exp/trade", "PF", "Win rate", "Sharpe", "Max DD", "Net return"]}
                rows={table.map((r: any) => [
                  <span className={r.is_baseline ? "text-zinc-400 italic" : "text-zinc-300"}>
                    {r.name}
                  </span>,
                  r.trades,
                  <span className={pnlClass(r.expectancy_pct)}>{fmtPct(r.expectancy_pct)}</span>,
                  fmtNum(r.profit_factor),
                  `${fmtNum(r.win_rate, 1)}%`,
                  fmtNum(r.sharpe_ratio),
                  `${fmtNum(r.max_drawdown_pct, 1)}%`,
                  <span className={pnlClass(r.net_return_pct)}>{fmtPct(r.net_return_pct)}</span>,
                ])}
              />
            </Sub>
          )}

          {/* Individual candidate cards */}
          {candidates.length > 0 && (
            <Sub title="Candidate detail (click to expand)" defaultOpen>
              <div className="space-y-2">
                {candidates.map((c: any) => (
                  <CandidateCard key={c.id} cand={c} />
                ))}
              </div>
            </Sub>
          )}
        </CardContent>
      )}
    </Card>
  );
}
