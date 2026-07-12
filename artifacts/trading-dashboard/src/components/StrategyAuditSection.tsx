import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChevronDown, ChevronRight, Microscope } from "lucide-react";
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
        data-testid={`audit-sub-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
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

/** Rows in the shared bucket/group shape used across audit tables. */
const BUCKET_COLS = ["Trades", "Net return", "Expectancy/trade", "PF", "Win rate", "Max DD", "Avg win", "Avg loss", "Avg hold"];
const bucketCells = (b: any) => [
  b?.trades ?? "—",
  <span className={pnlClass(b?.net_return_pct)}>{fmtPct(b?.net_return_pct)}</span>,
  <span className={pnlClass(b?.expectancy_pct)}>{fmtPct(b?.expectancy_pct)}</span>,
  fmtNum(b?.profit_factor),
  `${fmtNum(b?.win_rate, 1)}%`,
  `${fmtNum(b?.max_drawdown_pct, 1)}%`,
  fmtPct(b?.avg_win_pct),
  fmtPct(b?.avg_loss_pct),
  fmtNum(b?.avg_holding_days, 1),
];

const VERDICT_CLASS: Record<string, string> = {
  USEFUL: "text-emerald-400",
  HARMFUL: "text-red-400",
  NEUTRAL: "text-zinc-300",
  INCONCLUSIVE: "text-amber-400",
  KEEP: "text-emerald-400",
  MODIFY: "text-amber-400",
  DISABLE: "text-red-400",
};

const STATUS_CLASS = (s: string) =>
  /ELIGIBLE/i.test(s) && !/NOT/i.test(s) ? "text-emerald-400"
    : /DISABLE|NEGATIVE/i.test(s) ? "text-red-400"
    : /WATCH/i.test(s) ? "text-amber-400" : "text-zinc-300";

const BREAKDOWN_LABELS: Record<string, string> = {
  by_regime: "By market regime",
  by_sector: "By sector",
  by_holding_bucket: "By holding period",
  by_entry_subtype: "By entry sub-type",
  by_exit_reason: "By exit reason",
  by_volatility_band: "By volatility band (ATR%)",
  by_trend_band: "By trend strength (ADX)",
  by_volume_band: "By volume band",
};

export default function StrategyAuditSection({ audit }: { audit: any }) {
  const scorecards: any[] = audit?.scorecards ?? [];
  const [sel, setSel] = useState<string>(scorecards[0]?.strategy_id ?? "");
  const [breakdown, setBreakdown] = useState<string>("by_regime");
  const [open, setOpen] = useState(true);

  const header = (
    <CardHeader
      className="cursor-pointer select-none py-3"
      onClick={() => setOpen(!open)}
      data-testid="section-strategy-audit-phase-2b"
    >
      <CardTitle className="text-sm font-mono flex items-center gap-2">
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <Microscope className="h-4 w-4 text-cyan-400" />
        STRATEGY AUDIT — PHASE 2B (Analysis Only)
      </CardTitle>
    </CardHeader>
  );

  if (audit?.error) {
    return (
      <Card>
        {header}
        {open && (
          <CardContent className="pt-0">
            <div className="text-xs font-mono text-red-400 whitespace-normal" data-testid="text-audit-error">
              {audit.error}
            </div>
          </CardContent>
        )}
      </Card>
    );
  }

  const sc = scorecards.find((s) => s.strategy_id === sel) ?? scorecards[0];
  const findFor = (arr: any[] | undefined) =>
    (arr ?? []).find((x: any) => x.strategy_id === (sc?.strategy_id ?? sel));
  const entry = findFor(audit.entry_conditions);
  const exits = findFor(audit.exit_comparison);
  const losses = findFor(audit.loss_attribution);
  const holding = findFor(audit.holding_comparison);
  const regimes = findFor(audit.regime_eligibility);
  const costs = findFor(audit.cost_sensitivity);
  const variants = findFor(audit.variants);
  const fr = audit.final_report ?? {};
  const m = sc?.metrics ?? {};

  return (
    <Card>
      {header}
      {open && (
        <CardContent className="pt-0 space-y-4">
          <div className="text-[10px] font-mono text-amber-400 whitespace-normal" data-testid="text-audit-safety">
            {audit.safety ?? "Analysis only — the ranking engine and live paper-trading pipeline are unchanged."}
          </div>

          {/* Strategy picker */}
          <div className="flex flex-wrap gap-1.5" data-testid="audit-strategy-picker">
            {scorecards.map((s) => (
              <button
                key={s.strategy_id}
                type="button"
                onClick={() => setSel(s.strategy_id)}
                className={cn(
                  "px-2.5 py-1 rounded text-[11px] font-mono border",
                  (sc?.strategy_id === s.strategy_id)
                    ? "bg-cyan-500/15 border-cyan-500/40 text-cyan-300"
                    : "bg-zinc-800/60 border-zinc-700 text-muted-foreground hover:text-foreground",
                )}
                data-testid={`button-audit-strategy-${s.strategy_id}`}
              >
                {s.name ?? s.strategy_id}
              </button>
            ))}
          </div>

          {sc && (
            <>
              {/* §1 Scorecard */}
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3" data-testid="audit-scorecard">
                <Stat label="Trades" value={String(m.total_trades ?? 0)} />
                <Stat label="Net return" value={fmtPct(m.total_return_pct)} valueClass={pnlClass(m.total_return_pct)} />
                <Stat label="Gross return" value={fmtPct(sc.gross_return_pct)} valueClass={pnlClass(sc.gross_return_pct)} />
                <Stat label="Expectancy/trade" value={fmtINR(m.expectancy)} valueClass={pnlClass(m.expectancy)} />
                <Stat label="Profit factor" value={fmtNum(m.profit_factor)} />
                <Stat label="Win rate" value={`${fmtNum(m.win_rate, 1)}%`} />
                <Stat label="Max drawdown" value={`${fmtNum(m.max_drawdown_pct, 1)}%`} />
                <Stat label="Sharpe" value={fmtNum(m.sharpe_ratio)} />
                <Stat label="Reward:risk (realised)" value={fmtNum(sc.reward_risk_realised)} />
                <Stat label="Median holding" value={`${sc.median_holding_days ?? "—"} d`} />
                <Stat label="Avg MAE / MFE" value={`${fmtNum(sc.avg_mae_pct, 1)}% / ${fmtNum(sc.avg_mfe_pct, 1)}%`} />
                <Stat label="Total costs" value={fmtINR(m.total_costs)} />
              </div>
              <div className="text-[10px] font-mono text-muted-foreground">
                Exit mix: stop {fmtNum(sc.stop_hit_rate, 1)}% · target {fmtNum(sc.target_hit_rate, 1)}% ·
                signal {fmtNum(sc.signal_exit_rate, 1)}% · time {fmtNum(sc.time_exit_rate, 1)}% ·
                forced {fmtNum(sc.forced_exit_rate, 1)}%
              </div>

              {/* §1 Breakdowns */}
              <Sub title="Performance breakdowns (8 views)" defaultOpen>
                <div className="flex flex-wrap gap-1.5">
                  {Object.keys(BREAKDOWN_LABELS).map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setBreakdown(k)}
                      className={cn(
                        "px-2 py-0.5 rounded text-[10px] font-mono border",
                        breakdown === k
                          ? "bg-zinc-700 border-zinc-500 text-foreground"
                          : "bg-zinc-800/60 border-zinc-700 text-muted-foreground hover:text-foreground",
                      )}
                      data-testid={`button-audit-breakdown-${k}`}
                    >
                      {BREAKDOWN_LABELS[k]}
                    </button>
                  ))}
                </div>
                <Tbl
                  cols={["Group", ...BUCKET_COLS]}
                  rows={((sc.breakdowns?.[breakdown]) ?? []).map((b: any) => [b.group, ...bucketCells(b)])}
                  testId="table-audit-breakdown"
                />
              </Sub>

              {/* §3 Entry-condition diagnostics */}
              <Sub title="Entry condition diagnostics (with vs without)">
                <Tbl
                  cols={["Condition", "With (n)", "With exp.", "Without (n)", "Without exp.", "Δ expectancy", "Δ win rate", "z", "Verdict"]}
                  rows={(entry?.conditions ?? []).map((c: any) => [
                    <span className="whitespace-normal">{c.condition}</span>,
                    c.with?.trades ?? 0,
                    <span className={pnlClass(c.with?.expectancy_pct)}>{fmtPct(c.with?.expectancy_pct)}</span>,
                    c.without?.trades ?? 0,
                    <span className={pnlClass(c.without?.expectancy_pct)}>{fmtPct(c.without?.expectancy_pct)}</span>,
                    <span className={pnlClass(c.expectancy_diff_pct)}>{fmtPct(c.expectancy_diff_pct)}</span>,
                    fmtNum(c.win_rate_diff, 1),
                    fmtNum(c.z_score, 2),
                    <span className={cn("font-bold", VERDICT_CLASS[c.verdict] ?? "")}>{c.verdict}{c.note ? ` — ${c.note}` : ""}</span>,
                  ])}
                  testId="table-audit-entry-conditions"
                />
              </Sub>

              {/* §4 Exit alternatives */}
              <Sub title="Exit rule alternatives A–G (identical entries)">
                <Tbl
                  cols={["Exit rule", ...BUCKET_COLS]}
                  rows={(exits?.alternatives ?? []).map((a: any) => [
                    <span className="whitespace-normal">{a.key} — {a.label}</span>,
                    ...bucketCells(a),
                  ])}
                  testId="table-audit-exit-alternatives"
                />
              </Sub>

              {/* §4b Loss attribution */}
              <Sub title="Loss attribution">
                <ul className="space-y-1">
                  {(losses?.findings ?? []).map((f: string, i: number) => (
                    <li key={i} className="text-xs font-mono text-muted-foreground whitespace-normal">• {f}</li>
                  ))}
                </ul>
              </Sub>

              {/* §6 Holding-period analysis */}
              <Sub title="Holding period analysis">
                <Tbl
                  cols={["Max holding", ...BUCKET_COLS]}
                  rows={(holding?.buckets ?? []).map((b: any) => [b.label, ...bucketCells(b)])}
                  testId="table-audit-holding"
                />
                {(holding?.train_selected ?? []).length > 0 && (
                  <div className="text-[10px] font-mono text-muted-foreground whitespace-normal">
                    Train-window pick: {(holding.train_selected ?? [])
                      .map((t: any) => `${t.max_holding_days}d (${t.windows_selected}×)`).join(", ")}. {holding?.note}
                  </div>
                )}
              </Sub>

              {/* §7 Regime eligibility */}
              <Sub title="Regime eligibility map">
                <Tbl
                  cols={["Regime", "Trades", "Expectancy", "Shrunk exp.", "PF", "Win rate", "Status", "Reason"]}
                  rows={(regimes?.regimes ?? []).map((g: any) => [
                    g.regime,
                    g.trades,
                    <span className={pnlClass(g.expectancy_pct)}>{fmtPct(g.expectancy_pct)}</span>,
                    <span className={pnlClass(g.shrunk_expectancy_pct)}>{fmtPct(g.shrunk_expectancy_pct)}</span>,
                    fmtNum(g.profit_factor),
                    `${fmtNum(g.win_rate, 1)}%`,
                    <span className={cn("font-bold", STATUS_CLASS(String(g.status ?? "")))}>{g.status}</span>,
                    <span className="whitespace-normal text-[10px]">{g.reason}</span>,
                  ])}
                  testId="table-audit-regimes"
                />
              </Sub>

              {/* §8 Cost sensitivity */}
              <Sub title="Cost sensitivity">
                <Tbl
                  cols={["Scenario", "Net return", "Expectancy/trade", "PF", "Win rate"]}
                  rows={(costs?.scenarios ?? []).map((s: any) => [
                    s.label,
                    <span className={pnlClass(s.net_return_pct)}>{fmtPct(s.net_return_pct)}</span>,
                    <span className={pnlClass(s.expectancy_pct)}>{fmtPct(s.expectancy_pct)}</span>,
                    fmtNum(s.profit_factor),
                    `${fmtNum(s.win_rate, 1)}%`,
                  ])}
                  testId="table-audit-costs"
                />
                {(costs?.flags ?? []).map((f: string, i: number) => (
                  <div key={i} className="text-[10px] font-mono text-amber-400 whitespace-normal">⚠ {f}</div>
                ))}
              </Sub>

              {/* §10 Variants + §9 robustness */}
              <Sub title="Entry variants (train-selected, test-evaluated)">
                <Tbl
                  cols={["Configuration", "Trades", "Net return", "Expectancy", "PF", "Win rate", "Max DD", "Δ exp. vs baseline", "Selected on train", "Robustness"]}
                  rows={[
                    [
                      <span className="whitespace-normal font-bold">baseline (current rules)</span>,
                      variants?.baseline?.trades ?? 0,
                      <span className={pnlClass(variants?.baseline?.net_return_pct)}>{fmtPct(variants?.baseline?.net_return_pct)}</span>,
                      <span className={pnlClass(variants?.baseline?.expectancy_pct)}>{fmtPct(variants?.baseline?.expectancy_pct)}</span>,
                      fmtNum(variants?.baseline?.profit_factor),
                      `${fmtNum(variants?.baseline?.win_rate, 1)}%`,
                      `${fmtNum(variants?.baseline?.max_drawdown_pct, 1)}%`,
                      "—", "—", "—",
                    ],
                    ...(variants?.variants ?? []).map((v: any) => [
                      <span className="whitespace-normal">{v.name}<br /><span className="text-[10px] text-muted-foreground">{v.description}</span></span>,
                      v.test?.trades ?? 0,
                      <span className={pnlClass(v.test?.net_return_pct)}>{fmtPct(v.test?.net_return_pct)}</span>,
                      <span className={pnlClass(v.test?.expectancy_pct)}>{fmtPct(v.test?.expectancy_pct)}</span>,
                      fmtNum(v.test?.profit_factor),
                      `${fmtNum(v.test?.win_rate, 1)}%`,
                      `${fmtNum(v.test?.max_drawdown_pct, 1)}%`,
                      <span className={pnlClass(v.vs_baseline_expectancy_diff)}>{fmtPct(v.vs_baseline_expectancy_diff)}</span>,
                      v.selected_any_window ? `yes (${v.windows_selected}×)` : "no",
                      v.robustness
                        ? <span className={v.robustness.passed ? "text-emerald-400" : "text-amber-400"}>
                            {(v.robustness.checks ?? []).filter((c: any) => c.passed).length}/{(v.robustness.checks ?? []).length} checks
                          </span>
                        : "—",
                    ]),
                  ]}
                  testId="table-audit-variants"
                />
                {(variants?.variants ?? []).map((v: any) => (
                  <div key={v.name} className="text-[10px] font-mono text-muted-foreground whitespace-normal">
                    {v.name}: {(v.robustness?.checks ?? []).map((c: any) =>
                      `${c.passed ? "✓" : "✗"} ${c.check} (${c.observed})`).join(" · ")}
                  </div>
                ))}
                <div className="text-[10px] font-mono text-muted-foreground whitespace-normal">{variants?.note}</div>
              </Sub>
            </>
          )}

          {/* §11 Model comparison A–F */}
          <Sub title="Model comparison A–F" defaultOpen>
            <Tbl
              cols={["Model", "Net return", "PF", "Expectancy", "Win rate", "Sharpe", "Max DD", "Trades", "Cash time"]}
              rows={(audit.model_comparison ?? []).map((row: any) => [
                <span className="whitespace-normal">{row.label}</span>,
                <span className={pnlClass(row.net_return_pct)}>{fmtPct(row.net_return_pct)}</span>,
                fmtNum(row.profit_factor),
                row.expectancy === null || row.expectancy === undefined ? "—" : fmtINR(row.expectancy),
                row.win_rate === null || row.win_rate === undefined ? "—" : `${fmtNum(row.win_rate, 1)}%`,
                fmtNum(row.sharpe_ratio),
                row.max_drawdown_pct === null || row.max_drawdown_pct === undefined ? "—" : `${fmtNum(row.max_drawdown_pct, 1)}%`,
                row.total_trades ?? "—",
                row.cash_time_pct === null || row.cash_time_pct === undefined ? "—" : `${fmtNum(row.cash_time_pct, 1)}%`,
              ])}
              testId="table-audit-model-comparison"
            />
            {(audit.ef_selections ?? []).length > 0 && (
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wide text-muted-foreground mb-1">
                  E/F variant selection per window (from train data only)
                </div>
                <Tbl
                  cols={["Window", "Selected configurations", "Excluded strategies"]}
                  rows={(audit.ef_selections ?? []).map((s: any) => [
                    s.window,
                    <span className="whitespace-normal text-[10px]">
                      {Object.entries(s.selected ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || "none"}
                    </span>,
                    <span className="whitespace-normal text-[10px]">{(s.excluded ?? []).join(", ") || "—"}</span>,
                  ])}
                  testId="table-audit-ef-selections"
                />
              </div>
            )}
          </Sub>

          {/* §12 Recommendations + final report */}
          <Sub title="Recommendations & final report" defaultOpen>
            <Tbl
              cols={["Strategy", "Recommendation", "Reason"]}
              rows={(audit.recommendations ?? []).map((rec: any) => [
                rec.name ?? rec.strategy_id,
                <span className={cn("font-bold", VERDICT_CLASS[rec.recommendation] ?? "")}>{rec.recommendation}</span>,
                <span className="whitespace-normal text-[10px]">{rec.reason}</span>,
              ])}
              testId="table-audit-recommendations"
            />
            <div className="space-y-2 text-xs font-mono whitespace-normal" data-testid="audit-final-report">
              {[
                ["Strategies with net-positive out-of-sample edge", fr.q1_net_positive_edge],
                ["Strategies that should be disabled or regime-restricted", fr.q2_should_disable],
                ["Entry filters that measurably helped", fr.q3_entry_filters_helped],
                ["Exit rules that measurably helped", fr.q4_exit_rules_helped],
                ["Best-performing holding periods", fr.q5_best_holding_periods],
                ["Variant configurations that passed validation", fr.q7_variants_passed],
                ["Models E/F vs existing models", fr.q8_e_f_vs_base],
              ].map(([label, items]: any) => (
                <div key={label}>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
                  {(items ?? []).length === 0
                    ? <div className="text-muted-foreground">—</div>
                    : (items ?? []).map((s: string, i: number) => <div key={i}>• {s}</div>)}
                </div>
              ))}
              {fr.q6_costs_main_cause && (
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Are costs the main cause of losses?</div>
                  <div>{fr.q6_costs_main_cause}</div>
                </div>
              )}
              {fr.q9_safe_to_deploy && (
                <div className="bg-zinc-800/60 border border-zinc-700 rounded px-3 py-2" data-testid="text-audit-deploy-verdict">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Safe to deploy with real capital later?</div>
                  <div>{fr.q9_safe_to_deploy}</div>
                  {fr.q10_reasons_if_none && <div className="text-muted-foreground mt-1">{fr.q10_reasons_if_none}</div>}
                </div>
              )}
              {fr.summary && (
                <div className="text-muted-foreground" data-testid="text-audit-summary">{fr.summary}</div>
              )}
            </div>
          </Sub>
        </CardContent>
      )}
    </Card>
  );
}
