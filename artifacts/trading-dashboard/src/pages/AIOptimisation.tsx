/**
 * AIOptimisation.tsx — Phase 6.3
 * AI Optimisation & Continuous Learning Framework Dashboard.
 *
 * Nine sections:
 *   1. AI Health (score, grade, trend)
 *   2. Confidence Calibration (5 bands)
 *   3. Prediction Quality (accuracy, precision, recall, F1, FPR, FNR)
 *   4. False Signal Analysis
 *   5. Model Drift (6 dimensions)
 *   6. Learning Progress
 *   7. Version Comparison (future-ready stub)
 *   8. Recommendations (advisory only)
 *   9. Historical Trend
 *
 * READ-ONLY. ADVISORY-ONLY.
 * No AI models, orders, portfolio, signals, or risk engine are modified.
 */
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2, RefreshCw, Download, Brain, Activity, Target, BarChart3,
  TrendingUp, TrendingDown, Minus, AlertTriangle, Zap, GitCompare,
  BookOpen, Layers, Shield, FlaskConical, ArrowUpRight, ArrowDownRight,
  CheckCircle2, XCircle, Settings2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "AI OPTIMISATION — ADVISORY ONLY — NO AI BEHAVIOUR AUTO-MODIFIED";
const BASE_URL = import.meta.env.BASE_URL ?? "/trading-dashboard/";

// ---------------------------------------------------------------------------
// UI Primitives
// ---------------------------------------------------------------------------

