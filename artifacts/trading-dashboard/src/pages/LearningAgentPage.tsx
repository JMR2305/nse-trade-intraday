/**
 * LearningAgentPage.tsx — Phase 10D
 * Learning Agent — analyses completed sessions and recommendation outcomes.
 *
 * READ-ONLY · ADVISORY-ONLY
 * No model retraining. No parameter tuning. No automatic optimisation.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Brain, TrendingUp, TrendingDown, Activity, Shield,
  BarChart2, Target, Clock, Zap, AlertTriangle, CheckCircle2,
  Minus, ArrowUpRight, ArrowDownRight,
} from "lucide-react";

const REFETCH = 60_000;
const q = (path: string) => ({
  queryKey:  ["learning-agent", path],
  queryFn:   () => apiJson("learning-layer/" + path),
  refetchInterval: REFETCH,
  retry: 1,
  staleTime: 30_000,
});

function HealthBadge({ health }: { health: string }) {
  const map: Record<string, string> = {
    HEALTHY:      "bg-emerald-600 text-white",
    DEGRADED:     "bg-amber-500 text-white",
    NEEDS_REVIEW: "bg-red-600 text-white",
    UNKNOWN:      "bg-slate-500 text-white",
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${map[health] ?? "bg-slate-500 text-white"}`}>
      {health?.replace(/_/g, " ") ?? "UNKNOWN"}
    </span>
  );
}

function KpiCard({ label, value, unit = "", sub, color = "text-foreground" }: {
  label: string; value: any; unit?: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-card rounded-xl border border-border p-4 flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value == null ? "—" : `${value}${unit}`}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function SectionHeader({ icon: Icon, title }: { icon: any; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-teal-400" />
      <h2 className="font-semibold text-sm tracking-wide uppercase text-muted-foreground">{title}</h2>
    </div>
  );
}

function MetricRow({ label, value, format = "number" }: { label: string; value: any; format?: string }) {
  const disp =
    format === "pct"    ? `${value?.toFixed?.(1) ?? "—"}%`  :
    format === "score"  ? `${value?.toFixed?.(3) ?? "—"}`   :
    format === "mins"   ? `${value?.toFixed?.(1) ?? "—"} min` :
    value == null       ? "—" : String(value);
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-mono font-semibold">{disp}</span>
    </div>
  );
}

function PatternCard({ pattern }: { pattern: any }) {
  const catColor: Record<string, string> = {
    PRICE_ACTION: "border-violet-500/40 bg-violet-500/5",
    VOLATILITY:   "border-amber-500/40 bg-amber-500/5",
    TIME_BASED:   "border-blue-500/40 bg-blue-500/5",
    SECTOR:       "border-teal-500/40 bg-teal-500/5",
    RISK:         "border-red-500/40 bg-red-500/5",
    META:         "border-slate-500/40 bg-slate-500/5",
  };
  const conf = pattern.confidence ?? 0;
  return (
    <div className={`rounded-xl border p-4 ${catColor[pattern.category] ?? "border-border bg-card"}`}>
      <div className="flex items-start justify-between mb-2">
        <p className="font-semibold text-sm">{pattern.name}</p>
        <span className="text-xs text-muted-foreground font-mono">{(conf * 100).toFixed(0)}% conf</span>
      </div>
      <p className="text-xs text-muted-foreground mb-2">{pattern.description}</p>
      <p className="text-xs text-teal-400">Advisory: {pattern.advisory}</p>
      <div className="mt-2 flex items-center gap-2">
        <Badge variant="outline" className="text-xs">{pattern.category}</Badge>
        <span className="text-xs text-muted-foreground">{pattern.occurrences} occurrence{pattern.occurrences !== 1 ? "s" : ""}</span>
      </div>
    </div>
  );
}

export default function LearningAgentPage() {
  const snapQ = useQuery(q("learning/snapshot"));
  const snap: any = snapQ.data ?? {};
  const metrics  = snap.metrics  ?? {};
  const insights = snap.insights ?? {};
  const patterns = (snap.patterns ?? []).filter((p: any) => p.pattern_id !== "BASELINE_OBSERVATION");

  const isLoading = snapQ.isLoading;
  const isError   = snapQ.isError;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="w-6 h-6 text-violet-400" />
          <div>
            <h1 className="text-xl font-bold">Learning Agent</h1>
            <p className="text-sm text-muted-foreground">
              Analyses completed sessions · Advisory only · No model changes
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs border-violet-500/50 text-violet-400">READ-ONLY</Badge>
          <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-400">ADVISORY</Badge>
          {snap.learning_health && <HealthBadge health={snap.learning_health} />}
        </div>
      </div>

      {/* Safety banner */}
      <Alert className="border-violet-500/30 bg-violet-500/10">
        <Shield className="h-4 w-4 text-violet-400" />
        <AlertDescription className="text-xs text-violet-300">
          Auto model updates: {snap.auto_model_updates === false ? "DISABLED" : "—"} ·{" "}
          Auto strategy tuning: {snap.auto_strategy_tuning === false ? "DISABLED" : "—"} ·{" "}
          All improvements require operator review before adoption.
        </AlertDescription>
      </Alert>

      {isError && (
        <Alert className="border-red-500/30 bg-red-500/10">
          <AlertTriangle className="h-4 w-4 text-red-400" />
          <AlertDescription className="text-xs">Learning Agent unavailable. Check API server.</AlertDescription>
        </Alert>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
        <KpiCard label="Trades Analysed"    value={metrics.trades_analysed ?? "—"}     color="text-violet-400" />
        <KpiCard label="Win Rate"            value={metrics.strategy_win_rate != null ? metrics.strategy_win_rate.toFixed(1) : "—"} unit="%" />
        <KpiCard label="Rec Accuracy"        value={metrics.recommendation_accuracy != null ? metrics.recommendation_accuracy.toFixed(1) : "—"} unit="%" />
        <KpiCard label="Calibration Score"   value={metrics.confidence_calibration != null ? metrics.confidence_calibration.toFixed(3) : "—"} color={metrics.confidence_calibration >= 0.6 ? "text-emerald-400" : "text-amber-400"} />
        <KpiCard label="Avg Holding"         value={metrics.avg_holding_minutes != null ? metrics.avg_holding_minutes.toFixed(1) : "—"} unit=" min" />
        <KpiCard label="Avg R:R"             value={metrics.avg_reward_risk != null ? metrics.avg_reward_risk.toFixed(2) : "—"} color={metrics.avg_reward_risk >= 1.5 ? "text-emerald-400" : "text-amber-400"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Metrics detail */}
        <div className="bg-card rounded-xl border border-border p-5">
          <SectionHeader icon={BarChart2} title="Learning Metrics" />
          <MetricRow label="Recommendation Accuracy"    value={metrics.recommendation_accuracy}        format="pct" />
          <MetricRow label="Strategy Win Rate"           value={metrics.strategy_win_rate}              format="pct" />
          <MetricRow label="Confidence Calibration"      value={metrics.confidence_calibration}         format="score" />
          <MetricRow label="Avg Holding Time"            value={metrics.avg_holding_minutes}            format="mins" />
          <MetricRow label="Avg Reward/Risk"             value={metrics.avg_reward_risk}                format="score" />
          <MetricRow label="Risk Prediction Accuracy"    value={metrics.risk_prediction_accuracy}       format="pct" />
          <MetricRow label="Exec Validation Accuracy"    value={metrics.execution_validation_accuracy}  format="pct" />
          <MetricRow label="Learning Latency"            value={snap.learning_latency_ms != null ? `${snap.learning_latency_ms.toFixed(0)} ms` : "—"} />
        </div>

        {/* Insights */}
        <div className="bg-card rounded-xl border border-border p-5">
          <SectionHeader icon={Zap} title="Session Insights" />
          <div className="space-y-3 text-sm">
            <div className="flex justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Best Strategy</span>
              <span className="font-semibold text-emerald-400">{insights.best_strategy_today ?? "—"}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Worst Strategy</span>
              <span className="font-semibold text-red-400">{insights.worst_strategy_today ?? "—"}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Top Sector</span>
              <span className="font-semibold text-teal-400">{insights.most_profitable_sector ?? "—"}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Weakest Sector</span>
              <span className="font-semibold text-amber-400">{insights.weakest_sector ?? "—"}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-border/50">
              <span className="text-muted-foreground">Most Reliable Rec</span>
              <span className="font-semibold">{insights.most_reliable_rec_type ?? "—"}</span>
            </div>
          </div>

          {(insights.common_rejection_reasons ?? []).length > 0 && (
            <div className="mt-4">
              <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase">Top Rejections</p>
              {(insights.common_rejection_reasons ?? []).slice(0, 3).map((r: any, i: number) => (
                <div key={i} className="flex justify-between text-xs py-1">
                  <span className="text-muted-foreground">{r.reason}</span>
                  <span className="font-mono text-amber-400">{r.count}×</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Sector performance */}
        <div className="bg-card rounded-xl border border-border p-5">
          <SectionHeader icon={TrendingUp} title="Sector Performance" />
          {Object.keys(metrics.sector_performance ?? {}).length === 0 ? (
            <p className="text-sm text-muted-foreground">No sector data yet.</p>
          ) : (
            <div className="space-y-2">
              {Object.entries(metrics.sector_performance ?? {}).map(([sec, d]: [string, any]) => (
                <div key={sec} className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
                  <span className="text-sm font-medium">{sec}</span>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-muted-foreground">{d.count} trades</span>
                    <span className={`text-sm font-mono font-semibold ${d.avg_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {d.avg_pnl_pct >= 0 ? "+" : ""}{d.avg_pnl_pct?.toFixed(2)}%
                    </span>
                    <span className="text-xs text-muted-foreground">{d.win_rate?.toFixed(0)}% WR</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Patterns */}
      <div>
        <SectionHeader icon={Activity} title={`Pattern Observations (${patterns.length})`} />
        {patterns.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recurring patterns detected — continue monitoring.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {patterns.map((p: any) => <PatternCard key={p.pattern_id} pattern={p} />)}
          </div>
        )}
      </div>

      {/* Recurring patterns text */}
      {(insights.recurring_patterns ?? []).length > 0 && (
        <div className="bg-card rounded-xl border border-border p-5">
          <SectionHeader icon={Target} title="Session Observations" />
          <ul className="space-y-2">
            {(insights.recurring_patterns ?? []).map((p: string, i: number) => (
              <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                <span className="mt-1 w-1.5 h-1.5 rounded-full bg-teal-400 flex-shrink-0" />
                {p}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-muted-foreground text-right">
        Updated {snap.generated_at ?? "—"} · READ-ONLY · ADVISORY-ONLY · No automated changes
      </p>
    </div>
  );
}
