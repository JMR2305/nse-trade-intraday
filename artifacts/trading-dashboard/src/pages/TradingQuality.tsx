/**
 * TradingQuality.tsx — Phase 26D: Trading Quality & Readiness dashboard.
 *
 * READ-ONLY · ADVISORY-ONLY · PAPER TRADING / RESEARCH ONLY
 *
 * Presentation of PERSISTED Phase 26 validation outputs — nothing here
 * recalculates:
 *  - Session funnel + all-time quality stats (26C QUALITY latest run)
 *  - Performance grades (26C PERFORMANCE latest run)
 *  - Daily Validation Report status (+ manual generate)
 *  - Five-Day Acceptance tracker
 *  - Final Production Readiness report + exports (Phase 23.9 engine)
 *  - Open issues from the Phase 26 issue store
 *
 * Slow aggregate endpoints get explicit long apiJson timeouts (the 15s
 * default kills them), and shared page-level queries are never refetched
 * per-widget.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson, API_BASE } from "@/lib/api";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import {
  Gauge, ShieldCheck, ShieldAlert, CheckCircle2, XCircle, AlertTriangle,
  HelpCircle, Loader2, Filter, TrendingUp, FileBarChart2, Download,
  CalendarCheck2, RefreshCw, Award, Bug,
} from "lucide-react";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ── Backend shapes (persisted validation results) ────────────────────────────

interface QualityReport {
  verdict: string;
  scan_id?: string | null;
  generated_at?: string;
  funnel_available?: boolean;
  funnel?: {
    scanned: number; scan_rejected: number; analysed: number;
    risk_approved: number; risk_rejected: number;
    signals: { buy: number; sell: number; watch: number; ignore: number };
    executed_trades: number; missed_count: number;
    missed_opportunities?: { symbol: string; reason: string }[];
  } | null;
  quality_stats?: {
    available: boolean; scope?: string; total_trades?: number;
    win_rate?: number; profit_factor?: number; expectancy?: number;
    total_pnl?: number; avg_hold_seconds?: number; min_evidence?: number;
    note?: string;
  };
}

interface PerformanceReport {
  verdict: string;
  generated_at?: string;
  grade_counts?: Record<string, number>;
  metrics?: { metric: string; value: any; grade: string; detail: string }[];
}

interface DailyReport {
  report_id?: string;
  report_date: string;
  generated_at?: string;
  verdict: string;
  validation_score?: number | null;
  sections?: Record<string, { status: string; source: string }>;
  certification?: { certification_pct?: number; verdict?: string } | null;
  acceptance?: { passed: boolean; critical_open_issues?: number;
                 failed_sections?: string[] };
  recommendations?: string[];
}

interface DailyStatus {
  status: "NOT_EXPECTED" | "NOT_DUE" | "GENERATED" | "ERROR" | "PENDING" | string;
  mode?: "scheduler" | "manual" | string;
  detail?: string;
  error?: string;
  generated_at_ist?: string | null;
  report_date?: string;
}

interface FiveDay {
  verdict: string;
  days: { date: string; status: string; verdict?: string;
          critical_open_issues?: number | null;
          failed_sections?: string[]; detail?: string }[];
  days_passed: number; days_failed: number; days_pending: number;
  policy?: string;
}

interface Readiness {
  verdict: "READY" | "PENDING" | "NOT_READY" | string;
  ready?: boolean;
  blockers?: string[];
  pending?: string[];
  certification?: { certification_pct?: number; verdict?: string } | null;
  generated_at?: string;
}

interface Issue {
  category: string; key: string; severity: string; title: string;
  detail?: string; last_seen?: string; count?: number;
}

// ── Small UI pieces ───────────────────────────────────────────────────────────

const BADGE: Record<string, { cls: string; icon: any }> = {
  PASS: { cls: "bg-emerald-500/15 border-emerald-600/50 text-emerald-300", icon: CheckCircle2 },
  WARN: { cls: "bg-amber-500/15 border-amber-600/50 text-amber-300", icon: AlertTriangle },
  FAIL: { cls: "bg-red-500/15 border-red-600/50 text-red-300", icon: XCircle },
  PENDING: { cls: "bg-slate-600/40 border-slate-600/50 text-slate-300", icon: HelpCircle },
  INSUFFICIENT_EVIDENCE: { cls: "bg-slate-600/40 border-slate-600/50 text-slate-300", icon: HelpCircle },
};

function Badge({ v }: { v?: string | null }) {
  const key = String(v ?? "PENDING").toUpperCase();
  const s = BADGE[key] ?? BADGE.PENDING;
  const Icon = s.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-semibold rounded border ${s.cls}`}>
      <Icon size={11} />
      {key === "INSUFFICIENT_EVIDENCE" ? "INSUFFICIENT" : key}
    </span>
  );
}

function Card({ title, icon: Icon, right, children }: {
  title: string; icon: any; right?: any; children: any;
}) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-700/50 flex items-center gap-2">
        <Icon size={15} className="text-teal-400" />
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {right && <div className="ml-auto">{right}</div>}
      </div>
      {children}
    </div>
  );
}

function LoadRow({ q, label }: { q: { isLoading: boolean; isError: boolean; error?: any }; label: string }) {
  if (q.isLoading) {
    return (
      <div className="p-5 text-sm text-slate-400 flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Loading {label}…
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="p-5 text-sm text-red-300">
        {label} unavailable: {String((q.error as any)?.message ?? q.error)}
      </div>
    );
  }
  return (
    <div className="p-5 text-sm text-slate-500">
      No {label} recorded yet — run the corresponding validation first.
    </div>
  );
}

const fmtNum = (v: any, digits = 2) =>
  typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TradingQuality() {
  const qc = useQueryClient();
  const [genRunning, setGenRunning] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  // Shared page-level queries — long explicit timeouts for slow aggregates.
  const qualityQ = useQuery<{ ok: boolean; result: QualityReport }>({
    queryKey: ["p26d-quality"],
    queryFn: () => apiJson("phase26c/quality/latest", undefined, 120_000),
    staleTime: 60_000,
  });
  const perfQ = useQuery<{ ok: boolean; result: PerformanceReport }>({
    queryKey: ["p26d-performance"],
    queryFn: () => apiJson("phase26c/performance/latest", undefined, 120_000),
    staleTime: 60_000,
  });
  const dailyQ = useQuery<{ ok: boolean; report: DailyReport }>({
    queryKey: ["p26d-daily"],
    queryFn: () => apiJson("phase26d/daily-report/latest", undefined, 60_000),
    staleTime: 60_000,
  });
  const dailyStatusQ = useQuery<DailyStatus>({
    queryKey: ["p26d-daily-status"],
    queryFn: () => apiJson("phase26d/daily-report/status", undefined, 60_000),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const fiveQ = useQuery<FiveDay>({
    queryKey: ["p26d-five-day"],
    queryFn: () => apiJson("phase26d/five-day", undefined, 60_000),
    staleTime: 60_000,
  });
  const readyQ = useQuery<Readiness>({
    queryKey: ["p26d-readiness"],
    queryFn: () => apiJson("phase26d/readiness", undefined, 180_000),
    staleTime: 120_000,
  });
  const issuesQ = useQuery<{ ok: boolean; issues: Issue[] }>({
    queryKey: ["p26d-issues"],
    queryFn: () =>
      apiJson("live-validation/issues?status=OPEN&limit=100", undefined, 60_000),
    staleTime: 30_000,
  });

  const quality = qualityQ.data?.result;
  const perf = perfQ.data?.result;
  const daily = dailyQ.data?.report;
  const dailyStatus = dailyStatusQ.data;
  const five = fiveQ.data;
  const ready = readyQ.data;
  const issues = issuesQ.data?.issues ?? [];
  const funnel = quality?.funnel;
  const stats = quality?.quality_stats;

  const generateDaily = async () => {
    if (genRunning) return;
    setGenRunning(true);
    setGenError(null);
    try {
      await apiJson("phase26d/daily-report/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }, 180_000);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["p26d-daily"] }),
        qc.invalidateQueries({ queryKey: ["p26d-daily-status"] }),
        qc.invalidateQueries({ queryKey: ["p26d-five-day"] }),
        qc.invalidateQueries({ queryKey: ["p26d-readiness"] }),
      ]);
    } catch (e: any) {
      setGenError(String(e?.message ?? e));
    } finally {
      setGenRunning(false);
    }
  };

  const readyStyle = ready?.verdict === "READY"
    ? "bg-emerald-900/20 border-emerald-600/50"
    : ready?.verdict === "PENDING"
      ? "bg-amber-900/20 border-amber-600/50"
      : "bg-red-900/20 border-red-700/50";

  const funnelSteps = funnel ? [
    { label: "Scanned", value: funnel.scanned },
    { label: "Analysed", value: funnel.analysed },
    { label: "Risk Approved", value: funnel.risk_approved },
    { label: "BUY Signals", value: funnel.signals?.buy },
    { label: "Executed", value: funnel.executed_trades },
  ] : [];
  const funnelMax = Math.max(1, ...funnelSteps.map((s) => s.value ?? 0));

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Gauge size={22} className="text-teal-400" />
            Trading Quality
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Phase 26D — session funnel, quality metrics, performance grades, daily reports,
            five-day acceptance &amp; production readiness. Advisory only · paper trading / research.
          </p>
        </div>
        <button
          onClick={generateDaily}
          disabled={genRunning}
          data-testid="generate-daily-report"
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold border transition-all ${
            genRunning
              ? "bg-slate-700/40 border-slate-600 text-slate-400 cursor-not-allowed"
              : "bg-teal-500/20 border-teal-500/60 text-teal-300 hover:bg-teal-500/30"
          }`}>
          {genRunning
            ? (<><Loader2 size={14} className="animate-spin" /> Generating…</>)
            : (<><RefreshCw size={14} /> Generate Daily Report</>)}
        </button>
      </div>

      <DataFreshnessBar variant="scan" />

      {genError && (
        <div className="flex items-center gap-2 bg-red-900/20 border border-red-700/40 rounded-xl px-4 py-2.5 text-red-300 text-xs">
          <XCircle size={13} className="flex-shrink-0" /> Daily report generation failed: {genError}
        </div>
      )}

      {/* Readiness banner */}
      {readyQ.isLoading ? (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 text-slate-400 text-sm flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> Assembling production readiness report…
        </div>
      ) : ready ? (
        <div className={`rounded-xl p-5 border ${readyStyle}`}>
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              {ready.verdict === "READY"
                ? <ShieldCheck size={28} className="text-emerald-400" />
                : <ShieldAlert size={28} className={ready.verdict === "PENDING" ? "text-amber-400" : "text-red-400"} />}
              <div>
                <p className={`text-lg font-bold ${
                  ready.verdict === "READY" ? "text-emerald-300"
                    : ready.verdict === "PENDING" ? "text-amber-300" : "text-red-300"}`}>
                  {ready.verdict?.replace("_", " ")}
                </p>
                <p className="text-xs text-slate-400">
                  Final Production Readiness — five-day acceptance + certification + open issues.
                  READY requires all three clean; warnings never pass.
                </p>
                {(ready.blockers?.length ?? 0) > 0 && (
                  <p className="text-xs text-red-300/80 mt-1">Blockers: {ready.blockers!.join(" · ")}</p>
                )}
                {(ready.pending?.length ?? 0) > 0 && (
                  <p className="text-xs text-amber-300/80 mt-1">Pending: {ready.pending!.join(" · ")}</p>
                )}
              </div>
            </div>
            <div className="flex gap-1.5 items-center">
              <span className="text-xs text-slate-500 mr-1 inline-flex items-center gap-1">
                <Download size={11} /> Export
              </span>
              {(["pdf", "csv", "json", "md"] as const).map((fmt) => (
                <a key={fmt}
                  href={`${API_BASE}/phase239/export/readiness/${fmt}`}
                  download
                  className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium border bg-slate-700/40 border-slate-600/50 text-slate-300 hover:border-teal-500/60 hover:text-teal-300 transition-all uppercase">
                  {fmt}
                </a>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 text-sm text-red-300">
          Readiness report unavailable{readyQ.isError ? `: ${String((readyQ.error as any)?.message ?? readyQ.error)}` : ""}
        </div>
      )}

      {/* Five-day acceptance tracker */}
      <Card title="Five-Day Acceptance" icon={CalendarCheck2}
        right={five ? <Badge v={five.verdict} /> : null}>
        {five ? (
          <div className="p-4">
            <div className="grid grid-cols-5 gap-2">
              {five.days.map((d) => (
                <div key={d.date}
                  data-testid={`five-day-${d.date}`}
                  className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3 text-center">
                  <p className="text-xs text-slate-400 font-mono">{d.date.slice(5)}</p>
                  <div className="mt-1.5 flex justify-center"><Badge v={d.status} /></div>
                  {(d.failed_sections?.length ?? 0) > 0 && (
                    <p className="text-[10px] text-red-300/80 mt-1">{d.failed_sections!.join(", ")}</p>
                  )}
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-500 mt-3">
              {five.days_passed} passed · {five.days_failed} failed · {five.days_pending} pending — {five.policy}
            </p>
          </div>
        ) : <LoadRow q={fiveQ} label="five-day acceptance tracker" />}
      </Card>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Session funnel */}
        <Card title="Session Funnel" icon={Filter}
          right={quality ? <Badge v={quality.verdict} /> : null}>
          {quality && funnel ? (
            <div className="p-4 space-y-2">
              {funnelSteps.map((s) => (
                <div key={s.label} className="flex items-center gap-3">
                  <span className="w-28 text-xs text-slate-400">{s.label}</span>
                  <div className="flex-1 h-5 bg-slate-900/50 rounded overflow-hidden">
                    <div className="h-full bg-teal-500/50 rounded"
                      style={{ width: `${Math.max(2, ((s.value ?? 0) / funnelMax) * 100)}%` }} />
                  </div>
                  <span className="w-10 text-right text-xs font-mono text-slate-200">{s.value ?? "—"}</span>
                </div>
              ))}
              <p className="text-xs text-slate-500 pt-1">
                Scan {quality.scan_id ?? "—"} · rejected at scan: {funnel.scan_rejected} ·
                rejected at risk: {funnel.risk_rejected} · missed: {funnel.missed_count}
              </p>
            </div>
          ) : quality && !funnel ? (
            <div className="p-5 text-sm text-slate-500">
              No funnel available for the latest quality run (no canonical scan events yet).
            </div>
          ) : <LoadRow q={qualityQ} label="trading-quality run" />}
        </Card>

        {/* Quality metrics */}
        <Card title="Quality Metrics" icon={TrendingUp}
          right={stats?.scope
            ? <span className="text-[10px] uppercase tracking-widest text-slate-500">{stats.scope.replace(/_/g, " ")}</span>
            : null}>
          {stats?.available ? (
            <div className="p-4">
              <div className="grid grid-cols-3 gap-3">
                {[
                  ["Closed Trades", String(stats.total_trades ?? "—")],
                  ["Win Rate", stats.win_rate != null ? `${fmtNum(stats.win_rate, 1)}%` : "—"],
                  ["Profit Factor", fmtNum(stats.profit_factor)],
                  ["Expectancy", `₹${fmtNum(stats.expectancy)}`],
                  ["Total P&L", `₹${fmtNum(stats.total_pnl)}`],
                  ["Avg Hold", stats.avg_hold_seconds != null
                    ? `${Math.round((stats.avg_hold_seconds ?? 0) / 60)}m` : "—"],
                ].map(([label, value]) => (
                  <div key={label} className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-3">
                    <p className="text-[10px] text-slate-500 uppercase tracking-widest">{label}</p>
                    <p className="text-sm font-mono text-white mt-1">{value}</p>
                  </div>
                ))}
              </div>
              {stats.note && <p className="text-xs text-amber-300/80 mt-3">{stats.note}</p>}
            </div>
          ) : quality ? (
            <div className="p-5 text-sm text-slate-500">Quality statistics unavailable in the latest run.</div>
          ) : <LoadRow q={qualityQ} label="quality statistics" />}
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* Performance grades */}
        <Card title="Performance Grades" icon={Award}
          right={perf ? <Badge v={perf.verdict} /> : null}>
          {perf?.metrics?.length ? (
            <div className="divide-y divide-slate-700/30">
              {perf.metrics.map((m) => (
                <div key={m.metric} className="flex items-center justify-between gap-3 px-4 py-2.5">
                  <div className="min-w-0">
                    <p className="text-sm text-white font-medium">{m.metric.replace(/_/g, " ")}</p>
                    <p className="text-xs text-slate-500 truncate">{m.detail}</p>
                  </div>
                  <Badge v={m.grade} />
                </div>
              ))}
            </div>
          ) : <LoadRow q={perfQ} label="performance validation run" />}
        </Card>

        {/* Daily validation report */}
        <Card title="Daily Validation Report" icon={FileBarChart2}
          right={daily ? <Badge v={daily.verdict} /> : null}>
          {dailyStatus && (
            <div
              data-testid="daily-report-status"
              className={`px-4 py-2 text-xs border-b border-slate-700/40 flex items-center gap-2 ${
                dailyStatus.status === "GENERATED" ? "text-emerald-300/90 bg-emerald-500/5"
                  : dailyStatus.status === "ERROR" ? "text-red-300 bg-red-500/5"
                  : dailyStatus.status === "PENDING" ? "text-amber-300/90 bg-amber-500/5"
                  : "text-slate-400 bg-slate-900/30"
              }`}>
              {dailyStatus.status === "GENERATED" ? <CheckCircle2 size={12} className="flex-shrink-0" />
                : dailyStatus.status === "ERROR" ? <XCircle size={12} className="flex-shrink-0" />
                : dailyStatus.status === "PENDING" ? <Loader2 size={12} className="animate-spin flex-shrink-0" />
                : <HelpCircle size={12} className="flex-shrink-0" />}
              <span>
                Today&rsquo;s report ({dailyStatus.report_date}): {dailyStatus.detail ?? dailyStatus.status}
              </span>
            </div>
          )}
          {daily ? (
            <div className="p-4 space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span className="font-mono">{daily.report_date}</span>
                <span>
                  Validation score:{" "}
                  <span className="text-white font-mono">
                    {daily.validation_score != null ? `${daily.validation_score}%` : "—"}
                  </span>
                  {daily.certification?.certification_pct != null && (
                    <> · Certification: <span className="text-white font-mono">{daily.certification.certification_pct}%</span></>
                  )}
                </span>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {Object.entries(daily.sections ?? {}).map(([name, s]) => (
                  <div key={name} className="bg-slate-900/40 border border-slate-700/40 rounded-lg p-2 text-center">
                    <p className="text-[10px] text-slate-500 uppercase tracking-widest">{name}</p>
                    <div className="mt-1 flex justify-center"><Badge v={s.status} /></div>
                  </div>
                ))}
              </div>
              {(daily.recommendations?.length ?? 0) > 0 && (
                <ul className="text-xs text-slate-400 space-y-1 list-disc pl-4">
                  {daily.recommendations!.slice(0, 5).map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              )}
            </div>
          ) : <LoadRow q={dailyQ} label="daily validation report" />}
        </Card>
      </div>

      {/* Open issues */}
      <Card title="Open Issues" icon={Bug}
        right={<span className="text-xs text-slate-500">{issues.length} open</span>}>
        {issuesQ.isLoading ? (
          <LoadRow q={issuesQ} label="open issues" />
        ) : issues.length === 0 ? (
          <div className="p-5 text-sm text-emerald-300/80 flex items-center gap-2">
            <CheckCircle2 size={14} /> No open issues in the Phase 26 issue store.
          </div>
        ) : (
          <div className="divide-y divide-slate-700/30">
            {issues.slice(0, 30).map((i) => (
              <div key={`${i.category}:${i.key}`} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <div className="min-w-0">
                  <p className="text-sm text-white font-medium">{i.title}</p>
                  <p className="text-xs text-slate-500 font-mono truncate">
                    {i.category} · {i.key}{i.count ? ` · seen ×${i.count}` : ""}
                  </p>
                </div>
                <Badge v={i.severity === "CRITICAL" ? "FAIL" : i.severity === "WARNING" ? "WARN" : "PASS"} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
