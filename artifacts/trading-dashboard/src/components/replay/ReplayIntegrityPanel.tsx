/**
 * ReplayIntegrityPanel — V4.2
 * Fetches the /integrity endpoint and renders a PASS / WARNING / ERROR
 * checklist. Errors also surface as a prominent banner above the panel.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  CheckCircle2, AlertTriangle, XCircle, ShieldCheck, RefreshCw,
} from "lucide-react";

interface IntegrityCheck {
  check: string;
  status: "PASS" | "WARNING" | "ERROR";
  detail: string;
  stage?: string;
}

interface IntegrityData {
  scan_id: string;
  snapshot_ts: string;
  overall: "PASS" | "WARNING" | "ERROR";
  checks: IntegrityCheck[];
  stages_count: number;
  trades_count: number;
}

interface Props {
  scanId: string;
}

function statusIcon(status: IntegrityCheck["status"]) {
  switch (status) {
    case "PASS":    return <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0 mt-0.5" />;
    case "WARNING": return <AlertTriangle size={13} className="text-amber-400 flex-shrink-0 mt-0.5" />;
    case "ERROR":   return <XCircle size={13} className="text-red-400 flex-shrink-0 mt-0.5" />;
  }
}

function statusBg(status: IntegrityCheck["status"]) {
  switch (status) {
    case "PASS":    return "bg-emerald-900/10 border-emerald-700/20";
    case "WARNING": return "bg-amber-900/20 border-amber-700/30";
    case "ERROR":   return "bg-red-900/20 border-red-700/30";
  }
}

function overallBadge(overall: IntegrityData["overall"]) {
  switch (overall) {
    case "PASS":    return "bg-emerald-900/30 border-emerald-600/40 text-emerald-400";
    case "WARNING": return "bg-amber-900/30 border-amber-600/40 text-amber-400";
    case "ERROR":   return "bg-red-900/30 border-red-600/40 text-red-400";
  }
}

export function ReplayIntegrityPanel({ scanId }: Props) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["replay-integrity", scanId],
    queryFn: () => apiJson<IntegrityData>(`replay/sessions/${scanId}/integrity`),
    staleTime: 60_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-3 flex items-center gap-2 text-xs text-slate-500 animate-pulse">
        <ShieldCheck size={13} className="text-slate-600" />
        Running integrity checks…
      </div>
    );
  }

  if (error || !data) return null; // fail silent — main replay still works

  const errors   = data.checks.filter(c => c.status === "ERROR");
  const warnings = data.checks.filter(c => c.status === "WARNING");

  return (
    <div className="space-y-2">
      {/* Error banner — shown prominently when any check fails */}
      {errors.length > 0 && (
        <div className="bg-red-950/60 border border-red-700/50 rounded-xl px-4 py-3 flex items-start gap-3">
          <XCircle size={15} className="text-red-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-red-300 mb-0.5">
              Replay Integrity Errors ({errors.length})
            </div>
            <ul className="text-xs text-red-400/80 space-y-0.5">
              {errors.map((e, i) => (
                <li key={i} className="truncate" title={e.detail}>
                  • {e.check}: {e.detail}
                  {e.stage && <span className="ml-1 text-red-500/80">[{e.stage}]</span>}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Compact check panel */}
      <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden">
        {/* Header */}
        <div className="px-4 py-2.5 border-b border-slate-800/60 flex items-center gap-2">
          <ShieldCheck size={13} className="text-teal-400" />
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Replay Integrity</span>
          <span className={`ml-2 px-2 py-0.5 rounded text-xs font-bold border ${overallBadge(data.overall)}`}>
            {data.overall}
          </span>
          <div className="ml-auto flex items-center gap-3 text-xs text-slate-600">
            <span>{data.stages_count} stages · {data.trades_count} trades</span>
            <button
              onClick={() => void refetch()}
              className="text-slate-500 hover:text-teal-400 transition-colors"
              title="Re-run checks"
            >
              <RefreshCw size={11} />
            </button>
          </div>
        </div>

        {/* Checks table */}
        <div className="divide-y divide-slate-800/40">
          {data.checks.map((check, i) => (
            <div
              key={i}
              className={`flex items-start gap-3 px-4 py-2 border-l-2 ${
                check.status === "ERROR"   ? "border-l-red-500" :
                check.status === "WARNING" ? "border-l-amber-500" :
                                             "border-l-emerald-500/40"
              } ${statusBg(check.status)}`}
            >
              {statusIcon(check.status)}
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-slate-300">
                  {check.check}
                  {check.stage && (
                    <span className="ml-2 px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] text-slate-400">
                      {check.stage}
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500 truncate" title={check.detail}>{check.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
