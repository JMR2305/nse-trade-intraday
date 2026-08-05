/** Sections 8 (Learning Feedback Loop) + 10 (AI Coach) */
import { useState } from "react";
import { CheckCircle2, Clock, ArrowDown, Lightbulb } from "lucide-react";
import type { LearningStage } from "./types";

// ── Section 8: Learning Feedback Loop ────────────────────────────────────────
const STAGE_DESCRIPTIONS: Record<string, string> = {
  completed_trade:    "A paper trade completes (entry + exit recorded in the portfolio).",
  learning_generated: "The learning agent analyses the trade outcome against the original signal and generates pattern insights.",
  knowledge_updated:  "The knowledge base is updated with new patterns, including confidence adjustments and regime-specific rules.",
  threshold_impact:   "The system evaluates whether any gate threshold should be flagged for operator review based on accumulated learning.",
  future_reco:        "A future-trade recommendation is generated, incorporating the updated knowledge.",
};

export function LearningFeedbackSection({ data }: {
  data: {
    has_data: boolean;
    patterns_discovered?: number;
    knowledge_updates?: number;
    last_learning_at?: string;
    stages: LearningStage[];
    future_recommendations?: string[];
    threshold_impacts?: unknown[];
  };
}) {
  const stages = data?.stages ?? [];

  return (
    <div className="space-y-5">
      {/* Metrics */}
      {data?.has_data && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Patterns Discovered", value: data.patterns_discovered ?? 0, color: "text-purple-400" },
            { label: "Knowledge Updates",   value: data.knowledge_updates ?? 0,   color: "text-blue-400" },
            { label: "Last Run",            value: data.last_learning_at ? new Date(data.last_learning_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—", color: "text-slate-300" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-3 text-center">
              <div className={`text-lg font-bold ${color}`}>{value}</div>
              <div className="text-xs text-slate-500 mt-0.5">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Pipeline visual */}
      <div className="space-y-1">
        {stages.map((stage, i) => {
          const isActive = stage.status === "active";
          return (
            <div key={stage.id}>
              <div className={`flex items-start gap-3 rounded-xl border p-3 ${isActive ? "border-purple-700/40 bg-purple-900/15" : "border-slate-700/30 bg-slate-800/20"}`}>
                <div className={`mt-0.5 shrink-0 ${isActive ? "text-purple-400" : "text-slate-600"}`}>
                  {isActive ? <CheckCircle2 className="w-4 h-4" /> : <Clock className="w-4 h-4" />}
                </div>
                <div>
                  <div className={`text-sm font-semibold ${isActive ? "text-purple-300" : "text-slate-500"}`}>
                    {stage.label}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    {STAGE_DESCRIPTIONS[stage.id] ?? ""}
                  </div>
                </div>
                <div className={`ml-auto text-xs px-2 py-0.5 rounded border font-medium shrink-0 ${isActive ? "text-purple-300 bg-purple-900/30 border-purple-700/40" : "text-slate-600 bg-slate-700/20 border-slate-700/30"}`}>
                  {isActive ? "Active" : "Pending"}
                </div>
              </div>
              {i < stages.length - 1 && (
                <div className="flex justify-center py-1">
                  <ArrowDown className="w-3.5 h-3.5 text-slate-600" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Future recommendations */}
      {data?.future_recommendations && data.future_recommendations.length > 0 && (
        <div className="rounded-xl border border-purple-700/30 bg-purple-900/10 p-4 space-y-2">
          <div className="text-sm font-semibold text-purple-300 flex items-center gap-2">
            <Lightbulb className="w-4 h-4" /> Future Recommendations
          </div>
          {data.future_recommendations.map((r, i) => (
            <div key={i} className="text-xs text-slate-400 pl-6">• {r}</div>
          ))}
        </div>
      )}

      {!data?.has_data && (
        <div className="text-center py-4 text-slate-500 text-xs">
          Learning agent has not run yet. Complete paper trades are needed to generate learning feedback.
        </div>
      )}
    </div>
  );
}

// ── Section 10: AI Coach ──────────────────────────────────────────────────────
export function AICoachSection({ advisories }: { advisories: string[] }) {
  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500 mb-2">
        Plain-English advisory generated from rejection patterns and historical data. No automatic changes are made.
      </div>
      {(advisories ?? []).map((text, i) => (
        <div key={i} className="flex gap-3 bg-slate-800/30 border border-slate-700/40 rounded-xl p-4">
          <Lightbulb className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-sm text-slate-300 leading-relaxed">{text}</p>
        </div>
      ))}
      {(!advisories || advisories.length === 0) && (
        <div className="text-slate-500 text-sm text-center py-6">No advisories generated yet.</div>
      )}
    </div>
  );
}

type S8Data = Parameters<typeof LearningFeedbackSection>[0]["data"];

export function LearningTab({ s8, s10 }: { s8: S8Data; s10: string[] }) {
  const [sub, setSub] = useState<"s8" | "s10">("s8");
  return (
    <div className="space-y-4">
      <div className="flex gap-1.5">
        {[{ key: "s8" as const, label: "Learning Feedback Loop" }, { key: "s10" as const, label: "AI Coach" }].map(({ key, label }) => (
          <button key={key} onClick={() => setSub(key)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition ${sub === key ? "bg-slate-700 border-slate-600 text-white" : "border-slate-700/40 text-slate-400 hover:border-slate-600"}`}>
            {label}
          </button>
        ))}
      </div>
      {sub === "s8" && <LearningFeedbackSection data={s8 as Parameters<typeof LearningFeedbackSection>[0]["data"]} />}
      {sub === "s10" && <AICoachSection advisories={s10} />}
    </div>
  );
}
