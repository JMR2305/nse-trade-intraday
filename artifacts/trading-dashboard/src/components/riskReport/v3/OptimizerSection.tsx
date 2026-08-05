/** Sections 4 (AI Threshold Optimizer) + 5 (Regime Optimization) */
import { useState } from "react";
import { TrendingDown, TrendingUp, Minus, Info } from "lucide-react";
import type { ThresholdOptimizerRow, RegimeRow } from "./types";

const fmt1 = (n?: number | null) => n != null ? n.toFixed(1) : "—";

// ── Section 4: AI Threshold Optimizer ─────────────────────────────────────────
const DIR_CONFIG: Record<string, { icon: React.ReactNode; label: string; color: string; bg: string }> = {
  keep:           { icon: <Minus        className="w-3.5 h-3.5" />, label: "Keep",            color: "text-slate-300",    bg: "bg-slate-700/30 border-slate-600/40" },
  tighten:        { icon: <TrendingUp   className="w-3.5 h-3.5" />, label: "Tighten ↑",       color: "text-purple-300",   bg: "bg-purple-900/30 border-purple-700/40" },
  relax:          { icon: <TrendingDown className="w-3.5 h-3.5" />, label: "Relax ↓",         color: "text-blue-300",     bg: "bg-blue-900/30 border-blue-700/40" },
  slightly_relax: { icon: <TrendingDown className="w-3.5 h-3.5" />, label: "Slightly Relax ↓",color: "text-teal-300",     bg: "bg-teal-900/30 border-teal-700/40" },
};

export function ThresholdOptimizerSection({ data }: { data: ThresholdOptimizerRow[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!data || data.length === 0) {
    return (
      <div className="text-center py-10 text-slate-500 text-sm">
        <div className="text-3xl mb-2">⚙️</div>
        <div className="font-medium text-slate-400">Data accumulating</div>
        <div className="text-xs mt-1 text-slate-600">Threshold suggestions require at least 5 resolved rejections per gate.</div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2 items-start text-xs text-blue-300 bg-blue-900/15 border border-blue-700/30 rounded-lg px-3 py-2.5">
        <Info className="w-4 h-4 shrink-0 mt-0.5" />
        Suggestions only — no automatic changes. All thresholds remain at their current values until an operator manually updates them.
      </div>
      <div className="space-y-2">
        {data.map(row => {
          const dc = DIR_CONFIG[row.direction] ?? DIR_CONFIG.keep;
          const isExpanded = expanded === row.gate_id;
          const changed = Math.abs(row.suggested_value - row.current_value) >= 0.1;
          return (
            <div key={row.gate_id} className="rounded-xl border border-slate-700/40 bg-slate-800/30 overflow-hidden">
              <button
                onClick={() => setExpanded(isExpanded ? null : row.gate_id)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-700/20"
              >
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-slate-200">{row.label}</span>
                  <span className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded border font-medium ${dc.bg} ${dc.color}`}>
                    {dc.icon} {dc.label}
                  </span>
                  {row.sample_size < 5 && (
                    <span className="text-xs text-slate-600 bg-slate-700/30 px-1.5 py-0.5 rounded">insufficient data</span>
                  )}
                </div>
                <div className="flex items-center gap-4 text-sm">
                  <div className="text-right">
                    <div className="text-xs text-slate-500">Current</div>
                    <div className="font-mono font-semibold text-slate-300">{row.current_value}</div>
                  </div>
                  {changed && (
                    <>
                      <div className="text-slate-600 text-lg">→</div>
                      <div className="text-right">
                        <div className="text-xs text-slate-500">Suggested</div>
                        <div className={`font-mono font-semibold ${dc.color}`}>{row.suggested_value}</div>
                      </div>
                    </>
                  )}
                </div>
              </button>
              {isExpanded && (
                <div className="border-t border-slate-700/30 px-4 py-3 space-y-2 text-xs text-slate-400 bg-slate-900/20">
                  <div>{row.reason}</div>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="bg-slate-700/20 rounded p-2 text-center">
                      <div className="text-slate-600">False Rejection Rate</div>
                      <div className={`font-bold ${row.false_rejection_pct >= 40 ? "text-red-400" : "text-slate-300"}`}>
                        {fmt1(row.false_rejection_pct)}%
                      </div>
                    </div>
                    <div className="bg-slate-700/20 rounded p-2 text-center">
                      <div className="text-slate-600">Correct Rate</div>
                      <div className={`font-bold ${(row.correct_rejection_pct ?? 0) >= 60 ? "text-emerald-400" : "text-slate-300"}`}>
                        {row.correct_rejection_pct != null ? `${fmt1(row.correct_rejection_pct)}%` : "—"}
                      </div>
                    </div>
                    <div className="bg-slate-700/20 rounded p-2 text-center">
                      <div className="text-slate-600">Sample Size</div>
                      <div className="font-bold text-slate-300">{row.sample_size}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Section 5: Regime Optimization ───────────────────────────────────────────
export function RegimeOptimizationSection({ data }: { data: RegimeRow[] }) {
  const fields = [
    { key: "min_confidence",    label: "Min Confidence",  suffix: "%" },
    { key: "min_risk_reward",   label: "Min R:R",         suffix: "×" },
    { key: "min_trade_quality", label: "Min Quality",     suffix: "%" },
    { key: "sector_cap",        label: "Sector Cap",      suffix: "%" },
    { key: "per_stock_cap",     label: "Stock Cap",       suffix: "%" },
  ];
  return (
    <div className="space-y-4">
      <div className="text-xs text-slate-500 mb-2">
        Suggested threshold adjustments per market regime. Advisory only — not automatically applied.
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-700/40">
              <th className="pb-2 pr-4 text-left font-medium">Regime</th>
              {fields.map(f => (
                <th key={f.key} className="pb-2 pr-3 text-center font-medium">{f.label}</th>
              ))}
              <th className="pb-2 text-left font-medium">Rationale</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/20">
            {data.map(r => (
              <tr key={r.regime} className="hover:bg-slate-700/10">
                <td className="py-2 pr-4 font-semibold text-slate-200 whitespace-nowrap">{r.regime}</td>
                {fields.map(f => (
                  <td key={f.key} className="py-2 pr-3 text-center font-mono text-slate-300">
                    {(r as unknown as Record<string, number>)[f.key]}{f.suffix}
                  </td>
                ))}
                <td className="py-2 text-xs text-slate-500 max-w-xs">{r.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function OptimizerTab({ s4, s5 }: { s4: ThresholdOptimizerRow[]; s5: RegimeRow[] }) {
  const [sub, setSub] = useState<"s4" | "s5">("s4");
  return (
    <div className="space-y-4">
      <div className="flex gap-1.5">
        {[{ key: "s4" as const, label: "AI Threshold Optimizer" }, { key: "s5" as const, label: "Regime Optimization" }].map(({ key, label }) => (
          <button key={key} onClick={() => setSub(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${sub === key ? "bg-slate-700 border-slate-600 text-white" : "border-slate-700/40 text-slate-400 hover:border-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>
      {sub === "s4" && <ThresholdOptimizerSection data={s4} />}
      {sub === "s5" && <RegimeOptimizationSection data={s5} />}
    </div>
  );
}
