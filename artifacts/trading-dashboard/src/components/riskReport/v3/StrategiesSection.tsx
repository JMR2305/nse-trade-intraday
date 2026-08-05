/** Sections 6 (Strategy Effectiveness) + 7 (Trade Outcome Predictor) */
import { useState } from "react";
import type { StrategyRow, PredictorRow } from "./types";

const fmt1 = (n?: number | null) => n != null ? n.toFixed(1) : "—";
const fmt2 = (n?: number | null) => n != null ? n.toFixed(2) : "—";

// ── Section 6: Strategy Effectiveness ────────────────────────────────────────
export function StrategyEffectivenessSection({ data }: { data: StrategyRow[] }) {
  if (!data || data.length === 0) {
    return (
      <div className="text-center py-10 text-slate-500 text-sm">
        <div className="text-3xl mb-2">📊</div>
        <div className="font-medium text-slate-400">No strategy data yet</div>
        <div className="text-xs mt-1 text-slate-600">Strategy effectiveness is computed from rejection tracker and paper trades.</div>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-slate-500 border-b border-slate-700/40">
            {["Strategy","Rejections","False Rej. %","Avg Confidence","Avg R:R","Paper Trades"].map(h => (
              <th key={h} className="pb-2 pr-3 text-left font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/20">
          {data.map(r => {
            const frPct = r.false_rejection_pct;
            const frColor = frPct == null ? "text-slate-500" : frPct >= 50 ? "text-red-400" : frPct >= 30 ? "text-amber-400" : "text-emerald-400";
            return (
              <tr key={r.strategy} className="hover:bg-slate-700/10">
                <td className="py-2 pr-3 font-semibold text-slate-200">{r.strategy}</td>
                <td className="py-2 pr-3 text-center text-slate-400">{r.total_rejections}</td>
                <td className={`py-2 pr-3 text-center font-semibold ${frColor}`}>
                  {frPct != null ? `${fmt1(frPct)}%` : "—"}
                </td>
                <td className="py-2 pr-3 text-center text-slate-300">{r.avg_confidence != null ? `${fmt1(r.avg_confidence)}%` : "—"}</td>
                <td className="py-2 pr-3 text-center text-slate-300">{r.avg_rr != null ? `${fmt2(r.avg_rr)}×` : "—"}</td>
                <td className="py-2 text-center text-slate-400">{r.paper_trades_count}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="text-xs text-slate-600 mt-3">
        False Rejection % = % of resolved rejections for this strategy that would have been profitable. Lower is better.
      </div>
    </div>
  );
}

// ── Section 7: Trade Outcome Predictor ────────────────────────────────────────
function ProbBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-slate-700/40 rounded overflow-hidden">
        <div className={`h-full rounded ${color}`} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="text-xs font-mono w-8 text-right">{Math.round(value * 100)}%</span>
    </div>
  );
}

export function OutcomePredictorSection({ data }: { data: PredictorRow[] }) {
  if (!data || data.length === 0) {
    return <div className="text-slate-500 text-sm text-center py-8">No candidates available for prediction.</div>;
  }

  const confLabel = (c: string) =>
    c === "High" ? "text-emerald-400" : c === "Medium" ? "text-amber-400" : "text-red-400";

  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500 mb-2">
        Probability estimates based on confidence, opportunity score, trade quality and R:R. Advisory only — not a guarantee of outcome.
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        {data.map(r => (
          <div key={r.symbol}
            className={`rounded-xl border p-4 space-y-3 ${r.eligible ? "border-emerald-700/30 bg-emerald-950/10" : "border-slate-700/40 bg-slate-800/30"}`}>
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-200">{r.symbol}</span>
              <span className={`text-xs font-medium ${confLabel(r.prediction_confidence)}`}>
                {r.prediction_confidence} confidence
              </span>
            </div>
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-slate-500">
                <span>Prob. Success</span>
                <span className="text-emerald-400 font-semibold">{Math.round(r.probability_success * 100)}%</span>
              </div>
              <ProbBar value={r.probability_success} color="bg-emerald-500" />
              <div className="flex justify-between text-xs text-slate-500 mt-1">
                <span>Prob. Failure</span>
                <span className="text-red-400 font-semibold">{Math.round(r.probability_failure * 100)}%</span>
              </div>
              <ProbBar value={r.probability_failure} color="bg-red-500" />
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs text-center">
              <div className="bg-slate-700/20 rounded p-1.5">
                <div className="text-slate-600">Exp. Return</div>
                <div className={`font-semibold ${r.expected_return_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {r.expected_return_pct >= 0 ? "+" : ""}{fmt1(r.expected_return_pct)}%
                </div>
              </div>
              <div className="bg-slate-700/20 rounded p-1.5">
                <div className="text-slate-600">Exp. Drawdown</div>
                <div className="font-semibold text-amber-400">-{fmt1(r.expected_drawdown_pct)}%</div>
              </div>
              <div className="bg-slate-700/20 rounded p-1.5">
                <div className="text-slate-600">Hold Days</div>
                <div className="font-semibold text-slate-300">{r.expected_holding_days}d</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function StrategiesTab({ s6, s7 }: { s6: StrategyRow[]; s7: PredictorRow[] }) {
  const [sub, setSub] = useState<"s6" | "s7">("s6");
  return (
    <div className="space-y-4">
      <div className="flex gap-1.5">
        {[{ key: "s6" as const, label: "Strategy Effectiveness" }, { key: "s7" as const, label: "Outcome Predictor" }].map(({ key, label }) => (
          <button key={key} onClick={() => setSub(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${sub === key ? "bg-slate-700 border-slate-600 text-white" : "border-slate-700/40 text-slate-400 hover:border-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>
      {sub === "s6" && <StrategyEffectivenessSection data={s6} />}
      {sub === "s7" && <OutcomePredictorSection data={s7} />}
    </div>
  );
}
