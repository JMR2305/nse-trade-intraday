import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import {
  Microscope, RefreshCw, Download, Brain, TrendingUp, TrendingDown,
  AlertTriangle, CheckCircle2, XCircle, Eye, ShieldCheck, Dna,
  BarChart2, Activity, Zap, ChevronDown, ChevronRight, Info,
  Shield, Clock, Star, ArrowUpRight, ArrowDownRight, GitCompare,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────────

interface FactorScore { score: number; rationale: string; weight: number }
interface Contributor { factor: string; score: number; weight: number; contribution: number }
interface RelStrength { rs_vs_index: number | null; rs_vs_sector: number | null; rs_rank_label: string; sector: string | null }
interface Contradiction { level: string; explanation: string; bullish_factors: string[]; bearish_factors: string[] }
interface Sizing { feasible: boolean; suggested_quantity: number; position_value: number; max_loss: number; capital_utilization_pct: number; sizing_note: string; regime_adj: string }
interface CalibInfo { raw_score: number; calibrated_score: number; evidence: string; precision: string; note: string }
interface FusedResult {
  symbol: string; sector: string | null;
  p13_action: string; fused_score: number; calibrated_score: number;
  evidence: string; calibration: CalibInfo;
  factor_scores: Record<string, number>;
  factor_rationales: Record<string, string>;
  positive_contributors: Contributor[];
  negative_contributors: Contributor[];
  regime: string; selected_strategy: string | null; eligible_strategies: string[];
  contradiction: Contradiction; relative_strength: RelStrength;
  sizing: Sizing; is_stale: boolean; blocker: string | null;
  what_would_change: string; price: number | null;
}
interface RegimeInfo {
  regime: string; confidence: number; prev_regime: string | null;
  regime_duration_bars: number; regime_changed: boolean;
  eligible_strategies: string[]; score_multiplier: number;
  reasoning: string; all_scores: Record<string, number>;
}
interface SectorRow { sector: string; avg_score: number | null; rank: number | null; vs_median: number | null; momentum: string; stock_count: number }
interface P13Analysis {
  phase: number; generated_at: string; label: string; scan_stale: boolean; scan_age_minutes: number | null;
  regime: RegimeInfo; sector_rotation: SectorRow[];
  fused_results: FusedResult[];
  action_summary: Record<string, number>;
  evidence_summary: Record<string, number>;
  contradiction_summary: Record<string, number>;
  completed_trade_count: number;
  factor_weights: Record<string, number>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const REGIME_STYLE: Record<string, { color: string; bg: string }> = {
  TRENDING_UP:   { color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30" },
  RANGE_BOUND:   { color: "text-blue-400",    bg: "bg-blue-500/10 border-blue-500/30" },
  TRENDING_DOWN: { color: "text-orange-400",  bg: "bg-orange-500/10 border-orange-500/30" },
  VOLATILE:      { color: "text-yellow-400",  bg: "bg-yellow-500/10 border-yellow-500/30" },
  CRISIS:        { color: "text-red-400",     bg: "bg-red-500/10 border-red-500/30" },
};

const ACTION_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  STRONG_BUY: { color: "text-emerald-300", bg: "bg-emerald-500/15", border: "border-emerald-500/50" },
  BUY:        { color: "text-green-400",   bg: "bg-green-500/10",   border: "border-green-500/30" },
  WATCH:      { color: "text-yellow-400",  bg: "bg-yellow-500/10",  border: "border-yellow-500/30" },
  AVOID:      { color: "text-red-400",     bg: "bg-red-500/10",     border: "border-red-500/30" },
  EXIT:       { color: "text-orange-400",  bg: "bg-orange-500/10",  border: "border-orange-500/30" },
};

const EVIDENCE_COLOR: Record<string, string> = {
  validated: "text-emerald-400", strong: "text-green-400", moderate: "text-blue-400",
  low: "text-yellow-400", very_low: "text-orange-400", insufficient: "text-red-400",
};

const MOMENTUM_COLOR: Record<string, string> = {
  STRONG: "text-emerald-400", OUTPERFORMING: "text-green-400", NEUTRAL: "text-slate-400",
  UNDERPERFORMING: "text-orange-400", WEAK: "text-red-400",
};

const CONTRA_COLOR: Record<string, string> = {
  NONE: "text-emerald-400", LOW: "text-yellow-400", MEDIUM: "text-orange-400", HIGH: "text-red-400",
};

const FACTOR_LABELS: Record<string, string> = {
  trend: "Trend", momentum: "Momentum", volatility: "Volatility", volume: "Volume",
  relative_strength: "Relative Strength", market_regime: "Market Regime",
  sector_strength: "Sector Strength", liquidity: "Liquidity",
  hist_expectancy: "Hist. Expectancy", calibration_quality: "Calibration",
  data_freshness: "Data Freshness", historical_similarity: "Hist. Similarity",
  risk_reward: "Risk/Reward", portfolio_context: "Portfolio Context",
};

function ScoreBar({ score, max = 100 }: { score: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (score / max) * 100));
  const color = score >= 70 ? "bg-emerald-500" : score >= 50 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted/40 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-7 text-right">{score.toFixed(0)}</span>
    </div>
  );
}

