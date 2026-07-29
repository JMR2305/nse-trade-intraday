/**
 * StrategyOptimisation.tsx — Phase 6.2
 * Strategy Optimisation & Adaptive Learning Dashboard.
 *
 * Eight sections:
 *   1. Overall Strategy Ranking
 *   2. Market Regime Ranking
 *   3. Sector Ranking
 *   4. Time Window Ranking
 *   5. Parameter Recommendations
 *   6. Adaptive Learning
 *   7. Pattern Discovery
 *   8. Historical Improvements (underperforming actions)
 *
 * READ-ONLY. ADVISORY-ONLY.
 * No strategy parameters, orders, portfolio, signals, or risk engine
 * are ever modified by this dashboard.
 */
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2, RefreshCw, Download, TrendingUp, TrendingDown, AlertTriangle,
  Zap, BarChart3, Clock, Layers, Brain, Activity, Target, Settings2,
  ShieldCheck, ArrowUpRight, ArrowDownRight, Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "STRATEGY OPTIMISATION — ADVISORY ONLY — NO PARAMETERS AUTO-MODIFIED";
const BASE_URL = import.meta.env.BASE_URL ?? "/trading-dashboard/";

// ---------------------------------------------------------------------------
// UI primitives
// ---------------------------------------------------------------------------

function DisabledBanner({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded border border-amber-800 bg-amber-950/30 p-8 text-center">
      <Settings2 className="h-8 w-8 text-amber-400" />
      <div className="text-amber-400 font-semibold">Strategy Optimisation is disabled</div>
      <code className="rounded bg-zinc-900 px-2 py-1 text-xs text-amber-300">
        {message ?? "Set STRATEGY_OPTIMISATION_ENABLED=true to enable."}
      </code>
    </div>
  );
}

function SectionCard({ title, icon: Icon, children, className }: {
  title: string; icon: any; children: React.ReactNode; className?: string;
}) {
  return (
    <Card className={cn("border-zinc-800 bg-zinc-950", className)}>
      <CardHeader className="py-3">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <Icon className="h-4 w-4 text-sky-400" /> {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">{children}</CardContent>
    </Card>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  const fmt = (v: any) => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "—";
    return String(v);
  };
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={cn("text-sm font-mono", cls ?? "text-zinc-200")}>{fmt(value)}</div>
    </div>
  );
}

