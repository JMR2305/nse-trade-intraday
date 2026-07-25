import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChevronDown, ChevronRight, Scale,
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
  "ELIGIBLE FOR LIMITED SHADOW PAPER TEST": {
    icon: ShieldCheck,
    color: "text-emerald-400",
    bg: "bg-emerald-900/30 border-emerald-700",
    short: "ELIGIBLE (SHADOW TEST)",
  },
  "CONTINUE ANALYSIS": {
    icon: ShieldAlert,
    color: "text-warn",
    bg: "bg-warn-surface border-warn",
    short: "CONTINUE ANALYSIS",
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
    VERDICT_META[v as keyof typeof VERDICT_META]
    ?? VERDICT_META["CONTINUE ANALYSIS"]
  );
}

const LABEL_COLORS: Record<string, string> = {
  "STRONG BUY": "text-emerald-400",
  BUY: "text-emerald-300",
  WATCH: "text-warn",
  AVOID: "text-red-300",
  "NO TRADE": "text-zinc-500",
  EXIT: "text-blue-300",
};

// ── Sub-section (collapsible) ─────────────────────────────────────────────────
function Sub({
  title, children, defaultOpen = false, testId,
}: {
  title: string; children: React.ReactNode; defaultOpen?: boolean;
  testId?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-zinc-800 rounded-md" data-testid={testId}>
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

// ── Main component ────────────────────────────────────────────────────────────
export default function BalancedDecisionSection({ balanced }: { balanced: any }) {
  const [open, setOpen] = useState(true);

  const verdict = balanced?.final_recommendation ?? {};
  const vm = verdictMeta(verdict.recommendation);
  const VIcon = vm.icon;
  const comparison: any[] = balanced?.model_comparison ?? [];
  const gRow = comparison.find((r) => r.model === "G") ?? {};
  const windows: any[] = balanced?.windows ?? [];
  const labelDist: Record<string, number> =
    balanced?.recommendation_distribution ?? {};
  const tm = balanced?.transition_matrix ?? {};
  const cells: any[] = tm.cells ?? [];
  const changed: any[] = balanced?.changed_decision_examples ?? [];
  const calCmp = balanced?.calibration_comparison ?? {};
  const gCal = calCmp.balanced_model;
  const cCal = calCmp.current_model ?? {};
  const fp = balanced?.false_positive_analysis ?? {};
  const gates: Record<string, number> = balanced?.gate_failure_counts ?? {};
  const conc = balanced?.concentration ?? {};
  const audit = balanced?.safety_audit ?? {};
  const config = balanced?.config ?? {};
  const weights: Record<string, number> = config.weights ?? {};
  const checks: any[] = verdict.checks ?? [];

  const header = (
    <CardHeader
      className="cursor-pointer select-none py-3"
      onClick={() => setOpen(!open)}
      data-testid="section-balanced-decision-phase-3a"
    >
      <CardTitle className="text-sm font-mono flex items-center gap-2 flex-wrap">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Scale className="h-4 w-4 text-violet-400" />
        Phase 3A — Balanced Decision Model
        <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border bg-violet-900/30 border-violet-700 text-violet-300">
          ANALYSIS ONLY
        </span>
        {verdict.recommendation && (
          <span className={cn(
            "text-[10px] font-mono font-bold px-1.5 py-0.5 rounded border",
            vm.bg, vm.color,
          )}>
            {vm.short}
          </span>
        )}
      </CardTitle>
    </CardHeader>
  );

  if (balanced?.error) {
    return (
      <Card className="bg-zinc-900 border-zinc-800">
        {header}
        {open && (
          <CardContent>
            <p className="text-xs font-mono text-red-400" data-testid="balanced-error">
              {balanced.error}
            </p>
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
          <div className="rounded-md border border-violet-800/50 bg-violet-900/20 p-3">
            <p className="text-xs font-mono text-violet-300">{balanced?.safety}</p>
          </div>

          {/* Verdict banner */}
          {verdict.recommendation && (
            <div className={cn("rounded-md border p-3", vm.bg)}
              data-testid="balanced-verdict">
              <div className={cn("text-xs font-mono font-bold mb-1 flex items-center gap-2", vm.color)}>
                <VIcon className="h-4 w-4" />
                {verdict.recommendation}
              </div>
              <p className="text-[11px] font-mono text-muted-foreground">
                {verdict.summary}
              </p>
            </div>
          )}

          {/* Headline stats for shadow model G */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Shadow trades (G)" value={String(gRow.trades ?? "—")} />
            <Stat label="Net return" value={fmtPct(gRow.net_return_pct)}
              valueClass={pnlClass(gRow.net_return_pct)} />
            <Stat label="Profit factor" value={fmtNum(gRow.profit_factor)} />
            <Stat label="Expectancy" value={fmtNum(gRow.expectancy)}
              valueClass={pnlClass(gRow.expectancy)} />
            <Stat label="Win rate" value={`${fmtNum(gRow.win_rate, 1)}%`} />
            <Stat label="Max drawdown" value={`${fmtNum(gRow.max_drawdown_pct, 1)}%`} />
            <Stat label="Cash time" value={`${fmtNum(balanced?.cash_time_pct, 1)}%`} />
            <Stat label="Decisions changed" value={`${fmtNum(tm.changed_pct, 1)}%`} />
          </div>

          {/* Success criteria checklist */}
          {checks.length > 0 && (
            <Sub
              title={`Success criteria (${checks.filter((c: any) => c.passed).length}/${checks.length} passed)`}
              defaultOpen
              testId="balanced-criteria"
            >
              <div className="space-y-1">
                {checks.map((c: any, i: number) => (
                  <div key={i} className="flex items-start gap-2 text-[11px] font-mono">
                    {c.passed
                      ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
                      : <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />}
                    <span className={c.passed ? "text-foreground" : "text-red-300"}>
                      {c.name}
                    </span>
                    <span className="text-muted-foreground ml-1">
                      (observed {String(c.observed)}, needs {String(c.threshold)})
                    </span>
                  </div>
                ))}
              </div>
            </Sub>
          )}

          {/* Model comparison A-G */}
          {comparison.length > 0 && (
            <Sub title="Model comparison A–G (identical windows and costs)"
              defaultOpen testId="balanced-model-comparison">
              <Tbl
                cols={["Model", "Trades", "Net return", "PF", "Expectancy",
                       "Win rate", "Sharpe", "Max DD", "Cash %", "FP BUY %"]}
                rows={comparison.map((r: any) => [
                  <span className={r.model === "G"
                    ? "text-violet-300 font-bold" : "text-zinc-300"}>
                    {r.label ?? r.model}
                  </span>,
                  r.trades,
                  <span className={pnlClass(r.net_return_pct)}>{fmtPct(r.net_return_pct)}</span>,
                  fmtNum(r.profit_factor),
                  <span className={pnlClass(r.expectancy)}>{fmtNum(r.expectancy)}</span>,
                  `${fmtNum(r.win_rate, 1)}%`,
                  fmtNum(r.sharpe_ratio),
                  `${fmtNum(r.max_drawdown_pct, 1)}%`,
                  `${fmtNum(r.cash_time_pct, 1)}%`,
                  `${fmtNum(r.false_positive_rate_pct, 1)}%`,
                ])}
              />
              {balanced?.model_mapping_note && (
                <p className="text-[10px] font-mono text-zinc-500">
                  {balanced.model_mapping_note}
                </p>
              )}
            </Sub>
          )}

          {/* Shadow label distribution */}
          {Object.keys(labelDist).length > 0 && (
            <Sub title="Shadow recommendation distribution" testId="balanced-labels">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
                {Object.entries(labelDist).map(([k, v]) => (
                  <Stat key={k} label={k} value={String(v)}
                    valueClass={LABEL_COLORS[k]} />
                ))}
              </div>
            </Sub>
          )}

          {/* Transition matrix */}
          {cells.length > 0 && (
            <Sub title={`Decision transitions vs current model (${tm.changed ?? 0} changed / ${tm.unchanged ?? 0} unchanged)`}
              testId="balanced-transitions">
              <Tbl
                cols={["Current model", "Balanced model G", "Count"]}
                rows={cells.map((c: any) => [
                  <span className={LABEL_COLORS[c.from_label] ?? ""}>{c.from_label}</span>,
                  <span className={LABEL_COLORS[c.to_label] ?? ""}>{c.to_label}</span>,
                  c.count,
                ])}
              />
            </Sub>
          )}

          {/* Changed decision examples */}
          {changed.length > 0 && (
            <Sub title={`Changed decision examples (${changed.length})`}
              testId="balanced-changed-examples">
              <div className="space-y-2">
                {changed.map((e: any, i: number) => (
                  <div key={i} className="border border-zinc-800 rounded-md p-2.5">
                    <div className="flex items-center gap-2 flex-wrap text-[11px] font-mono">
                      <span className="font-bold text-zinc-300">{e.symbol}</span>
                      <span className="text-zinc-500">{e.date}</span>
                      <span className={LABEL_COLORS[e.current_label] ?? ""}>{e.current_label}</span>
                      <span className="text-zinc-500">→</span>
                      <span className={LABEL_COLORS[e.balanced_label] ?? ""}>{e.balanced_label}</span>
                      <span className="text-zinc-500">
                        score {fmtNum(e.balanced_score, 1)} · p {fmtNum(e.calibrated_probability, 2)}
                      </span>
                    </div>
                    {e.reason && (
                      <p className="text-[10px] font-mono text-muted-foreground mt-1">
                        {e.reason}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </Sub>
          )}

          {/* Per-window results */}
          {windows.length > 0 && (
            <Sub title="Per-window shadow results" testId="balanced-windows">
              <Tbl
                cols={["Window", "Test period", "Trades", "Net return", "PF",
                       "Win rate", "Max DD", "Cash %"]}
                rows={windows.map((w: any) => [
                  w.window,
                  `${String(w.test_start).slice(0, 10)} → ${String(w.test_end).slice(0, 10)}`,
                  w.trades,
                  <span className={pnlClass(w.net_return_pct)}>{fmtPct(w.net_return_pct)}</span>,
                  fmtNum(w.profit_factor),
                  `${fmtNum(w.win_rate, 1)}%`,
                  `${fmtNum(w.max_drawdown_pct, 1)}%`,
                  `${fmtNum(w.cash_time_pct, 1)}%`,
                ])}
              />
            </Sub>
          )}

          {/* Calibration comparison */}
          <Sub title="Calibration quality (balanced vs current)" testId="balanced-calibration">
            {gCal ? (
              <Tbl
                cols={["Model", "Samples", "Brier (lower=better)", "ECE", "Log loss"]}
                rows={[
                  [<span className="text-violet-300 font-bold">Balanced G</span>,
                   gCal.samples, fmtNum(gCal.brier_score, 4),
                   fmtNum(gCal.ece, 4), fmtNum(gCal.log_loss, 4)],
                  [<span className="text-zinc-300">Current model</span>,
                   cCal.samples ?? "—", fmtNum(cCal.brier_score, 4),
                   fmtNum(cCal.ece, 4), fmtNum(cCal.log_loss, 4)],
                ]}
              />
            ) : (
              <p className="text-[11px] font-mono text-muted-foreground">
                Not enough calibrated shadow decisions with outcomes yet.
              </p>
            )}
            {calCmp.note && (
              <p className="text-[10px] font-mono text-zinc-500">{calCmp.note}</p>
            )}
          </Sub>

          {/* False positives + gate failures + concentration */}
          <Sub title="Diagnostics: false positives, gate failures, concentration"
            testId="balanced-diagnostics">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat label="BUY decisions" value={String(fp.buy_decisions ?? "—")} />
              <Stat label="Evaluable (10d fwd)" value={String(fp.evaluable ?? "—")} />
              <Stat label="False positives" value={String(fp.false_positives ?? "—")} />
              <Stat label="FP rate"
                value={`${fmtNum(fp.false_positive_rate_pct, 1)}%`}
                valueClass={Number(fp.false_positive_rate_pct) > 50 ? "text-red-400" : ""} />
            </div>
            {fp.note && (
              <p className="text-[10px] font-mono text-zinc-500">{fp.note}</p>
            )}
            {Object.keys(gates).length > 0 && (
              <Tbl
                cols={["Hard gate", "Failures"]}
                rows={Object.entries(gates)
                  .sort((a, b) => Number(b[1]) - Number(a[1]))
                  .map(([k, v]) => [k, v as number])}
              />
            )}
            {(conc.flags ?? []).length > 0 ? (
              <div className="space-y-1">
                {conc.flags.map((f: string, i: number) => (
                  <div key={i} className="flex items-start gap-2 text-[11px] font-mono text-warn">
                    <ShieldAlert className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    {f}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[11px] font-mono text-muted-foreground">
                No profit-concentration flags.
              </p>
            )}
          </Sub>

          {/* Scoring configuration */}
          <Sub title="Scoring configuration (weights, caps, gates)" testId="balanced-config">
            {Object.keys(weights).length > 0 && (
              <Tbl
                cols={["Component", "Weight"]}
                rows={Object.entries(weights).map(([k, v]) => [
                  k.replace(/_/g, " "), `${v}%`,
                ])}
              />
            )}
            <pre className="text-[10px] font-mono text-zinc-500 whitespace-pre-wrap">
              {JSON.stringify(
                { adjustment_caps: config.adjustment_caps,
                  eligibility_gates: config.eligibility_gates,
                  label_thresholds: config.label_thresholds,
                  smooth_ramps: config.smooth_ramps,
                  data_quality_multiplier_range:
                    config.data_quality_multiplier_range },
                null, 2)}
            </pre>
          </Sub>

          {/* Safety audit */}
          <Sub title="Safety & lookahead audit" testId="balanced-safety-audit">
            <div className="space-y-1">
              {[
                ["Analysis only (no live changes)", audit.analysis_only === true],
                ["Live recommendations unchanged", audit.live_recommendations_changed === false],
                ["Portfolio untouched", audit.portfolio_modified === false],
                ["No paper trades created/closed", audit.paper_trades_created_or_closed === false],
                ["Thresholds/enablement unchanged", audit.thresholds_or_enablement_changed === false],
                [`Lookahead: ${audit.lookahead_violations ?? "?"} violations in ${audit.lookahead_decisions_checked ?? "?"} decisions`,
                 (audit.lookahead_violations ?? 1) === 0],
              ].map(([label, ok], i) => (
                <div key={i} className="flex items-start gap-2 text-[11px] font-mono">
                  {ok
                    ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
                    : <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />}
                  <span className={ok ? "text-foreground" : "text-red-300"}>
                    {String(label)}
                  </span>
                </div>
              ))}
              {audit.exit_logic && (
                <p className="text-[10px] font-mono text-zinc-500 mt-1">
                  Exit logic: {audit.exit_logic}
                </p>
              )}
              {(audit.window_errors ?? []).length > 0 && (
                <div className="mt-2 space-y-1">
                  {audit.window_errors.map((e: string, i: number) => (
                    <p key={i} className="text-[11px] font-mono text-red-400">{e}</p>
                  ))}
                </div>
              )}
            </div>
          </Sub>
        </CardContent>
      )}
    </Card>
  );
}
