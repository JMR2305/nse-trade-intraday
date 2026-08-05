/** Section 15: Optimization Dashboard — top-line V3 metrics */
import type { OptDashboard } from "./types";

const fmt1 = (n?: number | null) => n != null ? n.toFixed(1) : "—";

interface MetricTileProps {
  label:       string;
  value:       string;
  color:       string;
  subtext?:    string;
  width?:      string;
}

function MetricTile({ label, value, color, subtext }: MetricTileProps) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/40 rounded-xl px-4 py-3 text-center">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-0.5">{label}</div>
      {subtext && <div className="text-xs text-slate-600 mt-0.5">{subtext}</div>}
    </div>
  );
}

function ScoreRing({ score }: { score: number | null }) {
  if (score == null) return (
    <div className="flex items-center justify-center w-24 h-24 rounded-full border-4 border-slate-700/40 text-slate-600 text-sm">
      N/A
    </div>
  );
  const color = score >= 75 ? "#10b981" : score >= 55 ? "#f59e0b" : "#ef4444";
  const circumference = 2 * Math.PI * 40;
  const dasharray = `${(score / 100) * circumference} ${circumference}`;
  return (
    <div className="relative w-24 h-24">
      <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="40" fill="none" stroke="#334155" strokeWidth="8" />
        <circle cx="50" cy="50" r="40" fill="none" stroke={color} strokeWidth="8"
          strokeDasharray={dasharray} strokeLinecap="round" />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-bold text-white">{Math.round(score)}</span>
        <span className="text-xs text-slate-500">/100</span>
      </div>
    </div>
  );
}

export function OptimizationDashboard({ data }: { data: OptDashboard }) {
  if (!data) return null;

  const quality = data.data_quality;
  const isAccumulating = quality === "accumulating";

  return (
    <div className="space-y-4">
      {isAccumulating && (
        <div className="flex items-center gap-2 bg-slate-700/30 border border-slate-600/40 rounded-lg px-3 py-2 text-xs text-slate-400">
          <span className="text-amber-400">⚡</span>
          Analytics are accumulating — scores will improve as more rejection outcomes are resolved.
          <span className="ml-auto text-slate-500">{data.total_tracked} tracked · {data.total_resolved} resolved · {data.history_days} days history</span>
        </div>
      )}

      <div className="flex gap-6 items-center">
        <div className="text-center space-y-1 shrink-0">
          <ScoreRing score={data.optimization_score} />
          <div className="text-xs text-slate-500 font-medium">Optimization Score</div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 flex-1">
          <MetricTile
            label="Risk Accuracy"
            value={data.overall_risk_accuracy != null ? `${fmt1(data.overall_risk_accuracy)}%` : "—"}
            color={data.overall_risk_accuracy != null && data.overall_risk_accuracy >= 60 ? "text-emerald-400" : "text-slate-400"}
            subtext="correct rejections / total resolved"
          />
          <MetricTile
            label="False Rejection Rate"
            value={data.false_rejection_rate != null ? `${fmt1(data.false_rejection_rate)}%` : "—"}
            color={data.false_rejection_rate != null && data.false_rejection_rate >= 40 ? "text-red-400" : "text-emerald-400"}
            subtext="lower is better"
          />
          <MetricTile
            label="Correct Rejection Rate"
            value={data.correct_rejection_rate != null ? `${fmt1(data.correct_rejection_rate)}%` : "—"}
            color={data.correct_rejection_rate != null && data.correct_rejection_rate >= 60 ? "text-emerald-400" : "text-amber-400"}
          />
          <MetricTile
            label="Opportunity Leakage"
            value={data.opportunity_leakage_pct != null ? `${fmt1(data.opportunity_leakage_pct)}%` : "—"}
            color={data.opportunity_leakage_pct != null && data.opportunity_leakage_pct >= 40 ? "text-red-400" : "text-teal-400"}
            subtext="false rej. as % of resolved"
          />
          <MetricTile
            label="Threshold Stability"
            value={data.threshold_stability_pct != null ? `${fmt1(data.threshold_stability_pct)}%` : "—"}
            color={data.threshold_stability_pct != null && data.threshold_stability_pct >= 70 ? "text-emerald-400" : "text-amber-400"}
            subtext="% of gates on 'keep'"
          />
          <MetricTile
            label="Learning Progress"
            value={`${Math.round(data.learning_progress_pct ?? 0)}%`}
            color="text-purple-400"
            subtext={`${data.history_days}d history · ${data.total_resolved} resolved`}
          />
        </div>
      </div>
    </div>
  );
}