function MiniTable({ headers, rows }: { headers: string[]; rows: any[][] }) {
  if (!rows.length) return <div className="text-zinc-500 font-mono text-[11px] py-2">No data yet.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] font-mono">
        <thead>
          <tr className="text-zinc-500 border-b border-zinc-800">
            {headers.map((h) => <th key={h} className="text-left py-1 pr-3 font-normal">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-zinc-900 text-zinc-300">
              {r.map((c, j) => <td key={j} className="py-1 pr-3">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Grade badge
const GRADE_CLS: Record<string, string> = {
  "A+": "text-emerald-400 border-emerald-700 bg-emerald-950/30",
  "A":  "text-sky-400 border-sky-700 bg-sky-950/30",
  "B":  "text-blue-400 border-blue-700 bg-blue-950/30",
  "C":  "text-amber-400 border-amber-700 bg-amber-950/30",
  "D":  "text-red-400 border-red-700 bg-red-950/30",
};

// Action badge
const ACTION_CLS: Record<string, string> = {
  Continue: "text-emerald-400 border-emerald-700",
  Observe:  "text-sky-400 border-sky-700",
  Retune:   "text-amber-400 border-amber-700",
  Pause:    "text-red-400 border-red-700",
};

// Lifecycle badge
const LIFECYCLE_CLS: Record<string, string> = {
  ACTIVE:    "text-emerald-400 border-emerald-700",
  EMERGING:  "text-sky-400 border-sky-700",
  DECLINING: "text-amber-400 border-amber-700",
  DORMANT:   "text-zinc-500 border-zinc-700",
};

// Trend icon
function TrendIcon({ trend }: { trend?: string }) {
  if (trend === "IMPROVING") return <ArrowUpRight className="h-3.5 w-3.5 text-emerald-400 inline" />;
  if (trend === "DECLINING") return <ArrowDownRight className="h-3.5 w-3.5 text-red-400 inline" />;
  return <Minus className="h-3.5 w-3.5 text-zinc-500 inline" />;
}

function pct(v: any) { return v !== null && v !== undefined ? `${(+v * 100).toFixed(1)}%` : "—"; }
function rs(v: any)  { return v !== null && v !== undefined ? `₹${(+v).toFixed(0)}` : "—"; }
function n2(v: any)  { return v !== null && v !== undefined ? (+v).toFixed(2) : "—"; }

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

export default function StrategyOptimisation() {
  const summaryQ = useQuery({
    queryKey: ["opt-summary"],
    queryFn: () => apiJson("/optimisation/summary"),
    refetchInterval: 120_000, staleTime: 60_000,
  });
  const strategiesQ = useQuery({
    queryKey: ["opt-strategies"],
    queryFn: () => apiJson("/optimisation/strategies"),
    refetchInterval: 120_000, staleTime: 60_000,
  });
  const recsQ = useQuery({
    queryKey: ["opt-recommendations"],
    queryFn: () => apiJson("/optimisation/recommendations"),
    refetchInterval: 120_000, staleTime: 60_000,
  });
  const patternsQ = useQuery({
    queryKey: ["opt-patterns"],
    queryFn: () => apiJson("/optimisation/patterns"),
    refetchInterval: 120_000, staleTime: 60_000,
  });

  const loading = summaryQ.isLoading || strategiesQ.isLoading || recsQ.isLoading || patternsQ.isLoading;

  const refetch = () => {
    void summaryQ.refetch();
    void strategiesQ.refetch();
    void recsQ.refetch();
    void patternsQ.refetch();
  };

  const isDisabled = summaryQ.data?.status === "DISABLED";

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <Zap className="h-5 w-5 text-sky-400" /> Strategy Optimisation
          </h1>
          <Badge variant="outline" className="mt-1 text-[10px] text-amber-400 border-amber-700">
            {LABEL}
          </Badge>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={refetch} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="ml-1">Refresh</span>
          </Button>
          <Button size="sm" variant="outline" disabled={isDisabled}
            onClick={() => window.open(`${BASE_URL}api/optimisation/export/csv`, "_blank")}>
            <Download className="h-4 w-4" /><span className="ml-1">Export CSV</span>
          </Button>
          <Button size="sm" variant="outline" disabled={isDisabled}
            onClick={() => window.open(`${BASE_URL}api/optimisation/export/json`, "_blank")}>
            <Download className="h-4 w-4" /><span className="ml-1">Export JSON</span>
          </Button>
        </div>
      </div>

      {isDisabled && <DisabledBanner message={summaryQ.data?.message} />}

      {!isDisabled && (
        <>
          {/* ----------------------------------------------------------------
              Section 1: Overall Strategy Ranking
          ---------------------------------------------------------------- */}
          <SectionCard title="Overall Strategy Ranking" icon={BarChart3}>
            {strategiesQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
            ) : (() => {
              const strategies = strategiesQ.data?.strategies ?? [];
              if (!strategies.length) return <div className="text-zinc-500 text-[11px]">No strategies yet — complete some paper trades first.</div>;
              return (
                <div className="space-y-2">
                  {strategies.map((s: any, i: number) => (
                    <div key={s.strategy} className="rounded border border-zinc-800 bg-zinc-900/40 p-3 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-zinc-400 font-mono text-[11px]">#{i + 1}</span>
                        <span className="text-zinc-100 font-semibold text-sm">{s.strategy}</span>
                        <Badge variant="outline" className={cn("text-[10px]", GRADE_CLS[s.grade] ?? "")}>
                          {s.grade}
                        </Badge>
                        <Badge variant="outline" className={cn("text-[10px]", ACTION_CLS[s.action] ?? "")}>
                          {s.action}
                        </Badge>
                        {s.is_underperforming && (
                          <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
                            ⚠ Underperforming
                          </Badge>
                        )}
                        <span className="ml-auto text-zinc-400 font-mono text-[11px]">
                          Health: <span className="text-zinc-200">{n2(s.health_score)}/100</span>
                        </span>
                      </div>
                      <div className="grid grid-cols-3 sm:grid-cols-6 lg:grid-cols-9 gap-1.5">
                        <Stat label="Trades" value={s.total_trades} />
                        <Stat label="Win Rate" value={pct(s.win_rate)} cls={s.win_rate >= 0.5 ? "text-emerald-400" : "text-red-400"} />
                        <Stat label="Avg Return" value={`${n2(s.avg_return_pct)}%`} cls={s.avg_return_pct >= 0 ? "text-emerald-400" : "text-red-400"} />
                        <Stat label="Profit Factor" value={n2(s.profit_factor)} cls={s.profit_factor >= 1.5 ? "text-emerald-400" : "text-amber-400"} />
                        <Stat label="Max DD" value={pct(s.max_drawdown)} cls="text-amber-400" />
                        <Stat label="Sharpe" value={n2(s.sharpe_ratio)} />
                        <Stat label="Consistency" value={pct(s.consistency_score)} />
                        <Stat label="Avg Confidence" value={n2(s.avg_confidence)} cls="text-sky-400" />
                        <Stat label="Avg EQ Score" value={n2(s.avg_execution_score)} cls="text-sky-400" />
                      </div>
                      {s.underperform_reasons?.length > 0 && (
                        <div className="text-[11px] text-amber-400 flex flex-wrap gap-1">
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                          {s.underperform_reasons.join(" · ")}
                        </div>
                      )}
                      {/* Regime breakdown */}
                      {s.regime_breakdown?.length > 0 && (
                        <div className="mt-1">
                          <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Regime Breakdown</div>
                          <div className="flex flex-wrap gap-1">
                            {s.regime_breakdown.map((rb: any) => (
                              <span key={rb.regime} className="rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 text-[10px] font-mono">
                                {rb.regime}: <span className={rb.win_rate >= 0.5 ? "text-emerald-400" : "text-red-400"}>{pct(rb.win_rate)}</span>
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 2 & 3: Regime + Sector side by side
          ---------------------------------------------------------------- */}
          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Market Regime Ranking" icon={TrendingUp}>
              {patternsQ.isLoading ? (
                <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
              ) : (
                <MiniTable
                  headers={["#", "Regime", "Trades", "Win%", "Net P&L", "Avg Conf"]}
                  rows={(patternsQ.data?.regime_ranking ?? []).map((r: any) => [
                    r.rank,
                    r.regime,
                    r.trades,
                    pct(r.win_rate),
                    <span key="pnl" className={r.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>{rs(r.net_pnl)}</span>,
                    n2(r.avg_confidence),
                  ])}
                />
              )}
            </SectionCard>

            <SectionCard title="Sector Ranking" icon={Layers}>
              {patternsQ.isLoading ? (
                <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
              ) : (
                <MiniTable
                  headers={["#", "Sector", "Trades", "Win%", "Net P&L", "Consistency"]}
                  rows={(patternsQ.data?.sector_ranking ?? []).map((s: any) => [
                    s.rank,
                    s.sector,
                    s.trades,
                    pct(s.win_rate),
                    <span key="pnl" className={s.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>{rs(s.net_pnl)}</span>,
                    pct(s.consistency_score),
                  ])}
                />
              )}
            </SectionCard>
          </div>

          {/* ----------------------------------------------------------------
              Section 4: Time Window Ranking
          ---------------------------------------------------------------- */}
          <SectionCard title="Time Window Ranking" icon={Clock}>
            {recsQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
            ) : (() => {
              const tw = recsQ.data?.time_window_recommendation;
              return (
                <div className="space-y-3">
                  {tw && (
                    <div className="rounded border border-sky-800 bg-sky-950/20 p-2 text-[11px]">
                      <span className="text-sky-400 font-semibold">Best Window Advisory: </span>
                      <span className="text-zinc-200">{tw.recommendation}</span>
                      <span className="text-zinc-400 ml-2">— {tw.rationale}</span>
                    </div>
                  )}
                  {/* Re-use strategies data for approximate time windows via regime */}
                  <div className="text-[11px] text-zinc-500">
                    Time window analysis uses approximate entry times (exit_ts − holding_time).
                    Windows: Opening Hour (09:15–10:15) · Morning (10:15–11:30) · Mid Session (11:30–13:00) · Afternoon (13:00–14:30) · Closing Hour (14:30–15:30).
                  </div>
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 5: Parameter Recommendations
          ---------------------------------------------------------------- */}
          <SectionCard title="Parameter Recommendations (Advisory Only — Never Auto-Applied)" icon={Target}>
            {recsQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
            ) : (() => {
              const recs = recsQ.data?.parameter_recommendations ?? [];
              if (!recs.length) return (
                <div className="text-zinc-500 text-[11px]">
                  No parameter recommendations yet — need ≥3 completed trades per strategy.
                </div>
              );
              const CONF_CLS: Record<string, string> = {
                HIGH: "text-emerald-400 border-emerald-700",
                MEDIUM: "text-sky-400 border-sky-700",
                LOW: "text-zinc-400 border-zinc-700",
              };
              return (
                <div className="space-y-2">
                  {recs.map((r: any, i: number) => (
                    <div key={i} className="rounded border border-zinc-800 bg-zinc-900/40 p-2 space-y-1">
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <Badge variant="outline" className="text-[10px]">{r.strategy}</Badge>
                        <span className="text-sky-400 font-semibold">{r.parameter}</span>
                        <Badge variant="outline" className={cn("text-[10px]", CONF_CLS[r.confidence] ?? "")}>
                          {r.confidence} confidence
                        </Badge>
                        <span className="text-zinc-500 italic ml-auto">advisory only</span>
                      </div>
                      <div className="text-zinc-400 text-[11px]">Current: {r.current_observation}</div>
                      <div className="text-emerald-400 text-[11px] font-mono">→ Recommended: {r.recommended_value}</div>
                      <div className="text-zinc-500 text-[11px]">{r.rationale}</div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 6: Adaptive Learning
          ---------------------------------------------------------------- */}
          <SectionCard title="Adaptive Learning" icon={Brain}>
            {recsQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
            ) : (() => {
              const al = recsQ.data?.adaptive_learning;
              if (!al) return <div className="text-zinc-500 text-[11px]">Adaptive learning data unavailable.</div>;
              return (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Overall Trend</div>
                      <div className="flex items-center gap-1 text-sm font-mono">
                        <TrendIcon trend={al.overall_trend} />
                        <span className={al.overall_trend === "IMPROVING" ? "text-emerald-400" : al.overall_trend === "DECLINING" ? "text-red-400" : "text-zinc-300"}>
                          {al.overall_trend ?? "—"}
                        </span>
                      </div>
                    </div>
                    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide">P&L Trend</div>
                      <div className="flex items-center gap-1 text-sm font-mono">
                        <TrendIcon trend={al.improvement_trend} />
                        <span className={al.improvement_trend === "IMPROVING" ? "text-emerald-400" : al.improvement_trend === "DECLINING" ? "text-red-400" : "text-zinc-300"}>
                          {al.improvement_trend ?? "—"}
                        </span>
                      </div>
                    </div>
                    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Stability</div>
                      <div className="text-sm font-mono text-zinc-200">{al.stability_trend ?? "—"}</div>
                    </div>
                    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Regression</div>
                      <div className={cn("text-sm font-mono", al.regression_trend === "DECLINING" ? "text-red-400" : "text-zinc-300")}>
                        {al.regression_trend ?? "—"}
                      </div>
                    </div>
                  </div>

                  {/* Strategy lifecycle states */}
                  {(al.strategies ?? []).length > 0 && (
                    <div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Strategy Lifecycle</div>
                      <div className="space-y-1">
                        {al.strategies.map((s: any) => (
                          <div key={s.strategy} className="flex flex-wrap items-center gap-2 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 text-[11px]">
                            <span className="text-zinc-200 font-semibold">{s.strategy}</span>
                            <Badge variant="outline" className={cn("text-[10px]", LIFECYCLE_CLS[s.lifecycle] ?? "text-zinc-400 border-zinc-700")}>
                              {s.lifecycle}
                            </Badge>
                            <TrendIcon trend={s.performance_trend} />
                            <span className="text-zinc-500">{s.performance_trend}</span>
                            <span className="ml-auto text-zinc-500">
                              Win Rate: <span className="text-zinc-300">{pct(s.current_win_rate)}</span>
                              {" "} → Recent: <span className={cn(s.recent_win_rate >= s.current_win_rate ? "text-emerald-400" : "text-red-400")}>
                                {pct(s.recent_win_rate)}
                              </span>
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 7: Pattern Discovery
          ---------------------------------------------------------------- */}
          <SectionCard title="Pattern Discovery" icon={Activity}>
            {patternsQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
            ) : (() => {
              const winning = patternsQ.data?.winning_patterns ?? [];
              const losing = patternsQ.data?.losing_patterns ?? [];
              const highConf = patternsQ.data?.high_confidence_patterns ?? [];
              const lowConf = patternsQ.data?.low_confidence_patterns ?? [];
              const allPatterns = [...winning, ...highConf, ...losing, ...lowConf];

              if (!allPatterns.length) return (
                <div className="text-zinc-500 text-[11px]">
                  No patterns discovered yet — need more completed trades for pattern clustering.
                </div>
              );

              const TYPE_CLS: Record<string, string> = {
                WINNING:   "text-emerald-400 border-emerald-700",
                HIGH_CONF: "text-sky-400 border-sky-700",
                LOSING:    "text-red-400 border-red-700",
                LOW_CONF:  "text-amber-400 border-amber-700",
              };

              return (
                <div className="space-y-2">
                  {allPatterns.map((p: any, i: number) => (
                    <div key={i} className="rounded border border-zinc-800 bg-zinc-900/40 p-2 space-y-1">
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <Badge variant="outline" className={cn("text-[10px]", TYPE_CLS[p.pattern_type] ?? "")}>
                          {p.pattern_type.replace("_", " ")}
                        </Badge>
                        <span className="text-zinc-200 font-semibold">{p.description}</span>
                        <span className="ml-auto text-zinc-500">
                          {p.trade_count} trades · Win: <span className={p.win_rate >= 0.5 ? "text-emerald-400" : "text-red-400"}>{pct(p.win_rate)}</span>
                          {" "}· Avg ret: <span className={p.avg_return_pct >= 0 ? "text-emerald-400" : "text-red-400"}>{n2(p.avg_return_pct)}%</span>
                        </span>
                      </div>
                      {p.conditions && Object.keys(p.conditions).length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(p.conditions as Record<string, any>).map(([k, v]) => (
                            <span key={k} className="rounded bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 text-[10px] font-mono text-zinc-400">
                              {k}: {String(v)}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 8: Historical Improvements (underperforming actions)
          ---------------------------------------------------------------- */}
          <SectionCard title="Historical Improvements & Underperforming Actions" icon={ShieldCheck}>
            {recsQ.isLoading ? (
              <div className="flex items-center gap-2 text-zinc-400 py-4 justify-center"><Loader2 className="h-4 w-4 animate-spin" /></div>
            ) : (() => {
              const actions = recsQ.data?.underperforming_actions ?? [];
              const regimeRec = recsQ.data?.regime_recommendation;

              return (
                <div className="space-y-3">
                  {regimeRec && (
                    <div className="rounded border border-sky-800 bg-sky-950/20 p-2 text-[11px]">
                      <span className="text-sky-400 font-semibold">Regime Advisory: </span>
                      <span className="text-zinc-200">{regimeRec.recommendation}</span>
                      <span className="text-zinc-400 ml-2">— {regimeRec.rationale}</span>
                      <span className="text-zinc-500 ml-2 italic">({regimeRec.advisory_only ? "advisory only" : ""})</span>
                    </div>
                  )}

                  {!actions.length ? (
                    <div className="text-zinc-500 text-[11px]">
                      {strategiesQ.data?.strategies?.length
                        ? "✓ No underperforming strategies detected."
                        : "No strategy data yet."}
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="text-[10px] uppercase tracking-wide text-zinc-500">
                        Underperforming Strategies — Advisory Actions Only
                      </div>
                      {actions.map((a: any, i: number) => (
                        <div key={i} className="rounded border border-zinc-800 bg-zinc-900/40 p-2 space-y-1">
                          <div className="flex flex-wrap items-center gap-2 text-[11px]">
                            <span className="text-zinc-200 font-semibold">{a.strategy}</span>
                            <Badge variant="outline" className={cn("text-[10px]", GRADE_CLS[a.grade] ?? "")}>
                              {a.grade}
                            </Badge>
                            <Badge variant="outline" className={cn("text-[10px]", ACTION_CLS[a.action] ?? "")}>
                              → {a.action}
                            </Badge>
                            <span className="text-zinc-500 font-mono">Health: {n2(a.health_score)}</span>
                            <span className="text-zinc-500 italic ml-auto text-[10px]">advisory only</span>
                          </div>
                          {a.reasons?.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {a.reasons.map((r: string) => (
                                <span key={r} className="rounded bg-amber-950/30 border border-amber-800 px-1.5 py-0.5 text-[10px] text-amber-400">
                                  {r}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="text-[11px] text-zinc-600 border-t border-zinc-800 pt-2">
                    ⚠ All recommendations are advisory only. No strategy parameters are ever modified automatically.
                  </div>
                </div>
              );
            })()}
          </SectionCard>
        </>
      )}
    </div>
  );
}
