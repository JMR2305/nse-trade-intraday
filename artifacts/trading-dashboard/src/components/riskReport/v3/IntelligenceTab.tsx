/**
 * Intelligence Tab — V3 AI Risk Intelligence & Optimization Center
 * Sections 1–15 organized into sub-tabs:
 *   Overview (S15) | Rejections (S1,S2,S9) | Leakage (S3,S13)
 *   Optimizer (S4,S5) | Strategies (S6,S7) | Learning (S8,S10)
 *   Reports (S11,S12) | Sandbox (S14)
 */
import { useQuery, useMutation } from "@tanstack/react-query";
import { RefreshCw, Brain, Info } from "lucide-react";
import { apiJson } from "@/lib/api";
import type { V3Analytics } from "./types";
import type { Candidate } from "../types";
import { OptimizationDashboard }  from "./OptimizationDashboard";
import { RejectionAnalysisTab }   from "./RejectionAnalysis";
import { LeakageSection, ConfidenceCalibrationSection } from "./LeakageSection";
import { OptimizerTab }           from "./OptimizerSection";
import { StrategiesTab }          from "./StrategiesSection";
import { LearningTab }            from "./LearningSection";
import { ReportsTab }             from "./ReportsSection";
import { SandboxSection }         from "./SandboxSection";
import { useState } from "react";

type SubTab = "overview" | "rejections" | "leakage" | "optimizer" | "strategies" | "learning" | "reports" | "sandbox";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "overview",    label: "Overview" },
  { key: "rejections",  label: "Rejections" },
  { key: "leakage",     label: "Leakage" },
  { key: "optimizer",   label: "Optimizer" },
  { key: "strategies",  label: "Strategies" },
  { key: "learning",    label: "Learning" },
  { key: "reports",     label: "Reports" },
  { key: "sandbox",     label: "Sandbox" },
];

function tsLabel(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata", hour12: false,
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

interface Props {
  candidates: Candidate[];
}

export function IntelligenceTab({ candidates }: Props) {
  const [subTab, setSubTab] = useState<SubTab>("overview");

  const { data, isLoading, error, refetch, isRefetching } = useQuery<V3Analytics>({
    queryKey:  ["phase15-v3-analytics"],
    queryFn:   () => apiJson("phase15/v3-analytics", undefined, 120_000),
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });

  const refreshMutation = useMutation({
    mutationFn: () => apiJson("phase15/v3-analytics/refresh", { method: "POST" } as RequestInit, 120_000),
    onSuccess:  () => refetch(),
  });

  function handleRefresh() { refreshMutation.mutate(); }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center space-y-3">
          <div className="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <div className="text-slate-400 text-sm">Loading V3 analytics…</div>
          <div className="text-slate-600 text-xs">This may take up to 60 seconds on first load (price data fetch)</div>
        </div>
      </div>
    );
  }

  if (error || !data?.available) {
    const msg = error instanceof Error ? error.message : (data as V3Analytics | undefined)?.label ?? "Unknown error";
    return (
      <div className="text-center py-16 space-y-3">
        <Brain className="w-10 h-10 text-purple-400/50 mx-auto" />
        <div className="text-slate-400 text-sm">V3 Analytics unavailable</div>
        <div className="text-slate-600 text-xs">{msg}</div>
        <button onClick={() => refetch()} className="text-xs bg-slate-700 hover:bg-slate-600 px-4 py-2 rounded-lg text-slate-300 mx-auto flex items-center gap-2">
          <RefreshCw className="w-3.5 h-3.5" /> Retry
        </button>
      </div>
    );
  }

  const isBusy = isRefetching || refreshMutation.isPending;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-purple-400" />
          <h2 className="text-base font-bold text-white">AI Risk Intelligence Center</h2>
          <span className="text-xs text-purple-400/70 bg-purple-900/20 border border-purple-700/30 px-2 py-0.5 rounded">V3</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>Generated: {tsLabel(data.generated_at)}</span>
          <span>{data.tracker_count} tracked · {data.history_entries} history entries</span>
          <button
            onClick={handleRefresh}
            disabled={isBusy}
            className="flex items-center gap-1.5 bg-slate-700/60 hover:bg-slate-700 border border-slate-600/40 text-slate-300 px-3 py-1.5 rounded-lg transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isBusy ? "animate-spin" : ""}`} />
            {isBusy ? "Refreshing…" : "Force Refresh"}
          </button>
        </div>
      </div>

      {/* Advisory banner */}
      <div className="flex gap-2 items-center text-xs text-purple-300/80 bg-purple-900/10 border border-purple-700/20 rounded-lg px-3 py-2">
        <Info className="w-4 h-4 shrink-0 text-purple-400" />
        All V3 analytics are advisory-only. Read-only. Paper / Research only.
        No thresholds are modified. No live execution. No automatic changes.
      </div>

      {/* Optimization Dashboard always visible at top */}
      {data.s15_optimization_dashboard && (
        <OptimizationDashboard data={data.s15_optimization_dashboard} />
      )}

      {/* Sub-tab navigation */}
      <div className="border-b border-slate-700/40">
        <div className="flex gap-0.5 flex-wrap -mb-px overflow-x-auto">
          {SUB_TABS.filter(t => t.key !== "overview").map(({ key, label }) => (
            <button key={key} onClick={() => setSubTab(key)}
              className={`flex-shrink-0 text-xs px-3 py-2 border-b-2 transition ${
                subTab === key
                  ? "border-purple-500 text-purple-400"
                  : "border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-600"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Sub-tab content */}
      {subTab === "rejections" && (
        <RejectionAnalysisTab
          s1={data.s1_false_rejections}
          s2={data.s2_gate_accuracy}
          s9={data.s9_threshold_impact}
        />
      )}
      {subTab === "leakage" && (
        <div className="space-y-6">
          <div>
            <div className="text-sm font-semibold text-slate-300 mb-3">Opportunity Leakage (S3)</div>
            <LeakageSection data={data.s3_opportunity_leakage as Parameters<typeof LeakageSection>[0]["data"]} />
          </div>
          <div className="border-t border-slate-700/30 pt-5">
            <div className="text-sm font-semibold text-slate-300 mb-3">AI Confidence Calibration (S13)</div>
            <ConfidenceCalibrationSection data={data.s13_confidence_calibration} />
          </div>
        </div>
      )}
      {subTab === "optimizer" && (
        <OptimizerTab s4={data.s4_threshold_optimizer} s5={data.s5_regime_optimization} />
      )}
      {subTab === "strategies" && (
        <StrategiesTab s6={data.s6_strategy_effectiveness} s7={data.s7_outcome_predictor} />
      )}
      {subTab === "learning" && (
        <LearningTab
          s8={data.s8_learning_loop as Parameters<typeof LearningTab>[0]["s8"]}
          s10={data.s10_ai_coach}
        />
      )}
      {subTab === "reports" && (
        <ReportsTab
          s11={data.s11_weekly_report as Record<string, unknown>}
          s12={data.s12_monthly_report as Record<string, unknown>}
        />
      )}
      {subTab === "sandbox" && (
        <SandboxSection
          candidates={candidates}
          sandboxData={data.s14_sandbox_data}
        />
      )}
    </div>
  );
}
