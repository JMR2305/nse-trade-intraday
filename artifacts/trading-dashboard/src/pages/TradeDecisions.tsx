import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { EntryEvaluationPanel } from "@/components/Phase20Lifecycle";
import {
  useGetTradeDecisions,
  getGetTradeDecisionsQueryKey,
} from "@workspace/api-client-react";
import type { TradeDecision } from "@workspace/api-client-react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Target,
  RefreshCcw,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Info,
} from "lucide-react";

const REC_STYLE: Record<string, string> = {
  STRONG_BUY: "text-emerald-300 bg-emerald-500/15 border-emerald-500/40",
  BUY:        "text-green-400 bg-green-500/10 border-green-500/30",
  EXIT:       "text-orange-400 bg-orange-500/10 border-orange-500/30",
  WATCH:      "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  AVOID:      "text-red-400 bg-red-500/10 border-red-500/30",
};

const REC_LABEL: Record<string, string> = {
  STRONG_BUY: "STRONG BUY",
  BUY:        "BUY",
  EXIT:       "EXIT",
  WATCH:      "WATCH",
  AVOID:      "AVOID",
};

// ── Phase 13 regime strip ──────────────────────────────────────────────────────

const P13_REGIME_STYLE: Record<string, string> = {
  TRENDING_UP:   "text-emerald-400 border-emerald-500/30 bg-emerald-500/8",
  RANGE_BOUND:   "text-blue-400 border-blue-500/30 bg-blue-500/8",
  TRENDING_DOWN: "text-orange-400 border-orange-500/30 bg-orange-500/8",
  VOLATILE:      "text-yellow-400 border-yellow-500/30 bg-yellow-500/8",
  CRISIS:        "text-red-400 border-red-500/30 bg-red-500/8",
};

function Phase13RegimeStrip() {
  const { data } = useQuery({
    queryKey: ["/api/phase13/regime"],
    queryFn: () => apiJson<any>("/phase13/regime"),
    staleTime: 120_000,
  });
  if (!data?.regime) return null;
  const style = P13_REGIME_STYLE[data.regime] ?? P13_REGIME_STYLE.RANGE_BOUND;
  const strats = data.eligible_strategies?.join(", ") || "none";
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded border px-3 py-2 text-[11px] font-mono ${style}`}>
      <span className="font-bold">P13 Regime: {data.regime.replace("_", " ")}</span>
      <span className="text-muted-foreground">confidence={data.confidence?.toFixed(0)}</span>
      <span className="text-muted-foreground">bars in regime: {data.regime_duration_bars}</span>
      <span>Score mult: {data.score_multiplier}×</span>
      <span>Eligible strategies: <span className="text-foreground">{strats}</span></span>
      {data.regime_changed && <span className="text-yellow-400 font-semibold">⚡ Regime change from {data.prev_regime}</span>}
      <a href="/phase13" className="ml-auto underline text-muted-foreground hover:text-foreground">Phase 13 Intel →</a>
    </div>
  );
}

const FILTERS = ["All", "STRONG_BUY", "BUY", "EXIT", "WATCH", "AVOID"];

function RecBadge({ rec }: { rec: string }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-[11px] font-mono font-bold whitespace-nowrap ${
        REC_STYLE[rec] ?? REC_STYLE.WATCH
      }`}
      data-testid={`badge-recommendation-${rec.toLowerCase()}`}
    >
      {REC_LABEL[rec] ?? rec}
    </span>
  );
}

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">
          {label}
        </div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

function fmt(n: number | undefined, digits = 2): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits);
}

function rupee(n: number | undefined): string {
  const v = Number(n ?? 0);
  return v > 0 ? `₹${v.toFixed(2)}` : "—";
}

