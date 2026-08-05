/** Section 14: Decision Sandbox — enhanced simulator with historical context */
import { useState, useMemo } from "react";
import { Info, Sliders } from "lucide-react";
import type { Candidate, SimSettings } from "../types";
import { simulateCandidate, extractThresholds } from "../helpers";

const fmt1 = (n: number | null | undefined) => Number(n ?? 0).toFixed(1);
const fmtCur = (n: number | null | undefined) =>
  `₹${Number(n ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

interface Props {
  candidates: Candidate[];
  sandboxData: {
    current_thresholds: Record<string, number>;
    suggested_thresholds: Record<string, number>;
    historical_tracker_count: number;
    resolved_count: number;
  };
}

type SliderDef = { key: keyof SimSettings; label: string; min: number; max: number; step: number; unit: string };
const SLIDERS: SliderDef[] = [
  { key: "minConfidence",   label: "Min Confidence",        min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "minOpportunity",  label: "Min Opportunity Score", min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "minRR",           label: "Min Risk / Reward",     min: 0,  max: 5,   step: 0.1, unit: "×" },
  { key: "minTradeQuality", label: "Min Trade Quality",     min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "sectorCap",       label: "Sector Cap",            min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "perStockCap",     label: "Per-Stock Cap",         min: 0,  max: 100, step: 1,   unit: "%" },
];

const KEY_MAP: Record<string, keyof SimSettings> = {
  min_confidence: "minConfidence", min_opportunity_score: "minOpportunity",
  min_risk_reward: "minRR", min_trade_quality: "minTradeQuality",
  sector_cap: "sectorCap", per_stock_cap: "perStockCap",
};

export function SandboxSection({ candidates, sandboxData }: Props) {
  const currentDefaults  = useMemo(() => extractThresholds(candidates), [candidates]);

  // Build suggested settings from backend
  const suggestedDefaults: SimSettings = useMemo(() => {
    const s = { ...currentDefaults };
    const st = sandboxData?.suggested_thresholds ?? {};
    for (const [gid, val] of Object.entries(st)) {
      const key = KEY_MAP[gid];
      if (key) (s as unknown as Record<string, number>)[key] = val;
    }
    return s;
  }, [currentDefaults, sandboxData]);

  const [mode, setMode] = useState<"current" | "suggested" | "custom">("current");
  const [sim, setSim] = useState<SimSettings>(currentDefaults);

  function applyMode(m: typeof mode) {
    setMode(m);
    if (m === "current")   setSim(currentDefaults);
    if (m === "suggested") setSim(suggestedDefaults);
  }

  function update(key: keyof SimSettings, v: number) {
    setMode("custom");
    setSim(s => ({ ...s, [key]: v }));
  }

  const results = useMemo(() => candidates.map(c => ({ c, passes: simulateCandidate(c, sim) })), [candidates, sim]);
  const approved = results.filter(r => r.passes);
  const rejected = results.filter(r => !r.passes);
  const exposure = approved.reduce((s, r) => s + (r.c.sizing.position_value ?? 0), 0);

  const histCount = sandboxData?.historical_tracker_count ?? 0;
  const resolved  = sandboxData?.resolved_count ?? 0;

  // Historical impact estimate: how many tracked rejections would have passed with these thresholds
  // (advisory only — based on tracker entry scores vs sim thresholds)
  const historicalImpact = {
    tracked: histCount,
    resolved,
    note: histCount > 0
      ? `Based on ${histCount} tracked rejections (${resolved} resolved), adjusting thresholds changes future candidate outcomes.`
      : "No historical rejection data yet. Historical impact will appear once rejections accumulate.",
  };

  return (
    <div className="space-y-5">
      <div className="flex gap-2 items-start text-xs text-blue-300 bg-blue-900/15 border border-blue-700/30 rounded-lg px-3 py-2.5">
        <Info className="w-4 h-4 shrink-0 mt-0.5" />
        Simulation only — no live threshold changes. Advisory only. Paper / Research only.
      </div>

      {/* Mode selector */}
      <div className="flex gap-2 flex-wrap">
        <div className="text-xs text-slate-500 self-center mr-2">Preset:</div>
        {([
          { key: "current"   as const, label: "Current Thresholds" },
          { key: "suggested" as const, label: "AI Suggested" },
          { key: "custom"    as const, label: "Custom" },
        ]).map(({ key, label }) => (
          <button key={key} onClick={() => applyMode(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${
              mode === key ? "bg-purple-600 border-purple-500 text-white" : "border-slate-700/40 text-slate-400 hover:border-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Sliders */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <Sliders className="w-4 h-4 text-purple-400" /> Threshold Controls
          </h3>
          {SLIDERS.map(({ key, label, min, max, step, unit }) => {
            const val     = (sim as unknown as Record<string, number>)[key];
            const currVal = (currentDefaults as unknown as Record<string, number>)[key];
            const suggVal = (suggestedDefaults as unknown as Record<string, number>)[key];
            const changed = Math.abs(val - currVal) >= step;
            return (
              <div key={key}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-slate-400">{label}</label>
                  <div className="flex items-center gap-2">
                    {changed && (
                      <span className="text-xs text-amber-400 bg-amber-900/30 px-1.5 py-0.5 rounded">
                        was {currVal}{unit}
                      </span>
                    )}
                    {Math.abs(suggVal - currVal) >= step && (
                      <span className="text-xs text-purple-400 bg-purple-900/30 px-1.5 py-0.5 rounded">
                        AI: {suggVal}{unit}
                      </span>
                    )}
                    <span className={`text-sm font-bold font-mono ${changed ? "text-amber-300" : "text-slate-200"}`}>
                      {val.toFixed(step < 1 ? 1 : 0)}{unit}
                    </span>
                  </div>
                </div>
                <input type="range" min={min} max={max} step={step} value={val}
                  onChange={e => update(key, parseFloat(e.target.value))}
                  className="w-full h-1.5 accent-purple-500 cursor-pointer" />
                <div className="flex justify-between text-xs text-slate-600 mt-0.5">
                  <span>{min}{unit}</span><span>{max}{unit}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Results */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-slate-300">Simulation Results</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-emerald-900/20 border border-emerald-700/40 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-emerald-400">{approved.length}</div>
              <div className="text-xs text-emerald-500">Would Approve</div>
            </div>
            <div className="bg-red-900/20 border border-red-700/40 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-red-400">{rejected.length}</div>
              <div className="text-xs text-red-500">Would Reject</div>
            </div>
            <div className="col-span-2 bg-slate-700/30 border border-slate-600/40 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-slate-200">{fmtCur(exposure)}</div>
              <div className="text-xs text-slate-500">Estimated Exposure</div>
            </div>
          </div>

          {/* Per-candidate chips */}
          <div className="flex flex-wrap gap-2">
            {results.map(({ c, passes }) => (
              <span key={c.symbol} className={`text-xs px-2 py-1 rounded border font-mono ${
                passes ? "bg-emerald-900/30 border-emerald-700/40 text-emerald-300"
                       : "bg-red-900/30 border-red-700/40 text-red-300"}`}>
                {c.symbol} {passes ? "✓" : "✗"}
              </span>
            ))}
          </div>

          {/* Historical context */}
          <div className="bg-purple-900/15 border border-purple-700/30 rounded-xl p-3 text-xs text-purple-300/80 space-y-1">
            <div className="font-semibold text-purple-300">Historical Impact Context</div>
            <div>{historicalImpact.note}</div>
          </div>

          {/* Diff from current */}
          {results.filter(r => r.passes !== r.c.eligible).length > 0 && (
            <div className="text-xs bg-amber-900/20 border border-amber-700/30 rounded-lg p-3 space-y-1">
              <div className="font-semibold text-amber-300">Changes from actual evaluation:</div>
              {results.filter(r => r.passes !== r.c.eligible).map(({ c, passes }) => (
                <div key={c.symbol} className="text-slate-400">
                  <span className="font-mono text-slate-300">{c.symbol}</span> →{" "}
                  {passes
                    ? <span className="text-emerald-400">would PASS (currently rejected)</span>
                    : <span className="text-red-400">would FAIL (currently eligible)</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
