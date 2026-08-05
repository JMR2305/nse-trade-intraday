/** Sections 3 (Opportunity Leakage) + 13 (Confidence Calibration) */
import { useState } from "react";
import type { LeakagePeriod, CalibrationPoint } from "./types";

const fmtCur = (n?: number | null) => n != null ? `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—";
const fmt1 = (n?: number | null) => n != null ? n.toFixed(1) : "—";

// ── Section 3: Opportunity Leakage ───────────────────────────────────────────
function LeakagePeriodCard({ label, period }: { label: string; period: LeakagePeriod }) {
  if (!period) return null;
  return (
    <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4 space-y-3">
      <div className="text-sm font-semibold text-slate-300">{label}</div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        {[
          { label: "Total Rejected",      value: period.total_rejected, color: "text-slate-300" },
          { label: "Resolved",            value: period.resolved,       color: "text-slate-400" },
          { label: "Potential Winners Missed", value: period.potential_winners_missed, color: "text-red-400" },
          { label: "Correct Rejections",  value: period.correct_rejections, color: "text-emerald-400" },
        ].map(({ label: l, value, color }) => (
          <div key={l} className="bg-slate-700/20 rounded px-2 py-1.5">
            <div className="text-slate-600">{l}</div>
            <div className={`font-bold ${color}`}>{value}</div>
          </div>
        ))}
      </div>
      <div className="space-y-1.5 text-xs">
        <div className="flex justify-between">
          <span className="text-slate-500">Potential Profit Missed</span>
          <span className="text-red-400 font-semibold">{fmtCur(period.potential_profit_missed_inr)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Potential Loss Avoided</span>
          <span className="text-emerald-400 font-semibold">{fmtCur(period.potential_loss_avoided_inr)}</span>
        </div>
        <div className="flex justify-between border-t border-slate-700/30 pt-1.5">
          <span className="text-slate-400 font-medium">Estimated Alpha Lost</span>
          <span className={`font-bold ${(period.estimated_alpha_lost_inr ?? 0) > 0 ? "text-amber-400" : "text-emerald-400"}`}>
            {fmtCur(period.estimated_alpha_lost_inr)}
          </span>
        </div>
        {period.false_rejection_pct != null && (
          <div className="flex justify-between text-slate-500">
            <span>False Rejection Rate</span>
            <span className={`${period.false_rejection_pct >= 40 ? "text-red-400" : "text-slate-300"}`}>
              {fmt1(period.false_rejection_pct)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export function LeakageSection({ data }: {
  data: {
    today: LeakagePeriod;
    this_week: LeakagePeriod;
    this_month: LeakagePeriod;
    daily_trend: Array<{ date: string; total_rejected: number; total_evaluated: number }>;
  };
}) {
  const trend = data?.daily_trend ?? [];
  const maxRej = Math.max(...trend.map(d => d.total_rejected), 1);

  return (
    <div className="space-y-5">
      <div className="grid sm:grid-cols-3 gap-3">
        <LeakagePeriodCard label="Today"      period={data?.today} />
        <LeakagePeriodCard label="This Week"  period={data?.this_week} />
        <LeakagePeriodCard label="This Month" period={data?.this_month} />
      </div>

      {trend.length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-2 font-semibold">Daily Rejection Trend</div>
          <div className="space-y-1">
            {trend.slice(-14).map((d, i) => {
              const pct = Math.round(d.total_rejected / maxRej * 100);
              const passPct = d.total_evaluated > 0
                ? Math.round((d.total_evaluated - d.total_rejected) / d.total_evaluated * 100) : 0;
              return (
                <div key={i} className="flex items-center gap-2">
                  <div className="text-xs text-slate-600 w-20 shrink-0">{d.date}</div>
                  <div className="flex-1 h-4 bg-slate-700/30 rounded overflow-hidden relative">
                    <div className="h-full bg-red-600/50 rounded" style={{ width: `${pct}%` }} />
                    <div className="absolute inset-0 flex items-center px-2 text-xs text-slate-400">
                      {d.total_rejected} rejected
                    </div>
                  </div>
                  <div className="text-xs text-slate-500 w-8 text-right">{passPct}%</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="text-xs text-slate-600">Advisory only. Alpha lost = profit missed − loss avoided (net unrealised cost of false rejections).</div>
    </div>
  );
}

// ── Section 13: AI Confidence Calibration ─────────────────────────────────────
export function ConfidenceCalibrationSection({ data }: {
  data: {
    calibration_points: CalibrationPoint[];
    average_drift: number;
    calibration_error: number;
    calibration_status: string;
    calibration_note: string;
    sample_size: number;
    insufficient_data: boolean;
  };
}) {
  if (data?.insufficient_data) {
    return (
      <div className="text-center py-10 text-slate-500 text-sm">
        <div className="text-3xl mb-2">🎯</div>
        <div className="font-medium text-slate-400">Insufficient data for calibration</div>
        <div className="text-xs mt-1 text-slate-600">Requires at least 10 resolved rejections. Currently {data.sample_size} resolved.</div>
      </div>
    );
  }

  const statusConfig: Record<string, { label: string; color: string; bg: string }> = {
    well_calibrated: { label: "Well Calibrated",  color: "text-emerald-300", bg: "bg-emerald-900/20 border-emerald-700/30" },
    overconservative:{ label: "Overconservative", color: "text-amber-300",   bg: "bg-amber-900/20 border-amber-700/30" },
    overoptimistic:  { label: "Overoptimistic",   color: "text-red-300",     bg: "bg-red-900/20 border-red-700/30" },
  };
  const sc = statusConfig[data?.calibration_status] ?? statusConfig.well_calibrated;
  const points = data?.calibration_points ?? [];

  return (
    <div className="space-y-4">
      {/* Status banner */}
      <div className={`rounded-lg border px-4 py-3 ${sc.bg}`}>
        <div className={`font-semibold text-sm ${sc.color}`}>{sc.label}</div>
        <div className="text-xs text-slate-400 mt-0.5">{data?.calibration_note}</div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Average Drift",      value: `${data?.average_drift > 0 ? "+" : ""}${fmt1(data?.average_drift)}%`, color: Math.abs(data?.average_drift ?? 0) < 5 ? "text-emerald-400" : "text-amber-400" },
          { label: "Calibration Error",  value: `${fmt1(data?.calibration_error)}%`, color: (data?.calibration_error ?? 0) < 10 ? "text-emerald-400" : "text-red-400" },
          { label: "Sample Size",        value: `${data?.sample_size} resolved`, color: "text-slate-300" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-3 text-center">
            <div className={`text-lg font-bold ${color}`}>{value}</div>
            <div className="text-xs text-slate-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Calibration chart (bucket table) */}
      {points.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 border-b border-slate-700/40">
                {["Confidence Bucket","Predicted","Actual Success Rate","Drift","Sample"].map(h => (
                  <th key={h} className="pb-2 pr-3 text-left font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/20">
              {points.map(p => {
                const drift = p.confidence_drift;
                const driftColor = Math.abs(drift) < 5 ? "text-emerald-400" : drift > 0 ? "text-amber-400" : "text-red-400";
                return (
                  <tr key={p.bucket} className="hover:bg-slate-700/10">
                    <td className="py-2 pr-3 font-mono text-slate-300">{p.bucket}</td>
                    <td className="py-2 pr-3 text-slate-400">{fmt1(p.predicted_confidence_pct)}%</td>
                    <td className="py-2 pr-3 text-slate-300 font-semibold">{fmt1(p.actual_success_rate_pct)}%</td>
                    <td className={`py-2 pr-3 font-semibold ${driftColor}`}>{drift > 0 ? "+" : ""}{fmt1(drift)}%</td>
                    <td className="py-2 text-slate-500">{p.sample_size}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-xs text-slate-600">Positive drift = model underestimates confidence. Negative drift = model overestimates.</div>
    </div>
  );
}