function ActionBadge({ action }: { action: string }) {
  const s = ACTION_STYLE[action] ?? ACTION_STYLE.WATCH;
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-[11px] font-mono font-bold ${s.color} ${s.bg} ${s.border}`}>
      {action.replace("_", " ")}
    </span>
  );
}

function EvidenceBadge({ ev }: { ev: string }) {
  return (
    <span className={`text-[11px] font-mono uppercase tracking-wider ${EVIDENCE_COLOR[ev] ?? "text-muted-foreground"}`}>
      [{ev.replace("_", " ")}]
    </span>
  );
}

function SummaryCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">{label}</div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground mt-1 font-mono">{sub}</div>}
      </CardContent>
    </Card>
  );
}

// ── Symbol Card ───────────────────────────────────────────────────────────────

function SymbolCard({ r }: { r: FusedResult }) {
  const [open, setOpen] = useState(false);
  const factors = Object.entries(r.factor_scores || {});
  const rs = r.relative_strength;
  const sz = r.sizing;
  const cal = r.calibration;
  const con = r.contradiction;

  return (
    <Card className={`border ${r.is_stale ? "border-zinc-700 opacity-70" : "border-border/50"} bg-card/40 backdrop-blur`}>
      <CardContent className="p-0">
        {/* Header row */}
        <div
          className="flex items-center gap-3 p-3 cursor-pointer hover:bg-muted/20 transition-colors"
          onClick={() => setOpen(!open)}
        >
          {open ? <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0" /> : <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono font-bold text-sm">{r.symbol}</span>
              {r.sector && <span className="text-[10px] text-muted-foreground font-mono">{r.sector}</span>}
              <ActionBadge action={r.p13_action} />
              <EvidenceBadge ev={r.evidence} />
              {r.is_stale && <span className="text-[10px] text-orange-400 font-mono">[STALE]</span>}
            </div>
          </div>
          {/* Score ring */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <div className="text-right">
              <div className="text-lg font-bold font-mono text-foreground">{r.calibrated_score.toFixed(0)}</div>
              <div className="text-[10px] text-muted-foreground font-mono">P13 score</div>
            </div>
            {r.price != null && (
              <div className="text-right">
                <div className="text-sm font-mono text-foreground">₹{r.price.toLocaleString("en-IN")}</div>
                <div className="text-[10px] text-muted-foreground font-mono">price</div>
              </div>
            )}
            <div className={`text-[10px] font-mono ${CONTRA_COLOR[con?.level ?? "NONE"]}`}>
              {con?.level ?? ""}
            </div>
          </div>
        </div>

        {/* Top-3 factor bars (always visible) */}
        <div className="px-4 pb-2 grid grid-cols-3 gap-2">
          {r.positive_contributors.slice(0, 3).map(c => (
            <div key={c.factor} className="text-[10px]">
              <div className="text-muted-foreground font-mono mb-0.5">{FACTOR_LABELS[c.factor] ?? c.factor}</div>
              <ScoreBar score={c.score} />
            </div>
          ))}
        </div>

        {/* Expanded detail */}
        {open && (
          <div className="border-t border-border/30 px-4 py-3 space-y-4">

            {/* Calibration */}
            {cal && (
              <div className="rounded bg-muted/20 p-2 text-[11px] font-mono text-muted-foreground">
                <span className="text-foreground font-semibold">Calibration</span>{" "}
                raw={cal.raw_score} → calibrated={cal.calibrated_score} {cal.precision} · {cal.note}
              </div>
            )}

            {/* Blocker */}
            {r.blocker && (
              <div className="flex items-center gap-2 text-orange-400 text-[11px] font-mono bg-orange-500/10 border border-orange-500/30 rounded px-2 py-1">
                <AlertTriangle className="h-3 w-3 flex-shrink-0" />
                {r.blocker}
              </div>
            )}

            {/* All 14 factors */}
            <div>
              <div className="text-xs font-mono text-muted-foreground uppercase tracking-wider mb-2">All 14 Factors</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                {factors.map(([f, s]) => (
                  <div key={f}>
                    <div className="flex justify-between items-center mb-0.5">
                      <span className="text-[10px] font-mono text-muted-foreground">{FACTOR_LABELS[f] ?? f}</span>
                      <span className="text-[10px] font-mono text-muted-foreground">×{((r as any).factor_weights?.[f] ?? 0.07).toFixed(2)}</span>
                    </div>
                    <div title={r.factor_rationales?.[f] ?? ""}><ScoreBar score={s} /></div>
                  </div>
                ))}
              </div>
            </div>

            {/* Contributors */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[10px] font-mono text-emerald-400 uppercase tracking-wider mb-1">Positive contributors</div>
                {r.positive_contributors.length === 0 ? <div className="text-[10px] text-muted-foreground">—</div> : r.positive_contributors.map(c => (
                  <div key={c.factor} className="flex items-center gap-1 text-[10px] font-mono text-emerald-300 mb-0.5">
                    <ArrowUpRight className="h-3 w-3" />{FACTOR_LABELS[c.factor] ?? c.factor} {c.score.toFixed(0)} (+{c.contribution.toFixed(2)})
                  </div>
                ))}
              </div>
              <div>
                <div className="text-[10px] font-mono text-red-400 uppercase tracking-wider mb-1">Negative contributors</div>
                {r.negative_contributors.length === 0 ? <div className="text-[10px] text-muted-foreground">—</div> : r.negative_contributors.map(c => (
                  <div key={c.factor} className="flex items-center gap-1 text-[10px] font-mono text-red-300 mb-0.5">
                    <ArrowDownRight className="h-3 w-3" />{FACTOR_LABELS[c.factor] ?? c.factor} {c.score.toFixed(0)} ({c.contribution.toFixed(2)})
                  </div>
                ))}
              </div>
            </div>

            {/* Relative strength */}
            {rs && (
              <div className="rounded bg-muted/10 border border-border/30 p-2 text-[11px] font-mono">
                <span className="text-foreground font-semibold">Relative Strength</span>{" "}
                <span>vs NIFTY: </span>
                {rs.rs_vs_index != null ? (
                  <span className={rs.rs_vs_index >= 0 ? "text-emerald-400" : "text-red-400"}>{rs.rs_vs_index > 0 ? "+" : ""}{rs.rs_vs_index.toFixed(1)}%</span>
                ) : <span className="text-muted-foreground">N/A</span>}
                {rs.rs_vs_sector != null && (
                  <span> · vs Sector: <span className={rs.rs_vs_sector >= 0 ? "text-emerald-400" : "text-red-400"}>{rs.rs_vs_sector > 0 ? "+" : ""}{rs.rs_vs_sector.toFixed(1)}%</span></span>
                )}
                {" "}<span className="text-blue-300">[{rs.rs_rank_label}]</span>
              </div>
            )}

            {/* Strategy + Regime */}
            <div className="flex flex-wrap gap-2 text-[11px] font-mono">
              <div className="rounded bg-muted/20 border border-border/30 px-2 py-1">
                <span className="text-muted-foreground">Regime: </span>
                <span className={(REGIME_STYLE[r.regime] ?? REGIME_STYLE.RANGE_BOUND).color}>{r.regime}</span>
              </div>
              {r.selected_strategy && (
                <div className="rounded bg-muted/20 border border-border/30 px-2 py-1">
                  <span className="text-muted-foreground">Strategy: </span>
                  <span className="text-blue-300">{r.selected_strategy}</span>
                </div>
              )}
              {r.eligible_strategies.length > 0 && (
                <div className="rounded bg-muted/20 border border-border/30 px-2 py-1">
                  <span className="text-muted-foreground">Eligible: </span>
                  <span>{r.eligible_strategies.join(", ")}</span>
                </div>
              )}
            </div>

            {/* Contradiction */}
            {con?.level && con.level !== "NONE" && (
              <div className={`rounded border px-2 py-1.5 text-[11px] font-mono ${CONTRA_COLOR[con.level]} bg-current/5 border-current/20`}>
                <div className="font-semibold mb-0.5">{con.level} CONTRADICTION</div>
                <div className="text-muted-foreground">{con.explanation}</div>
              </div>
            )}

            {/* Sizing */}
            {sz && (
              <div className="rounded bg-muted/10 border border-border/30 p-2 text-[11px] font-mono">
                <div className="text-foreground font-semibold mb-1">Suggested Paper Allocation</div>
                {sz.feasible ? (
                  <div className="flex flex-wrap gap-3 text-muted-foreground">
                    <span>Qty: <span className="text-foreground">{sz.suggested_quantity}</span></span>
                    <span>Value: <span className="text-foreground">₹{sz.position_value?.toLocaleString("en-IN")}</span></span>
                    <span>Max loss: <span className="text-red-400">₹{sz.max_loss?.toFixed(0)}</span></span>
                    <span>Cap: <span className="text-foreground">{sz.capital_utilization_pct?.toFixed(1)}%</span></span>
                    <span className="text-orange-300">[{sz.regime_adj}]</span>
                  </div>
                ) : (
                  <div className="text-orange-400">{sz.sizing_note}</div>
                )}
              </div>
            )}

            {/* What would change */}
            <div className="text-[11px] font-mono text-muted-foreground italic">
              <span className="text-foreground not-italic font-semibold">What would change: </span>
              {r.what_would_change}
            </div>

            {/* Research label */}
            <div className="text-[10px] font-mono text-zinc-600 uppercase tracking-wider">
              PAPER / RESEARCH ONLY — Phase 13
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Sector Rotation Table ─────────────────────────────────────────────────────

function SectorTable({ rows }: { rows: SectorRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="border-b border-border/40">
            <th className="text-left py-1.5 px-2 text-muted-foreground">Sector</th>
            <th className="text-right py-1.5 px-2 text-muted-foreground">Rank</th>
            <th className="text-right py-1.5 px-2 text-muted-foreground">Avg Score</th>
            <th className="text-right py-1.5 px-2 text-muted-foreground">vs Median</th>
            <th className="text-right py-1.5 px-2 text-muted-foreground">Momentum</th>
            <th className="text-right py-1.5 px-2 text-muted-foreground">Stocks</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.sector} className={`border-b border-border/20 ${i < 3 ? "bg-emerald-500/5" : ""}`}>
              <td className="py-1.5 px-2 font-semibold">{row.sector}</td>
              <td className="py-1.5 px-2 text-right text-muted-foreground">{row.rank ?? "—"}</td>
              <td className="py-1.5 px-2 text-right">{row.avg_score?.toFixed(1) ?? "—"}</td>
              <td className={`py-1.5 px-2 text-right ${(row.vs_median ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {row.vs_median != null ? `${row.vs_median > 0 ? "+" : ""}${row.vs_median.toFixed(1)}` : "—"}
              </td>
              <td className={`py-1.5 px-2 text-right ${MOMENTUM_COLOR[row.momentum] ?? "text-muted-foreground"}`}>
                {row.momentum}
              </td>
              <td className="py-1.5 px-2 text-right text-muted-foreground">{row.stock_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Evolution Panel ────────────────────────────────────────────────────────────

interface Proposal { proposal_id: string; strategy_id: string; status: string; oos_trade_count: number; evidence: string; stats_snapshot: any; mutation: { mutation: string; description: string; expected_effect: string; basis: string } }

function EvolutionPanel() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["/api/phase13/evolution"],
    queryFn: () => apiJson<{ proposals: Proposal[]; pending: number }>("/phase13/evolution?status=PENDING_APPROVAL"),
    staleTime: 30_000,
  });

  const generate = useMutation({
    mutationFn: () => apiJson("/phase13/evolution/generate", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase13/evolution"] }),
  });

  const review = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      apiJson(`/phase13/evolution/review/${id}`, { method: "POST", body: JSON.stringify({ action }), headers: { "Content-Type": "application/json" } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/phase13/evolution"] }),
  });

  const proposals = data?.proposals ?? [];

  return (
    <Card className="border-border/50 bg-card/40 backdrop-blur">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-mono flex items-center gap-2">
            <Dna className="h-4 w-4 text-purple-400" /> Strategy Evolution Proposals
          </CardTitle>
          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="text-[11px] font-mono px-3 py-1 rounded border border-purple-500/40 text-purple-300 hover:bg-purple-500/10 transition-colors disabled:opacity-50"
          >
            {generate.isPending ? "Generating…" : "Generate Proposals"}
          </button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="text-[10px] font-mono text-orange-400 bg-orange-500/10 border border-orange-500/30 rounded px-2 py-1 mb-3">
          All proposals require explicit human approval. No auto-promotion. PAPER / RESEARCH ONLY.
        </div>
        {proposals.length === 0 ? (
          <div className="text-[11px] text-muted-foreground font-mono py-2">
            No pending proposals. Click "Generate Proposals" to analyse completed OOS paper trades (min 20 required per strategy).
          </div>
        ) : (
          <div className="space-y-3">
            {proposals.map(p => (
              <div key={p.proposal_id} className="border border-border/40 rounded p-3 text-[11px] font-mono space-y-1">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div>
                    <span className="text-foreground font-semibold">{p.strategy_id}</span>
                    {" · "}<span className="text-purple-300">{p.mutation?.mutation}</span>
                    {" · "}<span className={EVIDENCE_COLOR[p.evidence] ?? "text-muted-foreground"}>[{p.evidence?.replace("_", " ")}]</span>
                    {" "}<span className="text-muted-foreground">({p.oos_trade_count} OOS trades)</span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => review.mutate({ id: p.proposal_id, action: "APPROVE" })}
                      disabled={review.isPending}
                      className="px-2 py-0.5 rounded border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
                    >Approve</button>
                    <button
                      onClick={() => review.mutate({ id: p.proposal_id, action: "REJECT" })}
                      disabled={review.isPending}
                      className="px-2 py-0.5 rounded border border-red-500/40 text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                    >Reject</button>
                  </div>
                </div>
                <div className="text-muted-foreground">{p.mutation?.description}</div>
                <div className="text-blue-300">Expected: {p.mutation?.expected_effect}</div>
                <div className="text-zinc-500">{p.mutation?.basis}</div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Audit Panel ───────────────────────────────────────────────────────────────

function AuditPanel() {
  const { data, refetch, isFetching } = useQuery({
    queryKey: ["/api/phase13/audit"],
    queryFn: () => apiJson<any>("/phase13/audit"),
    staleTime: 60_000,
    enabled: false,
  });

  const report = (data as any)?.report;

  return (
    <Card className="border-border/50 bg-card/40 backdrop-blur">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-mono flex items-center gap-2">
            <GitCompare className="h-4 w-4 text-blue-400" /> Phase 13 vs Phase 12 Audit
          </CardTitle>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="text-[11px] font-mono px-3 py-1 rounded border border-blue-500/40 text-blue-300 hover:bg-blue-500/10 transition-colors disabled:opacity-50"
          >
            {isFetching ? "Running…" : "Run Audit"}
          </button>
        </div>
      </CardHeader>
      <CardContent className="text-[11px] font-mono space-y-3">
        {!report ? (
          <div className="text-muted-foreground py-2">Click "Run Audit" to compare Phase 13 vs Phase 12 on OOS completed paper trades.</div>
        ) : (
          <>
            <div className="text-blue-300">{report.interpretation}</div>
            <div className="overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="border-b border-border/40">
                    <th className="text-left py-1 px-1 text-muted-foreground">Metric</th>
                    <th className="text-right py-1 px-1 text-emerald-400">Phase 13</th>
                    <th className="text-right py-1 px-1 text-blue-400">Phase 12</th>
                    <th className="text-right py-1 px-1 text-muted-foreground">Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["Win Rate", "win_rate", (v: any) => `${(v * 100).toFixed(1)}%`],
                    ["Expectancy After Costs", "expectancy_after_costs", (v: any) => `₹${v.toFixed(0)}`],
                    ["Profit Factor", "profit_factor", (v: any) => v.toFixed(2)],
                    ["Max Drawdown", "max_drawdown_pct", (v: any) => `${v.toFixed(1)}%`],
                    ["Sharpe (approx)", "sharpe_approx", (v: any) => v.toFixed(2)],
                  ].map(([label, key, fmt]) => {
                    const v13 = report.phase13?.[key as string];
                    const v12 = report.phase12?.[key as string];
                    const delta = report.delta?.[key as string];
                    return (
                      <tr key={key as string} className="border-b border-border/20">
                        <td className="py-1 px-1 text-muted-foreground">{label as string}</td>
                        <td className="py-1 px-1 text-right">{v13 != null ? (fmt as any)(v13) : "—"}</td>
                        <td className="py-1 px-1 text-right">{v12 != null ? (fmt as any)(v12) : "—"}</td>
                        <td className={`py-1 px-1 text-right ${delta?.direction === "better" ? "text-emerald-400" : delta?.direction === "worse" ? "text-red-400" : "text-muted-foreground"}`}>
                          {delta?.delta != null ? `${delta.delta > 0 ? "+" : ""}${delta.delta.toFixed(3)}` : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {report.caveats && (
              <div className="text-zinc-500 space-y-0.5">
                {report.caveats.map((c: string, i: number) => <div key={i}>• {c}</div>)}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const FILTERS = ["All", "STRONG_BUY", "BUY", "WATCH", "AVOID"];
const EV_FILTERS = ["All", "validated", "strong", "moderate", "low", "very_low", "insufficient"];

export default function Phase13Intelligence() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"signals" | "sectors" | "evolution" | "audit">("signals");
  const [actionFilter, setActionFilter] = useState("All");
  const [evFilter, setEvFilter] = useState("All");
  const [expanded, setExpanded] = useState(false);

  const { data, isLoading, error, dataUpdatedAt } = useQuery({
    queryKey: ["/api/phase13/analysis"],
    queryFn: () => apiJson<P13Analysis>("/phase13/analysis"),
    staleTime: 30_000,
    refetchInterval: 120_000,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["/api/phase13/analysis"] });
    apiJson("/phase13/analysis?force=true").catch(() => {});
  };

  const generateBundle = async () => {
    window.open(`${import.meta.env.BASE_URL}api/phase13/bundle/download?file=json`.replace("//", "/"), "_blank");
  };

  const downloadCsv = async () => {
    window.open(`${import.meta.env.BASE_URL}api/phase13/bundle/download?file=csv`.replace("//", "/"), "_blank");
  };

  const regime = data?.regime;
  const regimeStyle = REGIME_STYLE[regime?.regime ?? ""] ?? REGIME_STYLE.RANGE_BOUND;

  const results = data?.fused_results ?? [];
  const filtered = results.filter(r => {
    if (actionFilter !== "All" && r.p13_action !== actionFilter) return false;
    if (evFilter !== "All" && r.evidence !== evFilter) return false;
    return true;
  });

  const sum = data?.action_summary ?? {};
  const evSum = data?.evidence_summary ?? {};

  return (
    <div className="p-4 max-w-7xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Microscope className="h-5 w-5 text-purple-400" />
          <div>
            <h1 className="text-base font-mono font-bold tracking-tight">Phase 13 Intelligence</h1>
            <div className="text-[10px] font-mono text-muted-foreground">
              Institutional AI · 14-Factor Fusion · Strategy Evolution · PAPER / RESEARCH ONLY
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {data?.generated_at && (
            <span className="text-[10px] font-mono text-muted-foreground">
              <Clock className="inline h-3 w-3 mr-1" />
              {new Date(data.generated_at).toLocaleTimeString("en-IN")}
            </span>
          )}
          <button onClick={refresh} disabled={isLoading} className="p-1.5 rounded border border-border/50 hover:border-primary/50 transition-colors disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
          </button>
          <button onClick={generateBundle} className="flex items-center gap-1.5 text-[11px] font-mono px-3 py-1.5 rounded border border-border/50 hover:border-primary/50 transition-colors">
            <Download className="h-3 w-3" /> JSON
          </button>
          <button onClick={downloadCsv} className="flex items-center gap-1.5 text-[11px] font-mono px-3 py-1.5 rounded border border-border/50 hover:border-primary/50 transition-colors">
            <Download className="h-3 w-3" /> CSV
          </button>
        </div>
      </div>

      <DataFreshnessBar variant="scan" />

      {/* Stale warning */}
      {data?.scan_stale && (
        <div className="flex items-center gap-2 text-orange-400 text-[11px] font-mono bg-orange-500/10 border border-orange-500/30 rounded px-3 py-2">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          Scan data stale ({data.scan_age_minutes?.toFixed(0)} min old). Rankings and BUY signals suppressed until fresh scan.
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 text-red-400 text-[11px] font-mono bg-red-500/10 border border-red-500/30 rounded px-3 py-2">
          <XCircle className="h-4 w-4" /> {String(error)}
        </div>
      )}

      {/* Regime banner */}
      {regime && (
        <div className={`rounded border px-4 py-3 ${regimeStyle.bg} ${regimeStyle.color} border-current/20`}>
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <Activity className="h-4 w-4" />
              <div>
                <div className="text-sm font-mono font-bold">{regime.regime.replace("_", " ")}</div>
                <div className="text-[10px] text-muted-foreground font-mono">{regime.reasoning}</div>
              </div>
              {regime.regime_changed && (
                <span className="text-[10px] font-mono bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 rounded px-1.5 py-0.5">
                  REGIME CHANGE ↗ from {regime.prev_regime?.replace("_", " ")}
                </span>
              )}
            </div>
            <div className="flex items-center gap-4 text-[11px] font-mono">
              <div><span className="text-muted-foreground">conf: </span>{regime.confidence.toFixed(0)}</div>
              <div><span className="text-muted-foreground">bars: </span>{regime.regime_duration_bars}</div>
              <div><span className="text-muted-foreground">mult: </span>{regime.score_multiplier}×</div>
              <div><span className="text-muted-foreground">strategies: </span>{regime.eligible_strategies.join(", ") || "none"}</div>
            </div>
          </div>
        </div>
      )}

      {/* Summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <SummaryCard label="Strong Buy" value={sum.STRONG_BUY ?? 0} color="text-emerald-400" />
        <SummaryCard label="Buy" value={sum.BUY ?? 0} color="text-green-400" />
        <SummaryCard label="Watch" value={sum.WATCH ?? 0} color="text-yellow-400" />
        <SummaryCard label="Avoid" value={sum.AVOID ?? 0} color="text-red-400" />
        <SummaryCard label="Symbols" value={results.length} sub={data?.completed_trade_count ? `${data.completed_trade_count} OOS trades` : undefined} />
        <SummaryCard
          label="Evidence"
          value={Object.keys(evSum).length > 0 ? `${(evSum.validated ?? 0) + (evSum.strong ?? 0) + (evSum.moderate ?? 0)} solid` : "—"}
          color="text-blue-400"
        />
      </div>

      {/* Tab strip */}
      <div className="flex gap-1 border-b border-border/40 pb-0.5">
        {([["signals", Brain, "Signals"], ["sectors", BarChart2, "Sectors"], ["evolution", Dna, "Evolution"], ["audit", GitCompare, "Audit"]] as const).map(([id, Icon, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono rounded-t transition-colors ${tab === id ? "bg-card border border-border/50 border-b-card -mb-px text-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <Icon className="h-3.5 w-3.5" />{label}
          </button>
        ))}
      </div>

      {/* Signals tab */}
      {tab === "signals" && (
        <div className="space-y-3">
          {/* Filters */}
          <div className="flex flex-wrap gap-2 items-center">
            <div className="flex gap-1">
              {FILTERS.map(f => (
                <button key={f} onClick={() => setActionFilter(f)}
                  className={`text-[11px] font-mono px-2 py-0.5 rounded border transition-colors ${actionFilter === f ? "border-primary text-primary bg-primary/10" : "border-border/40 text-muted-foreground hover:text-foreground"}`}>
                  {f}
                </button>
              ))}
            </div>
            <div className="flex gap-1 ml-2">
              {EV_FILTERS.map(f => (
                <button key={f} onClick={() => setEvFilter(f)}
                  className={`text-[10px] font-mono px-2 py-0.5 rounded border transition-colors ${evFilter === f ? "border-blue-500 text-blue-400 bg-blue-500/10" : "border-border/30 text-muted-foreground hover:text-foreground"}`}>
                  {f.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          {isLoading ? (
            <div className="text-[11px] text-muted-foreground font-mono py-6 text-center animate-pulse">Loading Phase 13 analysis…</div>
          ) : filtered.length === 0 ? (
            <div className="text-[11px] text-muted-foreground font-mono py-6 text-center">
              No symbols match filters. {data ? `${results.length} total symbols analysed.` : "No data yet."}
            </div>
          ) : (
            <div className="space-y-2">
              {filtered.map(r => <SymbolCard key={r.symbol} r={r} />)}
            </div>
          )}

          {/* Factor weights legend */}
          <Card className="border-border/30 bg-card/30">
            <CardContent className="p-3">
              <div className="text-[10px] font-mono text-muted-foreground uppercase tracking-wider mb-2">14-Factor Weight Map</div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-1.5">
                {Object.entries(data?.factor_weights ?? {}).map(([f, w]) => (
                  <div key={f} className="text-[10px] font-mono">
                    <div className="text-muted-foreground">{FACTOR_LABELS[f] ?? f}</div>
                    <div className="font-bold text-foreground">{(w * 100).toFixed(0)}%</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Sectors tab */}
      {tab === "sectors" && (
        <Card className="border-border/50 bg-card/40 backdrop-blur">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-mono flex items-center gap-2">
              <BarChart2 className="h-4 w-4 text-blue-400" /> Sector Rotation Rankings
            </CardTitle>
          </CardHeader>
          <CardContent>
            {!data?.sector_rotation?.length ? (
              <div className="text-[11px] text-muted-foreground font-mono py-2">Run scan first to populate sector rotation.</div>
            ) : (
              <SectorTable rows={data.sector_rotation} />
            )}
          </CardContent>
        </Card>
      )}

      {/* Evolution tab */}
      {tab === "evolution" && <EvolutionPanel />}

      {/* Audit tab */}
      {tab === "audit" && <AuditPanel />}
    </div>
  );
}