function BreakdownPanel({ d }: { d: TradeDecision }) {
  const rows = d.breakdown ?? [];
  const maxContribution = Math.max(1, ...rows.map((b) => b.contribution));
  return (
    <div>
      <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
        Decision Breakdown
        <span className="ml-1 normal-case tracking-normal text-[9px] text-muted-foreground/70">
          (estimated contribution)
        </span>
      </div>
      <div className="space-y-1.5 font-mono text-xs">
        {rows.map((b) => (
          <div key={b.factor} className="flex items-center gap-2">
            <span className="w-40 flex-shrink-0 text-muted-foreground">{b.factor}</span>
            <div className="flex-1 h-1.5 rounded bg-border/40 overflow-hidden">
              <div
                className="h-full rounded bg-primary/70"
                style={{ width: `${Math.max(0, (b.contribution / maxContribution) * 100)}%` }}
              />
            </div>
            <span className="w-12 text-right font-bold">
              {b.contribution >= 0 ? "+" : ""}
              {b.contribution.toFixed(0)}
            </span>
          </div>
        ))}
        <div className="border-t border-border/50 mt-2 pt-2 flex items-center justify-between">
          <span className="text-muted-foreground">Final Confidence</span>
          <span className="font-bold text-sm">{d.final_confidence.toFixed(0)}%</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Recommendation</span>
          <RecBadge rec={d.recommendation} />
        </div>
      </div>
    </div>
  );
}

const RELIABILITY_STYLE: Record<string, string> = {
  HIGH:     "text-emerald-300 bg-emerald-500/15 border-emerald-500/40",
  MEDIUM:   "text-sky-300 bg-sky-500/10 border-sky-500/30",
  LOW:      "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  VERY_LOW: "text-red-400 bg-red-500/10 border-red-500/30",
};