function DisabledBanner({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded border border-amber-800 bg-amber-950/30 p-8 text-center">
      <Settings2 className="h-8 w-8 text-amber-400" />
      <div className="text-amber-400 font-semibold">AI Optimisation is disabled</div>
      <code className="rounded bg-zinc-900 px-2 py-1 text-xs text-amber-300">
        {message ?? "Set AI_OPTIMISATION_ENABLED=true to enable."}
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

function MiniTable({ headers, rows, emptyText }: {
  headers: string[]; rows: any[][]; emptyText?: string;
}) {
  if (!rows.length) return (
    <div className="text-zinc-500 font-mono text-[11px] py-2">{emptyText ?? "No data yet."}</div>
  );
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

function TrendIcon({ trend }: { trend?: string }) {
  if (trend === "IMPROVING") return <ArrowUpRight className="h-3.5 w-3.5 text-emerald-400 inline" />;
  if (trend === "DECLINING") return <ArrowDownRight className="h-3.5 w-3.5 text-red-400 inline" />;
  return <Minus className="h-3.5 w-3.5 text-zinc-500 inline" />;
}

const GRADE_CLS: Record<string, string> = {
  "A+": "text-emerald-400 border-emerald-700 bg-emerald-950/30",
  "A":  "text-sky-400 border-sky-700 bg-sky-950/30",
  "B":  "text-blue-400 border-blue-700 bg-blue-950/30",
  "C":  "text-amber-400 border-amber-700 bg-amber-950/30",
  "D":  "text-red-400 border-red-700 bg-red-950/30",
};

const SEVERITY_CLS: Record<string, string> = {
  HIGH:   "text-red-400 border-red-700",
  MEDIUM: "text-amber-400 border-amber-700",
  LOW:    "text-emerald-400 border-emerald-700",
  STABLE: "text-zinc-400 border-zinc-700",
  NONE:   "text-zinc-400 border-zinc-700",
};

const CONF_CLS: Record<string, string> = {
  HIGH:   "text-emerald-400 border-emerald-700",
  MEDIUM: "text-sky-400 border-sky-700",
  LOW:    "text-zinc-400 border-zinc-700",
};

function pct(v: any)  { return v != null ? `${(+v * 100).toFixed(1)}%` : "—"; }
function n2(v: any)   { return v != null ? (+v).toFixed(2) : "—"; }
function n1(v: any)   { return v != null ? (+v).toFixed(1) : "—"; }

// ---------------------------------------------------------------------------
// Score Ring (simple arc visualisation)
// ---------------------------------------------------------------------------
function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const cls = grade === "A+" || grade === "A" ? "text-emerald-400"
            : grade === "B" ? "text-sky-400"
            : grade === "C" ? "text-amber-400" : "text-red-400";
  const r = 40, cx = 50, cy = 50;
  const circumference = 2 * Math.PI * r;
  const dash = (score / 100) * circumference;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx={cx} cy={cy} r={r} fill="none" strokeWidth="8" stroke="#27272a" />
        <circle
          cx={cx} cy={cy} r={r} fill="none" strokeWidth="8"
          stroke="currentColor" className={cls}
          strokeDasharray={`${dash} ${circumference}`}
          strokeLinecap="round"
          transform="rotate(-90 50 50)"
        />
        <text x="50" y="46" textAnchor="middle" fill="currentColor"
          className={cls} fontSize="18" fontWeight="bold">{score.toFixed(0)}</text>
        <text x="50" y="60" textAnchor="middle" fill="#71717a" fontSize="10">/ 100</text>
      </svg>
      <Badge variant="outline" className={cn("text-[11px]", GRADE_CLS[grade] ?? "")}>Grade {grade}</Badge>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AIOptimisation() {
  const summaryQ = useQuery({
    queryKey: ["aio-summary"],
    queryFn: () => apiJson("/ai-optimisation/summary"),
    refetchInterval: 120_000, staleTime: 60_000,
  });
  const calibrationQ = useQuery({
    queryKey: ["aio-calibration"],
    queryFn: () => apiJson("/ai-optimisation/calibration"),
    refetchInterval: 120_000, staleTime: 60_000,
  });
  const driftQ = useQuery({
    queryKey: ["aio-drift"],
    queryFn: () => apiJson("/ai-optimisation/drift"),
    refetchInterval: 120_000, staleTime: 60_000,
  });
  const recsQ = useQuery({
    queryKey: ["aio-recommendations"],
    queryFn: () => apiJson("/ai-optimisation/recommendations"),
    refetchInterval: 120_000, staleTime: 60_000,
  });
  const historyQ = useQuery({
    queryKey: ["aio-history"],
    queryFn: () => apiJson("/ai-optimisation/history"),
    refetchInterval: 120_000, staleTime: 60_000,
  });

  const loading = summaryQ.isLoading || calibrationQ.isLoading || driftQ.isLoading
               || recsQ.isLoading || historyQ.isLoading;

  const refetch = () => {
    void summaryQ.refetch(); void calibrationQ.refetch();
    void driftQ.refetch();   void recsQ.refetch(); void historyQ.refetch();
  };

  const isDisabled = summaryQ.data?.status === "DISABLED";
  const s = summaryQ.data ?? {};

  return (
    <div className="space-y-4 p-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <Brain className="h-5 w-5 text-sky-400" /> AI Optimisation
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
            onClick={() => window.open(`${BASE_URL}api/ai-optimisation/export/csv`, "_blank")}>
            <Download className="h-4 w-4" /><span className="ml-1">Export CSV</span>
          </Button>
          <Button size="sm" variant="outline" disabled={isDisabled}
            onClick={() => window.open(`${BASE_URL}api/ai-optimisation/export/json`, "_blank")}>
            <Download className="h-4 w-4" /><span className="ml-1">Export JSON</span>
          </Button>
        </div>
      </div>

      {isDisabled && <DisabledBanner message={summaryQ.data?.message} />}

      {!isDisabled && (
        <>
          {/* ----------------------------------------------------------------
              Section 1: AI Health
          ---------------------------------------------------------------- */}
          <SectionCard title="AI Health" icon={Shield}>
            {summaryQ.isLoading ? (
              <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-zinc-400" /></div>
            ) : (
              <div className="flex flex-wrap gap-4 items-center">
                <ScoreRing score={s.ai_optimisation_score ?? 0} grade={s.grade ?? "D"} />
                <div className="flex-1 space-y-2">
                  <div className="flex flex-wrap gap-2 items-center">
                    <span className="text-zinc-400 text-[11px]">Trend</span>
                    <TrendIcon trend={s.trend} />
                    <span className={cn("text-[11px] font-semibold",
                      s.trend === "IMPROVING" ? "text-emerald-400"
                      : s.trend === "DECLINING" ? "text-red-400" : "text-zinc-400")}>
                      {s.trend ?? "—"}
                    </span>
                    <span className="text-zinc-600 mx-1">·</span>
                    <span className="text-zinc-400 text-[11px]">{s.total_trades ?? 0} trades analysed</span>
                    <span className="text-zinc-600 mx-1">·</span>
                    <span className="text-zinc-400 text-[11px]">Drift: </span>
                    <Badge variant="outline" className={cn("text-[10px]", SEVERITY_CLS[s.drift_severity ?? "NONE"] ?? "")}>
                      {s.drift_severity ?? "—"}
                    </Badge>
                  </div>
                  <div className="grid grid-cols-3 sm:grid-cols-6 gap-1.5">
                    <Stat label="Accuracy" value={pct(s.accuracy)} cls={s.accuracy >= 0.55 ? "text-emerald-400" : "text-amber-400"} />
                    <Stat label="Precision" value={pct(s.precision)} />
                    <Stat label="Recall" value={pct(s.recall)} />
                    <Stat label="F1 Score" value={pct(s.f1_score)} cls="text-sky-400" />
                    <Stat label="Avg Confidence" value={pct(s.avg_confidence)} cls="text-sky-400" />
                    <Stat label="ECE" value={n2(s.ece)} cls={s.ece < 0.1 ? "text-emerald-400" : "text-amber-400"} />
                  </div>
                  {s.total_trades === 0 && (
                    <div className="text-[11px] text-zinc-500 italic">
                      No trades recorded yet — complete paper trades to generate AI optimisation insights.
                    </div>
                  )}
                </div>
              </div>
            )}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 2: Confidence Calibration
          ---------------------------------------------------------------- */}
          <SectionCard title="Confidence Calibration" icon={Target}>
            {calibrationQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (() => {
              const bands = calibrationQ.data?.bands ?? [];
              const threshold = calibrationQ.data?.recommended_threshold;
              const rationale = calibrationQ.data?.threshold_rationale;
              const expectedWr = calibrationQ.data?.threshold_expected_win_rate;
              return (
                <div className="space-y-3">
                  {threshold != null && (
                    <div className="rounded border border-sky-800 bg-sky-950/20 p-2 text-[11px]">
                      <span className="text-sky-400 font-semibold">Threshold Advisory: </span>
                      <span className="text-zinc-200">Minimum confidence {(threshold * 100).toFixed(0)}%</span>
                      {expectedWr != null && (
                        <span className="text-zinc-400 ml-2">→ Expected win rate: {(expectedWr * 100).toFixed(1)}%</span>
                      )}
                      {rationale && <div className="text-zinc-500 mt-1">{rationale}</div>}
                    </div>
                  )}
                  <MiniTable
                    headers={["Band", "Trades", "Win %", "Avg Return", "Avg Risk", "Pred Error"]}
                    rows={bands.map((b: any) => [
                      <span key="band" className="text-zinc-200">{b.band}</span>,
                      b.trades,
                      <span key="wr" className={b.win_rate >= 0.55 ? "text-emerald-400" : "text-red-400"}>{pct(b.win_rate)}</span>,
                      <span key="ret" className={b.avg_return_pct >= 0 ? "text-emerald-400" : "text-red-400"}>{n2(b.avg_return_pct)}%</span>,
                      n2(b.avg_risk),
                      <span key="err" className={b.prediction_error < 0.1 ? "text-emerald-400" : b.prediction_error < 0.2 ? "text-amber-400" : "text-red-400"}>
                        {n2(b.prediction_error)}
                      </span>,
                    ])}
                    emptyText="No confidence data yet."
                  />
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 3: Prediction Quality
          ---------------------------------------------------------------- */}
          <SectionCard title="Prediction Quality" icon={BarChart3}>
            {summaryQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (
              <div className="space-y-2">
                <div className="grid grid-cols-3 sm:grid-cols-6 gap-1.5">
                  <Stat label="Accuracy"    value={pct(s.accuracy)}   cls={s.accuracy >= 0.55 ? "text-emerald-400" : "text-amber-400"} />
                  <Stat label="Precision"   value={pct(s.precision)}  cls="text-zinc-200" />
                  <Stat label="Recall"      value={pct(s.recall)}     cls="text-zinc-200" />
                  <Stat label="F1 Score"    value={pct(s.f1_score)}   cls="text-sky-400" />
                  <Stat label="FPR"         value={pct(s.supporting_metrics?.false_positive_rate ?? null)} cls="text-amber-400" />
                  <Stat label="FNR"         value={pct(s.supporting_metrics?.false_negative_rate ?? null)} cls="text-amber-400" />
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                  <Stat label="Avg Confidence"   value={pct(s.avg_confidence)} cls="text-sky-400" />
                  <Stat label="Confidence Error" value={n2(s.confidence_error ?? null)} cls={+s.confidence_error < 0.1 ? "text-emerald-400" : "text-amber-400"} />
                  <Stat label="Calibration Score" value={pct(s.calibration_score)} cls={s.calibration_score >= 0.8 ? "text-emerald-400" : "text-amber-400"} />
                  <Stat label="Pred Stability"    value={pct(s.supporting_metrics?.prediction_stability ?? null)} cls="text-zinc-200" />
                </div>
              </div>
            )}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 4: False Signal Analysis
          ---------------------------------------------------------------- */}
          <SectionCard title="False Signal Analysis" icon={AlertTriangle}>
            {driftQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (() => {
              const fs = driftQ.data?.false_signal_analysis ?? {};
              const signals = fs.false_signals ?? [];
              const insights = fs.advisory_insights ?? [];
              return (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2 items-center text-[11px]">
                    <span className="text-zinc-400">False Signal Rate:</span>
                    <span className={cn("font-mono font-semibold",
                      (fs.false_signal_rate ?? 0) > 0.3 ? "text-red-400"
                      : (fs.false_signal_rate ?? 0) > 0.15 ? "text-amber-400" : "text-emerald-400")}>
                      {pct(fs.false_signal_rate ?? null)}
                    </span>
                    <span className="text-zinc-600">·</span>
                    <span className="text-zinc-400">{fs.total_trades ?? 0} total trades</span>
                  </div>
                  <MiniTable
                    headers={["Type", "Count", "% of Trades", "Avg Loss %"]}
                    rows={signals.filter((sig: any) => sig.count > 0).map((sig: any) => {
                      const typeClsMap: Record<string, string> = {
                        FALSE_BUY: "text-red-400", FALSE_SELL: "text-red-400",
                        HIGH_CONF_LOSS: "text-orange-400", LOW_CONF_WIN: "text-sky-400",
                        LATE: "text-amber-400", EARLY: "text-amber-400",
                      };
                      return [
                        <span key="t" className={typeClsMap[sig.signal_type] ?? "text-zinc-300"}>
                          {sig.signal_type.replace(/_/g, " ")}
                        </span>,
                        sig.count,
                        pct(sig.pct_of_total),
                        <span key="l" className="text-red-400">{n2(sig.avg_loss_pct)}%</span>,
                      ];
                    })}
                    emptyText="No false signals detected yet."
                  />
                  {insights.length > 0 && (
                    <div className="space-y-1">
                      {insights.map((ins: string, i: number) => (
                        <div key={i} className="flex items-start gap-2 text-[11px] text-amber-300 bg-amber-950/20 rounded p-2 border border-amber-900/40">
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-400" />
                          {ins}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 5: Model Drift
          ---------------------------------------------------------------- */}
          <SectionCard title="Model Drift Detection" icon={Activity}>
            {driftQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (() => {
              const metrics = driftQ.data?.metrics ?? [];
              const overall = driftQ.data?.overall_drift_severity ?? "—";
              const driftScore = driftQ.data?.drift_score ?? 0;
              return (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2 items-center text-[11px]">
                    <span className="text-zinc-400">Overall:</span>
                    <Badge variant="outline" className={cn("text-[10px]", SEVERITY_CLS[overall] ?? "")}>
                      {overall}
                    </Badge>
                    <span className="text-zinc-600">·</span>
                    <span className="text-zinc-400">Drift Score: </span>
                    <span className={cn("font-mono font-semibold",
                      driftScore > 0.4 ? "text-red-400" : driftScore > 0.2 ? "text-amber-400" : "text-emerald-400")}>
                      {n2(driftScore)}
                    </span>
                  </div>
                  {metrics.length > 0 ? (
                    <div className="space-y-1.5">
                      {metrics.map((m: any) => (
                        <div key={m.dimension}
                          className="flex flex-wrap items-center gap-2 rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-[11px]">
                          <span className="text-zinc-200 w-28 font-semibold shrink-0">{m.dimension}</span>
                          <Badge variant="outline" className={cn("text-[10px]", SEVERITY_CLS[m.severity] ?? "")}>
                            {m.severity}
                          </Badge>
                          <span className="text-zinc-500">
                            Base: <span className="text-zinc-300">{n2(m.baseline)}</span>
                            {" "}→ Recent: <span className={cn(m.drift > 0 ? "text-emerald-400" : m.drift < -0.05 ? "text-red-400" : "text-zinc-300")}>
                              {n2(m.recent)}
                            </span>
                            {" "}(Δ <span className={m.drift >= 0 ? "text-emerald-400" : "text-red-400"}>{m.drift > 0 ? "+" : ""}{n2(m.drift)}</span>)
                          </span>
                          <span className="ml-auto text-zinc-500 italic text-[10px]">{m.advisory}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-zinc-500 text-[11px]">Insufficient history for drift analysis — need more paper trades.</div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 6: Learning Progress
          ---------------------------------------------------------------- */}
          <SectionCard title="Learning Progress" icon={TrendingUp}>
            {historyQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (() => {
              const h = historyQ.data ?? {};
              const history = h.history ?? [];
              return (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide">Adaptive Trend</div>
                      <div className="flex items-center gap-1 text-sm font-mono">
                        <TrendIcon trend={h.adaptive_trend} />
                        <span className={cn(h.adaptive_trend === "IMPROVING" ? "text-emerald-400"
                          : h.adaptive_trend === "DECLINING" ? "text-red-400" : "text-zinc-300")}>
                          {h.adaptive_trend ?? "—"}
                        </span>
                      </div>
                    </div>
                    <Stat label="Learning Velocity" value={n2(h.learning_velocity)} cls={
                      h.learning_velocity > 0.1 ? "text-emerald-400"
                      : h.learning_velocity < -0.1 ? "text-red-400" : "text-zinc-300"
                    } />
                    <Stat label="Improvement Rate" value={pct(h.improvement_rate)} cls="text-emerald-400" />
                    <Stat label="Regression Rate" value={pct(h.regression_rate)} cls="text-amber-400" />
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    <Stat label="Consistency Trend" value={h.consistency_trend ?? "—"} />
                    <Stat label="Confidence Trend" value={h.confidence_trend ?? "—"} />
                  </div>
                  {history.length > 0 && (
                    <div>
                      <div className="text-[10px] text-zinc-500 uppercase tracking-wide mb-1">Period Breakdown</div>
                      <MiniTable
                        headers={["Period", "Win Rate", "Avg Confidence", "Trades"]}
                        rows={history.map((p: any) => [
                          p.period,
                          <span key="wr" className={p.win_rate >= 0.5 ? "text-emerald-400" : "text-red-400"}>{pct(p.win_rate)}</span>,
                          pct(p.avg_confidence),
                          p.trade_count,
                        ])}
                      />
                    </div>
                  )}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 7: Version Comparison (future-ready)
          ---------------------------------------------------------------- */}
          <SectionCard title="Version Comparison (Future-Ready)" icon={GitCompare}>
            {calibrationQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (() => {
              const vc = calibrationQ.data?.version_comparison ?? {};
              return (
                <div className="space-y-2">
                  <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3 text-[11px] text-zinc-400">
                    <div className="flex items-center gap-2 mb-1">
                      <FlaskConical className="h-3.5 w-3.5 text-zinc-500" />
                      <span className="text-zinc-300 font-semibold">Version comparison framework is ready but disabled.</span>
                    </div>
                    <p>{vc.note ?? "Enable by providing AI version metadata when future ML retraining integration is activated."}</p>
                    <div className="mt-2 grid grid-cols-3 gap-2 opacity-40">
                      {["Current AI", "Previous AI", "Experimental AI"].map((v) => (
                        <div key={v} className="rounded border border-zinc-700 p-2 text-center text-zinc-500 text-[10px]">
                          {v}<div className="text-[9px] mt-0.5">Not yet configured</div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2 text-[10px] text-zinc-600">
                      Metrics compared when versions are available: Accuracy Δ · Risk Δ · Win Rate Δ · Recommendation Δ
                    </div>
                  </div>
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 8: Recommendations
          ---------------------------------------------------------------- */}
          <SectionCard title="Optimisation Recommendations (Advisory Only — Never Auto-Applied)" icon={BookOpen}>
            {recsQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (() => {
              const recs = recsQ.data?.explanations ?? [];
              if (!recs.length) return (
                <div className="text-zinc-500 text-[11px]">No recommendations yet — complete paper trades first.</div>
              );
              return (
                <div className="space-y-2">
                  {recs.map((r: any, i: number) => (
                    <div key={i} className="rounded border border-zinc-800 bg-zinc-900/40 p-3 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <Badge variant="outline" className="text-[10px] text-zinc-300">
                          {r.category?.replace(/([A-Z])/g, " $1").trim()}
                        </Badge>
                        <span className="text-zinc-100 font-semibold">{r.recommendation}</span>
                        <Badge variant="outline" className={cn("text-[10px]", CONF_CLS[r.confidence] ?? "")}>
                          {r.confidence} confidence
                        </Badge>
                        <span className="ml-auto text-zinc-500 text-[10px] italic">advisory only</span>
                      </div>
                      <div className="text-zinc-400 text-[11px]">{r.reason}</div>
                      <div className="text-zinc-500 text-[11px]">Evidence: {r.historical_evidence}</div>
                      <div className="flex items-center gap-1 text-[11px]">
                        <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0" />
                        <span className="text-emerald-400">{r.expected_benefit}</span>
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </SectionCard>

          {/* ----------------------------------------------------------------
              Section 9: Historical Trend
          ---------------------------------------------------------------- */}
          <SectionCard title="Historical Trend" icon={Layers}>
            {historyQ.isLoading ? (
              <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-zinc-400" /></div>
            ) : (() => {
              const pq = historyQ.data?.prediction_quality ?? {};
              const periods = historyQ.data?.periods_analysed ?? 0;
              return (
                <div className="space-y-3">
                  <div className="grid grid-cols-3 gap-1.5">
                    <Stat label="Overall Accuracy" value={pct(pq.accuracy)} cls={pq.accuracy >= 0.55 ? "text-emerald-400" : "text-amber-400"} />
                    <Stat label="F1 Score" value={pct(pq.f1_score)} cls="text-sky-400" />
                    <Stat label="Avg Confidence" value={pct(pq.avg_confidence)} cls="text-sky-400" />
                  </div>
                  <div className="text-[11px] text-zinc-500">
                    {periods > 0
                      ? `Analysed over ${periods} time periods. Each period covers an equal share of all closed paper trades.`
                      : "Complete at least 5 paper trades to enable historical trend analysis."}
                  </div>
                  <div className="rounded border border-zinc-800 bg-zinc-900/30 p-3 text-[11px] text-zinc-500 space-y-1">
                    <div className="text-zinc-300 font-semibold mb-1">Future ML Retraining Hook</div>
                    <p>This framework is designed to plug into a future ML retraining pipeline without architectural changes:</p>
                    <ul className="list-disc pl-4 space-y-0.5 mt-1">
                      <li>Learning velocity and regression rate serve as retraining triggers.</li>
                      <li>Confidence calibration output feeds directly into threshold tuning.</li>
                      <li>Drift metrics signal when the model's distribution has shifted enough to warrant retraining.</li>
                      <li>Version comparison framework accepts new model metadata without code changes.</li>
                      <li>All retraining remains <span className="text-amber-400">advisory-only</span> and requires explicit operator approval.</li>
                    </ul>
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
