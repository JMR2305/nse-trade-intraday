/** Sections 1 (False Rejection), 2 (Gate Accuracy), 9 (Threshold Impact) */
import { useState } from "react";
import { CheckCircle2, XCircle, Clock, TrendingUp, TrendingDown } from "lucide-react";
import type { FalseRejectionEntry, GateAccuracyRow, ThresholdImpactRow } from "./types";

const fmtCur = (n?: number | null) => n != null ? `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—";
const fmt1 = (n?: number | null) => n != null ? n.toFixed(1) : "—";

function NoData() {
  return (
    <div className="text-center py-10 text-slate-500 text-sm">
      <div className="text-3xl mb-2">📈</div>
      <div className="font-medium text-slate-400">Data accumulating</div>
      <div className="text-xs mt-1 text-slate-600">
        Rejection outcomes are classified after 1–5 trading days.<br />
        This section fills automatically as rejections are resolved.
      </div>
    </div>
  );
}

// ── Section 1: False Rejection Analysis ──────────────────────────────────────
export function FalseRejectionSection({ data }: {
  data: { summary: Record<string, number>; by_period: Record<string, FalseRejectionEntry[]> };
}) {
  const [period, setPeriod] = useState("10");
  const periods = [
    { key: "1", label: "1 Day" }, { key: "3", label: "3 Days" },
    { key: "5", label: "5 Days" }, { key: "10", label: "10 Days" }, { key: "30", label: "30 Days" },
  ];
  const entries = data.by_period?.[period] ?? [];
  const { false: falseN = 0, correct: correctN = 0, monitoring: monN = 0, total = 0 } = data.summary ?? {};

  function clsBadge(c: FalseRejectionEntry["classification"]) {
    if (c === "false_rejection")   return "bg-red-900/40 border-red-700/40 text-red-300";
    if (c === "correct_rejection") return "bg-emerald-900/40 border-emerald-700/40 text-emerald-300";
    return "bg-slate-700/40 border-slate-600/40 text-slate-400";
  }
  function clsLabel(c: FalseRejectionEntry["classification"]) {
    if (c === "false_rejection")   return "False Rejection";
    if (c === "correct_rejection") return "Correct Rejection";
    return "Still Monitoring";
  }
  function clsIcon(c: FalseRejectionEntry["classification"]) {
    if (c === "false_rejection")   return <XCircle      className="w-3.5 h-3.5 text-red-400" />;
    if (c === "correct_rejection") return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
    return                                <Clock        className="w-3.5 h-3.5 text-slate-400" />;
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total Tracked",   value: total,    color: "text-slate-200" },
          { label: "False Rejections",value: falseN,   color: "text-red-400" },
          { label: "Correct",         value: correctN, color: "text-emerald-400" },
          { label: "Still Monitoring",value: monN,     color: "text-amber-400" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-slate-800/50 border border-slate-700/40 rounded-xl px-4 py-3 text-center">
            <div className={`text-2xl font-bold ${color}`}>{value}</div>
            <div className="text-xs text-slate-500 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      {/* Period selector */}
      <div className="flex gap-1.5 flex-wrap">
        {periods.map(({ key, label }) => (
          <button key={key} onClick={() => setPeriod(key)}
            className={`text-xs px-3 py-1.5 rounded-full border transition ${
              period === key ? "bg-purple-600 border-purple-500 text-white"
                : "border-slate-700/40 text-slate-400 hover:border-slate-600"}`}>
            {label} ({(data.by_period?.[key] ?? []).length})
          </button>
        ))}
      </div>

      {entries.length === 0 ? <NoData /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-slate-700/40">
                {["Symbol","Date","Gates Failed","Conf.","R:R","Price @ Rej.","Max Gain","Max Loss","Current","Classification"].map(h => (
                  <th key={h} className="pb-2 pr-3 text-left font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/20">
              {entries.map((e, i) => (
                <tr key={i} className="hover:bg-slate-700/10">
                  <td className="py-2 pr-3 font-mono font-semibold text-slate-200">{e.symbol}</td>
                  <td className="py-2 pr-3 text-slate-500 whitespace-nowrap">{e.rejected_at}</td>
                  <td className="py-2 pr-3 text-slate-400">{(e.failed_gates ?? []).join(", ") || "—"}</td>
                  <td className="py-2 pr-3 text-slate-300">{fmt1(e.confidence)}%</td>
                  <td className="py-2 pr-3 text-slate-300">{fmt1(e.rr_ratio)}×</td>
                  <td className="py-2 pr-3 text-slate-300">{fmtCur(e.price_at_rejection)}</td>
                  <td className={`py-2 pr-3 font-semibold ${(e.max_gain_pct ?? 0) >= 5 ? "text-red-400" : "text-slate-400"}`}>
                    {e.max_gain_pct != null ? `+${fmt1(e.max_gain_pct)}%` : "—"}
                  </td>
                  <td className={`py-2 pr-3 font-semibold ${(e.max_loss_pct ?? 0) >= 3 ? "text-emerald-400" : "text-slate-400"}`}>
                    {e.max_loss_pct != null ? `-${fmt1(e.max_loss_pct)}%` : "—"}
                  </td>
                  <td className="py-2 pr-3 text-slate-300">{fmtCur(e.current_price)}</td>
                  <td className="py-2">
                    <span className={`flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-medium ${clsBadge(e.classification)}`}>
                      {clsIcon(e.classification)} {clsLabel(e.classification)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-xs text-slate-600">
        False Rejection = price rose ≥5% after rejection · Correct Rejection = price fell ≥3% · Advisory only.
      </div>
    </div>
  );
}

// ── Section 2: Gate Accuracy ──────────────────────────────────────────────────
export function GateAccuracySection({ data }: { data: GateAccuracyRow[] }) {
  if (!data || data.length === 0) return <NoData />;
  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500 mb-2">
        Based on resolved rejections only. "Correct" = gate blocked a trade that later fell. "Incorrect" = blocked a trade that later rose.
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-700/40">
              {["Gate","Blocked","Became Winners","Became Losers","Correct","Incorrect","Accuracy"].map(h => (
                <th key={h} className="pb-2 pr-3 text-left font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/20">
            {data.map(r => {
              const acc = r.accuracy_pct;
              const accColor = acc >= 70 ? "text-emerald-400" : acc >= 40 ? "text-amber-400" : "text-red-400";
              const barW = Math.min(100, acc);
              return (
                <tr key={r.gate_id} className="hover:bg-slate-700/10">
                  <td className="py-2 pr-3 text-slate-300 font-medium">{r.label}</td>
                  <td className="py-2 pr-3 text-center text-slate-400">{r.trades_blocked}</td>
                  <td className="py-2 pr-3 text-center text-red-400">{r.trades_became_winners}</td>
                  <td className="py-2 pr-3 text-center text-emerald-400">{r.trades_became_losers}</td>
                  <td className="py-2 pr-3 text-center text-emerald-400">{r.correct_decisions}</td>
                  <td className="py-2 pr-3 text-center text-red-400">{r.incorrect_decisions}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-slate-700/40 rounded overflow-hidden">
                        <div className={`h-full rounded ${acc >= 70 ? "bg-emerald-500" : acc >= 40 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${barW}%` }} />
                      </div>
                      <span className={`text-xs font-bold ${accColor}`}>{acc.toFixed(0)}%</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Section 9: Threshold Impact Report ───────────────────────────────────────
const RECO_CONFIG = {
  keep:    { label: "Keep",    color: "text-emerald-300", bg: "bg-emerald-900/30 border-emerald-700/40" },
  review:  { label: "Review",  color: "text-amber-300",   bg: "bg-amber-900/30 border-amber-700/40" },
  relax:   { label: "Relax",   color: "text-blue-300",    bg: "bg-blue-900/30 border-blue-700/40" },
  tighten: { label: "Tighten", color: "text-purple-300",  bg: "bg-purple-900/30 border-purple-700/40" },
};

export function ThresholdImpactSection({ data }: { data: ThresholdImpactRow[] }) {
  if (!data || data.length === 0) return <NoData />;
  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500 mb-2">Advisory recommendation per gate based on resolved rejection outcomes.</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-700/40">
              {["Gate","Rejected","Winners","Losers","Profit Missed","Loss Avoided","Net","Recommendation"].map(h => (
                <th key={h} className="pb-2 pr-3 text-left font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/20">
            {data.map(r => {
              const rc = RECO_CONFIG[r.recommendation] ?? RECO_CONFIG.keep;
              return (
                <tr key={r.gate_id} className="hover:bg-slate-700/10">
                  <td className="py-2 pr-3 text-slate-300 font-medium">{r.label}</td>
                  <td className="py-2 pr-3 text-center text-slate-400">{r.rejected_trades}</td>
                  <td className="py-2 pr-3 text-center text-red-400">{r.would_have_been_winners}</td>
                  <td className="py-2 pr-3 text-center text-emerald-400">{r.would_have_been_losers}</td>
                  <td className="py-2 pr-3 text-red-400">{fmtCur(r.estimated_profit_missed_inr)}</td>
                  <td className="py-2 pr-3 text-emerald-400">{fmtCur(r.estimated_loss_avoided_inr)}</td>
                  <td className={`py-2 pr-3 font-semibold ${r.net_impact_inr >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {r.net_impact_inr >= 0 ? "+" : ""}{fmtCur(r.net_impact_inr)}
                  </td>
                  <td className="py-2">
                    <span className={`text-xs px-2 py-0.5 rounded border font-bold ${rc.bg} ${rc.color}`}>{rc.label}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Combined Rejection Tab ────────────────────────────────────────────────────
export function RejectionAnalysisTab({ s1, s2, s9 }: {
  s1: { summary: Record<string, number>; by_period: Record<string, FalseRejectionEntry[]> };
  s2: GateAccuracyRow[];
  s9: ThresholdImpactRow[];
}) {
  const [sub, setSub] = useState<"s1" | "s2" | "s9">("s1");
  const tabs = [
    { key: "s1" as const, label: "False Rejection Analysis" },
    { key: "s2" as const, label: "Gate Accuracy" },
    { key: "s9" as const, label: "Threshold Impact" },
  ];
  return (
    <div className="space-y-4">
      <div className="flex gap-1.5 flex-wrap">
        {tabs.map(({ key, label }) => (
          <button key={key} onClick={() => setSub(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${
              sub === key ? "bg-slate-700 border-slate-600 text-white" : "border-slate-700/40 text-slate-400 hover:border-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>
      {sub === "s1" && <FalseRejectionSection data={s1} />}
      {sub === "s2" && <GateAccuracySection data={s2} />}
      {sub === "s9" && <ThresholdImpactSection data={s9} />}
    </div>
  );
}
