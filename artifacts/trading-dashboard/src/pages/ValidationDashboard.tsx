/**
 * ValidationDashboard.tsx — Phase 23.9
 * Validation Dashboard, Export & Final Acceptance.
 *
 * READ-ONLY · ADVISORY-ONLY · PAPER TRADING / RESEARCH ONLY
 *
 * - Per-domain validation statuses + certification score with a strict
 *   READY / NOT READY banner (WARN and INSUFFICIENT_EVIDENCE never pass).
 * - Run-certification action (server single-flights; long timeout; the UI
 *   shows progress instead of freezing).
 * - Export engine: certification report, validation logs, simulation
 *   results and comparison reports in PDF / CSV / JSON / Markdown.
 * - Final acceptance report: canonical-architecture audit of every
 *   Phase 23 system, downloadable in all four formats.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson, API_BASE } from "@/lib/api";
import {
  ShieldCheck, ShieldAlert, Download, RefreshCw, CheckCircle2,
  XCircle, AlertTriangle, HelpCircle, Award, FileBarChart2, Loader2,
  Database, Activity, Briefcase, RotateCcw, Brain, TrendingUp,
  GraduationCap, Radio,
} from "lucide-react";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ── Backend shapes ────────────────────────────────────────────────────────────

type Verdict = "PASS" | "WARN" | "FAIL" | "INSUFFICIENT_EVIDENCE" | string;

interface CertDomain {
  verdict: Verdict;
  weight: number;
  score_pct: number;
  checks_total: number;
  checks_failed: number;
  checks_warned: number;
}

interface CertReport {
  ok?: boolean;
  cert_id: string;
  created_at: string;
  certification_pct: number;
  verdict: "READY" | "NOT_READY" | string;
  ready_for_continuous_paper_trading?: boolean;
  blockers?: string[];
  domains: Record<string, CertDomain>;
  policy?: string;
}

interface CertHistoryItem {
  cert_id: string;
  created_at: string;
  certification_pct: number;
  verdict: string;
  domains: Record<string, string>;
}

interface AcceptanceSystem {
  system: string;
  module: string;
  verdict: Verdict;
  description?: string;
  checks: { check: string; status: string; detail: string }[];
}

interface AcceptanceReport {
  ok?: boolean;
  verdict: "ACCEPTED" | "NOT_ACCEPTED" | string;
  accepted?: boolean;
  score_pct: number;
  checks_total: number;
  checks_failed: number;
  checks_warned: number;
  systems: AcceptanceSystem[];
  runtime_checks: { check: string; status: string; detail: string }[];
  generated_at?: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const DOMAIN_META: Record<string, { label: string; icon: any }> = {
  data:            { label: "Data",            icon: Database },
  pipeline:        { label: "Pipeline",        icon: Activity },
  portfolio:       { label: "Portfolio",       icon: Briefcase },
  replay:          { label: "Replay",          icon: RotateCcw },
  ai_decision:     { label: "AI Decisions",    icon: Brain },
  performance:     { label: "Performance",     icon: TrendingUp },
  learning:        { label: "Learning",        icon: GraduationCap },
  mission_control: { label: "Mission Control", icon: Radio },
};

const VERDICT_STYLE: Record<string, { cls: string; icon: any }> = {
  PASS: { cls: "bg-emerald-500/15 border-emerald-600/50 text-emerald-300", icon: CheckCircle2 },
  WARN: { cls: "bg-amber-500/15 border-amber-600/50 text-amber-300",       icon: AlertTriangle },
  FAIL: { cls: "bg-red-500/15 border-red-600/50 text-red-300",             icon: XCircle },
  INSUFFICIENT_EVIDENCE: { cls: "bg-slate-600/40 border-slate-600/50 text-slate-300", icon: HelpCircle },
};

const EXPORTS: { id: string; label: string; sub: string }[] = [
  { id: "certification",   label: "Certification Report", sub: "Latest full certification with per-domain verdicts" },
  { id: "validation_logs", label: "Validation Logs",      sub: "Append-only certification run history" },
  { id: "simulation",      label: "Simulation Results",   sub: "All Simulation Lab runs with metrics" },
  { id: "comparison",      label: "Comparison Report",    sub: "Scenario comparison across sim runs" },
  { id: "acceptance",      label: "Acceptance Report",    sub: "Phase 23 canonical-architecture audit" },
];

const FORMATS = ["pdf", "csv", "json", "md"] as const;

// ── Small UI pieces ───────────────────────────────────────────────────────────

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const s = VERDICT_STYLE[verdict] ?? VERDICT_STYLE.INSUFFICIENT_EVIDENCE;
  const Icon = s.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-semibold rounded border ${s.cls}`}>
      <Icon size={11} />
      {verdict === "INSUFFICIENT_EVIDENCE" ? "INSUFFICIENT" : verdict}
    </span>
  );
}

function ScoreRing({ pct, label, color }: { pct: number | null; label: string; color: string }) {
  const r = 42, c = 2 * Math.PI * r;
  const val = pct ?? 0;
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative w-28 h-28">
        <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
          <circle cx="50" cy="50" r={r} fill="none" stroke="#334155" strokeWidth="8" />
          <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="8"
            strokeDasharray={c} strokeDashoffset={c - (c * val) / 100} strokeLinecap="round" />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xl font-bold font-mono text-white">
            {pct == null ? "—" : `${Math.round(val)}%`}
          </span>
        </div>
      </div>
      <span className="text-xs text-slate-400 uppercase tracking-widest">{label}</span>
    </div>
  );
}

function ExportRow({ report }: { report: { id: string; label: string; sub: string } }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-700/30 last:border-b-0">
      <div>
        <p className="text-sm font-semibold text-white">{report.label}</p>
        <p className="text-xs text-slate-500">{report.sub}</p>
      </div>
      <div className="flex gap-1.5">
        {FORMATS.map((fmt) => (
          <a key={fmt}
            href={`${API_BASE}/phase239/export/${report.id}/${fmt}`}
            download
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium border bg-slate-700/40 border-slate-600/50 text-slate-300 hover:border-teal-500/60 hover:text-teal-300 transition-all uppercase">
            <Download size={11} /> {fmt}
          </a>
        ))}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ValidationDashboard() {
  const qc = useQueryClient();
  const [certRunning, setCertRunning] = useState(false);
  const [certError, setCertError] = useState<string | null>(null);

  // Latest certification: history → full report
  const historyQ = useQuery<{ ok: boolean; items: CertHistoryItem[] }>({
    queryKey: ["p239-cert-history"],
    queryFn: () => apiJson("certification/history?limit=20", undefined, 60_000),
    staleTime: 30_000,
  });
  const latestId = historyQ.data?.items?.[0]?.cert_id ?? null;

  const certQ = useQuery<CertReport>({
    queryKey: ["p239-cert", latestId],
    queryFn: () => apiJson(`certification/${latestId}`, undefined, 60_000),
    enabled: !!latestId,
    staleTime: 30_000,
  });

  const acceptQ = useQuery<AcceptanceReport>({
    queryKey: ["p239-acceptance"],
    queryFn: () => apiJson("phase239/acceptance", undefined, 180_000),
    staleTime: 120_000,
  });

  const cert = certQ.data;
  const accept = acceptQ.data;
  const domains = cert?.domains ?? {};

  // Health score: share of individual checks that did not fail across domains
  const totals = Object.values(domains).reduce(
    (a, d) => ({
      total: a.total + (d.checks_total ?? 0),
      failed: a.failed + (d.checks_failed ?? 0),
      warned: a.warned + (d.checks_warned ?? 0),
    }),
    { total: 0, failed: 0, warned: 0 },
  );
  const healthScore = totals.total > 0
    ? Math.max(0, Math.round(((totals.total - totals.failed - 0.5 * totals.warned) / totals.total) * 100))
    : null;

  const ready = cert?.verdict === "READY";

  const runCertification = async () => {
    if (certRunning) return;
    setCertRunning(true);
    setCertError(null);
    try {
      // Server single-flights identical runs; 10-minute client timeout so
      // slow runs show progress state instead of aborting.
      await apiJson("certification/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }, 600_000);
      await qc.invalidateQueries({ queryKey: ["p239-cert-history"] });
      await qc.invalidateQueries({ queryKey: ["p239-cert"] });
    } catch (e: any) {
      setCertError(String(e?.message ?? e));
    } finally {
      setCertRunning(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ShieldCheck size={22} className="text-teal-400" />
            Validation Dashboard
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Phase 23.9 — validation domains, certification score, exports &amp; final acceptance.
            Advisory only · paper trading / research.
          </p>
        </div>
        <button
          onClick={runCertification}
          disabled={certRunning}
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold border transition-all ${
            certRunning
              ? "bg-slate-700/40 border-slate-600 text-slate-400 cursor-not-allowed"
              : "bg-teal-500/20 border-teal-500/60 text-teal-300 hover:bg-teal-500/30"
          }`}>
          {certRunning
            ? (<><Loader2 size={14} className="animate-spin" /> Certification running…</>)
            : (<><RefreshCw size={14} /> Run Certification</>)}
        </button>
      </div>

      {certRunning && (
        <div className="flex items-center gap-2 bg-teal-900/20 border border-teal-700/40 rounded-xl px-4 py-2.5 text-teal-300 text-xs">
          <Loader2 size={13} className="animate-spin flex-shrink-0" />
          Full certification run in progress — this validates all eight domains and can take several
          minutes. Duplicate runs are coalesced on the server.
        </div>
      )}
      {certError && (
        <div className="flex items-center gap-2 bg-red-900/20 border border-red-700/40 rounded-xl px-4 py-2.5 text-red-300 text-xs">
          <XCircle size={13} className="flex-shrink-0" /> Certification run failed: {certError}
        </div>
      )}

      {/* READY / NOT READY banner */}
      {historyQ.isLoading || (latestId && certQ.isLoading) ? (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 text-slate-400 text-sm">
          Loading latest certification…
        </div>
      ) : !cert ? (
        <div className="flex items-center gap-3 bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <HelpCircle size={20} className="text-slate-500" />
          <div>
            <p className="text-sm font-semibold text-slate-300">No certification runs yet</p>
            <p className="text-xs text-slate-500">Trigger “Run Certification” to produce the first certified report.</p>
          </div>
        </div>
      ) : (
        <div className={`flex items-center justify-between gap-4 flex-wrap rounded-xl p-5 border ${
          ready ? "bg-emerald-900/20 border-emerald-600/50" : "bg-red-900/20 border-red-700/50"
        }`}>
          <div className="flex items-center gap-3">
            {ready
              ? <ShieldCheck size={28} className="text-emerald-400" />
              : <ShieldAlert size={28} className="text-red-400" />}
            <div>
              <p className={`text-lg font-bold ${ready ? "text-emerald-300" : "text-red-300"}`}>
                {ready ? "READY" : "NOT READY"}
              </p>
              <p className="text-xs text-slate-400">
                {cert.cert_id} · {cert.created_at?.slice(0, 19).replace("T", " ")} ·
                READY requires every domain to PASS — warnings never pass.
              </p>
              {!ready && (cert.blockers?.length ?? 0) > 0 && (
                <p className="text-xs text-red-300/80 mt-1">
                  Blockers: {cert.blockers!.join(" · ")}
                </p>
              )}
            </div>
          </div>
          <div className="flex gap-8">
            <ScoreRing pct={cert.certification_pct} label="Certification"
              color={ready ? "#10B981" : cert.certification_pct >= 60 ? "#F59E0B" : "#EF4444"} />
            <ScoreRing pct={healthScore} label="Health"
              color={healthScore != null && healthScore >= 80 ? "#10B981" : healthScore != null && healthScore >= 60 ? "#F59E0B" : "#EF4444"} />
          </div>
        </div>
      )}

      {/* Domain status cards */}
      {cert && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(DOMAIN_META).map(([key, meta]) => {
            const d = domains[key];
            const Icon = meta.icon;
            return (
              <div key={key} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Icon size={14} className="text-teal-400" />
                    <span className="text-xs text-slate-400 uppercase tracking-widest">{meta.label}</span>
                  </div>
                </div>
                {d ? (
                  <>
                    <VerdictBadge verdict={d.verdict} />
                    <p className="text-xs text-slate-500 mt-2 font-mono">
                      {d.checks_total} checks · {d.checks_failed} failed · {d.checks_warned} warned
                    </p>
                  </>
                ) : (
                  <VerdictBadge verdict="INSUFFICIENT_EVIDENCE" />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Export engine */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
          <FileBarChart2 size={15} className="text-teal-400" />
          <h3 className="text-sm font-semibold text-white">Export Reports</h3>
          <span className="text-xs text-slate-500 ml-auto">PDF · CSV · JSON · Markdown</span>
        </div>
        {EXPORTS.map((r) => <ExportRow key={r.id} report={r} />)}
      </div>

      {/* Final acceptance report */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
          <Award size={15} className="text-teal-400" />
          <h3 className="text-sm font-semibold text-white">Final Acceptance — Canonical Architecture Audit</h3>
          {accept && (
            <span className={`ml-auto inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-bold rounded border ${
              accept.verdict === "ACCEPTED"
                ? "bg-emerald-500/15 border-emerald-600/50 text-emerald-300"
                : "bg-red-500/15 border-red-600/50 text-red-300"
            }`}>
              {accept.verdict === "ACCEPTED" ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
              {accept.verdict} · {accept.score_pct}%
            </span>
          )}
        </div>
        {acceptQ.isLoading ? (
          <div className="p-5 text-sm text-slate-400 flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" /> Auditing Phase 23 systems…
          </div>
        ) : acceptQ.isError ? (
          <div className="p-5 text-sm text-red-300">
            Acceptance audit unavailable: {String((acceptQ.error as any)?.message ?? acceptQ.error)}
          </div>
        ) : accept ? (
          <div className="divide-y divide-slate-700/30">
            {accept.systems.map((s) => (
              <div key={s.system} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <div>
                  <p className="text-sm text-white font-medium">{s.system}</p>
                  <p className="text-xs text-slate-500 font-mono">{s.module}{s.description ? ` — ${s.description}` : ""}</p>
                </div>
                <VerdictBadge verdict={s.verdict} />
              </div>
            ))}
            <div className="px-4 py-3 text-xs text-slate-500">
              {accept.checks_total} checks · {accept.checks_failed} failed · {accept.checks_warned} warned —
              ACCEPTED requires zero failed checks: no duplicate calculations, no independent strategy or
              portfolio engines.
            </div>
          </div>
        ) : null}
      </div>

      {/* Certification history */}
      {(historyQ.data?.items?.length ?? 0) > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50">
            <h3 className="text-sm font-semibold text-white">Certification History (append-only)</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-slate-700/50 text-slate-400">
                  {["Cert ID", "Created", "Score", "Verdict"].map((h) => (
                    <th key={h} className="px-3 py-2 text-left font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {historyQ.data!.items.slice(0, 10).map((it) => (
                  <tr key={it.cert_id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                    <td className="px-3 py-2 text-slate-300">{it.cert_id}</td>
                    <td className="px-3 py-2 text-slate-400">{it.created_at?.slice(0, 19).replace("T", " ")}</td>
                    <td className="px-3 py-2 text-slate-300">{it.certification_pct}%</td>
                    <td className="px-3 py-2">
                      <span className={it.verdict === "READY" ? "text-emerald-400" : "text-red-400"}>{it.verdict}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
