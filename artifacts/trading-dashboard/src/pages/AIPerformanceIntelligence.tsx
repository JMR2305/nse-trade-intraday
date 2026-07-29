/**
 * AIPerformanceIntelligence.tsx — Phase 5D.4 AI Performance Intelligence Dashboard
 * READ-ONLY analytics. Never modifies any trading state.
 * PAPER TRADING / ADVISORY ONLY.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart, Line, BarChart, Bar, ScatterChart, Scatter,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell, ReferenceLine, Legend,
} from "recharts";
import {
  Brain, Activity, Target, Gauge, TrendingUp, TrendingDown,
  Minus, RefreshCw, AlertTriangle, CheckCircle2, XCircle,
  AlertCircle, Info, BarChart3, Layers, Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────
interface HealthScore {
  total_score: number;
  label: string;
  components: Record<string, number>;
  weights: Record<string, number>;
}

interface PredMetrics {
  tp: number; fp: number; tn: number; fn: number;
  precision: number; recall: number; accuracy: number;
  false_positive_rate: number; false_negative_rate: number;
  true_positive_rate: number; true_negative_rate: number;
  f1_score: number; mcc: number; balanced_accuracy: number;
}

interface SummaryResponse {
  status: string;
  total_signals: number;
  successful_signals: number;
  failed_signals: number;
  signal_success_rate: number;
  avg_confidence: number;
  high_confidence_pct: number;
  health_score: HealthScore;
  prediction: PredMetrics;
  calibration_ece: number;
  calibration_reliability: number;
  trend_direction: string;
  accuracy_delta: number;
  recent_accuracy: number;
  confidence_distribution: {
    buckets: Array<{ bucket: string; count: number; winners: number; win_rate: number; avg_pnl: number; net_pnl: number; avg_confidence: number }>;
    avg_confidence: number;
    median_confidence: number;
    high_confidence_pct: number;
  };
}

interface CalibrationResponse {
  status: string;
  ece: number;
  reliability_score: number;
  confidence_bias: number;
  overconfidence_score: number;
  underconfidence_score: number;
  calibration_curve: Array<{ bucket: string; predicted_confidence: number; actual_success_rate: number; sample_count: number; calibration_error: number }>;
}

interface LearningResponse {
  status: string;
  daily: Array<{ period: string; count: number; wins: number; accuracy: number; net_pnl: number }>;
  weekly: Array<{ period: string; accuracy: number; count: number }>;
  monthly: Array<{ period: string; accuracy: number; count: number }>;
  rolling_30d: Array<{ date: string; accuracy: number; count: number }>;
  trend_direction: string;
  recent_accuracy: number;
  prior_accuracy: number;
  accuracy_delta: number;
}

interface ConfidenceResponse {
  status: string;
  distribution: SummaryResponse["confidence_distribution"];
  vs_regime: Array<{ regime: string; count: number; win_rate: number; avg_confidence: number; net_pnl: number }>;
  vs_sector: Array<{ sector: string; count: number; win_rate: number; avg_confidence: number; net_pnl: number }>;
}

interface RecResponse {
  status: string;
  total_signals: number;
  recommendation_success_pct: number;
  recommendation_failure_pct: number;
  avg_profit_per_recommendation: number;
  avg_loss_per_recommendation: number;
  accepted_win_rate: number;
  rejected_win_rate: number;
  per_recommendation: Array<{ recommendation: string; count: number; wins: number; win_rate: number; net_pnl: number; avg_pnl: number; category: string }>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const fmt = (v: number, d = 2) => (v ?? 0).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPct = (v: number) => `${fmt(v, 1)}%`;
const fmtRs  = (v: number) => `₹${fmt(v)}`;
const PALETTE = ["#0ea5e9","#10b981","#f59e0b","#8b5cf6","#ec4899","#f97316","#14b8a6"];

function trendIcon(dir: string) {
  if (dir === "Improving") return <TrendingUp  className="h-4 w-4 text-emerald-400" />;
  if (dir === "Declining") return <TrendingDown className="h-4 w-4 text-red-400" />;
  return <Minus className="h-4 w-4 text-muted-foreground" />;
}

function healthColor(score: number) {
  if (score >= 90) return "text-emerald-400";
  if (score >= 75) return "text-sky-400";
  if (score >= 60) return "text-amber-400";
  if (score >= 40) return "text-orange-400";
  return "text-red-400";
}

function healthRingColor(score: number) {
  if (score >= 90) return "#10b981";
  if (score >= 75) return "#0ea5e9";
  if (score >= 60) return "#f59e0b";
  if (score >= 40) return "#f97316";
  return "#f43f5e";
}

function KpiCard({ label, value, sub, icon: Icon, color = "text-foreground" }: {
  label: string; value: string; sub?: string; icon: React.ElementType; color?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Icon className="h-3.5 w-3.5" />{label}
      </div>
      <p className={cn("text-xl font-bold leading-none", color)}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function ChartCard({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-5", className)}>
      <h3 className="text-sm font-semibold mb-4">{title}</h3>
      {children}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">{label}</div>;
}

function DisabledBanner({ flag }: { flag?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-4 text-amber-400">
      <AlertTriangle className="h-5 w-5 shrink-0" />
      <div>
        <p className="font-semibold">AI Performance Intelligence is disabled</p>
        <p className="text-sm mt-0.5">Set <code className="bg-amber-500/20 px-1 rounded">{flag ?? "AI_PERFORMANCE_ENABLED"}=true</code> to enable analytics.</p>
      </div>
    </div>
  );
}

// ── Circular health score gauge ───────────────────────────────────────────────
function HealthGauge({ score, label }: { score: number; label: string }) {
  const r    = 44;
  const circ = 2 * Math.PI * r;
  const fill = ((score / 100) * circ);
  const color = healthRingColor(score);
  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="120" height="120" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={r} fill="none" stroke="hsl(var(--border))" strokeWidth="10" />
        <circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="10"
          strokeDasharray={`${fill} ${circ - fill}`}
          strokeLinecap="round"
          transform="rotate(-90 60 60)" />
        <text x="60" y="56" textAnchor="middle" fill={color} fontSize="22" fontWeight="bold">{Math.round(score)}</text>
        <text x="60" y="72" textAnchor="middle" fill="hsl(var(--muted-foreground))" fontSize="10">/100</text>
      </svg>
      <span className={cn("text-sm font-bold", healthColor(score))}>{label}</span>
    </div>
  );
}

// ── Confusion matrix ──────────────────────────────────────────────────────────
function ConfusionMatrix({ tp, fp, tn, fn }: { tp: number; fp: number; tn: number; fn: number }) {
  const total = tp + fp + tn + fn;
  const cell = (v: number, cls: string) => (
    <div className={cn("flex flex-col items-center justify-center rounded-lg p-3", cls)}>
      <span className="text-2xl font-bold">{v}</span>
      <span className="text-xs mt-0.5 opacity-75">{total > 0 ? `${(v / total * 100).toFixed(1)}%` : "0%"}</span>
    </div>
  );
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 text-center text-xs text-muted-foreground">
        <div />
        <div className="grid grid-cols-2 gap-2">
          <div>Predicted +</div><div>Predicted −</div>
        </div>
      </div>
      <div className="grid grid-cols-[auto_1fr] gap-2">
        <div className="flex flex-col justify-center gap-2 text-xs text-muted-foreground [writing-mode:vertical-lr] rotate-180 text-center">
          <span>Actual +</span><span>Actual −</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {cell(tp, "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400")}
          {cell(fn, "bg-amber-500/10 border border-amber-500/20 text-amber-400")}
          {cell(fp, "bg-red-500/10 border border-red-500/20 text-red-400")}
          {cell(tn, "bg-sky-500/10 border border-sky-500/20 text-sky-400")}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-center text-xs text-muted-foreground">
        <div /><div className="grid grid-cols-2 gap-2 text-xs">
          <div className="text-emerald-400">TP</div><div className="text-amber-400">FN</div>
          <div className="text-red-400">FP</div><div className="text-sky-400">TN</div>
        </div>
      </div>
    </div>
  );
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
type Tab = "overview" | "predictions" | "calibration" | "confidence" | "learning" | "recommendations";

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AIPerformanceIntelligence() {
  const [tab, setTab] = useState<Tab>("overview");

  const { data: summary, isLoading, refetch } = useQuery<SummaryResponse>({
    queryKey: ["ai-summary"],
    queryFn: () => apiJson("ai/summary"),
    refetchInterval: 90_000,
  });
  const { data: calibration } = useQuery<CalibrationResponse>({
    queryKey: ["ai-calibration"],
    queryFn: () => apiJson("ai/calibration"),
    refetchInterval: 90_000,
  });
  const { data: learning } = useQuery<LearningResponse>({
    queryKey: ["ai-learning"],
    queryFn: () => apiJson("ai/learning"),
    refetchInterval: 90_000,
  });
  const { data: confidence } = useQuery<ConfidenceResponse>({
    queryKey: ["ai-confidence"],
    queryFn: () => apiJson("ai/confidence"),
    refetchInterval: 90_000,
  });
  const { data: recs } = useQuery<RecResponse>({
    queryKey: ["ai-recommendations"],
    queryFn: () => apiJson("ai/recommendations"),
    refetchInterval: 90_000,
  });

  const disabled = summary?.status === "DISABLED";
  const h        = summary?.health_score;
  const p        = summary?.prediction;

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview",        label: "Overview" },
    { id: "predictions",     label: "Predictions" },
    { id: "calibration",     label: "Calibration" },
    { id: "confidence",      label: "Confidence" },
    { id: "learning",        label: "Learning" },
    { id: "recommendations", label: "Recommendations" },
  ];

  // Chart data
  const buckets    = summary?.confidence_distribution?.buckets ?? [];
  const bucketBar  = buckets.filter(b => b.count > 0).map(b => ({ bucket: b.bucket, win_rate: b.win_rate, avg_pnl: b.avg_pnl, count: b.count }));
  const calibCurve = (calibration?.calibration_curve ?? []).filter(p => p.sample_count > 0);
  const calibChart = calibCurve.map(p => ({ bucket: p.bucket, predicted: +(p.predicted_confidence * 100).toFixed(1), actual: +(p.actual_success_rate * 100).toFixed(1) }));
  const rollingData = (learning?.rolling_30d ?? []).slice(-30);
  const dailyData   = (learning?.daily ?? []).slice(-20).map(d => ({ date: d.period.slice(5), accuracy: d.accuracy, pnl: d.net_pnl }));
  const monthlyData = (learning?.monthly ?? []).map(m => ({ month: m.period.slice(0, 7), accuracy: m.accuracy }));

  const componentOrder = ["prediction_accuracy","calibration_quality","consistency","execution_outcome","risk_awareness","recommendation_quality"];
  const componentLabels: Record<string, string> = {
    prediction_accuracy: "Prediction Accuracy",
    calibration_quality: "Calibration Quality",
    consistency:         "Consistency",
    execution_outcome:   "Execution Outcome",
    risk_awareness:      "Risk Awareness",
    recommendation_quality: "Recommendation Quality",
  };
  const healthBar = componentOrder.map((k, i) => ({
    name:  componentLabels[k],
    score: h?.components[k] ?? 0,
    weight: ((h?.weights ?? {})[k] ?? 0) * 100,
    fill: PALETTE[i % PALETTE.length],
  }));

  const trendDir = learning?.trend_direction ?? summary?.trend_direction ?? "Stable";

  return (
    <div className="p-6 space-y-6 max-w-[1600px]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Brain className="h-6 w-6 text-violet-400" />
            AI Performance Intelligence
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Read-only · Paper trading only · Advisory only
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground bg-card border border-border px-3 py-1.5 rounded-lg">PAPER / ADVISORY ONLY</span>
          <button onClick={() => refetch()} disabled={isLoading}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg px-3 py-1.5 transition-colors">
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {disabled && <DisabledBanner flag={(summary as any)?.feature_flag} />}

      {!disabled && (
        <>
          {/* Top row: health gauge + key KPIs */}
          <div className="grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-4">
            {/* Health gauge card */}
            <div className="rounded-xl border border-border bg-card p-6 flex flex-col items-center justify-center gap-2 min-w-[180px]">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">AI Health Score</p>
              <HealthGauge score={h?.total_score ?? 0} label={h?.label ?? "—"} />
            </div>

            {/* KPI grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
              <KpiCard label="Prediction Accuracy" icon={Target}
                value={`${fmt(summary?.prediction?.accuracy != null ? summary.prediction.accuracy * 100 : 0, 1)}%`}
                sub={`Balanced: ${fmt(summary?.prediction?.balanced_accuracy != null ? summary.prediction.balanced_accuracy * 100 : 0, 1)}%`}
                color="text-sky-400" />
              <KpiCard label="Avg Confidence" icon={Gauge}
                value={`${fmt((summary?.avg_confidence ?? 0) * 100, 1)}%`}
                sub={`Median: ${fmt((summary?.confidence_distribution?.median_confidence ?? 0) * 100, 1)}%`}
                color="text-violet-400" />
              <KpiCard label="Calibration ECE" icon={Activity}
                value={fmt(summary?.calibration_ece ?? 0, 4)}
                sub={`Reliability: ${fmt(summary?.calibration_reliability ?? 0, 1)}/100`}
                color={(summary?.calibration_ece ?? 0) < 0.10 ? "text-emerald-400" : "text-amber-400"} />
              <KpiCard label="Precision" icon={BarChart3}
                value={`${fmt((p?.precision ?? 0) * 100, 1)}%`}
                sub={`Recall: ${fmt((p?.recall ?? 0) * 100, 1)}%`}
                color="text-teal-400" />
              <KpiCard label="AI Trend" icon={trendDir === "Improving" ? TrendingUp : trendDir === "Declining" ? TrendingDown : Minus}
                value={trendDir}
                sub={`Δ ${summary?.accuracy_delta != null && summary.accuracy_delta >= 0 ? "+" : ""}${fmt(summary?.accuracy_delta ?? 0, 1)}%`}
                color={trendDir === "Improving" ? "text-emerald-400" : trendDir === "Declining" ? "text-red-400" : "text-muted-foreground"} />
            </div>
          </div>

          {/* Signal stats row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "Total Signals",      value: summary?.total_signals ?? 0,      color: "" },
              { label: "Successful Signals", value: summary?.successful_signals ?? 0, color: "text-emerald-400" },
              { label: "Failed Signals",     value: summary?.failed_signals ?? 0,     color: "text-red-400" },
              { label: "Success Rate",       value: `${fmt(summary?.signal_success_rate ?? 0, 1)}%`, color: (summary?.signal_success_rate ?? 0) >= 50 ? "text-emerald-400" : "text-red-400" },
            ].map(({ label, value, color }) => (
              <div key={label} className="rounded-xl border border-border bg-card px-4 py-3">
                <p className="text-xs text-muted-foreground mb-1">{label}</p>
                <p className={cn("text-lg font-bold tabular-nums", color)}>{value}</p>
              </div>
            ))}
          </div>

          {/* Tabs */}
          <div className="flex gap-1 border-b border-border">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={cn("px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
                  tab === t.id
                    ? "border-violet-400 text-violet-400"
                    : "border-transparent text-muted-foreground hover:text-foreground")}>
                {t.label}
              </button>
            ))}
          </div>

          {/* ── Overview ── */}
          {tab === "overview" && (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <ChartCard title="AI Health Score Components">
                {healthBar.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={healthBar} layout="vertical" margin={{ top: 0, right: 10, left: 120, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
                      <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={120} />
                      <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                        formatter={(v: number) => [`${fmt(v, 1)} / 100`, "Score"]} />
                      <Bar dataKey="score" radius={[0, 3, 3, 0]}>
                        {healthBar.map((b, i) => <Cell key={i} fill={b.fill} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState label="No data" />}
              </ChartCard>

              <ChartCard title="Confidence Bucket Win Rate">
                {bucketBar.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={bucketBar} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${v}%`} width={36} />
                      <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                        formatter={(v: number) => [`${fmt(v, 1)}%`, "Win Rate"]} />
                      <Bar dataKey="win_rate" radius={[3, 3, 0, 0]}>
                        {bucketBar.map((b, i) => <Cell key={i} fill={b.win_rate >= 50 ? "#10b981" : "#f43f5e"} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState label="No confidence data" />}
              </ChartCard>

              <ChartCard title="Calibration Curve (Predicted vs Actual)">
                {calibChart.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={calibChart} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="bucket" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${v}%`} width={36} />
                      <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                      <Legend />
                      <Bar dataKey="predicted" name="Predicted %" fill="#8b5cf6" radius={[3, 3, 0, 0]} opacity={0.8} />
                      <Bar dataKey="actual"    name="Actual %"    fill="#10b981" radius={[3, 3, 0, 0]} opacity={0.8} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState label="Calibration data requires completed trades" />}
              </ChartCard>

              <ChartCard title="Rolling 30-day Accuracy">
                {rollingData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={rollingData} margin={{ top: 4, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="date" tick={{ fontSize: 8, fill: "hsl(var(--muted-foreground))" }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${v}%`} width={36} />
                      <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                        formatter={(v: number) => [`${fmt(v, 1)}%`, "Accuracy"]} />
                      <ReferenceLine y={50} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4" />
                      <Line type="monotone" dataKey="accuracy" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : <EmptyState label="Rolling accuracy needs multiple trading days" />}
              </ChartCard>
            </div>
          )}

          {/* ── Predictions ── */}
          {tab === "predictions" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Confusion Matrix">
                  {p && (p.tp + p.fp + p.tn + p.fn > 0) ? (
                    <ConfusionMatrix tp={p.tp} fp={p.fp} tn={p.tn} fn={p.fn} />
                  ) : <EmptyState label="No classification data yet" />}
                </ChartCard>

                <ChartCard title="Classification Metrics">
                  {p ? (
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        ["Precision",         p.precision * 100,         "%"],
                        ["Recall (TPR)",      p.true_positive_rate * 100,"%"],
                        ["Accuracy",          p.accuracy * 100,           "%"],
                        ["Balanced Accuracy", p.balanced_accuracy * 100, "%"],
                        ["F1 Score",          p.f1_score,                 ""],
                        ["MCC",               p.mcc,                      ""],
                        ["False Positive Rate",p.false_positive_rate * 100,"%"],
                        ["False Negative Rate",p.false_negative_rate * 100,"%"],
                        ["Specificity (TNR)", p.true_negative_rate * 100, "%"],
                      ].map(([label, value, unit]) => (
                        <div key={label as string} className="rounded-lg border border-border bg-muted/20 px-3 py-2">
                          <p className="text-xs text-muted-foreground">{label}</p>
                          <p className="text-base font-bold tabular-nums">
                            {fmt(value as number, 1)}{unit}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : <EmptyState label="No prediction data" />}
                </ChartCard>
              </div>

              <div className="rounded-xl border border-border bg-card p-4 text-xs text-muted-foreground">
                <p className="font-semibold mb-1">Classification methodology</p>
                <p>Positive class (predicted win) = signal confidence ≥ 60%. Negative class = confidence &lt; 60%.
                   TP = high confidence + winner · FP = high confidence + loser · TN = low confidence + loser · FN = low confidence + winner.
                   TN/FN are observable because lower-confidence signals that still executed provide the negative class sample.</p>
              </div>
            </div>
          )}

          {/* ── Calibration ── */}
          {tab === "calibration" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                {[
                  { label: "ECE",               value: fmt(calibration?.ece ?? 0, 4),          color: (calibration?.ece ?? 0) < 0.10 ? "text-emerald-400" : "text-amber-400", sub: "lower = better" },
                  { label: "Reliability Score", value: `${fmt(calibration?.reliability_score ?? 0, 1)}/100`, color: "text-sky-400", sub: "(1 – ECE) × 100" },
                  { label: "Confidence Bias",   value: fmt(calibration?.confidence_bias ?? 0, 4), color: (calibration?.confidence_bias ?? 0) > 0 ? "text-amber-400" : "text-sky-400", sub: (calibration?.confidence_bias ?? 0) > 0 ? "overconfident" : "underconfident" },
                  { label: "Overconfidence",    value: `${fmt(calibration?.overconfidence_score ?? 0, 1)}%`,  color: "text-orange-400", sub: "buckets over-predicting" },
                  { label: "Underconfidence",   value: `${fmt(calibration?.underconfidence_score ?? 0, 1)}%`, color: "text-sky-400",    sub: "buckets under-predicting" },
                ].map(({ label, value, color, sub }) => (
                  <div key={label} className="rounded-xl border border-border bg-card p-4">
                    <p className="text-xs text-muted-foreground mb-1">{label}</p>
                    <p className={cn("text-lg font-bold", color)}>{value}</p>
                    {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
                  </div>
                ))}
              </div>

              <ChartCard title="Calibration Curve — Predicted vs Actual Win Rate per Confidence Bucket">
                {calibChart.length > 0 ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={calibChart} margin={{ top: 4, right: 20, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${v}%`} width={36} />
                      <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                      <Legend />
                      <Bar dataKey="predicted" name="Predicted Confidence %" fill="#8b5cf6" opacity={0.85} radius={[3, 3, 0, 0]} />
                      <Bar dataKey="actual"    name="Actual Win Rate %"       fill="#10b981" opacity={0.85} radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState label="Calibration data requires completed trades across multiple confidence buckets" />}
              </ChartCard>

              {calibration?.calibration_curve && calibration.calibration_curve.length > 0 && (
                <div className="rounded-xl border border-border bg-card p-5">
                  <h3 className="text-sm font-semibold mb-3">Calibration Detail Table</h3>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        {["Bucket","Samples","Predicted %","Actual Win %","Error","Status"].map(h => (
                          <th key={h} className="text-right pb-2 px-2 first:text-left">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {calibration.calibration_curve.filter(r => r.sample_count > 0).map(r => {
                        const err = r.calibration_error;
                        return (
                          <tr key={r.bucket} className="border-b border-border/40">
                            <td className="py-2 px-2 font-medium">{r.bucket}</td>
                            <td className="py-2 px-2 text-right tabular-nums">{r.sample_count}</td>
                            <td className="py-2 px-2 text-right tabular-nums">{fmt(r.predicted_confidence * 100, 1)}%</td>
                            <td className="py-2 px-2 text-right tabular-nums">{fmt(r.actual_success_rate * 100, 1)}%</td>
                            <td className={cn("py-2 px-2 text-right tabular-nums", err < 0.05 ? "text-emerald-400" : err < 0.15 ? "text-amber-400" : "text-red-400")}>{fmt(err, 4)}</td>
                            <td className="py-2 px-2 text-right text-xs">{err < 0.05 ? "✓ Well-calibrated" : err < 0.15 ? "~ Acceptable" : "✗ Poorly calibrated"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* ── Confidence ── */}
          {tab === "confidence" && (
            <div className="space-y-4">
              <ChartCard title="Confidence Distribution — Count per Bucket">
                {buckets.filter(b => b.count > 0).length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={buckets.filter(b => b.count > 0)} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                      <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} width={30} />
                      <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                      <Bar dataKey="count" name="Signals" radius={[3, 3, 0, 0]}>
                        {buckets.filter(b => b.count > 0).map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState label="No confidence data" />}
              </ChartCard>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Confidence vs Regime (Avg Confidence)">
                  {(confidence?.vs_regime ?? []).length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={confidence!.vs_regime} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="regime" tick={{ fontSize: 8, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${(v*100).toFixed(0)}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${(v*100).toFixed(1)}%`, "Avg Confidence"]} />
                        <Bar dataKey="avg_confidence" radius={[3, 3, 0, 0]}>
                          {(confidence?.vs_regime ?? []).map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No regime data" />}
                </ChartCard>

                <ChartCard title="Confidence vs Sector (Win Rate)">
                  {(confidence?.vs_sector ?? []).length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={confidence!.vs_sector} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="sector" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis domain={[0,100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${v}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${fmt(v,1)}%`, "Win Rate"]} />
                        <Bar dataKey="win_rate" radius={[3, 3, 0, 0]}>
                          {(confidence?.vs_sector ?? []).map((r, i) => <Cell key={i} fill={r.win_rate >= 50 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="No sector data" />}
                </ChartCard>
              </div>

              <div className="rounded-xl border border-border bg-card p-5">
                <h3 className="text-sm font-semibold mb-3">Confidence Bucket Detail</h3>
                {buckets.filter(b => b.count > 0).length > 0 ? (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        {["Bucket","Signals","Winners","Win %","Avg P&L","Net P&L","Avg Confidence"].map(h => (
                          <th key={h} className="text-right pb-2 px-2 first:text-left">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {buckets.filter(b => b.count > 0).map(b => (
                        <tr key={b.bucket} className="border-b border-border/40">
                          <td className="py-2 px-2 font-medium">{b.bucket}</td>
                          <td className="py-2 px-2 text-right tabular-nums">{b.count}</td>
                          <td className="py-2 px-2 text-right tabular-nums text-emerald-400">{b.winners}</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums", b.win_rate >= 50 ? "text-emerald-400" : "text-red-400")}>{fmt(b.win_rate,1)}%</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums", b.avg_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtRs(b.avg_pnl)}</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums font-semibold", b.net_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtRs(b.net_pnl)}</td>
                          <td className="py-2 px-2 text-right tabular-nums">{fmt(b.avg_confidence * 100, 1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <EmptyState label="No confidence data yet" />}
              </div>
            </div>
          )}

          {/* ── Learning ── */}
          {tab === "learning" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: "Trend",           value: trendDir, color: trendDir === "Improving" ? "text-emerald-400" : trendDir === "Declining" ? "text-red-400" : "text-muted-foreground" },
                  { label: "Recent Accuracy", value: `${fmt(learning?.recent_accuracy ?? 0, 1)}%`, color: (learning?.recent_accuracy ?? 0) >= 50 ? "text-emerald-400" : "text-red-400" },
                  { label: "Prior Accuracy",  value: `${fmt(learning?.prior_accuracy ?? 0, 1)}%`,  color: "text-muted-foreground" },
                  { label: "Delta",           value: `${(learning?.accuracy_delta ?? 0) >= 0 ? "+" : ""}${fmt(learning?.accuracy_delta ?? 0, 1)}%`, color: (learning?.accuracy_delta ?? 0) >= 0 ? "text-emerald-400" : "text-red-400" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="rounded-xl border border-border bg-card p-4">
                    <p className="text-xs text-muted-foreground mb-1">{label}</p>
                    <p className={cn("text-lg font-bold", color)}>{value}</p>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Daily Accuracy">
                  {dailyData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <LineChart data={dailyData} margin={{ top: 4, right: 10, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="date" tick={{ fontSize: 8, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${v}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${fmt(v,1)}%`, "Accuracy"]} />
                        <ReferenceLine y={50} stroke="hsl(var(--muted-foreground))" strokeDasharray="4 4" />
                        <Line type="monotone" dataKey="accuracy" stroke="#8b5cf6" strokeWidth={2} dot={{ r: 3 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="Needs multiple trading days" />}
                </ChartCard>

                <ChartCard title="Monthly Accuracy Trend">
                  {monthlyData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={monthlyData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="month" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                        <YAxis domain={[0,100]} tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} tickFormatter={v => `${v}%`} width={36} />
                        <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                          formatter={(v: number) => [`${fmt(v,1)}%`, "Accuracy"]} />
                        <Bar dataKey="accuracy" radius={[3, 3, 0, 0]}>
                          {monthlyData.map((m, i) => <Cell key={i} fill={m.accuracy >= 50 ? "#10b981" : "#f43f5e"} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <EmptyState label="Needs multiple months of data" />}
                </ChartCard>
              </div>
            </div>
          )}

          {/* ── Recommendations ── */}
          {tab === "recommendations" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: "Success Rate",       value: `${fmt(recs?.recommendation_success_pct ?? 0, 1)}%`,   color: (recs?.recommendation_success_pct ?? 0) >= 50 ? "text-emerald-400" : "text-red-400" },
                  { label: "Accepted Win Rate",  value: `${fmt(recs?.accepted_win_rate ?? 0, 1)}%`,            color: "text-emerald-400" },
                  { label: "Flagged Win Rate",   value: `${fmt(recs?.rejected_win_rate ?? 0, 1)}%`,            color: "text-amber-400" },
                  { label: "Avg Profit",         value: fmtRs(recs?.avg_profit_per_recommendation ?? 0),        color: "text-sky-400" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="rounded-xl border border-border bg-card p-4">
                    <p className="text-xs text-muted-foreground mb-1">{label}</p>
                    <p className={cn("text-lg font-bold", color)}>{value}</p>
                  </div>
                ))}
              </div>

              <div className="rounded-xl border border-border bg-card p-5">
                <h3 className="text-sm font-semibold mb-3">Per-Recommendation Analysis</h3>
                {recs?.per_recommendation && recs.per_recommendation.length > 0 ? (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        {["Recommendation","Category","Signals","Wins","Win %","Net P&L","Avg P&L"].map(h => (
                          <th key={h} className="text-right pb-2 px-2 first:text-left">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {recs.per_recommendation.map(r => (
                        <tr key={r.recommendation} className="border-b border-border/40">
                          <td className="py-2 px-2 font-medium max-w-[180px] truncate">{r.recommendation}</td>
                          <td className="py-2 px-2 text-right">
                            <span className={cn("text-xs px-1.5 py-0.5 rounded",
                              r.category === "accepted" ? "bg-emerald-500/10 text-emerald-400" :
                              r.category === "flagged"  ? "bg-red-500/10 text-red-400" :
                              "bg-muted/30 text-muted-foreground")}>
                              {r.category}
                            </span>
                          </td>
                          <td className="py-2 px-2 text-right tabular-nums">{r.count}</td>
                          <td className="py-2 px-2 text-right tabular-nums text-emerald-400">{r.wins}</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums", r.win_rate >= 50 ? "text-emerald-400" : "text-red-400")}>{fmt(r.win_rate,1)}%</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums font-semibold", r.net_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtRs(r.net_pnl)}</td>
                          <td className={cn("py-2 px-2 text-right tabular-nums", r.avg_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>{fmtRs(r.avg_pnl)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <EmptyState label="No recommendation data yet" />}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
