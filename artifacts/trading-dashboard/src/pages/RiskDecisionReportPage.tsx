/**
 * Risk Decision Report — Version 2: AI Risk Analysis Centre
 * Tab structure: Candidates | Gate Analysis | Simulator | Compare | Export
 * Sections 1–15 covered across components.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  RefreshCw, AlertTriangle, ShieldAlert, BarChart3,
  Sliders, GitCompare, Download, FileBarChart2, Brain,
} from "lucide-react";
import { apiJson } from "@/lib/api";
import type { Report, Candidate } from "../components/riskReport/types";
import { EnhancedCandidateCard }  from "../components/riskReport/EnhancedCandidateCard";
import { GateAnalysisPanel }       from "../components/riskReport/GateAnalysisPanel";
import { SimulatorPanel }          from "../components/riskReport/SimulatorPanel";
import { ComparePanel }            from "../components/riskReport/ComparePanel";
import { ExportPanel }             from "../components/riskReport/ExportPanel";
import { tsLabel }                 from "../components/riskReport/helpers";
import { IntelligenceTab }         from "../components/riskReport/v3/IntelligenceTab";

// ─────────────────────────────────────────────────────────────────────────────
// Tabs
// ─────────────────────────────────────────────────────────────────────────────
type Tab = "candidates" | "gate-analysis" | "simulator" | "compare" | "export" | "intelligence";

const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: "candidates",    label: "Candidates",    icon: <FileBarChart2 className="w-3.5 h-3.5" /> },
  { key: "gate-analysis", label: "Gate Analysis", icon: <BarChart3     className="w-3.5 h-3.5" /> },
  { key: "simulator",     label: "Simulator",     icon: <Sliders       className="w-3.5 h-3.5" /> },
  { key: "compare",       label: "Compare",       icon: <GitCompare    className="w-3.5 h-3.5" /> },
  { key: "export",        label: "Export",        icon: <Download      className="w-3.5 h-3.5" /> },
  { key: "intelligence",  label: "Intelligence",  icon: <Brain         className="w-3.5 h-3.5" /> },
];

// ─────────────────────────────────────────────────────────────────────────────
// Candidates tab
// ─────────────────────────────────────────────────────────────────────────────
function CandidatesTab({
  candidates,
  onGateClick,
}: {
  candidates: Candidate[];
  onGateClick: (gateId: string) => void;
}) {
  const [filter, setFilter]   = useState<"all" | "eligible" | "rejected">("all");
  const [search, setSearch]   = useState("");

  const visible = candidates.filter(c => {
    if (filter === "eligible" && !c.eligible)  return false;
    if (filter === "rejected" && c.eligible)   return false;
    if (search && !c.symbol.toLowerCase().includes(search.toLowerCase()) &&
        !c.sector?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-3">
      {/* Filter + search */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="flex rounded-lg overflow-hidden border border-slate-700/40 text-xs">
          {(["all", "eligible", "rejected"] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 capitalize transition ${
                filter === f
                  ? "bg-slate-700 text-white"
                  : "text-slate-400 hover:bg-slate-700/30"
              }`}
            >
              {f} ({f === "all" ? candidates.length : candidates.filter(c => f === "eligible" ? c.eligible : !c.eligible).length})
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search symbol or sector…"
          className="bg-slate-800/60 border border-slate-700/40 rounded-lg px-3 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-blue-500/50 w-52"
        />
      </div>

      {/* Cards */}
      <div className="space-y-3">
        {visible.length === 0 && (
          <div className="text-center text-slate-500 text-sm py-8">No candidates match the current filter.</div>
        )}
        {visible.map(c => (
          <EnhancedCandidateCard
            key={c.symbol}
            candidate={c}
            defaultExpanded={!c.eligible}
            onGateClick={gateId => {
              onGateClick(gateId);
            }}
          />
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────
export default function RiskDecisionReportPage() {
  const [tab,        setTab]        = useState<Tab>("candidates");
  const [openGateId, setOpenGateId] = useState<string | undefined>();

  const { data, isLoading, error, refetch, isRefetching } = useQuery<Report>({
    queryKey: ["phase15-risk-decision-report"],
    queryFn:  () => apiJson("phase15/risk-decision-report", undefined, 60_000),
    staleTime: 60_000,
    retry: 1,
  });

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <div className="text-slate-400 text-sm">Loading risk decision report…</div>
        </div>
      </div>
    );
  }

  // Error state
  if (error || !data?.available) {
    const msg = error instanceof Error ? error.message : (data?.reason ?? "Unknown error");
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center p-6">
        <div className="max-w-md text-center space-y-4">
          <ShieldAlert className="w-12 h-12 text-red-400 mx-auto" />
          <div className="text-red-400 font-semibold">Risk Report Unavailable</div>
          <div className="text-slate-500 text-sm">{msg}</div>
          <button
            onClick={() => refetch()}
            className="flex items-center gap-2 mx-auto bg-slate-700 hover:bg-slate-600 text-slate-200 px-4 py-2 rounded-lg text-sm transition"
          >
            <RefreshCw className="w-4 h-4" /> Retry
          </button>
        </div>
      </div>
    );
  }

  const candidates = data.candidates ?? [];
  const pressure   = data.gate_pressure ?? [];
  const blocked    = candidates.filter(c => !c.eligible);
  const eligible   = candidates.filter(c => c.eligible);

  // ── Navigate to Gate Analysis tab and open modal ──────────────────────────
  function openGateInAnalysis(gateId: string) {
    setTab("gate-analysis");
    setOpenGateId(gateId);
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 print:bg-white print:text-black">
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">

        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-amber-400" />
              AI Risk Analysis Centre
            </h1>
            <div className="flex flex-wrap items-center gap-3 mt-1 text-xs text-slate-500">
              <span>Evaluated: {tsLabel(data.evaluated_at)}</span>
              {data.scan_id && <span>Scan: {data.scan_id.slice(0, 12)}…</span>}
              {data.market_state && <span className="text-slate-400">Market: {data.market_state}</span>}
              <span className="text-amber-500/70 bg-amber-900/20 border border-amber-700/30 px-1.5 py-0.5 rounded">
                {data.label}
              </span>
              {data.history_days !== undefined && (
                <span>{data.history_days} day{data.history_days !== 1 ? "s" : ""} of history</span>
              )}
            </div>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isRefetching}
            className="flex items-center gap-2 bg-slate-700/60 hover:bg-slate-700 border border-slate-600/40 text-slate-300 px-3 py-1.5 rounded-lg text-xs transition disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefetching ? "animate-spin" : ""}`} />
            {isRefetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {/* ── Summary KPI bar ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Total Candidates", value: candidates.length,    color: "text-slate-200" },
            { label: "Eligible",         value: eligible.length,      color: "text-emerald-400" },
            { label: "Rejected",         value: blocked.length,       color: "text-red-400" },
            { label: "Gates Tracked",    value: pressure.length,      color: "text-blue-400" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-slate-800/50 border border-slate-700/40 rounded-xl px-4 py-3 text-center">
              <div className={`text-2xl font-bold ${color}`}>{value}</div>
              <div className="text-xs text-slate-500 mt-0.5">{label}</div>
            </div>
          ))}
        </div>

        {/* ── Top Blockers banner ─────────────────────────────────────────── */}
        {data.top_blockers && data.top_blockers.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 bg-red-900/15 border border-red-700/30 rounded-lg px-3 py-2">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
            <span className="text-xs text-red-300 font-medium">Top blockers today:</span>
            {data.top_blockers.map(b => (
              <span key={b} className="text-xs bg-red-900/30 border border-red-700/40 text-red-300 px-2 py-0.5 rounded-full">
                {b}
              </span>
            ))}
          </div>
        )}

        {/* ── Global gates warning ────────────────────────────────────────── */}
        {data.global_gates && data.global_gates.some(g => !g.passed) && (
          <div className="bg-purple-900/20 border border-purple-700/40 rounded-lg px-3 py-2.5 text-xs text-purple-300 space-y-1">
            <div className="font-semibold flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" />
              Session-level gates failing — affects ALL candidates:
            </div>
            {data.global_gates.filter(g => !g.passed).map(g => (
              <div key={g.gate} className="text-purple-400/80 ml-5">• {g.label}: {g.reason}</div>
            ))}
          </div>
        )}

        {/* ── Tabs ────────────────────────────────────────────────────────── */}
        <div className="border-b border-slate-700/40">
          <div className="flex gap-1 flex-wrap -mb-px">
            {TABS.map(({ key, label, icon }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition ${
                  tab === key
                    ? "border-blue-500 text-blue-400"
                    : "border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-600"
                }`}
              >
                {icon}
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Tab content ─────────────────────────────────────────────────── */}
        <div className="print:block">
          {tab === "candidates" && (
            <CandidatesTab
              candidates={candidates}
              onGateClick={openGateInAnalysis}
            />
          )}
          {tab === "gate-analysis" && (
            <GateAnalysisPanel
              pressure={pressure}
              candidates={candidates}
              timeline={data.history_timeline}
              historyDays={data.history_days}
              openGateId={openGateId}
              onGateOpen={id => setOpenGateId(id)}
              onGateClose={() => setOpenGateId(undefined)}
            />
          )}
          {tab === "simulator" && (
            <SimulatorPanel candidates={candidates} />
          )}
          {tab === "compare" && (
            <ComparePanel candidates={candidates} />
          )}
          {tab === "export" && (
            <ExportPanel report={data} />
          )}
          {tab === "intelligence" && (
            <IntelligenceTab candidates={candidates} />
          )}
        </div>
      </div>

      {/* ── Print styles ─────────────────────────────────────────────────── */}
      <style>{`
        @media print {
          button, nav, .print\\:hidden { display: none !important; }
          body { background: white; color: black; }
          .print\\:block { display: block !important; }
        }
      `}</style>
    </div>
  );
}
