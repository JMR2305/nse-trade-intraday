/** Sections 5 (Top Blockers with history), 6 (Heatmap), 10 (Gate Details Modal), 11 (Timeline) */
import { useState } from "react";
import { X, TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { GatePressure, Candidate, HistoryEntry } from "./types";
import { GATE_DESCRIPTIONS, parseThreshold, fmtPct } from "./helpers";

// ─────────────────────────────────────────────────────────────────────────────
// Gate Details Modal (Section 10)
// ─────────────────────────────────────────────────────────────────────────────
function GateDetailsModal({
  gateId, pressure, candidates, onClose,
}: {
  gateId: string;
  pressure: GatePressure[];
  candidates: Candidate[];
  onClose: () => void;
}) {
  const p    = pressure.find(g => g.gate_id === gateId);
  const desc = GATE_DESCRIPTIONS[gateId];

  // Collect actual values from candidates for this gate
  const actuals: number[] = [];
  for (const c of candidates) {
    const g = c.gates.find(g => g.gate === gateId);
    if (g) {
      const { actualNum } = parseThreshold(g.reason);
      if (actualNum !== undefined) actuals.push(actualNum);
    }
  }
  actuals.sort((a, b) => a - b);
  const minVal = actuals.length ? actuals[0].toFixed(1) : "—";
  const maxVal = actuals.length ? actuals[actuals.length - 1].toFixed(1) : "—";
  const medVal = actuals.length
    ? actuals[Math.floor(actuals.length / 2)].toFixed(1) : "—";

  const trendIcon  = (t?: string) =>
    t === "increasing"  ? <TrendingUp  className="w-3.5 h-3.5 text-red-400"   /> :
    t === "decreasing"  ? <TrendingDown className="w-3.5 h-3.5 text-emerald-400" /> :
                          <Minus        className="w-3.5 h-3.5 text-slate-400" />;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-800 border border-slate-600/60 rounded-xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/40">
          <h3 className="font-bold text-white text-sm">{p?.label ?? gateId}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-4 space-y-4 text-sm">
          {desc && (
            <>
              <div>
                <div className="text-xs text-slate-500 mb-1 font-semibold uppercase tracking-wide">Purpose</div>
                <div className="text-slate-300">{desc.purpose}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1 font-semibold uppercase tracking-wide">Impact</div>
                <div className="text-slate-400">{desc.impact}</div>
              </div>
            </>
          )}
          {p && (
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-slate-700/30 rounded-lg p-3 text-center">
                <div className="text-xs text-slate-500">Blocked Today</div>
                <div className="text-lg font-bold text-red-400">{p.blocked}</div>
                <div className="text-xs text-slate-500">{fmtPct(p.blocked_pct)} of candidates</div>
              </div>
              <div className="bg-slate-700/30 rounded-lg p-3 text-center">
                <div className="text-xs text-slate-500">7-Day</div>
                <div className="text-lg font-bold text-slate-200">{p.blocked_7d ?? "—"}</div>
              </div>
              <div className="bg-slate-700/30 rounded-lg p-3 text-center">
                <div className="text-xs text-slate-500">30-Day</div>
                <div className="text-lg font-bold text-slate-200">{p.blocked_30d ?? "—"}</div>
              </div>
            </div>
          )}
          {p?.trend && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-500">Trend:</span>
              {trendIcon(p.trend)}
              <span className="text-slate-300 capitalize">{p.trend.replace("_", " ")}</span>
            </div>
          )}
          {actuals.length > 0 && (
            <div>
              <div className="text-xs text-slate-500 mb-2 font-semibold uppercase tracking-wide">Typical Actual Values</div>
              <div className="grid grid-cols-3 gap-3 text-center">
                {[["Min", minVal], ["Median", medVal], ["Max", maxVal]].map(([lbl, v]) => (
                  <div key={lbl} className="bg-slate-700/20 rounded p-2">
                    <div className="text-xs text-slate-500">{lbl}</div>
                    <div className="text-sm font-semibold text-slate-300">{v}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className={`text-xs px-2 py-1.5 rounded ${p?.is_global ? "bg-purple-900/20 text-purple-400" : "bg-slate-700/20 text-slate-400"}`}>
            {p?.is_global ? "Global gate — applies to all candidates regardless of individual metrics." : "Per-symbol gate — evaluated individually for each candidate."}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Heatmap (Section 6)
// ─────────────────────────────────────────────────────────────────────────────
function GateHeatmap({
  pressure, onGateClick,
}: { pressure: GatePressure[]; onGateClick: (id: string) => void }) {
  if (!pressure.length) return <div className="text-slate-500 text-sm">No gate data available.</div>;

  function heatColor(pct: number) {
    if (pct === 0)   return "bg-emerald-900/40 border-emerald-700/40 text-emerald-400";
    if (pct <= 30)   return "bg-yellow-900/40 border-yellow-700/40 text-yellow-400";
    if (pct <= 60)   return "bg-orange-900/40 border-orange-700/40 text-orange-400";
    return                  "bg-red-900/40 border-red-700/40 text-red-400";
  }
  function heatLabel(pct: number) {
    if (pct === 0)   return "✓ Clear";
    if (pct <= 30)   return "Medium";
    if (pct <= 60)   return "High";
    return                  "Very High";
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
      {pressure.map(p => (
        <button
          key={p.gate_id}
          onClick={() => onGateClick(p.gate_id)}
          className={`rounded-lg border p-3 text-left hover:brightness-110 transition ${heatColor(p.blocked_pct)}`}
        >
          <div className="text-xs font-semibold leading-tight line-clamp-2">{p.label}</div>
          <div className="mt-1.5 flex items-end justify-between">
            <span className="text-xl font-bold">{p.blocked}</span>
            <span className="text-xs opacity-70">{heatLabel(p.blocked_pct)}</span>
          </div>
          <div className="text-xs opacity-60 mt-0.5">{fmtPct(p.blocked_pct)} rejection rate</div>
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// History Timeline (Section 11)
// ─────────────────────────────────────────────────────────────────────────────
type TimeRange = "today" | "yesterday" | "7d" | "30d";

function HistoryTimeline({ timeline, historyDays }: { timeline?: HistoryEntry[]; historyDays?: number }) {
  const [range, setRange] = useState<TimeRange>("7d");

  const ranges: { key: TimeRange; label: string }[] = [
    { key: "today",     label: "Today" },
    { key: "yesterday", label: "Yesterday" },
    { key: "7d",        label: "Last 7 Days" },
    { key: "30d",       label: "Last 30 Days" },
  ];

  const now   = new Date();
  const today = now.toISOString().split("T")[0];
  const yest  = new Date(now.getTime() - 86400000).toISOString().split("T")[0];
  const d7    = new Date(now.getTime() - 7 * 86400000).toISOString().split("T")[0];

  const visible = (timeline ?? []).filter(e => {
    const d = e.date ?? e.evaluated_at?.split("T")[0] ?? "";
    if (range === "today")     return d === today;
    if (range === "yesterday") return d === yest;
    if (range === "7d")        return d >= d7;
    return true; // 30d — show all
  });

  const maxBlocked = Math.max(...visible.map(e => e.blocked_count), 1);

  if (!timeline || timeline.length === 0 || (historyDays ?? 0) < 1) {
    return (
      <div className="text-center py-8 text-slate-500 text-sm">
        <div className="text-2xl mb-2">📊</div>
        Insufficient history — data accumulates after each scan.
        {historyDays !== undefined && historyDays >= 0 && (
          <div className="text-xs mt-1">{historyDays} calendar day(s) of data collected so far.</div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Range selector */}
      <div className="flex gap-1.5 flex-wrap">
        {ranges.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setRange(key)}
            className={`text-xs px-3 py-1 rounded-full border transition ${
              range === key
                ? "bg-blue-600 border-blue-500 text-white"
                : "border-slate-600 text-slate-400 hover:border-slate-500"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <div className="text-slate-500 text-sm text-center py-4">No evaluations in this period.</div>
      ) : (
        <div className="space-y-1.5">
          {visible.map((e, i) => {
            const ts      = new Date(e.evaluated_at).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata", hour12: false,
              month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
            });
            const barPct  = Math.round((e.blocked_count / maxBlocked) * 100);
            const passPct = e.total_count > 0 ? Math.round((e.eligible_count / e.total_count) * 100) : 0;
            return (
              <div key={i} className="flex items-center gap-3">
                <div className="text-xs text-slate-500 w-28 shrink-0">{ts}</div>
                <div className="flex-1 h-5 bg-slate-700/40 rounded overflow-hidden relative">
                  <div
                    className="h-full bg-red-600/60 rounded"
                    style={{ width: `${barPct}%` }}
                  />
                  <div className="absolute inset-0 flex items-center px-2 text-xs text-slate-300">
                    {e.blocked_count} blocked / {e.total_count} total
                  </div>
                </div>
                <div className={`text-xs w-10 text-right font-semibold shrink-0 ${passPct >= 50 ? "text-emerald-400" : "text-amber-400"}`}>
                  {passPct}%
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Top Blockers Table (Section 5)
// ─────────────────────────────────────────────────────────────────────────────
function TopBlockersTable({ pressure, onGateClick }: { pressure: GatePressure[]; onGateClick: (id: string) => void }) {
  const trendIcon = (t?: string) =>
    t === "increasing"  ? <TrendingUp  className="w-3.5 h-3.5 text-red-400"    /> :
    t === "decreasing"  ? <TrendingDown className="w-3.5 h-3.5 text-emerald-400" /> :
    t === "stable"      ? <Minus        className="w-3.5 h-3.5 text-slate-400"  /> :
                          <span className="text-slate-600 text-xs">—</span>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-slate-500 border-b border-slate-700/40">
            <th className="text-left pb-2 pr-4 font-medium">Gate</th>
            <th className="text-center pb-2 px-3 font-medium">Today</th>
            <th className="text-center pb-2 px-3 font-medium">7-Day</th>
            <th className="text-center pb-2 px-3 font-medium">30-Day</th>
            <th className="text-center pb-2 px-3 font-medium">Trend</th>
            <th className="text-center pb-2 font-medium">Pct</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/20">
          {pressure.map(p => (
            <tr key={p.gate_id} className="hover:bg-slate-700/10">
              <td className="py-2 pr-4">
                <button
                  onClick={() => onGateClick(p.gate_id)}
                  className="text-left hover:text-blue-400 transition"
                >
                  <span className="font-medium text-slate-300">{p.label}</span>
                  {p.is_global && (
                    <span className="ml-1.5 text-xs text-purple-400 bg-purple-900/30 px-1 rounded">global</span>
                  )}
                </button>
              </td>
              <td className="py-2 px-3 text-center font-semibold text-red-400">{p.blocked}</td>
              <td className="py-2 px-3 text-center text-slate-400">{p.blocked_7d ?? "—"}</td>
              <td className="py-2 px-3 text-center text-slate-400">{p.blocked_30d ?? "—"}</td>
              <td className="py-2 px-3 text-center">{trendIcon(p.trend)}</td>
              <td className="py-2 text-center">
                <span className={`text-xs font-mono ${p.blocked_pct > 60 ? "text-red-400" : p.blocked_pct > 30 ? "text-amber-400" : "text-slate-400"}`}>
                  {fmtPct(p.blocked_pct)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// GateAnalysisPanel (exports)
// ─────────────────────────────────────────────────────────────────────────────
interface GateAnalysisPanelProps {
  pressure:    GatePressure[];
  candidates:  Candidate[];
  timeline?:   HistoryEntry[];
  historyDays?: number;
  openGateId?:  string;
  onGateOpen:  (id: string) => void;
  onGateClose: () => void;
}

export function GateAnalysisPanel({
  pressure, candidates, timeline, historyDays, openGateId, onGateOpen, onGateClose,
}: GateAnalysisPanelProps) {
  const [section, setSection] = useState<"heatmap" | "blockers" | "timeline">("heatmap");

  const tabs = [
    { key: "heatmap"  as const, label: "Gate Heatmap" },
    { key: "blockers" as const, label: "Top Blockers" },
    { key: "timeline" as const, label: "History Timeline" },
  ];

  return (
    <div className="space-y-4">
      {/* Sub-tabs */}
      <div className="flex gap-1.5 flex-wrap">
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setSection(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${
              section === key
                ? "bg-slate-700 border-slate-600 text-white"
                : "border-slate-700/40 text-slate-400 hover:border-slate-600"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Legend for heatmap */}
      {section === "heatmap" && (
        <div className="flex flex-wrap gap-3 text-xs text-slate-500">
          {[
            { color: "bg-emerald-500", label: "0% — Clear" },
            { color: "bg-yellow-500",  label: "1–30% — Medium" },
            { color: "bg-orange-500",  label: "30–60% — High" },
            { color: "bg-red-500",     label: "60%+ — Very High" },
          ].map(({ color, label }) => (
            <span key={label} className="flex items-center gap-1.5">
              <span className={`w-2.5 h-2.5 rounded-sm ${color}`} />
              {label}
            </span>
          ))}
          <span className="text-slate-600">· Click any gate to view details</span>
        </div>
      )}

      {section === "heatmap"  && <GateHeatmap pressure={pressure} onGateClick={onGateOpen} />}
      {section === "blockers" && <TopBlockersTable pressure={pressure} onGateClick={onGateOpen} />}
      {section === "timeline" && <HistoryTimeline timeline={timeline} historyDays={historyDays} />}

      {/* Gate Details Modal */}
      {openGateId && (
        <GateDetailsModal
          gateId={openGateId}
          pressure={pressure}
          candidates={candidates}
          onClose={onGateClose}
        />
      )}
    </div>
  );
}
