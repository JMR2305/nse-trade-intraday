// No live dataset used on this page
/**
 * DataQuality.tsx — Phase 8.3
 * Data Quality & Validation Framework Dashboard — ApexQuant AI
 *
 * 11 tabs: Overview · Market · Pre-Open · Paper Trading · Portfolio ·
 *          AI · Signals · Configuration · Alerts · History · Export
 *
 * READ-ONLY · ADVISORY-ONLY. Never modifies any data source.
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3, ShieldCheck, Zap, Activity, PieChart,
  Brain, Radio, Settings, Bell, Clock, Download,
  AlertTriangle, CheckCircle, XCircle, Info, Copy,
  ChevronDown, ChevronUp, RefreshCw,
} from "lucide-react";
import { apiJson } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type Grade = "A+" | "A" | "B" | "C" | "D" | string;

interface Issue {
  severity:  string;
  check:     string;
  field:     string;
  message:   string;
  symbol?:   string;
  value?:    unknown;
  domain?:   string;
}

interface DomainResult {
  status?:         string;
  available?:      boolean;
  advisory_only?:  boolean;
  domain?:         string;
  score?:          number;
  grade?:          Grade;
  checks_run?:     number;
  checks_passed?:  number;
  checks_failed?:  number;
  pass_rate?:      number;
  critical_count?: number;
  warning_count?:  number;
  issues?:         Issue[];
  generated_at?:   string;
  symbols_checked?: number;
  trades_checked?:  number;
  signals_checked?: number;
  flag_states?:     Record<string, string>;
  provider?:        string;
  note?:            string;
  [key: string]: unknown;
}

interface Summary {
  status?:           string;
  available?:        boolean;
  advisory_only?:    boolean;
  message?:          string;
  quality_score?:    number;
  grade?:            Grade;
  score_components?: Record<string, number>;
  total_issues?:     number;
  critical_count?:   number;
  warning_count?:    number;
  domains?:          Array<{
    domain:        string;
    score:         number;
    grade:         Grade;
    checks_run:    number;
    checks_passed: number;
    checks_failed: number;
    critical:      number;
    warnings:      number;
  }>;
  generated_at?: string;
}

interface AlertsData {
  status?:         string;
  available?:      boolean;
  total?:          number;
  total_critical?: number;
  total_warnings?: number;
  critical?:       Issue[];
  warnings?:       Issue[];
  info?:           Issue[];
  duplicates?:     Issue[];
  missing?:        Issue[];
  stale?:          Issue[];
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

const TABS = [
  { id: "overview",   label: "Overview",      icon: <BarChart3   className="w-4 h-4" /> },
  { id: "market",     label: "Market Data",   icon: <Activity    className="w-4 h-4" /> },
  { id: "preopen",    label: "Pre-Open",       icon: <Zap         className="w-4 h-4" /> },
  { id: "paper",      label: "Paper Trading", icon: <Radio       className="w-4 h-4" /> },
  { id: "portfolio",  label: "Portfolio",     icon: <PieChart    className="w-4 h-4" /> },
  { id: "ai",         label: "AI",            icon: <Brain       className="w-4 h-4" /> },
  { id: "signals",    label: "Signals",       icon: <ShieldCheck className="w-4 h-4" /> },
  { id: "config",     label: "Configuration", icon: <Settings    className="w-4 h-4" /> },
  { id: "alerts",     label: "Alerts",        icon: <Bell        className="w-4 h-4" /> },
  { id: "history",    label: "History",       icon: <Clock       className="w-4 h-4" /> },
  { id: "export",     label: "Export",        icon: <Download    className="w-4 h-4" /> },
] as const;
type TabId = typeof TABS[number]["id"];

const POLL = 60_000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(v: unknown, decimals = 1): string {
  if (v == null) return "—";
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return n.toFixed(decimals);
}

function gradeColor(g: Grade): string {
  if (g === "A+") return "text-emerald-400";
  if (g === "A")  return "text-blue-400";
  if (g === "B")  return "text-yellow-400";
  if (g === "C")  return "text-orange-400";
  return "text-red-400";
}

function scoreColor(s: number): string {
  if (s >= 90) return "text-emerald-400";
  if (s >= 75) return "text-blue-400";
  if (s >= 60) return "text-yellow-400";
  return "text-red-400";
}

function severityColor(sev: string): string {
  const s = (sev || "").toUpperCase();
  if (s === "CRITICAL")  return "text-red-400 bg-red-400/10";
  if (s === "WARNING")   return "text-yellow-400 bg-yellow-400/10";
  if (s === "DUPLICATE") return "text-orange-400 bg-orange-400/10";
  if (s === "MISSING")   return "text-purple-400 bg-purple-400/10";
  if (s === "STALE")     return "text-cyan-400 bg-cyan-400/10";
  return "text-slate-400 bg-slate-700/40";
}

function SeverityIcon({ sev }: { sev: string }) {
  const s = (sev || "").toUpperCase();
  if (s === "CRITICAL")  return <XCircle     className="w-3.5 h-3.5 text-red-400"    />;
  if (s === "WARNING")   return <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" />;
  if (s === "DUPLICATE") return <Copy        className="w-3.5 h-3.5 text-orange-400" />;
  return                        <Info        className="w-3.5 h-3.5 text-slate-400"  />;
}

// ── Shared UI primitives ──────────────────────────────────────────────────────

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 ${className}`}>
      {children}
    </div>
  );
}

function KpiCard({ label, value, sub, color }: { label: string; value: React.ReactNode; sub?: string; color?: string }) {
  return (
    <Card>
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-lg font-semibold leading-tight ${color ?? "text-slate-100"}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </Card>
  );
}

function SectionHeader({ icon, title, sub }: { icon: React.ReactNode; title: string; sub?: string }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <div className="p-2 bg-teal-500/10 rounded-lg">{icon}</div>
      <div>
        <h2 className="text-base font-semibold text-slate-100">{title}</h2>
        {sub && <p className="text-xs text-slate-500">{sub}</p>}
      </div>
    </div>
  );
}

function ScoreRing({ score, label }: { score: number; label: string }) {
  const r    = 52;
  const circ = 2 * Math.PI * r;
  const fill = (Math.min(score, 100) / 100) * circ;
  const color = score >= 90 ? "#34d399" : score >= 75 ? "#60a5fa" : score >= 60 ? "#fbbf24" : "#f87171";
  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="130" height="130" viewBox="0 0 130 130">
        <circle cx="65" cy="65" r={r} fill="none" stroke="#1e293b" strokeWidth="14" />
        <circle
          cx="65" cy="65" r={r} fill="none"
          stroke={color} strokeWidth="14"
          strokeDasharray={`${fill} ${circ - fill}`}
          strokeLinecap="round"
          transform="rotate(-90 65 65)"
          style={{ transition: "stroke-dasharray 0.6s ease" }}
          data-testid="dq-score-arc"
        />
        <text x="65" y="59" textAnchor="middle" fill={color} fontSize="26" fontWeight="bold"
              data-testid="dq-score-total">
          {Math.round(score)}
        </text>
        <text x="65" y="75" textAnchor="middle" fill="#94a3b8" fontSize="11">/100</text>
      </svg>
      <span className={`text-sm font-semibold ${scoreColor(score)}`}>{label}</span>
    </div>
  );
}

function DisabledView({ msg }: { msg?: string }) {
  return (
    <Card className="text-center py-12">
      <ShieldCheck className="w-8 h-8 text-slate-600 mx-auto mb-3" />
      <p className="text-slate-400 text-sm font-medium">Data Quality Disabled</p>
      <p className="text-slate-500 text-xs mt-1">{msg ?? "Set DATA_QUALITY_ENABLED=true"}</p>
    </Card>
  );
}

function LoadingView() {
  return (
    <div className="flex items-center justify-center py-20">
      <RefreshCw className="w-6 h-6 text-slate-500 animate-spin" />
    </div>
  );
}

// ── Issue table (shared by all domain tabs) ───────────────────────────────────

function IssueTable({ issues }: { issues: Issue[] }) {
  if (!issues || issues.length === 0) {
    return (
      <div className="flex items-center gap-2 py-6 text-emerald-400">
        <CheckCircle className="w-5 h-5" />
        <span className="text-sm font-medium">All checks passed — no issues detected</span>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-700/50">
            {["Severity", "Check", "Field", "Message", "Symbol"].map(h => (
              <th key={h} className="pb-2 px-2 text-left text-slate-500 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, i) => (
            <tr key={i} className="border-b border-slate-700/20 hover:bg-slate-700/10">
              <td className="py-2 px-2">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${severityColor(issue.severity)}`}>
                  <SeverityIcon sev={issue.severity} />
                  {issue.severity}
                </span>
              </td>
              <td className="py-2 px-2 font-mono text-slate-300">{issue.check}</td>
              <td className="py-2 px-2 text-slate-400">{issue.field}</td>
              <td className="py-2 px-2 text-slate-300 max-w-xs truncate">{issue.message}</td>
              <td className="py-2 px-2 text-slate-400">{issue.symbol ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Domain tab renderer (generic) ─────────────────────────────────────────────

function DomainTab({
  data, domainLabel, icon, extra,
}: {
  data: DomainResult | undefined;
  domainLabel: string;
  icon: React.ReactNode;
  extra?: React.ReactNode;
}) {
  if (!data) return <LoadingView />;
  if (data.status === "DISABLED" || !data.available)
    return <DisabledView msg={data.message as string | undefined} />;

  const score   = data.score ?? 0;
  const passed  = data.checks_passed ?? 0;
  const failed  = data.checks_failed ?? 0;
  const run     = data.checks_run ?? 0;

  return (
    <div className="space-y-5">
      <SectionHeader icon={icon} title={`${domainLabel} Validation`}
        sub={`Generated: ${data.generated_at?.slice(0, 16) ?? "—"} UTC`} />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Quality Score" value={`${fmt(score)}%`}
          color={scoreColor(score)} />
        <KpiCard label="Grade" value={data.grade ?? "—"}
          color={gradeColor(data.grade ?? "D")} />
        <KpiCard label="Checks Passed" value={`${passed} / ${run}`}
          color={failed === 0 ? "text-emerald-400" : "text-yellow-400"} />
        <KpiCard label="Critical Issues" value={data.critical_count ?? 0}
          color={(data.critical_count ?? 0) > 0 ? "text-red-400" : "text-emerald-400"} />
      </div>
      {extra}
      <Card>
        <p className="text-xs font-semibold text-slate-400 mb-3">Issues Detected</p>
        <IssueTable issues={data.issues ?? []} />
      </Card>
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function renderOverview(S: Summary | undefined | null) {
  if (!S) return <LoadingView />;
  if (S.status === "DISABLED") return <DisabledView msg={S.message as string | undefined} />;
  if (!S.available) return <DisabledView />;

  const score = S.quality_score ?? 0;
  const comps = S.score_components ?? {};

  const DOMAIN_LABELS: Record<string, string> = {
    market: "Market Data", preopen: "Pre-Open", paper: "Paper Trading",
    portfolio: "Portfolio", ai: "AI", signals: "Signals", config: "Configuration",
  };

  return (
    <div className="space-y-5">
      <SectionHeader icon={<BarChart3 className="w-4 h-4 text-teal-400" />}
        title="Data Quality Overview"
        sub={`Generated: ${S.generated_at?.slice(0, 16) ?? "—"} UTC · Advisory Only`} />

      {/* Score + advisory badge */}
      <div className="flex flex-col sm:flex-row gap-5 items-start">
        <div className="flex flex-col items-center gap-2">
          <ScoreRing score={score} label={S.grade ?? "D"} />
          <span className="text-xs px-2 py-1 rounded-full bg-amber-500/10 text-amber-400 font-medium">
            ADVISORY ONLY
          </span>
        </div>
        <div className="flex-1 grid grid-cols-2 sm:grid-cols-3 gap-3">
          {Object.entries(comps).map(([dim, val]) => (
            <KpiCard key={dim}
              label={dim.charAt(0).toUpperCase() + dim.slice(1)}
              value={`${fmt(val)}%`}
              color={scoreColor(val)} />
          ))}
        </div>
      </div>

      {/* Alert summary */}
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label="Total Issues" value={S.total_issues ?? 0} />
        <KpiCard label="Critical" value={S.critical_count ?? 0}
          color={(S.critical_count ?? 0) > 0 ? "text-red-400" : "text-emerald-400"} />
        <KpiCard label="Warnings" value={S.warning_count ?? 0}
          color={(S.warning_count ?? 0) > 0 ? "text-yellow-400" : "text-emerald-400"} />
      </div>

      {/* Domain summary table */}
      <Card>
        <p className="text-xs font-semibold text-slate-400 mb-3">Domain Scores</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700/50">
                {["Domain", "Score", "Grade", "Passed", "Failed", "Critical", "Warnings"].map(h => (
                  <th key={h} className="pb-2 px-2 text-left text-slate-500 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(S.domains ?? []).map(d => (
                <tr key={d.domain} className="border-b border-slate-700/20 hover:bg-slate-700/10">
                  <td className="py-2 px-2 text-slate-200 font-medium">{DOMAIN_LABELS[d.domain] ?? d.domain}</td>
                  <td className="py-2 px-2">
                    <span className={scoreColor(d.score)}>{fmt(d.score)}%</span>
                  </td>
                  <td className={`py-2 px-2 font-bold ${gradeColor(d.grade)}`}>{d.grade}</td>
                  <td className="py-2 px-2 text-emerald-400">{d.checks_passed}</td>
                  <td className={`py-2 px-2 ${d.checks_failed > 0 ? "text-red-400" : "text-slate-400"}`}>{d.checks_failed}</td>
                  <td className={`py-2 px-2 ${d.critical > 0 ? "text-red-400" : "text-slate-500"}`}>{d.critical}</td>
                  <td className={`py-2 px-2 ${d.warnings > 0 ? "text-yellow-400" : "text-slate-500"}`}>{d.warnings}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ── Config tab extra content ──────────────────────────────────────────────────

function ConfigExtra({ data }: { data: DomainResult }) {
  const flags     = data.flag_states as Record<string, string> | undefined;
  const provider  = data.provider as string | undefined;
  if (!flags) return null;
  return (
    <Card>
      <p className="text-xs font-semibold text-slate-400 mb-3">Feature Flags</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {Object.entries(flags).map(([flag, state]) => (
          <div key={flag} className="flex items-center justify-between py-1.5 px-2 rounded bg-slate-700/30">
            <span className="font-mono text-xs text-slate-300">{flag}</span>
            <span className={`text-xs font-bold ${state === "ENABLED" ? "text-emerald-400" : "text-slate-500"}`}>
              {state}
            </span>
          </div>
        ))}
      </div>
      {provider && (
        <p className="text-xs text-slate-500 mt-2">
          Market data provider: <span className="text-slate-300 font-mono">{provider}</span>
        </p>
      )}
    </Card>
  );
}

// ── Alerts tab ────────────────────────────────────────────────────────────────

function AlertsSection({ label, issues, color }: { label: string; issues: Issue[]; color: string }) {
  const [open, setOpen] = useState(true);
  if (!issues || issues.length === 0) return null;
  return (
    <Card>
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between">
        <span className={`text-sm font-semibold ${color}`}>
          {label} ({issues.length})
        </span>
        {open ? <ChevronUp className="w-4 h-4 text-slate-500" />
               : <ChevronDown className="w-4 h-4 text-slate-500" />}
      </button>
      {open && (
        <div className="mt-3">
          <IssueTable issues={issues} />
        </div>
      )}
    </Card>
  );
}

function renderAlerts(A: AlertsData | undefined | null) {
  if (!A) return <LoadingView />;
  if (A.status === "DISABLED") return <DisabledView />;

  const total = A.total ?? 0;

  return (
    <div className="space-y-4">
      <SectionHeader icon={<Bell className="w-4 h-4 text-teal-400" />}
        title="All Alerts"
        sub={`${total} total · ${A.total_critical ?? 0} critical · ${A.total_warnings ?? 0} warnings`} />
      {total === 0 ? (
        <div className="flex items-center gap-2 py-8 text-emerald-400">
          <CheckCircle className="w-5 h-5" />
          <span className="text-sm font-medium">No alerts — all data quality checks passing</span>
        </div>
      ) : (
        <>
          <AlertsSection label="Critical"   issues={A.critical   ?? []} color="text-red-400"    />
          <AlertsSection label="Warnings"   issues={A.warnings   ?? []} color="text-yellow-400" />
          <AlertsSection label="Duplicates" issues={A.duplicates ?? []} color="text-orange-400" />
          <AlertsSection label="Missing"    issues={A.missing    ?? []} color="text-purple-400" />
          <AlertsSection label="Stale"      issues={A.stale      ?? []} color="text-cyan-400"   />
          <AlertsSection label="Info"       issues={A.info       ?? []} color="text-slate-400"  />
        </>
      )}
    </div>
  );
}

// ── Export tab ────────────────────────────────────────────────────────────────

function renderExport(qc: unknown) {
  return (
    <div className="space-y-5">
      <SectionHeader icon={<Download className="w-4 h-4 text-teal-400" />}
        title="Export Validation Report"
        sub="Advisory-only outputs — do not use for automated trading decisions" />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card className="flex flex-col items-start gap-3">
          <p className="text-sm font-semibold text-slate-200">Full JSON Report</p>
          <p className="text-xs text-slate-500">
            Complete validation results for all 7 domains including issues, scores,
            grades, and score components.
          </p>
          <button
            onClick={() => {
              apiJson("data-quality/export?format=json").then((data: unknown) => {
                const blob = new Blob([JSON.stringify(data, null, 2)],
                                      { type: "application/json" });
                const url  = URL.createObjectURL(blob);
                const a    = document.createElement("a");
                a.href = url; a.download = "data-quality-report.json"; a.click();
              });
            }}
            className="px-4 py-2 bg-teal-600 hover:bg-teal-500 text-white text-xs font-medium rounded-lg transition-colors"
            data-testid="download-json"
          >
            Download JSON
          </button>
        </Card>
        <Card className="flex flex-col items-start gap-3">
          <p className="text-sm font-semibold text-slate-200">CSV Issue List</p>
          <p className="text-xs text-slate-500">
            All detected issues in tabular format: domain, severity, check, field,
            message, symbol, value.
          </p>
          <button
            onClick={() => {
              apiJson("data-quality/export?format=csv").then((data: unknown) => {
                const csv  = (data as Record<string, string>)?.csv ?? "";
                const blob = new Blob([csv], { type: "text/csv" });
                const url  = URL.createObjectURL(blob);
                const a    = document.createElement("a");
                a.href = url; a.download = "data-quality-issues.csv"; a.click();
              });
            }}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs font-medium rounded-lg transition-colors"
            data-testid="download-csv"
          >
            Download CSV
          </button>
        </Card>
      </div>
      <Card>
        <p className="text-xs text-amber-400 font-medium mb-1">⚠ Advisory Only</p>
        <p className="text-xs text-slate-500">
          All exports are read-only advisory reports. This module never modifies market data,
          paper trades, AI predictions, strategies, portfolio, execution engine, or any data source.
          Exports are for operator review only — Phase 8.3 · ApexQuant AI.
        </p>
      </Card>
    </div>
  );
}

// ── History tab ───────────────────────────────────────────────────────────────

function renderHistory() {
  return (
    <div className="space-y-4">
      <SectionHeader icon={<Clock className="w-4 h-4 text-teal-400" />}
        title="Validation Run History"
        sub="Historical validation snapshots — available in Phase 8.4+" />
      <Card className="py-10 text-center">
        <Clock className="w-8 h-8 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 text-sm font-medium">History Coming in Phase 8.4</p>
        <p className="text-slate-500 text-xs mt-1">
          Validation run history will be stored and queryable in the next phase.
          Each run will record scores, grades, and issue counts per domain.
        </p>
      </Card>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DataQuality() {
  const [tab, setTab] = useState<TabId>("overview");

  const summary   = useQuery<Summary>({
    queryKey: ["dq-summary"],
    queryFn:  () => apiJson("data-quality/summary"),
    refetchInterval: POLL,
  });

  const market = useQuery<DomainResult>({
    queryKey: ["dq-market"],
    queryFn:  () => apiJson("data-quality/market"),
    enabled:  tab === "market",
    refetchInterval: POLL,
  });

  const preopen = useQuery<DomainResult>({
    queryKey: ["dq-preopen"],
    queryFn:  () => apiJson("data-quality/preopen"),
    enabled:  tab === "preopen",
    refetchInterval: POLL,
  });

  const paper = useQuery<DomainResult>({
    queryKey: ["dq-paper"],
    queryFn:  () => apiJson("data-quality/paper"),
    enabled:  tab === "paper",
    refetchInterval: POLL,
  });

  const portfolio = useQuery<DomainResult>({
    queryKey: ["dq-portfolio"],
    queryFn:  () => apiJson("data-quality/portfolio"),
    enabled:  tab === "portfolio",
    refetchInterval: POLL,
  });

  const ai = useQuery<DomainResult>({
    queryKey: ["dq-ai"],
    queryFn:  () => apiJson("data-quality/ai"),
    enabled:  tab === "ai",
    refetchInterval: POLL,
  });

  const signals = useQuery<DomainResult>({
    queryKey: ["dq-signals"],
    queryFn:  () => apiJson("data-quality/signals"),
    enabled:  tab === "signals",
    refetchInterval: POLL,
  });

  const config = useQuery<DomainResult>({
    queryKey: ["dq-config"],
    queryFn:  () => apiJson("data-quality/config"),
    enabled:  tab === "config",
    refetchInterval: POLL,
  });

  const alerts = useQuery<AlertsData>({
    queryKey: ["dq-alerts"],
    queryFn:  () => apiJson("data-quality/alerts"),
    enabled:  tab === "alerts",
    refetchInterval: POLL,
  });

  const S = summary.data;

  const tabContent: Record<TabId, () => React.ReactNode> = {
    overview:  () => renderOverview(S),
    market:    () => (
      <DomainTab data={market.data}    domainLabel="Market Data"   icon={<Activity    className="w-4 h-4 text-teal-400" />}
        extra={market.data?.symbols_checked != null && (
          <p className="text-xs text-slate-500">Symbols checked: {market.data.symbols_checked}</p>
        )}
      />
    ),
    preopen:   () => (
      <DomainTab data={preopen.data}   domainLabel="Pre-Open Data"  icon={<Zap         className="w-4 h-4 text-teal-400" />}
        extra={preopen.data?.symbols_checked != null && (
          <p className="text-xs text-slate-500">Symbols checked: {preopen.data.symbols_checked}</p>
        )}
      />
    ),
    paper:     () => (
      <DomainTab data={paper.data}     domainLabel="Paper Trading"  icon={<Radio       className="w-4 h-4 text-teal-400" />}
        extra={paper.data?.trades_checked != null && (
          <p className="text-xs text-slate-500">Trades checked: {paper.data.trades_checked}</p>
        )}
      />
    ),
    portfolio: () => (
      <DomainTab data={portfolio.data} domainLabel="Portfolio"      icon={<PieChart    className="w-4 h-4 text-teal-400" />} />
    ),
    ai:        () => (
      <DomainTab data={ai.data}        domainLabel="AI Data"        icon={<Brain       className="w-4 h-4 text-teal-400" />} />
    ),
    signals:   () => (
      <DomainTab data={signals.data}   domainLabel="Signals"        icon={<ShieldCheck className="w-4 h-4 text-teal-400" />}
        extra={signals.data?.note && (
          <p className="text-xs text-slate-500 italic">{String(signals.data.note)}</p>
        )}
      />
    ),
    config:    () => (
      <DomainTab data={config.data}    domainLabel="Configuration"  icon={<Settings    className="w-4 h-4 text-teal-400" />}
        extra={config.data?.available && <ConfigExtra data={config.data} />}
      />
    ),
    alerts:    () => renderAlerts(alerts.data),
    history:   () => renderHistory(),
    export:    () => renderExport(null),
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-4 sm:p-6">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <ShieldCheck className="w-6 h-6 text-teal-400" />
          <h1 className="text-xl font-bold text-slate-100">Data Quality</h1>
          {S?.grade && (
            <span className={`text-sm font-bold px-2 py-0.5 rounded ${gradeColor(S.grade)} bg-slate-800`}>
              {S.grade}
            </span>
          )}
        </div>
        <p className="text-sm text-slate-500">
          Data Quality &amp; Validation Framework · Phase 8.3 · Advisory Only
        </p>
        {(S?.critical_count ?? 0) > 0 && (
          <div className="mt-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-medium">
            <XCircle className="w-4 h-4" />
            {S!.critical_count} critical data quality issue{(S!.critical_count ?? 0) > 1 ? "s" : ""} detected — review Alerts tab
          </div>
        )}
      </div>

      {/* Tab navigation */}
      <div className="flex flex-wrap gap-1 mb-5 bg-slate-800/40 p-1 rounded-xl">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              tab === t.id
                ? "bg-teal-500/20 text-teal-300 border border-teal-500/30"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/40"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>{tabContent[tab]()}</div>
    </div>
  );
}
