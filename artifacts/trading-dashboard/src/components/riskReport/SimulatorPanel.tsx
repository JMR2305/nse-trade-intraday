/** Section 7 — Pass Simulator: sliders + live re-evaluation client-side */
import { useState, useMemo } from "react";
import { Sliders, Info } from "lucide-react";
import type { Candidate, SimSettings } from "./types";
import { simulateCandidate, extractThresholds, fmtCur } from "./helpers";

interface Props {
  candidates: Candidate[];
}

type SliderDef = {
  key:   keyof SimSettings;
  label: string;
  min:   number;
  max:   number;
  step:  number;
  unit:  string;
};

const SLIDERS: SliderDef[] = [
  { key: "minConfidence",   label: "Min Confidence",         min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "minOpportunity",  label: "Min Opportunity Score",  min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "minRR",           label: "Min Risk / Reward",      min: 0,  max: 5,   step: 0.1, unit: "×" },
  { key: "minTradeQuality", label: "Min Trade Quality",      min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "sectorCap",       label: "Sector Cap",             min: 0,  max: 100, step: 1,   unit: "%" },
  { key: "perStockCap",     label: "Per-Stock Cap",          min: 0,  max: 100, step: 1,   unit: "%" },
];

export function SimulatorPanel({ candidates }: Props) {
  const defaults  = useMemo(() => extractThresholds(candidates), [candidates]);
  const [sim, setSim] = useState<SimSettings>(defaults);

  const results = useMemo(() => {
    return candidates.map(c => ({ c, passes: simulateCandidate(c, sim) }));
  }, [candidates, sim]);

  const approved    = results.filter(r => r.passes);
  const rejected    = results.filter(r => !r.passes);
  const exposure    = approved.reduce((s, r) => s + (r.c.sizing.position_value ?? 0), 0);
  const totalCap    = candidates.reduce((s, c) => s + (c.sizing.position_value ?? 0), 0);
  const exposurePct = totalCap > 0 ? (exposure / totalCap * 100) : 0;

  function update(key: keyof SimSettings, v: number) {
    setSim(s => ({ ...s, [key]: v }));
  }
  function reset() { setSim(defaults); }

  return (
    <div className="space-y-5">
      {/* Disclaimer */}
      <div className="flex gap-2 text-xs text-blue-300 bg-blue-900/20 border border-blue-700/30 rounded-lg px-3 py-2.5">
        <Info className="w-4 h-4 shrink-0 mt-0.5" />
        Simulation only — changes here are not applied to live settings. This shows how different thresholds would affect current candidates.
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Sliders */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
              <Sliders className="w-4 h-4 text-blue-400" />
              Threshold Controls
            </h3>
            <button
              onClick={reset}
              className="text-xs text-slate-500 hover:text-slate-300 underline underline-offset-2"
            >
              Reset to current
            </button>
          </div>
          {SLIDERS.map(({ key, label, min, max, step, unit }) => {
            const val     = (sim as unknown as Record<string, number>)[key];
            const defVal  = (defaults as unknown as Record<string, number>)[key];
            const changed = Math.abs(val - defVal) >= step;
            return (
              <div key={key}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-slate-400">{label}</label>
                  <div className="flex items-center gap-2">
                    {changed && (
                      <span className="text-xs text-amber-400 bg-amber-900/30 px-1.5 py-0.5 rounded">
                        was {defVal}{unit}
                      </span>
                    )}
                    <span className={`text-sm font-bold font-mono ${changed ? "text-amber-300" : "text-slate-200"}`}>
                      {val.toFixed(step < 1 ? 1 : 0)}{unit}
                    </span>
                  </div>
                </div>
                <input
                  type="range"
                  min={min}
                  max={max}
                  step={step}
                  value={val}
                  onChange={e => update(key, parseFloat(e.target.value))}
                  className="w-full h-1.5 accent-blue-500 cursor-pointer"
                />
                <div className="flex justify-between text-xs text-slate-600 mt-0.5">
                  <span>{min}{unit}</span>
                  <span>{max}{unit}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Results */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-slate-300">Simulation Results</h3>

          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-emerald-900/20 border border-emerald-700/40 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-emerald-400">{approved.length}</div>
              <div className="text-xs text-emerald-500">Would Approve</div>
            </div>
            <div className="bg-red-900/20 border border-red-700/40 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-red-400">{rejected.length}</div>
              <div className="text-xs text-red-500">Would Reject</div>
            </div>
            <div className="bg-slate-700/30 border border-slate-600/40 rounded-lg p-3 text-center col-span-2">
              <div className="text-lg font-bold text-slate-200">{fmtCur(exposure)}</div>
              <div className="text-xs text-slate-500">Estimated Exposure ({exposurePct.toFixed(1)}% of candidates' total capital)</div>
            </div>
          </div>

          {/* Per-candidate chips */}
          <div>
            <div className="text-xs text-slate-500 mb-2">Per-candidate outcome:</div>
            <div className="flex flex-wrap gap-2">
              {results.map(({ c, passes }) => (
                <span
                  key={c.symbol}
                  className={`text-xs px-2 py-1 rounded border font-mono ${
                    passes
                      ? "bg-emerald-900/30 border-emerald-700/40 text-emerald-300"
                      : "bg-red-900/30 border-red-700/40 text-red-300"
                  }`}
                >
                  {c.symbol} {passes ? "✓" : "✗"}
                </span>
              ))}
            </div>
          </div>

          {/* Change summary */}
          {results.filter(r => r.passes !== r.c.eligible).length > 0 && (
            <div className="text-xs bg-amber-900/20 border border-amber-700/30 rounded-lg p-3 space-y-1">
              <div className="font-semibold text-amber-300">Changes from actual evaluation:</div>
              {results.filter(r => r.passes !== r.c.eligible).map(({ c, passes }) => (
                <div key={c.symbol} className="text-slate-400">
                  <span className="font-mono text-slate-300">{c.symbol}</span>
                  {" → "}
                  {passes ? (
                    <span className="text-emerald-400">would PASS (currently rejected)</span>
                  ) : (
                    <span className="text-red-400">would FAIL (currently eligible)</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {results.filter(r => r.passes !== r.c.eligible).length === 0 && (
            <div className="text-xs text-slate-500 text-center bg-slate-700/20 rounded-lg px-3 py-4">
              Current thresholds — no outcome changes from the actual evaluation.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
