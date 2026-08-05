/** Section 8 (Pipeline Replay) + Section 9 (Stock Comparison) */
import { useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import type { Candidate } from "./types";
import { computeRiskScore, getSeverity, SEVERITY_CONFIG, fmt1, fmt2, fmtCur, fmtPct } from "./helpers";

// ─────────────────────────────────────────────────────────────────────────────
// Section 8 — Pipeline Replay
// ─────────────────────────────────────────────────────────────────────────────
const PIPELINE_NODES = [
  { id: "supervisor",   label: "Supervisor",   color: "bg-blue-800/60 border-blue-600/60" },
  { id: "market-data",  label: "Market Data",  color: "bg-slate-700/60 border-slate-600/60" },
  { id: "research",     label: "Research",     color: "bg-slate-700/60 border-slate-600/60" },
  { id: "market-intel", label: "Market Intel", color: "bg-slate-700/60 border-slate-600/60" },
  { id: "monitoring",   label: "Monitoring",   color: "bg-slate-700/60 border-slate-600/60" },
  { id: "strategy",     label: "Strategy",     color: "bg-slate-700/60 border-slate-600/60" },
  { id: "risk",         label: "Risk Agent",   color: "bg-red-900/60 border-red-600/60",   blocked: true },
  { id: "execution",    label: "Execution (BLOCKED)", color: "bg-slate-800/40 border-slate-700/30", muted: true },
];

function PipelineReplay({ candidate: c }: { candidate: Candidate }) {
  const failedLocal  = c.gates.filter(g => !g.passed && !g.is_global);
  const failedGlobal = c.gates.filter(g => !g.passed && g.is_global);

  return (
    <div className="space-y-4">
      <div className="text-xs text-slate-500">
        Execution path for <span className="text-white font-semibold">{c.symbol}</span>
      </div>

      {/* Pipeline waterfall */}
      <div className="flex flex-wrap items-center gap-1.5">
        {PIPELINE_NODES.map((node, i) => (
          <div key={node.id} className="flex items-center gap-1.5">
            <div className={`relative rounded-lg border px-3 py-2 text-xs font-medium text-center min-w-[80px] ${node.color}`}>
              <span className={node.muted ? "text-slate-600" : node.blocked ? "text-red-300" : "text-slate-200"}>
                {node.label}
              </span>
              {node.blocked && (
                <div className="absolute -top-2 -right-2 bg-red-500 rounded-full w-4 h-4 flex items-center justify-center text-white text-xs font-bold">
                  ✗
                </div>
              )}
            </div>
            {i < PIPELINE_NODES.length - 1 && (
              <div className={`text-lg font-bold ${i >= 5 ? "text-red-600" : "text-slate-600"}`}>→</div>
            )}
          </div>
        ))}
      </div>

      {/* Rejection summary */}
      {failedLocal.length > 0 && (
        <div className="bg-red-900/20 border border-red-700/30 rounded-lg p-3 space-y-1.5">
          <div className="text-xs font-semibold text-red-300">Blocked at Risk Agent — {failedLocal.length} gate{failedLocal.length !== 1 ? "s" : ""} failed:</div>
          {failedLocal.map(g => (
            <div key={g.gate} className="flex items-start gap-2 text-xs text-slate-400">
              <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
              <span><span className="text-red-300 font-medium">{g.label}</span> — {g.reason}</span>
            </div>
          ))}
        </div>
      )}
      {failedGlobal.length > 0 && (
        <div className="bg-purple-900/20 border border-purple-700/30 rounded-lg p-3 space-y-1.5">
          <div className="text-xs font-semibold text-purple-300">Session-level gates also failing:</div>
          {failedGlobal.map(g => (
            <div key={g.gate} className="flex items-start gap-2 text-xs text-slate-400">
              <XCircle className="w-3.5 h-3.5 text-purple-400 shrink-0 mt-0.5" />
              <span><span className="text-purple-300 font-medium">{g.label}</span> — {g.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Section 9 — Stock Comparison
// ─────────────────────────────────────────────────────────────────────────────
function StockComparison({ candidates }: { candidates: Candidate[] }) {
  const [selected, setSelected] = useState<string[]>([]);

  function toggle(sym: string) {
    setSelected(prev =>
      prev.includes(sym)
        ? prev.filter(s => s !== sym)
        : prev.length < 3 ? [...prev, sym] : prev
    );
  }

  const compared = candidates.filter(c => selected.includes(c.symbol));

  // Collect all gate IDs that appear across selected candidates
  const allGates = Array.from(new Set(
    compared.flatMap(c => c.gates.map(g => g.gate))
  )).map(gid => {
    const lbl = compared.flatMap(c => c.gates).find(g => g.gate === gid)?.label ?? gid;
    return { gid, lbl };
  });

  const FIELDS: { label: string; fn: (c: Candidate) => string }[] = [
    { label: "Sector",         fn: c => c.sector || "—" },
    { label: "Strategy",       fn: c => c.strategy_name || "—" },
    { label: "Regime",         fn: c => c.regime || "—" },
    { label: "Recommendation", fn: c => c.recommendation },
    { label: "Confidence",     fn: c => `${fmt1(c.confidence)}%` },
    { label: "Opp. Score",     fn: c => `${fmt1(c.opportunity_score)}%` },
    { label: "R:R",            fn: c => `${fmt2(c.sizing.rr_ratio)}×` },
    { label: "Trade Quality",  fn: c => `${fmt1(c.trade_quality_score)}%` },
    { label: "Entry Price",    fn: c => fmtCur(c.sizing.entry_price) },
    { label: "Stop Loss",      fn: c => fmtCur(c.sizing.stop_loss) },
    { label: "Target",         fn: c => fmtCur(c.sizing.target_price) },
    { label: "Position Value", fn: c => fmtCur(c.sizing.position_value) },
    { label: "Risk Amount",    fn: c => fmtCur(c.sizing.risk_amount) },
    { label: "Qty",            fn: c => `${c.sizing.quantity} shares` },
    { label: "Risk Score",     fn: c => `${computeRiskScore(c).score}/100 ${computeRiskScore(c).level}` },
    { label: "Severity",       fn: c => { const s = getSeverity(c); return c.eligible ? "ELIGIBLE" : SEVERITY_CONFIG[s].label; } },
    { label: "Failed Gates",   fn: c => `${c.gates.filter(g => !g.passed).length}` },
  ];

  return (
    <div className="space-y-4">
      {/* Stock selector */}
      <div>
        <div className="text-xs text-slate-500 mb-2">Select up to 3 rejected stocks to compare:</div>
        <div className="flex flex-wrap gap-2">
          {candidates.map(c => {
            const isSel = selected.includes(c.symbol);
            const canAdd = selected.length < 3 || isSel;
            return (
              <button
                key={c.symbol}
                onClick={() => toggle(c.symbol)}
                disabled={!canAdd}
                className={`text-xs px-2.5 py-1 rounded border transition ${
                  isSel
                    ? "bg-blue-600 border-blue-500 text-white"
                    : canAdd
                      ? "border-slate-600 text-slate-300 hover:border-slate-500"
                      : "border-slate-700/30 text-slate-600 cursor-not-allowed"
                }`}
              >
                {c.symbol}
                {!c.eligible && (
                  <span className="ml-1 text-red-400/70">
                    ({c.gates.filter(g => !g.passed).length}✗)
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {selected.length === 3 && (
          <div className="text-xs text-amber-400 mt-1">Maximum 3 stocks selected.</div>
        )}
      </div>

      {/* Comparison table */}
      {compared.length >= 2 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-slate-700/40">
                <th className="text-left text-xs text-slate-500 py-2 pr-4 font-medium w-36">Field</th>
                {compared.map(c => (
                  <th key={c.symbol} className={`text-center text-xs py-2 px-3 font-bold ${c.eligible ? "text-emerald-400" : "text-red-400"}`}>
                    {c.symbol}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/20">
              {FIELDS.map(({ label, fn }) => (
                <tr key={label} className="hover:bg-slate-700/10">
                  <td className="py-1.5 pr-4 text-xs text-slate-500">{label}</td>
                  {compared.map(c => (
                    <td key={c.symbol} className="py-1.5 px-3 text-center text-xs text-slate-300">{fn(c)}</td>
                  ))}
                </tr>
              ))}
              {/* Gate rows */}
              {allGates.map(({ gid, lbl }) => (
                <tr key={gid} className="hover:bg-slate-700/10">
                  <td className="py-1.5 pr-4 text-xs text-slate-500">{lbl}</td>
                  {compared.map(c => {
                    const g = c.gates.find(g => g.gate === gid);
                    if (!g) return <td key={c.symbol} className="py-1.5 px-3 text-center text-slate-600 text-xs">—</td>;
                    return (
                      <td key={c.symbol} className="py-1.5 px-3 text-center">
                        {g.passed
                          ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mx-auto" />
                          : <XCircle      className="w-3.5 h-3.5 text-red-400 mx-auto" />}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-slate-500 text-sm text-center py-8 bg-slate-800/30 rounded-lg border border-slate-700/30">
          Select at least 2 stocks above to compare them side-by-side.
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ComparePanel — tab between Pipeline Replay + Stock Comparison
// ─────────────────────────────────────────────────────────────────────────────
interface ComparePanelProps {
  candidates: Candidate[];
}

export function ComparePanel({ candidates }: ComparePanelProps) {
  const [view, setView] = useState<"pipeline" | "compare">("pipeline");
  const [replaySymbol, setReplaySymbol] = useState<string | null>(
    candidates.find(c => !c.eligible)?.symbol ?? candidates[0]?.symbol ?? null
  );

  const replayCandidate = candidates.find(c => c.symbol === replaySymbol);

  return (
    <div className="space-y-4">
      <div className="flex gap-1.5 flex-wrap">
        {[
          { key: "pipeline" as const, label: "Section 8 — Pipeline Replay" },
          { key: "compare"  as const, label: "Section 9 — Stock Comparison" },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${
              view === key
                ? "bg-slate-700 border-slate-600 text-white"
                : "border-slate-700/40 text-slate-400 hover:border-slate-600"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {view === "pipeline" && (
        <div className="space-y-3">
          {/* Symbol selector */}
          <div className="flex flex-wrap gap-2">
            {candidates.map(c => (
              <button
                key={c.symbol}
                onClick={() => setReplaySymbol(c.symbol)}
                className={`text-xs px-2.5 py-1 rounded border transition ${
                  replaySymbol === c.symbol
                    ? "bg-blue-600 border-blue-500 text-white"
                    : "border-slate-600 text-slate-300 hover:border-slate-500"
                }`}
              >
                {c.symbol}
                {!c.eligible && <span className="ml-1 text-red-400/70">✗</span>}
              </button>
            ))}
          </div>
          {replayCandidate && <PipelineReplay candidate={replayCandidate} />}
        </div>
      )}

      {view === "compare" && <StockComparison candidates={candidates} />}
    </div>
  );
}