function SimilarityEvidencePanel({ d }: { d: TradeDecision }) {
  const ev = d.similarity_evidence;
  const reliability = d.evidence_reliability ?? "VERY_LOW";
  const adj = d.similarity_adjustment ?? 0;
  const stats = ev?.stats;
  const matches = ev?.top_matches ?? [];
  return (
    <div className="mt-4 border-t border-border/50 pt-4" data-testid="panel-similarity-evidence">
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <span className="text-xs font-mono uppercase text-muted-foreground">
          2. Historical Similarity Evidence
        </span>
        <span
          className={`inline-block rounded border px-2 py-0.5 text-[10px] font-mono font-bold ${
            RELIABILITY_STYLE[reliability] ?? RELIABILITY_STYLE.VERY_LOW
          }`}
          data-testid="badge-evidence-reliability"
        >
          {reliability.replace("_", " ")} RELIABILITY
        </span>
        <span
          className={`text-xs font-mono font-bold ${adj > 0 ? "text-green-400" : adj < 0 ? "text-red-400" : "text-muted-foreground"}`}
          data-testid="text-similarity-adjustment"
        >
          {adj > 0 ? "+" : ""}{fmt(adj, 1)} confidence
        </span>
      </div>
      {!ev || ev.match_count === 0 ? (
        <p className="text-xs text-muted-foreground font-mono">
          No sufficiently similar historical setups found (need ≥65% similarity).
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-2 mb-3 font-mono text-xs">
            <div><div className="text-muted-foreground">Matches</div><div className="font-bold">{ev.match_count}</div></div>
            <div><div className="text-muted-foreground">Avg similarity</div><div className="font-bold">{fmt(ev.avg_similarity, 0)}%</div></div>
            <div><div className="text-muted-foreground">Win rate</div><div className="font-bold">{fmt(stats?.win_rate, 0)}%</div></div>
            <div><div className="text-muted-foreground">Expectancy</div><div className={`font-bold ${(stats?.expectancy ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>{(stats?.expectancy ?? 0) >= 0 ? "+" : ""}{fmt(stats?.expectancy)}%</div></div>
            <div><div className="text-muted-foreground">Profit factor</div><div className="font-bold">{fmt(stats?.profit_factor)}</div></div>
            <div><div className="text-muted-foreground">Avg return</div><div className={`font-bold ${(stats?.avg_return ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>{(stats?.avg_return ?? 0) >= 0 ? "+" : ""}{fmt(stats?.avg_return)}%</div></div>
            <div><div className="text-muted-foreground">Exp. drawdown</div><div className="font-bold text-red-400">{fmt(stats?.historical_drawdown)}%</div></div>
            <div><div className="text-muted-foreground">Avg holding</div><div className="font-bold">{fmt(stats?.avg_holding_days, 0)}d</div></div>
          </div>
          {matches.length > 0 && (
            <div className="overflow-x-auto mb-2">
              <table className="w-full text-[11px] font-mono">
                <thead>
                  <tr className="text-muted-foreground text-left">
                    <th className="pr-3 py-1 font-normal">Similar past setup</th>
                    <th className="pr-3 py-1 font-normal">Date</th>
                    <th className="pr-3 py-1 font-normal">Strategy</th>
                    <th className="pr-3 py-1 font-normal">Sector</th>
                    <th className="pr-3 py-1 font-normal">Regime</th>
                    <th className="pr-3 py-1 font-normal text-right">Similarity</th>
                    <th className="pr-3 py-1 font-normal text-right">Return</th>
                    <th className="pr-3 py-1 font-normal text-right">Held</th>
                    <th className="py-1 font-normal">Exit</th>
                  </tr>
                </thead>
                <tbody>
                  {matches.map((m, i) => (
                    <tr key={i} className="border-t border-border/30" data-testid={`row-similar-match-${i}`}>
                      <td className="pr-3 py-1 font-bold">
                        {m.symbol}
                        {m.partial_match && (
                          <span className="ml-1 text-[9px] text-yellow-400/80">(partial)</span>
                        )}
                      </td>
                      <td className="pr-3 py-1">{m.entry_date}</td>
                      <td className="pr-3 py-1">{m.strategy}</td>
                      <td className="pr-3 py-1">{m.sector}</td>
                      <td className="pr-3 py-1">{m.regime}</td>
                      <td className="pr-3 py-1 text-right">{fmt(m.similarity, 0)}%</td>
                      <td className={`pr-3 py-1 text-right ${m.return_percent >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {m.return_percent >= 0 ? "+" : ""}{fmt(m.return_percent)}%
                      </td>
                      <td className="pr-3 py-1 text-right">{m.holding_days}d</td>
                      <td className="py-1">{m.exit_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {ev.reliability_reasons.length > 0 && (
            <ul className="list-disc list-inside text-[11px] text-muted-foreground space-y-0.5 mb-2">
              {ev.reliability_reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          <p className="text-xs text-foreground/80">{ev.explanation}</p>
          {ev.root_cause && (ev.root_cause.winners > 0 || ev.root_cause.losers > 0) && (
            <div className="mt-3 rounded border border-border/50 bg-muted/20 p-3" data-testid="panel-root-cause">
              <div className="text-xs font-mono uppercase text-muted-foreground mb-1">
                Root Cause Analysis
              </div>
              <p className="text-xs text-foreground/90 leading-relaxed mb-2" data-testid="text-root-cause-narrative">
                {ev.root_cause.narrative}
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px] font-mono">
                {ev.root_cause.shared_with_losers.length > 0 && (
                  <div>
                    <div className="text-red-400/90 mb-1">Shared with losing trades</div>
                    {ev.root_cause.shared_with_losers.map((f, i) => (
                      <div key={i} className="flex justify-between gap-2" data-testid={`row-loser-factor-${i}`}>
                        <span className="text-foreground/80">{f.factor}</span>
                        <span className="text-red-400">{f.loser_prevalence.toFixed(0)}% of losers · {f.lift.toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                )}
                {ev.root_cause.shared_with_winners.length > 0 && (
                  <div>
                    <div className="text-green-400/90 mb-1">Shared with winning trades</div>
                    {ev.root_cause.shared_with_winners.map((f, i) => (
                      <div key={i} className="flex justify-between gap-2" data-testid={`row-winner-factor-${i}`}>
                        <span className="text-foreground/80">{f.factor}</span>
                        <span className="text-green-400">{f.winner_prevalence.toFixed(0)}% of winners · +{f.lift.toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {ev.root_cause.factor_table.length > 0 && (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-[11px] font-mono">
                    <thead>
                      <tr className="text-muted-foreground text-left">
                        <th className="pr-3 py-1 font-normal">Factor ({ev.root_cause.winners}W / {ev.root_cause.losers}L similar trades)</th>
                        <th className="pr-3 py-1 font-normal text-right">Winners</th>
                        <th className="pr-3 py-1 font-normal text-right">Losers</th>
                        <th className="py-1 font-normal text-right">Predictive lift</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ev.root_cause.factor_table.map((f, i) => (
                        <tr key={i} className="border-t border-border/30" data-testid={`row-factor-${i}`}>
                          <td className="pr-3 py-0.5">{f.factor}</td>
                          <td className="pr-3 py-0.5 text-right">{f.winner_prevalence.toFixed(0)}%</td>
                          <td className="pr-3 py-0.5 text-right">{f.loser_prevalence.toFixed(0)}%</td>
                          <td className={`py-0.5 text-right ${f.lift > 0 ? "text-green-400" : f.lift < 0 ? "text-red-400" : "text-muted-foreground"}`}>
                            {f.lift > 0 ? "+" : ""}{f.lift.toFixed(0)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
      <p className="text-[11px] text-yellow-400/80 mt-2 flex items-start gap-1">
        <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
        Historical similarity does not guarantee that the current trade will have the
        same outcome. Paper trading and research only.
      </p>
    </div>
  );
}

function TechnicalAnalysisPanel({ d }: { d: TradeDecision }) {
  const t = d.explanation_sections?.technical;
  if (!t) return null;
  return (
    <div data-testid="panel-technical-analysis">
      <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
        1. Current Technical Analysis
      </div>
      <dl className="space-y-1 font-mono text-xs">
        <div className="flex justify-between"><dt className="text-muted-foreground">Technical score</dt><dd>{fmt(t.technical_score, 0)}</dd></div>
        <div className="flex justify-between"><dt className="text-muted-foreground">Opportunity score</dt><dd>{fmt(t.opportunity_score, 0)}</dd></div>
        <div className="flex justify-between"><dt className="text-muted-foreground">Risk filters</dt><dd className={t.risk_filters_passed ? "text-green-400" : "text-red-400"}>{t.risk_filters_passed ? "Passed" : "Failed"}</dd></div>
        {!t.risk_filters_passed && t.risk_filter_notes.length > 0 && (
          <div className="text-red-400/80 text-[11px]">{t.risk_filter_notes.join("; ")}</div>
        )}
        <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Trend</dt><dd className="text-right">{t.trend}</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Momentum</dt><dd className="text-right">{t.momentum}</dd></div>
        <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Volume</dt><dd className="text-right">{t.volume}</dd></div>
      </dl>
      <p className="text-[10px] text-muted-foreground mt-2">
        Source: current market indicators only.
      </p>
    </div>
  );
}

function PatternKnowledgePanel({ d }: { d: TradeDecision }) {
  const p = d.explanation_sections?.pattern;
  return (
    <div className="mt-4 border-t border-border/50 pt-4" data-testid="panel-pattern-knowledge">
      <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
        3. Pattern Knowledge
      </div>
      {!p ? (
        <p className="text-xs text-muted-foreground font-mono">
          No historical pattern data available yet.
        </p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 font-mono text-xs">
          <div><div className="text-muted-foreground">Strategy</div><div className="font-bold">{p.strategy || "—"}</div></div>
          <div><div className="text-muted-foreground">Sector</div><div className="font-bold">{p.sector || "—"}</div></div>
          <div><div className="text-muted-foreground">Regime</div><div className="font-bold">{p.regime || "—"}</div></div>
          <div><div className="text-muted-foreground">Historical expectancy</div><div className={`font-bold ${p.expectancy >= 0 ? "text-green-400" : "text-red-400"}`}>{p.expectancy >= 0 ? "+" : ""}{fmt(p.expectancy)}%</div></div>
          <div><div className="text-muted-foreground">Profit factor</div><div className="font-bold">{fmt(p.profit_factor)}</div></div>
          <div><div className="text-muted-foreground">Sample size</div><div className="font-bold">{p.sample_size}</div></div>
        </div>
      )}
      <p className="text-[11px] text-muted-foreground mt-2 flex items-start gap-1" data-testid="text-pattern-note">
        <Info className="h-3 w-3 mt-0.5 flex-shrink-0" />
        This information is descriptive only and did not affect the confidence adjustment.
      </p>
    </div>
  );
}

function adjClass(v: number): string {
  return v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-muted-foreground";
}

const STATE_STYLE: Record<string, string> = {
  VALID:        "text-green-400 bg-green-500/10 border-green-500/30",
  WEAKENING:    "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  INVALIDATED:  "text-red-400 bg-red-500/10 border-red-500/30",
  IMPROVING:    "text-sky-300 bg-sky-500/10 border-sky-500/30",
  EXPIRED:      "text-slate-400 bg-slate-500/10 border-slate-500/30",
  DATA_LIMITED: "text-slate-400 bg-slate-500/10 border-slate-500/30",
};

function StateBadge({ state }: { state?: string }) {
  if (!state) return null;
  return (
    <span
      className={`inline-block rounded border px-1.5 py-0.5 text-[9px] font-mono font-bold whitespace-nowrap ${
        STATE_STYLE[state] ?? STATE_STYLE.VALID
      }`}
      data-testid={`badge-decision-state-${state.toLowerCase()}`}
    >
      {state.replace("_", " ")}
    </span>
  );
}

const CONFLICT_STYLE: Record<string, string> = {
  LOW:    "border-yellow-500/30 bg-yellow-500/10 text-yellow-400",
  MEDIUM: "border-orange-500/30 bg-orange-500/10 text-orange-400",
  HIGH:   "border-red-500/30 bg-red-500/10 text-red-400",
};

function ConditionsTable({
  title,
  conditions,
}: {
  title: string;
  conditions: TradeDecision["invalidation_conditions"];
}) {
  if (!conditions || conditions.length === 0) return null;
  return (
    <div className="mt-3">
      <div className="text-[11px] font-mono uppercase text-muted-foreground mb-1">{title}</div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono">
          <thead>
            <tr className="text-muted-foreground text-left">
              <th className="pr-3 py-1 font-normal">Metric</th>
              <th className="pr-3 py-1 font-normal">Now</th>
              <th className="pr-3 py-1 font-normal">Trigger</th>
              <th className="pr-3 py-1 font-normal">Status</th>
              <th className="py-1 font-normal">Why it matters</th>
            </tr>
          </thead>
          <tbody>
            {conditions.map((c, i) => (
              <tr key={i} className="border-t border-border/30" data-testid={`row-condition-${i}`}>
                <td className="pr-3 py-1 font-bold">{c.metric}</td>
                <td className="pr-3 py-1">{c.current_value}</td>
                <td className="pr-3 py-1">
                  {c.direction} {c.trigger_value}
                </td>
                <td className={`pr-3 py-1 font-bold ${c.met ? "text-red-400" : "text-green-400"}`}>
                  {c.met ? "TRIGGERED" : "not met"}
                </td>
                <td className="py-1 text-muted-foreground">{c.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AnalystPanel({ d }: { d: TradeDecision }) {
  if (!d.analyst_summary) return null;
  const isBuy = d.recommendation === "STRONG_BUY" || d.recommendation === "BUY";
  const validUntil = d.valid_until ? new Date(d.valid_until).toLocaleString() : null;
  return (
    <div className="mt-4 border-t border-border/50 pt-4" data-testid="panel-analyst-reasoning">
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <span className="text-xs font-mono uppercase text-muted-foreground">Analyst View</span>
        <StateBadge state={d.decision_state} />
        <span className="text-[10px] font-mono text-muted-foreground">
          {validUntil ? `Valid until ${validUntil}` : d.validity_note}
        </span>
      </div>

      <p
        className="text-xs text-foreground/90 leading-relaxed rounded border border-border/50 bg-muted/20 p-3 mb-3"
        data-testid="text-analyst-summary"
      >
        {d.analyst_summary}
      </p>

      {d.conflict_level && d.conflict_level !== "NONE" && (
        <div
          className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs mb-3 ${
            CONFLICT_STYLE[d.conflict_level] ?? CONFLICT_STYLE.LOW
          }`}
          data-testid="banner-conflict"
        >
          <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          <div>
            <span className="font-mono font-bold">{d.conflict_level} CONFLICT — </span>
            {d.conflict_explanation}
          </div>
        </div>
      )}

      {d.decision_state === "DATA_LIMITED" && (d.missing_data_fields?.length ?? 0) > 0 && (
        <div className="text-[11px] text-slate-400 font-mono mb-3" data-testid="text-missing-data">
          Assessment is provisional — missing: {d.missing_data_fields.join(", ")}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs">
        <div data-testid="panel-current-observation">
          <div className="text-[11px] font-mono uppercase text-muted-foreground mb-1">
            A. What the system sees now
          </div>
          <p className="text-foreground/80 leading-relaxed">{d.current_observation}</p>
        </div>
        <div data-testid="panel-historical-assessment">
          <div className="text-[11px] font-mono uppercase text-muted-foreground mb-1">
            B. What happened in similar setups
          </div>
          <p className="text-foreground/80 leading-relaxed">{d.historical_assessment}</p>
        </div>
        <div data-testid="panel-decision-reasoning">
          <div className="text-[11px] font-mono uppercase text-muted-foreground mb-1">
            C. Why this recommendation
          </div>
          <p className="text-foreground/80 leading-relaxed">{d.decision_reasoning}</p>
        </div>
      </div>

      {isBuy ? (
        <>
          <ConditionsTable
            title={`D. What would invalidate this decision (${d.invalidation_met ?? 0} of ${d.invalidation_conditions?.length ?? 0} triggered)`}
            conditions={d.invalidation_conditions}
          />
        </>
      ) : (
        <ConditionsTable
          title={
            d.recommendation === "EXIT"
              ? `D. What would argue against this exit (${d.upgrade_met ?? 0} of ${d.upgrade_conditions?.length ?? 0} met)`
              : `D. What would upgrade this decision (${d.upgrade_met ?? 0} of ${d.upgrade_conditions?.length ?? 0} met)`
          }
          conditions={d.upgrade_conditions}
        />
      )}
    </div>
  );
}

function FinalSummaryPanel({ d }: { d: TradeDecision }) {
  const s = d.explanation_sections?.summary;
  if (!s) return null;
  return (
    <div className="mt-4 border-t border-border/50 pt-4" data-testid="panel-final-summary">
      <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
        Final Decision Summary
      </div>
      <dl className="space-y-1 font-mono text-xs max-w-md">
        <div className="flex justify-between"><dt className="text-muted-foreground">Technical confidence</dt><dd>{fmt(s.technical_confidence, 0)}</dd></div>
        <div className="flex justify-between"><dt className="text-muted-foreground">Learning adjustment <span className="text-[10px]">(adaptive learning)</span></dt><dd className={adjClass(s.learning_adjustment)}>{s.learning_adjustment >= 0 ? "+" : ""}{fmt(s.learning_adjustment, 0)}</dd></div>
        <div className="flex justify-between"><dt className="text-muted-foreground">Model adjustment <span className="text-[10px]">(self-evaluation model v{d.model_version ?? 0})</span></dt><dd className={adjClass(s.model_adjustment)}>{s.model_adjustment >= 0 ? "+" : ""}{fmt(s.model_adjustment, 1)}</dd></div>
        <div className="flex justify-between"><dt className="text-muted-foreground">Similarity adjustment <span className="text-[10px]">(similar historical trades)</span></dt><dd className={adjClass(s.similarity_adjustment)}>{s.similarity_adjustment >= 0 ? "+" : ""}{fmt(s.similarity_adjustment, 1)}</dd></div>
        {s.pattern_adjustment !== 0 && (
          <div className="flex justify-between"><dt className="text-muted-foreground">Pattern adjustment</dt><dd className={adjClass(s.pattern_adjustment)}>{s.pattern_adjustment >= 0 ? "+" : ""}{fmt(s.pattern_adjustment, 1)}</dd></div>
        )}
        <div className="flex justify-between border-t border-border/50 pt-1 mt-1"><dt className="text-muted-foreground">Final confidence</dt><dd className="font-bold">{fmt(s.final_confidence, 0)}</dd></div>
        <div className="flex justify-between items-center"><dt className="text-muted-foreground">Recommendation</dt><dd><RecBadge rec={s.recommendation} /></dd></div>
      </dl>
      {s.learning_note && (
        <p className="text-[11px] text-muted-foreground mt-2" data-testid="text-learning-note">
          {s.learning_note}
        </p>
      )}
      <p className="text-[10px] text-muted-foreground mt-2">
        Each adjustment comes from exactly one evidence source. Pattern knowledge is
        descriptive only and contributes no adjustment.
      </p>
    </div>
  );
}

function DetailRow({ d }: { d: TradeDecision }) {
  return (
    <tr className="bg-muted/20">
      <td colSpan={11} className="px-6 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 text-sm">
          <BreakdownPanel d={d} />
          <div>
            <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
              Why this recommendation
            </div>
            <p className="text-foreground/90 leading-relaxed">
              {REC_LABEL[d.recommendation] ?? d.recommendation}: {d.reason}.
            </p>
            {d.failed_conditions.length > 0 && (
              <div className="mt-3">
                <div className="text-xs font-mono uppercase text-muted-foreground mb-1">
                  What's missing for a stronger rating
                </div>
                <ul className="list-disc list-inside space-y-0.5 text-foreground/80">
                  {d.failed_conditions.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <TechnicalAnalysisPanel d={d} />
          <div>
            <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
              Risk &amp; position
            </div>
            <dl className="space-y-1 font-mono text-xs">
              <div className="flex justify-between"><dt className="text-muted-foreground">Entry</dt><dd>{rupee(d.entry_price)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Stop-loss</dt><dd>{rupee(d.stop_loss)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Target</dt><dd>{rupee(d.target)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Risk : Reward</dt><dd>{d.rr_ratio > 0 ? `${fmt(d.rr_ratio, 1)} : 1` : "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Expected holding</dt><dd>{d.expected_holding_days > 0 ? `${fmt(d.expected_holding_days, 0)} days` : "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Expected drawdown</dt><dd>{d.expected_drawdown !== 0 ? `${fmt(d.expected_drawdown)}%` : "—"}</dd></div>
              {d.position_open && (
                <>
                  <div className="border-t border-border/50 my-2" />
                  <div className="flex justify-between"><dt className="text-muted-foreground">Open position</dt><dd>{d.position_quantity} @ {rupee(d.position_avg_price)}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Unrealized P&amp;L</dt><dd className={d.position_pnl_pct >= 0 ? "text-green-400" : "text-red-400"}>{d.position_pnl_pct >= 0 ? "+" : ""}{fmt(d.position_pnl_pct)}%</dd></div>
                  {d.exit_reason && (
                    <div className="text-orange-400 mt-1">{d.exit_reason}</div>
                  )}
                </>
              )}
            </dl>
          </div>
        </div>
        <SimilarityEvidencePanel d={d} />
        <PatternKnowledgePanel d={d} />
        <FinalSummaryPanel d={d} />
        <AnalystPanel d={d} />
      </td>
    </tr>
  );
}

export default function TradeDecisions() {
  const { data, isLoading } = useGetTradeDecisions(
    undefined,
    { query: { queryKey: getGetTradeDecisionsQueryKey() } },
  );
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("All");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function handleRefresh() {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      // force=true bypasses the server-side 10-min cache and regenerates
      // decisions from a fresh pipeline run.
      const fresh = await apiJson<any>("/trade-decisions?force=true");
      queryClient.setQueryData(getGetTradeDecisionsQueryKey(), fresh);
    } catch (e) {
      console.error("Trade decisions refresh failed:", e);
    } finally {
      setIsRefreshing(false);
    }
  }

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">
            SCANNING MARKET &amp; BUILDING DECISIONS... (~30s)
          </p>
        </div>
      </div>
    );
  }

  const decisions = data?.decisions ?? [];
  const visible =
    filter === "All" ? decisions : decisions.filter((d) => d.recommendation === filter);

  const updatedAt = data?.generated_at
    ? new Date(data.generated_at).toLocaleString()
    : "—";
  const updatedTime = data?.generated_at
    ? new Date(data.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "—";

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full" data-testid="page-trade-decisions">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold font-mono flex items-center gap-2">
            <Target className="h-6 w-6 text-primary" />
            TRADE DECISIONS
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            One clear recommendation per stock — paper trading only, not investment advice.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-mono hover:bg-accent disabled:opacity-50"
          data-testid="button-refresh-decisions"
        >
          <RefreshCcw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
          {isRefreshing ? "SCANNING..." : "REFRESH"}
        </button>
      </div>

      <DataFreshnessBar variant="scan" />

      {/* Phase 20 auto paper-entry gates (collapsible) */}
      <details className="rounded-lg border border-border/50 bg-card/30">
        <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground">
          Auto paper-entry gates <span className="normal-case text-muted-foreground/60">— PAPER / RESEARCH ONLY (click to load)</span>
        </summary>
        <div className="p-3 pt-0">
          <EntryEvaluationPanel />
        </div>
      </details>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        <SummaryCard label="Strong Buy" value={data?.strong_buy_count ?? 0} color="text-emerald-300" />
        <SummaryCard label="Buy" value={data?.buy_count ?? 0} color="text-green-400" />
        <SummaryCard label="Exit" value={data?.exit_count ?? 0} color="text-orange-400" />
        <SummaryCard label="Watch" value={data?.watch_count ?? 0} color="text-yellow-400" />
        <SummaryCard label="Avoid" value={data?.avoid_count ?? 0} color="text-red-400" />
        <SummaryCard label="Market Regime" value={data?.market_regime ?? "—"} />
        <SummaryCard label="Model Version" value={`v${data?.model_version ?? 0}`} />
        <SummaryCard label="Last Updated" value={updatedTime} />
      </div>

      {(data?.data_unavailable_count ?? 0) > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-400">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          Live NSE data unavailable for {data?.data_unavailable_count} stock(s) — no
          buy recommendations are issued on fallback data.
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-md border px-3 py-1 text-xs font-mono ${
              filter === f
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-accent"
            }`}
            data-testid={`button-filter-${f.toLowerCase()}`}
          >
            {f === "All" ? "ALL" : REC_LABEL[f] ?? f}
          </button>
        ))}
        <span className="ml-auto text-xs font-mono text-muted-foreground flex items-center gap-1">
          <Info className="h-3 w-3" /> Last updated: {updatedAt}
        </span>
      </div>

      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 text-xs font-mono uppercase text-muted-foreground">
                <th className="px-4 py-2 text-left w-8"></th>
                <th className="px-2 py-2 text-left">Stock</th>
                <th className="px-2 py-2 text-left">Decision</th>
                <th className="px-2 py-2 text-right">Confidence</th>
                <th className="px-2 py-2 text-right">Price</th>
                <th className="px-2 py-2 text-right">Entry</th>
                <th className="px-2 py-2 text-right">Stop</th>
                <th className="px-2 py-2 text-right">Target</th>
                <th className="px-2 py-2 text-right">R:R</th>
                <th className="px-2 py-2 text-right">Hold (Days)</th>
                <th className="px-4 py-2 text-left">Reason</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((d) => {
                const isOpen = expanded === d.stock;
                return (
                  <React.Fragment key={d.stock}>
                    <tr
                      className="border-b border-border/30 hover:bg-accent/30 cursor-pointer"
                      onClick={() => setExpanded(isOpen ? null : d.stock)}
                      data-testid={`row-decision-${d.stock}`}
                    >
                      <td className="px-4 py-2 text-muted-foreground">
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </td>
                      <td className="px-2 py-2 font-mono font-bold">
                        {d.stock}
                        {d.position_open && (
                          <span className="ml-1.5 rounded bg-blue-500/15 border border-blue-500/30 px-1 py-0.5 text-[9px] text-blue-400 font-mono align-middle">
                            HELD
                          </span>
                        )}
                        <div className="text-[10px] font-normal text-muted-foreground">
                          {d.sector}
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex flex-col items-start gap-1">
                          <RecBadge rec={d.recommendation} />
                          {d.low_reliability && (
                            <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1 py-0.5 text-[9px] font-mono text-amber-400 whitespace-nowrap">
                              LOW RELIABILITY
                            </span>
                          )}
                          {d.data_status !== "OK" && (
                            <span className="rounded border border-slate-500/30 bg-slate-500/10 px-1 py-0.5 text-[9px] font-mono text-slate-400 whitespace-nowrap">
                              DATA UNAVAILABLE
                            </span>
                          )}
                          {d.decision_state && d.decision_state !== "VALID" && (
                            <StateBadge state={d.decision_state} />
                          )}
                        </div>
                      </td>
                      <td className="px-2 py-2 text-right font-mono">{fmt(d.final_confidence, 0)}</td>
                      <td className="px-2 py-2 text-right font-mono">{rupee(d.price)}</td>
                      <td className="px-2 py-2 text-right font-mono">{rupee(d.entry_price)}</td>
                      <td className="px-2 py-2 text-right font-mono text-red-400/90">{rupee(d.stop_loss)}</td>
                      <td className="px-2 py-2 text-right font-mono text-green-400/90">{rupee(d.target)}</td>
                      <td className="px-2 py-2 text-right font-mono">
                        {d.rr_ratio > 0 ? `${fmt(d.rr_ratio, 1)}:1` : "—"}
                      </td>
                      <td className="px-2 py-2 text-right font-mono">
                        {d.expected_holding_days > 0 ? fmt(d.expected_holding_days, 0) : "—"}
                      </td>
                      <td className="px-4 py-2 text-muted-foreground max-w-md truncate">
                        {d.reason}
                      </td>
                    </tr>
                    {isOpen && <DetailRow d={d} />}
                  </React.Fragment>
                );
              })}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-8 text-center text-muted-foreground font-mono text-sm">
                    No stocks in this category.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Phase13RegimeStrip />

      <p className="text-xs text-muted-foreground font-mono">
        {data?.warning ?? "Paper trading only — research tool, not investment advice."}
      </p>
    </div>
  );
}
