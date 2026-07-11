import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetLearningReview,
  getGetLearningReviewQueryKey,
  useRunLearningCycle,
  useApproveLearningAdjustment,
  useRejectLearningAdjustment,
  useRollbackModelVersion,
  useApproveHypothesis,
  useRejectHypothesis,
} from "@workspace/api-client-react";
import type {
  LearningReviewTrade,
  ProposedAdjustment,
  ModelVersion,
  CalibrationBand,
  Hypothesis,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  GraduationCap, RefreshCcw, PlayCircle, CheckCircle2, XCircle,
  Undo2, AlertTriangle, ChevronDown, ChevronRight, Scale, History,
  FlaskConical, TrendingDown, TrendingUp, Lightbulb,
} from "lucide-react";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, dp = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(dp);
}

function signed(n: number | null | undefined, dp = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(dp)}`;
}

function pnlColor(n: number | null | undefined): string {
  if (n === null || n === undefined) return "text-muted-foreground";
  return n >= 0 ? "text-emerald-400" : "text-red-400";
}

function shortDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString([], { day: "2-digit", month: "short" });
  } catch {
    return iso;
  }
}

const OUTCOME_COLORS: Record<string, string> = {
  Excellent: "text-emerald-300 border-emerald-500/40 bg-emerald-500/10",
  Good: "text-green-400 border-green-500/40 bg-green-500/10",
  Mediocre: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10",
  Poor: "text-orange-400 border-orange-500/40 bg-orange-500/10",
  Bad: "text-red-400 border-red-500/40 bg-red-500/10",
};

function scopeLabel(a: ProposedAdjustment): string {
  return `${a.scope_type.replace(/_/g, " ")} · ${a.scope_key}`;
}

// ── Calibration table ─────────────────────────────────────────────────────────

function CalibrationTable({ bands, score }: { bands: CalibrationBand[]; score: number | null | undefined }) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardHeader className="py-3 px-4 border-b border-border/50">
        <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center justify-between">
          <span className="flex items-center gap-2">
            <Scale className="h-3.5 w-3.5" />
            Confidence Calibration
          </span>
          <span className="text-foreground">
            Score: {score !== null && score !== undefined ? `${fmt(score, 0)}/100` : "not enough data"}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border/50 text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
              <th className="py-2 px-3">Confidence Band</th>
              <th className="py-2 px-3">Trades</th>
              <th className="py-2 px-3">Predicted Success</th>
              <th className="py-2 px-3">Actual Success</th>
              <th className="py-2 px-3">Gap</th>
              <th className="py-2 px-3">Conclusion</th>
            </tr>
          </thead>
          <tbody>
            {bands.map((b) => (
              <tr key={b.band} className="border-b border-border/30" data-testid={`row-calibration-${b.band}`}>
                <td className="py-2 px-3 text-xs font-mono font-bold">{b.band}</td>
                <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{b.trades}</td>
                <td className="py-2 px-3 text-xs font-mono">{fmt(b.predicted_success_rate, 1)}%</td>
                <td className="py-2 px-3 text-xs font-mono">
                  {b.actual_success_rate !== null && b.actual_success_rate !== undefined
                    ? `${fmt(b.actual_success_rate, 1)}%` : "—"}
                </td>
                <td className={`py-2 px-3 text-xs font-mono ${b.gap !== null && b.gap !== undefined && Math.abs(b.gap) > 10 ? "text-orange-400" : "text-muted-foreground"}`}>
                  {b.gap !== null && b.gap !== undefined ? signed(b.gap, 1) : "—"}
                </td>
                <td className="py-2 px-3 text-xs">{b.conclusion}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

// ── Trade evaluation row ──────────────────────────────────────────────────────

function TradeRow({ t }: { t: LearningReviewTrade }) {
  const [open, setOpen] = useState(false);
  const outcomeCls = OUTCOME_COLORS[t.outcome_class] ?? "text-muted-foreground border-border bg-muted/10";
  return (
    <>
      <tr
        className="border-b border-border/30 hover:bg-muted/10 cursor-pointer"
        onClick={() => setOpen(!open)}
        data-testid={`row-evaluation-${t.trade_id}`}
      >
        <td className="py-2 px-3 text-xs font-mono">
          <span className="flex items-center gap-1">
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {t.symbol}
          </span>
        </td>
        <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{shortDate(t.exit_time)}</td>
        <td className="py-2 px-3 text-xs font-mono">
          {t.predicted_confidence !== null && t.predicted_confidence !== undefined ? fmt(t.predicted_confidence, 0) : "—"}
        </td>
        <td className={`py-2 px-3 text-xs font-mono ${pnlColor(t.expected_return)}`}>
          {t.expected_return !== null && t.expected_return !== undefined ? `${signed(t.expected_return, 1)}%` : "—"}
        </td>
        <td className={`py-2 px-3 text-xs font-mono font-bold ${pnlColor(t.actual_return)}`}>
          {signed(t.actual_return, 1)}%
        </td>
        <td className={`py-2 px-3 text-xs font-mono ${pnlColor(t.prediction_error)}`}>
          {t.prediction_error !== null && t.prediction_error !== undefined ? signed(t.prediction_error, 1) : "—"}
        </td>
        <td className="py-2 px-3">
          <span className={`text-[10px] font-mono border rounded px-1.5 py-0.5 ${outcomeCls}`}>
            {t.outcome_class || "—"}
          </span>
        </td>
        <td className="py-2 px-3 text-xs font-mono text-muted-foreground">
          {t.learn_eligible ? "Yes" : <span className="text-orange-400">No</span>}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border/30 bg-muted/5">
          <td colSpan={8} className="py-3 px-6">
            <div className="grid md:grid-cols-3 gap-4 text-xs">
              <div>
                <div className="font-mono uppercase text-muted-foreground mb-1.5">Prediction vs Actual</div>
                <dl className="space-y-1 font-mono">
                  <div className="flex justify-between"><dt className="text-muted-foreground">Exit type</dt><dd>{t.exit_type}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Holding days</dt><dd>{fmt(t.actual_holding_days, 0)}{t.expected_holding_days ? ` (expected ${fmt(t.expected_holding_days, 0)})` : ""}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Best price reached (MFE)</dt><dd>{t.mfe !== null && t.mfe !== undefined ? `${signed(t.mfe, 1)}%` : "—"}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Worst drawdown (MAE)</dt><dd>{t.mae !== null && t.mae !== undefined ? `${signed(t.mae, 1)}%` : "—"}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Direction correct</dt><dd>{t.direction_correct ? "Yes" : "No"}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Stop hit / Target hit</dt><dd>{t.stop_hit ? "Stop" : t.target_hit ? "Target" : "Neither"}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Data source</dt><dd className={t.data_source === "yfinance" ? "" : "text-orange-400"}>{t.data_source || "unknown"}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Model version at entry</dt><dd>v{t.model_version}</dd></div>
                </dl>
              </div>
              <div>
                <div className="font-mono uppercase text-muted-foreground mb-1.5">
                  {(t.failure_causes?.length ?? 0) > 0 ? "Why it failed (evidence-based)" : "Why it worked"}
                </div>
                {(t.failure_causes?.length ?? 0) > 0 ? (
                  <ul className="space-y-1.5">
                    {t.failure_causes.map((c, i) => (
                      <li key={i} className="border border-red-500/20 bg-red-500/5 rounded px-2 py-1.5">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-red-300">{c.cause}</span>
                          <span className="text-[10px] font-mono text-muted-foreground">{c.severity} · {fmt(c.diagnosis_confidence, 0)}%</span>
                        </div>
                        <div className="text-muted-foreground mt-0.5">{c.evidence}</div>
                      </li>
                    ))}
                  </ul>
                ) : (t.success_factors?.length ?? 0) > 0 ? (
                  <ul className="space-y-1.5">
                    {t.success_factors.map((f, i) => (
                      <li key={i} className="border border-emerald-500/20 bg-emerald-500/5 rounded px-2 py-1.5">
                        <div className="font-bold text-emerald-300">{f.factor}</div>
                        <div className="text-muted-foreground mt-0.5">{f.evidence}</div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-muted-foreground font-mono">No clear evidence found — not guessing.</div>
                )}
              </div>
              <div>
                <div className="font-mono uppercase text-muted-foreground mb-1.5">Lesson</div>
                <p className="text-foreground/85 leading-relaxed">{t.lesson || "—"}</p>
                {!t.learn_eligible && (
                  <p className="text-orange-400 font-mono mt-2 flex items-start gap-1">
                    <AlertTriangle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
                    Excluded from learning{t.data_source !== "yfinance" ? " — not verified live data" : ""}.
                  </p>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LearningReview() {
  const queryClient = useQueryClient();
  const { data, isLoading, refetch, isFetching } = useGetLearningReview({
    query: { queryKey: getGetLearningReviewQueryKey() },
  });
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: getGetLearningReviewQueryKey() });

  const cycleMut = useRunLearningCycle({
    mutation: {
      onSuccess: (r) => {
        setActionMsg(
          `Learning cycle finished — ${r.eligible_trades} eligible trade(s), ${r.proposals_created} new proposal(s). Nothing was applied.`,
        );
        invalidate();
      },
      onError: (e) => setActionMsg(`Learning cycle failed: ${e instanceof Error ? e.message : String(e)}`),
    },
  });
  const approveMut = useApproveLearningAdjustment({
    mutation: {
      onSuccess: (r) => {
        setActionMsg(r.message);
        invalidate();
      },
      onError: (e) => setActionMsg(`Approve failed: ${e instanceof Error ? e.message : String(e)}`),
    },
  });
  const rejectMut = useRejectLearningAdjustment({
    mutation: {
      onSuccess: (r) => {
        setActionMsg(r.message);
        invalidate();
      },
      onError: (e) => setActionMsg(`Reject failed: ${e instanceof Error ? e.message : String(e)}`),
    },
  });
  const rollbackMut = useRollbackModelVersion({
    mutation: {
      onSuccess: (r) => {
        setActionMsg(r.message);
        invalidate();
      },
      onError: (e) => setActionMsg(`Rollback failed: ${e instanceof Error ? e.message : String(e)}`),
    },
  });
  const hypApproveMut = useApproveHypothesis({
    mutation: {
      onSuccess: (r) => {
        setActionMsg(r.message);
        invalidate();
      },
      onError: (e) => setActionMsg(`Hypothesis approve failed: ${e instanceof Error ? e.message : String(e)}`),
    },
  });
  const hypRejectMut = useRejectHypothesis({
    mutation: {
      onSuccess: (r) => {
        setActionMsg(r.message);
        invalidate();
      },
      onError: (e) => setActionMsg(`Hypothesis reject failed: ${e instanceof Error ? e.message : String(e)}`),
    },
  });

  const busy = cycleMut.isPending || approveMut.isPending || rejectMut.isPending
    || rollbackMut.isPending || hypApproveMut.isPending || hypRejectMut.isPending;

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">EVALUATING PAST TRADES...</p>
        </div>
      </div>
    );
  }

  const trades = data?.trades ?? [];
  const proposals = (data?.proposed_adjustments ?? []) as ProposedAdjustment[];
  const pending = proposals.filter((p) => p.status === "PROPOSED");
  const decided = proposals.filter((p) => p.status !== "PROPOSED");
  const versions = (data?.model_versions ?? []) as ModelVersion[];
  const hypotheses = (data?.hypotheses ?? []) as Hypothesis[];
  const pendingHyps = hypotheses.filter((h) => h.status === "PROPOSED");
  const decidedHyps = hypotheses.filter((h) => h.status !== "PROPOSED");
  const weights = data?.active_weights ?? {};
  const weightEntries = Object.entries(weights).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));

  return (
    <div className="p-6 space-y-5 overflow-y-auto h-full max-w-7xl mx-auto" data-testid="page-learning-review">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold font-mono flex items-center gap-2">
            <GraduationCap className="h-6 w-6 text-primary" />
            LEARNING REVIEW
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            The system grades its own predictions after every closed paper trade.
            Analysis mode — nothing changes without your approval. Paper trading only.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => cycleMut.mutate()}
            disabled={busy}
            className="flex items-center gap-2 rounded-md border border-primary/50 bg-primary/10 text-primary px-3 py-1.5 text-sm font-mono hover:bg-primary/20 disabled:opacity-50"
            data-testid="button-run-learning-cycle"
          >
            <PlayCircle className={`h-4 w-4 ${cycleMut.isPending ? "animate-spin" : ""}`} />
            {cycleMut.isPending ? "ANALYSING..." : "RUN LEARNING CYCLE"}
          </button>
          <button
            onClick={() => refetch()}
            disabled={isFetching || busy}
            className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-mono hover:bg-accent disabled:opacity-50"
            data-testid="button-refresh-learning-review"
          >
            <RefreshCcw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            REFRESH
          </button>
        </div>
      </div>

      {actionMsg && (
        <div
          className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm font-mono"
          data-testid="text-action-message"
        >
          {actionMsg}
        </div>
      )}

      {(data?.warnings ?? []).map((w, i) => (
        <div key={i} className="flex items-center gap-2 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-400">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {w}
        </div>
      ))}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: "Trades Evaluated", value: String(data?.trades_evaluated ?? 0) },
          { label: "Learn-Eligible", value: String(data?.learn_eligible_trades ?? 0) },
          { label: "Predictions Right", value: String(data?.successful_predictions ?? 0), color: "text-emerald-400" },
          { label: "Predictions Wrong", value: String(data?.failed_predictions ?? 0), color: "text-red-400" },
          {
            label: "Avg Prediction Error",
            value: data?.avg_prediction_error !== null && data?.avg_prediction_error !== undefined
              ? `${signed(data.avg_prediction_error, 1)}%` : "—",
          },
          { label: "Active Model", value: `v${data?.active_model_version ?? 0}` },
        ].map((c) => (
          <Card key={c.label} className="bg-card/50 backdrop-blur border-border/50">
            <CardContent className="p-3">
              <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{c.label}</div>
              <div className={`text-lg font-bold font-mono mt-0.5 ${c.color ?? ""}`}>{c.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Proposed adjustments */}
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="py-3 px-4 border-b border-border/50">
          <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <FlaskConical className="h-3.5 w-3.5" />
            Proposed Adjustments — awaiting your decision ({pending.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {pending.length === 0 ? (
            <div className="py-6 text-center text-muted-foreground text-sm font-mono">
              No pending proposals. Run a learning cycle after more trades complete.
            </div>
          ) : (
            <div className="divide-y divide-border/30">
              {pending.map((p) => (
                <div key={p.id} className="px-4 py-3 flex flex-wrap items-center gap-3" data-testid={`row-proposal-${p.id}`}>
                  <div className="flex-1 min-w-[240px]">
                    <div className="flex items-center gap-2 font-mono text-sm">
                      {p.points >= 0
                        ? <TrendingUp className="h-4 w-4 text-emerald-400" />
                        : <TrendingDown className="h-4 w-4 text-red-400" />}
                      <span className="font-bold">{scopeLabel(p)}</span>
                      <span className={p.points >= 0 ? "text-emerald-400" : "text-red-400"}>
                        {signed(p.points, 1)} pts
                      </span>
                      <span className="text-muted-foreground text-xs">
                        · {p.sample_size} trades
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{p.reason}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => approveMut.mutate({ id: p.id })}
                      disabled={busy}
                      className="flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 px-3 py-1.5 text-xs font-mono hover:bg-emerald-500/20 disabled:opacity-50"
                      data-testid={`button-approve-${p.id}`}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      APPROVE
                    </button>
                    <button
                      onClick={() => rejectMut.mutate({ id: p.id })}
                      disabled={busy}
                      className="flex items-center gap-1.5 rounded-md border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-1.5 text-xs font-mono hover:bg-red-500/20 disabled:opacity-50"
                      data-testid={`button-reject-${p.id}`}
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      REJECT
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {decided.length > 0 && (
            <div className="border-t border-border/50 px-4 py-2">
              <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
                Previously decided
              </div>
              <div className="space-y-1">
                {decided.slice(0, 8).map((p) => (
                  <div key={p.id} className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
                    <span className={
                      p.status === "APPLIED" || p.status === "APPROVED"
                        ? "text-emerald-400" : "text-red-400"
                    }>
                      {p.status}
                    </span>
                    <span>{scopeLabel(p)}</span>
                    <span>{signed(p.points, 1)} pts</span>
                    {p.applied_version ? <span>→ v{p.applied_version}</span> : null}
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* v2.1 Hypotheses */}
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="py-3 px-4 border-b border-border/50">
          <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <Lightbulb className="h-3.5 w-3.5 text-yellow-400" />
            Hypotheses — patterns found by comparing wins vs losses ({pendingHyps.length} awaiting decision)
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {hypotheses.length === 0 ? (
            <div className="py-6 text-center text-muted-foreground text-sm font-mono">
              No hypotheses yet — the system needs at least 30 completed trades in a
              segment before it will claim a pattern.
            </div>
          ) : (
            <div className="divide-y divide-border/30">
              {pendingHyps.map((h) => (
                <div key={h.id} className="px-4 py-3" data-testid={`row-hypothesis-${h.id}`}>
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="flex-1 min-w-[260px]">
                      <div className="flex items-center gap-2 flex-wrap">
                        {h.direction === "reduce"
                          ? <TrendingDown className="h-4 w-4 text-red-400 flex-shrink-0" />
                          : <TrendingUp className="h-4 w-4 text-emerald-400 flex-shrink-0" />}
                        <span className="font-mono text-sm font-bold">{h.statement}</span>
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-[11px] font-mono text-muted-foreground flex-wrap">
                        <span className="text-primary">{fmt(h.confidence_pct, 0)}% statistical confidence</span>
                        <span>· {h.sample_size} trades in segment</span>
                        <span>· applied step capped at {signed(h.step_points, 1)} pts</span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1.5">{h.rationale}</p>
                      {h.evidence?.segment && h.evidence?.baseline ? (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          <span className="text-[10px] font-mono border border-red-500/30 text-red-300 rounded px-1.5 py-0.5">
                            segment: {signed((h.evidence.segment as Record<string, number>).expectancy, 2)}% avg
                            · {fmt((h.evidence.segment as Record<string, number>).win_rate, 0)}% wins
                            · {(h.evidence.segment as Record<string, number>).trades} trades
                          </span>
                          <span className="text-[10px] font-mono border border-border text-muted-foreground rounded px-1.5 py-0.5">
                            everything else: {signed((h.evidence.baseline as Record<string, number>).expectancy, 2)}% avg
                            · {fmt((h.evidence.baseline as Record<string, number>).win_rate, 0)}% wins
                            · {(h.evidence.baseline as Record<string, number>).trades} trades
                          </span>
                        </div>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => hypApproveMut.mutate({ id: h.id })}
                        disabled={busy}
                        className="flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 px-3 py-1.5 text-xs font-mono hover:bg-emerald-500/20 disabled:opacity-50"
                        data-testid={`button-hypothesis-approve-${h.id}`}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        APPROVE
                      </button>
                      <button
                        onClick={() => hypRejectMut.mutate({ id: h.id })}
                        disabled={busy}
                        className="flex items-center gap-1.5 rounded-md border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-1.5 text-xs font-mono hover:bg-red-500/20 disabled:opacity-50"
                        data-testid={`button-hypothesis-reject-${h.id}`}
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        REJECT
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {decidedHyps.length > 0 && (
            <div className="border-t border-border/50 px-4 py-2">
              <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
                Previously decided / tracked
              </div>
              <div className="space-y-1.5">
                {decidedHyps.slice(0, 8).map((h) => (
                  <div key={h.id} className="text-xs font-mono text-muted-foreground" data-testid={`row-hypothesis-decided-${h.id}`}>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={
                        h.status === "APPLIED" ? "text-emerald-400"
                          : h.status === "ROLLED_BACK" ? "text-orange-400"
                          : "text-red-400"
                      }>
                        {h.status.replace("_", " ")}
                      </span>
                      <span className="truncate">{h.statement}</span>
                      {h.applied_version ? <span>→ v{h.applied_version}</span> : null}
                    </div>
                    {h.effectiveness?.note ? (
                      <div className="text-[10px] text-muted-foreground/80 pl-1 mt-0.5">
                        {String(h.effectiveness.note)}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Calibration + model versions */}
      <div className="grid lg:grid-cols-2 gap-4">
        <CalibrationTable bands={(data?.calibration_bands ?? []) as CalibrationBand[]} score={data?.calibration_score} />

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="py-3 px-4 border-b border-border/50">
            <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <History className="h-3.5 w-3.5" />
              Model Versions (active: v{data?.active_model_version ?? 0})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {weightEntries.length > 0 && (
              <div className="px-4 py-2 border-b border-border/30">
                <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground mb-1">
                  Active weights (capped ±15 total)
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {weightEntries.map(([k, v]) => (
                    <span key={k} className={`text-[10px] font-mono border rounded px-1.5 py-0.5 ${v >= 0 ? "border-emerald-500/30 text-emerald-300" : "border-red-500/30 text-red-300"}`}>
                      {k.replace("|", " · ")} {signed(v, 1)}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {versions.length === 0 ? (
              <div className="py-6 text-center text-muted-foreground text-sm font-mono">
                No adjustments applied yet — model is at baseline (v0).
              </div>
            ) : (
              <div className="divide-y divide-border/30">
                {versions.map((v) => (
                  <div key={v.version} className="px-4 py-2 flex items-center gap-3" data-testid={`row-version-${v.version}`}>
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-xs">
                        <span className="font-bold">v{v.version}</span>
                        <span className={`ml-2 ${v.status === "ACTIVE" ? "text-emerald-400" : "text-muted-foreground"}`}>{v.status}</span>
                        <span className="ml-2 text-muted-foreground">{shortDate(v.created_at)}</span>
                      </div>
                      <p className="text-xs text-muted-foreground truncate">{v.reason}</p>
                    </div>
                    {v.status === "ACTIVE" && v.version > 0 && (
                      <button
                        onClick={() => rollbackMut.mutate({ version: v.version })}
                        disabled={busy}
                        className="flex items-center gap-1.5 rounded-md border border-orange-500/40 bg-orange-500/10 text-orange-300 px-2.5 py-1 text-xs font-mono hover:bg-orange-500/20 disabled:opacity-50"
                        data-testid={`button-rollback-${v.version}`}
                      >
                        <Undo2 className="h-3 w-3" />
                        ROLL BACK
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Common causes / success factors */}
      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="py-3 px-4 border-b border-border/50">
            <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <TrendingDown className="h-3.5 w-3.5 text-red-400" />
              Most Common Failure Causes
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {(data?.common_failure_causes ?? []).length === 0 ? (
              <div className="py-6 text-center text-muted-foreground text-sm font-mono">No failures analysed yet</div>
            ) : (
              <div className="divide-y divide-border/30">
                {(data?.common_failure_causes ?? []).map((c, i) => (
                  <div key={i} className="px-4 py-2">
                    <div className="flex items-center justify-between font-mono text-xs">
                      <span className="font-bold text-red-300">{c.cause}</span>
                      <span className="text-muted-foreground">{c.count}×</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{c.example}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="py-3 px-4 border-b border-border/50">
            <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
              Strongest Success Factors
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {(data?.strongest_success_factors ?? []).length === 0 ? (
              <div className="py-6 text-center text-muted-foreground text-sm font-mono">No winners analysed yet</div>
            ) : (
              <div className="divide-y divide-border/30">
                {(data?.strongest_success_factors ?? []).map((f, i) => (
                  <div key={i} className="px-4 py-2">
                    <div className="flex items-center justify-between font-mono text-xs">
                      <span className="font-bold text-emerald-300">{f.factor}</span>
                      <span className="text-muted-foreground">{f.count}×</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{f.example}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Trade-by-trade evaluations */}
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="py-3 px-4 border-b border-border/50">
          <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            Trade-by-Trade Report Card ({trades.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 overflow-x-auto">
          {trades.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground text-sm font-mono">
              No completed trades evaluated yet — evaluations appear automatically after each paper SELL.
            </div>
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border/50 text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
                  <th className="py-2 px-3">Stock</th>
                  <th className="py-2 px-3">Exited</th>
                  <th className="py-2 px-3">Confidence</th>
                  <th className="py-2 px-3">Expected</th>
                  <th className="py-2 px-3">Actual</th>
                  <th className="py-2 px-3">Error</th>
                  <th className="py-2 px-3">Outcome</th>
                  <th className="py-2 px-3">Learned From</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <TradeRow key={t.trade_id} t={t} />
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
