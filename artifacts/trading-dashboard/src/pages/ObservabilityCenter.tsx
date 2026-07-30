/**
 * ObservabilityCenter.tsx — Phase 8.1
 * Production Monitoring & Observability Center
 * READ-ONLY · ADVISORY-ONLY
 */
import { useState, useEffect } from "react";
import { useQuery }             from "@tanstack/react-query";
import {
  Activity, AlertTriangle, CheckCircle2, XCircle, Clock, Server,
  Database, HardDrive, Cpu, Gauge, Zap, Bell, FileText, Download,
  RefreshCw, TrendingUp, TrendingDown, Minus, Shield, Package,
  BarChart3, Eye, AlertCircle, Info, Monitor,
} from "lucide-react";
import { apiJson } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────
type Status = "HEALTHY" | "DEGRADED" | "DOWN" | "UNKNOWN" | "DISABLED" | "ENABLED";
type Grade  = "A+" | "A" | "B" | "C" | "D";
type Trend  = "IMPROVING" | "STABLE" | "DEGRADING";

// ── Helpers ───────────────────────────────────────────────────────────────────
function statusColor(s: string) {
  if (s === "HEALTHY" || s === "ENABLED") return "text-emerald-400";
  if (s === "DEGRADED")                   return "text-amber-400";
  if (s === "DOWN")                       return "text-rose-400";
  if (s === "DISABLED")                   return "text-slate-500";
  return "text-slate-400";
}
function statusBg(s: string) {
  if (s === "HEALTHY" || s === "ENABLED")
    return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
  if (s === "DEGRADED")
    return "bg-amber-500/15  text-amber-400  border-amber-500/30";
  if (s === "DOWN")
    return "bg-rose-500/15   text-rose-400   border-rose-500/30";
  if (s === "DISABLED")
    return "bg-slate-600/30  text-slate-500  border-slate-600/30";
  return   "bg-slate-600/30  text-slate-400  border-slate-600/30";
}
function gradeColor(g: string) {
  if (g === "A+") return "text-emerald-400";
  if (g === "A")  return "text-teal-400";
  if (g === "B")  return "text-sky-400";
  if (g === "C")  return "text-amber-400";
  return "text-rose-400";
}
function sevColor(sev: string) {
  if (sev === "CRITICAL") return "bg-rose-500/15  text-rose-400  border-rose-500/30";
  if (sev === "WARNING")  return "bg-amber-500/15 text-amber-400 border-amber-500/30";
  return "bg-sky-500/15 text-sky-400 border-sky-500/30";
}
function formatTs(ts: string) {
  try { return new Date(ts).toLocaleTimeString(); } catch { return ts; }
}
function TrendIcon({ t }: { t: Trend }) {
  if (t === "IMPROVING") return <TrendingUp   className="w-4 h-4 text-emerald-400 inline" />;
  if (t === "DEGRADING") return <TrendingDown  className="w-4 h-4 text-rose-400   inline" />;
  return                        <Minus         className="w-4 h-4 text-slate-400   inline" />;
}
function UsageBar({ pct, warn = 80, crit = 90 }: { pct: number; warn?: number; crit?: number }) {
  const color = pct >= crit ? "bg-rose-500" : pct >= warn ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="w-full bg-slate-700/50 rounded-full h-1.5 mt-1">
      <div className={`${color} h-1.5 rounded-full`} style={{ width: `${Math.min(100, pct)}%` }} />
    </div>
  );
}
function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const r = 42; const circ = 2 * Math.PI * r;
  const dash = (score / 100 * circ).toFixed(1);
  const color = score >= 80 ? "#10b981" : score >= 60 ? "#f59e0b" : "#ef4444";
  return (
    <svg viewBox="0 0 100 100" className="w-24 h-24">
      <circle cx="50" cy="50" r={r} fill="none" stroke="#1e293b" strokeWidth="10" />
      <circle cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="10"
        strokeDasharray={`${dash} ${circ.toFixed(1)}`}
        strokeLinecap="round" transform="rotate(-90 50 50)" />
      <text x="50" y="47" textAnchor="middle" fill={color} fontSize="18" fontWeight="700">{score.toFixed(0)}</text>
      <text x="50" y="63" textAnchor="middle" fill="#94a3b8" fontSize="12">{grade}</text>
    </svg>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────
function KpiCard({ label, value, status, icon }: { label: string; value: string; status: string; icon: React.ReactNode }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <div className={`flex items-center gap-1.5 text-xs mb-2 ${statusColor(status)}`}>
        {icon} <span className="text-slate-400">{label}</span>
      </div>
      <div className={`text-sm font-bold ${statusColor(status)}`}>{value}</div>
    </div>
  );
}
function NumCard({ label, value, sub, warn }: { label: string; value: string; sub: string; warn?: boolean }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      <div className={`text-xl font-bold ${warn ? "text-amber-400" : "text-white"}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-0.5">{sub}</div>
    </div>
  );
}
function InfoCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-slate-400">{icon}</span>
        <span className="text-sm font-semibold text-white">{title}</span>
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}
function Row({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-slate-500">{label}</span>
      <span className={`font-medium ${warn ? "text-amber-400" : "text-slate-300"}`}>{value}</span>
    </div>
  );
}
function SectionHeader({ icon, title, status, score, grade }: {
  icon: React.ReactNode; title: string;
  status?: string; score?: number; grade?: string;
}) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className="text-sky-400">{icon}</span>
      <span className="text-lg font-bold text-white">{title}</span>
      {status && (
        <span className={`text-xs px-2 py-0.5 rounded border ${statusBg(status)}`}>{status}</span>
      )}
      {score !== undefined && (
        <span className="ml-auto text-sm text-slate-400">
          Score <span className="font-bold text-white">{score.toFixed(0)}</span>
          {grade && <span className={`ml-1 font-bold ${gradeColor(grade)}`}>{grade}</span>}
        </span>
      )}
    </div>
  );
}
function DisabledCard() {
  return (
    <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-6 text-center">
      <Monitor className="w-10 h-10 text-slate-600 mx-auto mb-3" />
      <div className="text-slate-400 font-medium">Observability Center Disabled</div>
      <div className="text-slate-500 text-sm mt-1">
        Set <code className="font-mono text-sky-400">OBSERVABILITY_CENTER_ENABLED=true</code> to activate.
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
const TABS = [
  "Overview", "System", "Performance", "Database",
  "Cache", "Jobs", "Errors", "Alerts", "Audit",
  "Availability", "Flags", "Export",
] as const;
type Tab = typeof TABS[number];

export default function ObservabilityCenter() {
  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const [refreshKey, setRefreshKey] = useState(0);

  const opts = { refetchInterval: 30_000, refetchOnWindowFocus: false };

  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ["obs-summary", refreshKey],
    queryFn:  () => apiJson("observability/summary"),
    ...opts,
  });
  const { data: systemData, isLoading: sysLoading } = useQuery({
    queryKey: ["obs-system", refreshKey],
    queryFn:  () => apiJson("observability/system"),
    ...opts,
  });
  const { data: perfData } = useQuery({
    queryKey: ["obs-performance", refreshKey],
    queryFn:  () => apiJson("observability/performance"),
    ...opts,
  });
  const { data: errorsData } = useQuery({
    queryKey: ["obs-errors", refreshKey],
    queryFn:  () => apiJson("observability/errors"),
    ...opts,
  });
  const { data: alertsData } = useQuery({
    queryKey: ["obs-alerts", refreshKey],
    queryFn:  () => apiJson("observability/alerts"),
    ...opts,
  });
  const { data: auditData } = useQuery({
    queryKey: ["obs-audit", refreshKey],
    queryFn:  () => apiJson("observability/audit"),
    ...opts,
  });

  function refresh() { setRefreshKey(k => k + 1); }

  // ── Overview Tab ───────────────────────────────────────────────────────────
  function OverviewTab() {
    if (sumLoading || !summary) return <div className="text-slate-400 text-sm p-4">Loading overview…</div>;
    if (!summary.available)     return <DisabledCard />;
    return (
      <div className="space-y-6">
        {/* Score hero */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-6">
            <ScoreRing score={summary.observability_score ?? 0} grade={summary.grade ?? "—"} />
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <h2 className="text-xl font-bold text-white">Observability Score</h2>
                <span className={`px-2 py-0.5 text-xs rounded border ${statusBg("HEALTHY")}`}>
                  ADVISORY ONLY
                </span>
              </div>
              <div className="flex items-center gap-2 text-sm text-slate-400 flex-wrap">
                <TrendIcon t={summary.trend ?? "STABLE"} />
                <span>{summary.trend}</span>
                <span className="text-slate-600">·</span>
                <span>Updated {formatTs(summary.generated_at)}</span>
                <span className="text-slate-600">·</span>
                <span>Uptime {(summary.uptime_hours ?? 0).toFixed(1)}h</span>
              </div>
            </div>
          </div>
        </div>
        {/* Status KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KpiCard label="System"    value={summary.system_status}    status={summary.system_status}    icon={<Server    className="w-4 h-4" />} />
          <KpiCard label="Database"  value={summary.db_status}        status={summary.db_status}        icon={<Database  className="w-4 h-4" />} />
          <KpiCard label="Scheduler" value={summary.scheduler_status} status={summary.scheduler_status} icon={<Clock     className="w-4 h-4" />} />
          <KpiCard label="API"       value={summary.api_status}       status={summary.api_status}       icon={<Zap       className="w-4 h-4" />} />
        </div>
        {/* Numeric KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <NumCard label="Availability"  value={`${(summary.availability_pct ?? 0).toFixed(1)}%`}     sub="module availability" />
          <NumCard label="Perf Score"    value={`${(summary.performance_score ?? 0).toFixed(0)}/100`} sub="snapshot generation" />
          <NumCard label="Errors/h"      value={(summary.error_rate_per_h ?? 0).toFixed(1)} sub={`${summary.error_count_session ?? 0} total this session`} warn={(summary.error_rate_per_h ?? 0) > 5} />
          <NumCard label="Cache Entries" value={String(summary.cache_entries ?? 0)}          sub="in-process caches" />
        </div>
        {/* Critical alert banner */}
        {(alertsData?.critical_count ?? 0) > 0 && (
          <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-4">
            <div className="flex items-center gap-2 text-rose-400 font-semibold mb-2">
              <AlertTriangle className="w-4 h-4" />
              <span>{alertsData.critical_count} critical alert{alertsData.critical_count > 1 ? "s" : ""}</span>
            </div>
            {(alertsData.critical_alerts ?? []).slice(0, 3).map((a: any) => (
              <div key={a.alert_id} className="text-sm text-rose-300 mb-1">· {a.title}: {a.detail}</div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ── System Tab ─────────────────────────────────────────────────────────────
  function SystemTab() {
    if (sysLoading || !systemData) return <div className="text-slate-400 text-sm p-4">Loading system data…</div>;
    if (!systemData.available)    return <DisabledCard />;
    const d = systemData;
    return (
      <div className="space-y-6">
        <SectionHeader icon={<Server className="w-5 h-5" />} title="System Health"
          status={d.overall_status} score={d.health_score} />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Memory */}
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <HardDrive className="w-4 h-4 text-sky-400" />
              <span className="text-sm font-medium text-white">Memory</span>
              <span className={`ml-auto text-xs px-1.5 py-0.5 rounded border ${statusBg(d.memory?.status ?? "UNKNOWN")}`}>
                {d.memory?.status}
              </span>
            </div>
            <div className="text-2xl font-bold text-white">{(d.memory?.usage_pct ?? 0).toFixed(1)}%</div>
            <UsageBar pct={d.memory?.usage_pct ?? 0} />
            <div className="text-xs text-slate-500 mt-1">
              {(d.memory?.used_mb ?? 0).toFixed(0)} / {(d.memory?.total_mb ?? 0).toFixed(0)} MB
            </div>
          </div>
          {/* CPU */}
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Cpu className="w-4 h-4 text-violet-400" />
              <span className="text-sm font-medium text-white">CPU Load</span>
              <span className={`ml-auto text-xs px-1.5 py-0.5 rounded border ${statusBg(d.cpu?.status ?? "UNKNOWN")}`}>
                {d.cpu?.status}
              </span>
            </div>
            <div className="text-2xl font-bold text-white">{d.cpu?.load_1m ?? "—"}</div>
            <div className="text-xs text-slate-500 mt-1">
              1m avg · 5m: {d.cpu?.load_5m} · 15m: {d.cpu?.load_15m}
            </div>
          </div>
          {/* Disk */}
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <HardDrive className="w-4 h-4 text-amber-400" />
              <span className="text-sm font-medium text-white">Disk</span>
              <span className={`ml-auto text-xs px-1.5 py-0.5 rounded border ${statusBg(d.disk?.status ?? "UNKNOWN")}`}>
                {d.disk?.status}
              </span>
            </div>
            <div className="text-2xl font-bold text-white">{(d.disk?.usage_pct ?? 0).toFixed(1)}%</div>
            <UsageBar pct={d.disk?.usage_pct ?? 0} />
            <div className="text-xs text-slate-500 mt-1">
              {(d.disk?.used_gb ?? 0).toFixed(1)} / {(d.disk?.total_gb ?? 0).toFixed(1)} GB
            </div>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <InfoCard title="Process" icon={<Package className="w-4 h-4 text-teal-400" />}>
            <Row label="PID"     value={String(d.process?.pid     ?? "—")} />
            <Row label="RSS"     value={`${d.process?.rss_mb     ?? "—"} MB`} />
            <Row label="VM"      value={`${d.process?.vm_mb      ?? "—"} MB`} />
            <Row label="Threads" value={String(d.process?.threads ?? "—")} />
          </InfoCard>
          <InfoCard title="Uptime & Environment" icon={<Clock className="w-4 h-4 text-sky-400" />}>
            <Row label="Uptime"            value={`${(d.uptime_hours ?? 0).toFixed(1)}h (${(d.uptime_days ?? 0).toFixed(2)}d)`} />
            <Row label="Environment"       value={d.environment?.environment ?? "—"} />
            <Row label="Broker configured" value={d.environment?.broker_configured ? "Yes" : "No"} />
            <Row label="Missing critical"
              value={(d.environment?.missing_critical?.length ?? 0) === 0 ? "None" : d.environment?.missing_critical?.join(", ")}
              warn={(d.environment?.missing_critical?.length ?? 0) > 0} />
          </InfoCard>
        </div>
      </div>
    );
  }

  // ── Performance Tab ────────────────────────────────────────────────────────
  function PerformanceTab() {
    if (!perfData) return <div className="text-slate-400 text-sm p-4">Loading performance data…</div>;
    const d = perfData;
    return (
      <div className="space-y-6">
        <SectionHeader icon={<Gauge className="w-5 h-5" />} title="Performance Dashboard"
          status={d.status} score={d.overall_score} grade={d.grade} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <NumCard label="Avg Snapshot"  value={`${(d.avg_snapshot_ms ?? 0).toFixed(0)}ms`} sub="module response" />
          <NumCard label="Fast Modules"  value={String(d.fast_modules ?? 0)} sub="< 100ms" />
          <NumCard label="Slow Modules"  value={String(d.slow_modules ?? 0)} sub="> 500ms" warn={(d.slow_modules ?? 0) > 0} />
          <NumCard label="API p95"       value={`${(d.api_metrics?.stats?.p95_latency_ms ?? 0).toFixed(0)}ms`} sub="p95 latency" />
        </div>
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50">
            <span className="text-sm font-semibold text-white">Module Response Times</span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 border-b border-slate-700/30">
                <th className="text-left px-4 py-2">Module</th>
                <th className="text-right px-4 py-2">Response (ms)</th>
                <th className="text-right px-4 py-2">Grade</th>
                <th className="text-right px-4 py-2">Available</th>
              </tr>
            </thead>
            <tbody>
              {(d.module_probes ?? []).map((p: any) => (
                <tr key={p.module} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                  <td className="px-4 py-2 text-slate-300">{p.module}</td>
                  <td className="px-4 py-2 text-right font-mono text-white">{(p.response_ms ?? 0).toFixed(0)}</td>
                  <td className="px-4 py-2 text-right">
                    <span className={`text-xs font-semibold ${
                      p.grade === "FAST"      ? "text-emerald-400" :
                      p.grade === "NORMAL"    ? "text-sky-400"     :
                      p.grade === "SLOW"      ? "text-amber-400"   : "text-rose-400"}`}>
                      {p.grade}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right flex justify-end">
                    {p.available
                      ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      : <XCircle      className="w-4 h-4 text-rose-400" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {d.api_metrics?.available && (
          <InfoCard title="API Session Metrics" icon={<Zap className="w-4 h-4 text-amber-400" />}>
            <Row label="Requests"    value={String(d.api_metrics.stats?.request_count ?? 0)} />
            <Row label="Errors"      value={String(d.api_metrics.stats?.error_count   ?? 0)} />
            <Row label="Error rate"  value={`${d.api_metrics.stats?.error_rate_pct   ?? 0}%`} />
            <Row label="Avg latency" value={`${d.api_metrics.stats?.avg_latency_ms   ?? 0}ms`} />
            <Row label="p95 latency" value={`${d.api_metrics.stats?.p95_latency_ms   ?? 0}ms`} />
          </InfoCard>
        )}
      </div>
    );
  }

  // ── Errors Tab ─────────────────────────────────────────────────────────────
  function ErrorsTab() {
    if (!errorsData) return <div className="text-slate-400 text-sm p-4">Loading error data…</div>;
    const d = errorsData;
    return (
      <div className="space-y-6">
        <SectionHeader icon={<AlertCircle className="w-5 h-5" />} title="Error Monitor"
          status={d.status} score={d.health_score} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <NumCard label="Total Errors"    value={String(d.total_errors      ?? 0)} sub="this session"  warn={(d.total_errors ?? 0) > 10} />
          <NumCard label="App Errors"      value={String(d.app_errors        ?? 0)} sub="exceptions" />
          <NumCard label="API Errors"      value={String(d.api_errors        ?? 0)} sub="4xx/5xx" />
          <NumCard label="Rate / hour"     value={(d.error_rate_per_h        ?? 0).toFixed(1)} sub="errors/h" warn={(d.error_rate_per_h ?? 0) > 5} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <InfoCard title="By Error Type" icon={<BarChart3 className="w-4 h-4 text-violet-400" />}>
            {Object.keys(d.frequency?.by_type ?? {}).length === 0 ? (
              <p className="text-slate-500 text-xs py-2">No errors recorded this session.</p>
            ) : (
              Object.entries(d.frequency?.by_type ?? {}).map(([type, count]: any) => (
                <Row key={type} label={type} value={String(count)} />
              ))
            )}
          </InfoCard>
          <InfoCard title="By Source" icon={<Package className="w-4 h-4 text-teal-400" />}>
            {Object.keys(d.frequency?.by_source ?? {}).length === 0 ? (
              <p className="text-slate-500 text-xs py-2">No errors recorded this session.</p>
            ) : (
              Object.entries(d.frequency?.by_source ?? {}).map(([src, count]: any) => (
                <Row key={src} label={src} value={String(count)} />
              ))
            )}
          </InfoCard>
        </div>
        {(d.recent_errors ?? []).length > 0 && (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700/50 text-sm font-semibold text-white">
              Recent Errors
            </div>
            <div className="divide-y divide-slate-700/30 max-h-64 overflow-y-auto">
              {(d.recent_errors ?? []).slice(0, 20).map((e: any) => (
                <div key={e.error_id} className="px-4 py-2 hover:bg-slate-700/20">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-rose-400 font-mono">{e.error_type}</span>
                    <span className="text-xs text-slate-500">· {e.source}</span>
                    <span className="ml-auto text-xs text-slate-600">{formatTs(e.ts)}</span>
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5 truncate">{e.message}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        {d.note && <p className="text-xs text-slate-500">{d.note}</p>}
      </div>
    );
  }

  // ── Alerts Tab ─────────────────────────────────────────────────────────────
  function AlertsTab() {
    if (!alertsData) return <div className="text-slate-400 text-sm p-4">Loading alerts…</div>;
    const d = alertsData;
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <NumCard label="Active"   value={String(d.total_active   ?? 0)} sub="open alerts"  warn={(d.total_active   ?? 0) > 0} />
          <NumCard label="Critical" value={String(d.critical_count ?? 0)} sub="need attention" warn={(d.critical_count ?? 0) > 0} />
          <NumCard label="Warnings" value={String(d.warning_count  ?? 0)} sub="investigate" />
          <NumCard label="Resolved" value={String(d.resolved_count ?? 0)} sub="this session" />
        </div>
        {(d.total_active ?? 0) === 0 && (
          <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-5 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
            <div className="text-emerald-400 font-semibold">All Clear</div>
            <div className="text-xs text-slate-400 mt-1">No active alerts — system operating normally.</div>
          </div>
        )}
        {[
          { label: "Critical Alerts", items: d.critical_alerts ?? [], sev: "CRITICAL" },
          { label: "Warnings",        items: d.warnings        ?? [], sev: "WARNING"  },
        ].map(group => group.items.length > 0 && (
          <div key={group.label} className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700/50 text-sm font-semibold text-white">{group.label}</div>
            <div className="divide-y divide-slate-700/30">
              {group.items.map((a: any) => (
                <div key={a.alert_id} className="px-4 py-3 hover:bg-slate-700/20">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`text-xs px-1.5 py-0.5 rounded border font-semibold ${sevColor(a.severity)}`}>{a.severity}</span>
                    <span className="text-xs text-slate-500">{a.category}</span>
                    <span className="ml-auto text-xs text-slate-600">{formatTs(a.generated_at)}</span>
                  </div>
                  <div className="text-sm text-white font-medium">{a.title}</div>
                  <div className="text-xs text-slate-400 mt-0.5">{a.detail}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // ── Audit Tab ──────────────────────────────────────────────────────────────
  function AuditTab() {
    if (!auditData) return <div className="text-slate-400 text-sm p-4">Loading audit data…</div>;
    const d = auditData;
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <NumCard label="Total Entries" value={String(d.total_entries ?? 0)} sub="this session" />
          {Object.entries(d.category_counts ?? {}).slice(0, 3).map(([cat, cnt]: any) => (
            <NumCard key={cat} label={cat} value={String(cnt)} sub="events" />
          ))}
        </div>
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50 text-sm font-semibold text-white">Event Timeline</div>
          <div className="divide-y divide-slate-700/30 max-h-96 overflow-y-auto">
            {(d.timeline ?? []).length === 0 ? (
              <div className="px-4 py-6 text-center text-slate-500 text-sm">No audit entries recorded yet.</div>
            ) : (
              (d.timeline ?? []).map((e: any, i: number) => (
                <div key={i} className="px-4 py-2.5 hover:bg-slate-700/20 flex items-start gap-3">
                  <div className="w-1.5 h-1.5 rounded-full bg-sky-400 mt-2 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-mono text-sky-400">{e.action}</span>
                      <span className="text-xs text-slate-500">by {e.actor}</span>
                      <span className={`ml-auto text-xs px-1 py-0.5 rounded ${statusBg("UNKNOWN")}`}>{e.category}</span>
                    </div>
                    <div className="text-xs text-slate-400 truncate mt-0.5">{e.detail}</div>
                    <div className="text-xs text-slate-600">{formatTs(e.ts)}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Availability Tab ───────────────────────────────────────────────────────
  function AvailabilityTab() {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <NumCard label="Availability" value={`${(summary?.availability_pct ?? 0).toFixed(1)}%`} sub="module availability" />
          <NumCard label="Uptime"       value={`${(summary?.uptime_hours ?? 0).toFixed(1)}h`}     sub="process uptime" />
          <NumCard label="Perf Score"   value={`${(summary?.performance_score ?? 0).toFixed(0)}/100`} sub="overall" />
        </div>
        {systemData?.feature_flags && (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-700/50 text-sm font-semibold text-white">
              Module Availability ({systemData.feature_flags.enabled_count}/{systemData.feature_flags.total_flags} enabled)
            </div>
            <div className="divide-y divide-slate-700/30">
              {Object.entries(systemData.feature_flags.flags ?? {}).map(([flag, enabled]: any) => (
                <div key={flag} className="px-4 py-2.5 flex items-center hover:bg-slate-700/20">
                  <span className="text-xs font-mono text-slate-300">{flag}</span>
                  <span className={`ml-auto text-xs px-2 py-0.5 rounded border ${enabled ? statusBg("HEALTHY") : statusBg("DISABLED")}`}>
                    {enabled ? "ENABLED" : "DISABLED"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Flags Tab ──────────────────────────────────────────────────────────────
  function FlagsTab() {
    if (!systemData) return <div className="text-slate-400 text-sm p-4">Loading flag data…</div>;
    const flags = systemData.feature_flags ?? { flags: {}, enabled_count: 0, total_flags: 0 };
    return (
      <div className="space-y-6">
        <p className="text-slate-400 text-sm font-medium">
          {flags.enabled_count} of {flags.total_flags} feature flags enabled
        </p>
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="divide-y divide-slate-700/30">
            {Object.entries(flags.flags ?? {}).map(([flag, enabled]: any) => (
              <div key={flag} className="px-4 py-3 flex items-center hover:bg-slate-700/20">
                <div>
                  <div className="text-sm font-mono text-slate-300">{flag}</div>
                  <div className="text-xs text-slate-500 mt-0.5">Environment variable</div>
                </div>
                <div className="ml-auto flex items-center gap-2">
                  {enabled
                    ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    : <XCircle      className="w-4 h-4 text-slate-600" />}
                  <span className={`text-xs font-semibold ${enabled ? "text-emerald-400" : "text-slate-500"}`}>
                    {enabled ? "ENABLED" : "DISABLED"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Database / Cache / Jobs stub tabs ─────────────────────────────────────
  function StubTab({ icon, title, note }: { icon: React.ReactNode; title: string; note: string }) {
    return (
      <div className="space-y-4">
        <SectionHeader icon={icon} title={title} />
        <InfoCard title="Note" icon={<Info className="w-4 h-4 text-sky-400" />}>
          <p className="text-xs text-slate-400">{note}</p>
        </InfoCard>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <NumCard label="System Status" value={summary?.system_status ?? "—"} sub="see System tab" />
          <NumCard label="Alerts"        value={String(alertsData?.total_active ?? 0)} sub="see Alerts tab" />
          <NumCard label="Perf Score"    value={`${(summary?.performance_score ?? 0).toFixed(0)}/100`} sub="see Performance tab" />
        </div>
      </div>
    );
  }

  // ── Export Tab ─────────────────────────────────────────────────────────────
  function ExportTab() {
    const [exporting, setExporting] = useState(false);
    async function download(fmt: "csv" | "json") {
      setExporting(true);
      try {
        const d = await apiJson(`observability/export?format=${fmt}`);
        const content = fmt === "csv" ? d.csv ?? "" : JSON.stringify(d, null, 2);
        const mime    = fmt === "csv" ? "text/csv" : "application/json";
        const blob = new Blob([content], { type: mime });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement("a");
        a.href = url; a.download = `observability_export.${fmt}`; a.click();
        URL.revokeObjectURL(url);
      } finally { setExporting(false); }
    }
    return (
      <div className="space-y-6">
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 space-y-4">
          <h3 className="text-white font-semibold">Export Observability Data</h3>
          <p className="text-slate-400 text-sm">
            Download a snapshot of all observability metrics for offline analysis or audit purposes.
          </p>
          <div className="flex gap-3">
            <button onClick={() => download("csv")} disabled={exporting}
              className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg disabled:opacity-50 transition-colors">
              <Download className="w-4 h-4" /> Export CSV
            </button>
            <button onClick={() => download("json")} disabled={exporting}
              className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white text-sm rounded-lg disabled:opacity-50 transition-colors">
              <Download className="w-4 h-4" /> Export JSON
            </button>
          </div>
        </div>
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
          <div className="flex items-start gap-2">
            <Info className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" />
            <div>
              <div className="text-amber-400 text-sm font-semibold">Advisory Export Only</div>
              <div className="text-amber-300/70 text-xs mt-1">
                This export contains observability snapshots only. No trading data, positions, or strategy
                configurations are included. All data is read-only and advisory.
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const criticalCount = alertsData?.critical_count ?? 0;
  const isLoading     = sumLoading;

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Header */}
      <div className="border-b border-slate-800 bg-slate-900/80 sticky top-0 z-10 backdrop-blur-sm">
        <div className="px-4 py-3 flex items-center gap-3 flex-wrap">
          <Monitor className="w-5 h-5 text-sky-400 flex-shrink-0" />
          <h1 className="text-lg font-bold text-white">Observability Center</h1>
          <span className="text-xs px-2 py-0.5 bg-sky-500/15 text-sky-400 border border-sky-500/30 rounded whitespace-nowrap">
            Phase 8.1 · Advisory Only
          </span>
          {summary?.observability_score !== undefined && (
            <span className={`ml-auto text-sm font-bold ${gradeColor(summary.grade)}`}>
              {summary.observability_score.toFixed(0)}/100 · {summary.grade}
            </span>
          )}
          <button onClick={refresh}
            className="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors">
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
        {/* Tab bar */}
        <div className="px-4 flex gap-0.5 overflow-x-auto pb-1 scrollbar-none">
          {TABS.map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              className={`px-3 py-1.5 text-xs font-medium rounded-t whitespace-nowrap transition-colors ${
                activeTab === tab
                  ? "bg-slate-700/60 text-white border-b-2 border-sky-500"
                  : "text-slate-500 hover:text-slate-300"
              }`}>
              {tab}
              {tab === "Alerts" && criticalCount > 0 && (
                <span className="ml-1 bg-rose-500 text-white text-xs rounded-full px-1.5 py-0.5">
                  {criticalCount}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        {activeTab === "Overview"     && <OverviewTab />}
        {activeTab === "System"       && <SystemTab />}
        {activeTab === "Performance"  && <PerformanceTab />}
        {activeTab === "Database"     && <StubTab icon={<Database   className="w-5 h-5" />} title="Database Metrics"   note="DB connectivity is probed via the Python DB layer. Check Alerts for active database alerts, and System for overall health." />}
        {activeTab === "Cache"        && <StubTab icon={<Package    className="w-5 h-5" />} title="Cache Metrics"      note="In-process Python module caches are introspected. Cache entry counts appear in the Overview summary." />}
        {activeTab === "Jobs"         && <StubTab icon={<Clock      className="w-5 h-5" />} title="Background Jobs"    note="Job scheduler status is derived from the latest scan snapshot. Check Alerts for stale scan warnings." />}
        {activeTab === "Errors"       && <ErrorsTab />}
        {activeTab === "Alerts"       && <AlertsTab />}
        {activeTab === "Audit"        && <AuditTab />}
        {activeTab === "Availability" && <AvailabilityTab />}
        {activeTab === "Flags"        && <FlagsTab />}
        {activeTab === "Export"       && <ExportTab />}
      </div>
    </div>
  );
}
