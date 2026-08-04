/**
 * RiskValidation.tsx — Phase 8.4
 * Advanced Risk Validation Framework dashboard.
 * READ-ONLY · ADVISORY-ONLY.
 */
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ShieldCheck, AlertTriangle, AlertCircle, Info,
  TrendingDown, TrendingUp, Minus, Activity,
  BarChart2, Layers, GitMerge, Zap, Target,
  Globe, ArrowRightLeft, Download, RefreshCw,
} from "lucide-react";
import { apiJson } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────────

interface Issue {
  severity:  string;
  check:     string;
  field:     string;
  message:   string;
  value?:    number;
  category?: string;
  domain?:   string;
}

interface DomainSummary {
  domain:         string;
  score:          number;
  grade:          string;
  checks_run:     number;
  checks_passed:  number;
  checks_failed:  number;
  critical:       number;
  warnings:       number;
  available:      boolean;
}

interface RVSummary {
  status?:         string;
  available?:      boolean;
  advisory_only?:  boolean;
  generated_at?:   string;
  risk_score?:     number;
  grade?:          string;
  trend?:          string;
  total_issues?:   number;
  critical_count?: number;
  warning_count?:  number;
  domains?:        DomainSummary[];
}

interface DomainData {
  status?:         string;
  available?:      boolean;
  advisory_only?:  boolean;
  domain?:         string;
  score?:          number;
  grade?:          string;
  checks_run?:     number;
  checks_passed?:  number;
  checks_failed?:  number;
  critical_count?: number;
  warning_count?:  number;
  issues?:         Issue[];
  [key: string]:   any;
}

interface StressScenario {
  id:                     string;
  label:                  string;
  shock_pct:              number;
  impact_value:           number;
  portfolio_value_after:  number;
  advisory_note:          string;
}

// ── Constants ──────────────────────────────────────────────────────────────────

const POLL = 60_000;

const TABS = [
  "overview", "trade-approvals", "portfolio", "positions", "sectors",
  "correlation", "stress", "tail", "execution",
  "market", "drift", "alerts", "export",
] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  overview:          "Overview",
  "trade-approvals": "Trade Approvals",
  portfolio:         "Portfolio",
  positions:         "Positions",
  sectors:           "Sectors",
  correlation:       "Correlation",
  stress:            "Stress Tests",
  tail:              "Tail Risk",
  execution:         "Execution",
  market:            "Market Risk",
  drift:             "Risk Drift",
  alerts:            "Alerts",
  export:            "Export",
};

// ── Helpers ────────────────────────────────────────────────────────────────────

const fmt = (n: number, dec = 1) => Number(n ?? 0).toFixed(dec);
const fmtCur = (n: number) =>
  `₹${Number(n ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

function scoreColor(s: number) {
  if (s >= 80) return "text-emerald-400";
  if (s >= 60) return "text-teal-400";
  if (s >= 40) return "text-yellow-400";
  return "text-red-400";
}

function gradeColor(g: string) {
  if (g === "A+" || g === "A") return "text-emerald-400";
  if (g === "B")               return "text-teal-400";
  if (g === "C")               return "text-yellow-400";
  return "text-red-400";
}

function shockColor(pct: number) {
  if (pct >= 0)   return "text-emerald-400";
  if (pct >= -10) return "text-yellow-400";
  return "text-red-400";
}

// ── Shared UI primitives ───────────────────────────────────────────────────────

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 ${className ?? ""}`}>
      {children}
    </div>
  );
}

function KpiCard({ label, value, color, sub }: {
  label: string; value: string; color?: string; sub?: string;
}) {
  return (
    <Card>
      <p className="text-xs text-slate-500 font-medium mb-1">{label}</p>
      <p className={`text-xl font-bold ${color ?? "text-slate-200"}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </Card>
  );
}

function SectionHeader({ icon, title, sub }: {
  icon: React.ReactNode; title: string; sub?: string;
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      {icon}
      <div>
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
        {sub && <p className="text-xs text-slate-500">{sub}</p>}
      </div>
    </div>
  );
}

function LoadingView() {
  return (
    <div className="flex items-center gap-2 py-8 text-slate-400 text-sm">
      <RefreshCw className="w-4 h-4 animate-spin" />
      Loading…
    </div>
  );
}

function DisabledView({ msg }: { msg?: string }) {
  return (
    <Card className="py-10 text-center">
      <ShieldCheck className="w-8 h-8 text-slate-600 mx-auto mb-3" />
      <p className="text-slate-300 text-sm font-medium">Risk Validation Disabled</p>
      <p className="text-slate-500 text-xs mt-1">
        {msg ?? "Set RISK_VALIDATION_ENABLED=true to enable"}
      </p>
    </Card>
  );
}

function AdvisoryBanner() {
  return (
    <div className="flex items-center gap-2 bg-teal-900/20 border border-teal-700/30 rounded-lg px-3 py-2 text-xs text-teal-300">
      <Info className="w-3 h-3 flex-shrink-0" />
      <span>
        <strong>ADVISORY-ONLY</strong> — This module is read-only and never modifies positions,
        strategies, or orders.
      </span>
    </div>
  );
}

// ── Score Ring ─────────────────────────────────────────────────────────────────

function ScoreRing({ score, grade }: { score: number; grade: string }) {
  const R   = 52;
  const C   = 2 * Math.PI * R;
  const fill = (Math.min(score, 100) / 100) * C;
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="132" height="132" viewBox="0 0 132 132" data-testid="rv-score-ring">
        <circle cx="66" cy="66" r={R} fill="none" stroke="#1e293b" strokeWidth="10" />
        <circle
          cx="66" cy="66" r={R} fill="none"
          stroke="currentColor"
          className={scoreColor(score)}
          strokeWidth="10"
          strokeDasharray={`${fill} ${C}`}
          strokeLinecap="round"
          transform="rotate(-90 66 66)"
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
        <text x="66" y="62" textAnchor="middle" fill="#e2e8f0"
              fontSize="22" fontWeight="700">
          {fmt(score, 0)}
        </text>
        <text x="66" y="76" textAnchor="middle" fill="#64748b" fontSize="10">
          RISK SCORE
        </text>
      </svg>
      <span className={`text-2xl font-bold ${gradeColor(grade)}`}
            data-testid="rv-grade">{grade}</span>
    </div>
  );
}

// ── Issues Table ───────────────────────────────────────────────────────────────

function IssuesTable({ issues, emptyMsg }: { issues: Issue[]; emptyMsg?: string }) {
  if (!issues.length)
    return <p className="text-slate-500 text-xs py-4">{emptyMsg ?? "✓ All checks passed"}</p>;
  return (
    <div className="overflow-x-auto" data-testid="rv-issues-table">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-700/50">
            {["Severity","Check","Field","Message"].map(h => (
              <th key={h} className="pb-2 px-2 text-left text-slate-500 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {issues.map((iss, i) => (
            <tr key={i} className="border-b border-slate-700/20">
              <td className="py-2 px-2">
                <span className={`px-1.5 py-0.5 rounded text-xs font-semibold ${
                  iss.severity === "CRITICAL" ? "bg-red-900/40 text-red-400" :
                  iss.severity === "WARNING"  ? "bg-yellow-900/40 text-yellow-400" :
                                               "bg-slate-700 text-slate-400"
                }`}>{iss.severity}</span>
              </td>
              <td className="py-2 px-2 text-slate-300 font-mono">{iss.check}</td>
              <td className="py-2 px-2 text-slate-400">{iss.field}</td>
              <td className="py-2 px-2 text-slate-300">{iss.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DomainCard({ d }: { d: DomainData }) {
  if (!d?.available) return null;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-3">
        <KpiCard label="Score"    value={`${fmt(d.score ?? 0)}%`} color={scoreColor(d.score ?? 0)} />
        <KpiCard label="Grade"    value={d.grade ?? "—"}           color={gradeColor(d.grade ?? "")} />
        <KpiCard label="Critical" value={String(d.critical_count ?? 0)}
                 color={(d.critical_count ?? 0) > 0 ? "text-red-400" : "text-slate-400"} />
        <KpiCard label="Warnings" value={String(d.warning_count ?? 0)}
                 color={(d.warning_count ?? 0) > 0 ? "text-yellow-400" : "text-slate-400"} />
      </div>
      <Card>
        <p className="text-xs font-semibold text-slate-400 mb-3">
          Validation Checks ({d.checks_passed}/{d.checks_run} passed)
        </p>
        <IssuesTable issues={d.issues ?? []} />
      </Card>
    </div>
  );
}

// ── Tab renderers ──────────────────────────────────────────────────────────────

function renderOverview(S: RVSummary | undefined) {
  if (!S) return <LoadingView />;
  if (S.status === "DISABLED") return <DisabledView />;

  const trend = S.trend ?? "Stable";
  const TrendIcon = trend === "Improving" ? TrendingUp : trend === "Deteriorating" ? TrendingDown : Minus;
  const trendColor = trend === "Improving"    ? "text-emerald-400"
                   : trend === "Deteriorating" ? "text-red-400"
                   : "text-slate-400";

  return (
    <div className="space-y-5">
      <SectionHeader
        icon={<ShieldCheck className="w-4 h-4 text-teal-400" />}
        title="Advanced Risk Validation"
        sub={`Generated ${(S.generated_at ?? "").slice(0,19).replace("T"," ")} UTC · Advisory-only`}
      />
      <div className="flex flex-col sm:flex-row gap-6 items-start">
        <div data-testid="rv-score-total">
          <ScoreRing score={S.risk_score ?? 0} grade={S.grade ?? "D"} />
        </div>
        <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard label="Trend" value={trend} color={trendColor} />
          <KpiCard label="Critical Issues"
            value={String(S.critical_count ?? 0)}
            color={(S.critical_count ?? 0) > 0 ? "text-red-400" : "text-emerald-400"} />
          <KpiCard label="Warnings"
            value={String(S.warning_count ?? 0)}
            color={(S.warning_count ?? 0) > 0 ? "text-yellow-400" : "text-slate-400"} />
          <KpiCard label="Total Issues" value={String(S.total_issues ?? 0)} />
        </div>
      </div>
      <Card>
        <p className="text-xs font-semibold text-slate-400 mb-3">Domain Scores</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="rv-domain-table">
            <thead>
              <tr className="border-b border-slate-700/50">
                {["Domain","Score","Grade","Passed/Run","Critical","Warnings","Available"].map(h => (
                  <th key={h} className="pb-2 px-2 text-left text-slate-500 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(S.domains ?? []).map((d, i) => (
                <tr key={i} className="border-b border-slate-700/20">
                  <td className="py-2 px-2 text-slate-300 capitalize font-medium">
                    {d.domain?.replace("_"," ")}
                  </td>
                  <td className={`py-2 px-2 font-semibold ${scoreColor(d.score)}`}>
                    {fmt(d.score)}%
                  </td>
                  <td className={`py-2 px-2 font-bold ${gradeColor(d.grade)}`}>{d.grade}</td>
                  <td className="py-2 px-2 text-slate-400">{d.checks_passed}/{d.checks_run}</td>
                  <td className={`py-2 px-2 ${d.critical > 0 ? "text-red-400" : "text-slate-500"}`}>{d.critical}</td>
                  <td className={`py-2 px-2 ${d.warnings > 0 ? "text-yellow-400" : "text-slate-500"}`}>{d.warnings}</td>
                  <td className="py-2 px-2">
                    {d.available
                      ? <span className="text-emerald-400">✓</span>
                      : <span className="text-slate-600">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function renderPortfolio(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">No portfolio data available</Card>;

  return (
    <div className="space-y-4">
      <SectionHeader icon={<Layers className="w-4 h-4 text-teal-400" />}
        title="Portfolio Risk" sub="Capital, exposure, drawdown and heat validation" />
      <div className="grid grid-cols-3 md:grid-cols-5 gap-3">
        <KpiCard label="Total Value"   value={fmtCur(D.total_value ?? 0)} />
        <KpiCard label="Cash"          value={fmtCur(D.cash_available ?? 0)} />
        <KpiCard label="Invested"      value={fmtCur(D.invested_capital ?? 0)} />
        <KpiCard label="Utilisation"
          value={`${fmt(D.portfolio_utilisation_pct ?? 0)}%`}
          color={scoreColor(100 - (D.portfolio_utilisation_pct ?? 0))} />
        <KpiCard label="Max Drawdown"
          value={`${fmt(D.max_drawdown_pct ?? 0)}%`}
          color={(D.max_drawdown_pct ?? 0) > 10 ? "text-red-400" : "text-emerald-400"} />
      </div>
      <DomainCard d={D} />
    </div>
  );
}

function renderPositions(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  const positions: any[] = D.positions ?? [];
  const total = D.total_value ?? 0;
  return (
    <div className="space-y-4">
      <SectionHeader icon={<Target className="w-4 h-4 text-teal-400" />}
        title="Position Risk"
        sub={`${D.positions_count ?? positions.length} positions · concentration and sizing`} />
      {positions.length === 0 ? (
        <Card className="py-8 text-center text-slate-400 text-sm">No open positions</Card>
      ) : (
        <Card>
          <div className="overflow-x-auto" data-testid="rv-positions-table">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700/50">
                  {["Symbol","Value","Portfolio %","P&L","Status"].map(h => (
                    <th key={h} className="pb-2 px-2 text-left text-slate-500 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.map((p: any, i: number) => {
                  const val = p.current_value ?? p.value ?? 0;
                  const pct = total > 0 ? val / total * 100 : 0;
                  return (
                    <tr key={i} className="border-b border-slate-700/20">
                      <td className="py-2 px-2 font-semibold text-slate-200">{p.symbol}</td>
                      <td className="py-2 px-2 text-slate-300">{fmtCur(val)}</td>
                      <td className={`py-2 px-2 font-semibold ${
                        pct > 25 ? "text-red-400" : pct > 15 ? "text-yellow-400" : "text-slate-300"
                      }`}>{fmt(pct)}%</td>
                      <td className={`py-2 px-2 ${(p.pnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {fmtCur(p.pnl ?? 0)}
                      </td>
                      <td className="py-2 px-2 text-slate-400">{p.status ?? p.trade_status ?? "OPEN"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function renderSectors(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">No sector data</Card>;

  const sectors = D.sectors ?? {};
  const entries = Object.entries(sectors).sort((a, b) => (b[1] as number) - (a[1] as number));
  return (
    <div className="space-y-4">
      <SectionHeader icon={<GitMerge className="w-4 h-4 text-teal-400" />}
        title="Sector Risk"
        sub={`${D.sector_count ?? entries.length} sectors · concentration & diversification`} />
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label="Sector Count"    value={String(D.sector_count ?? entries.length)} />
        <KpiCard label="Dominant Sector" value={D.dominant_sector ?? "—"} />
        <KpiCard label="Dominant %"      value={`${fmt(D.dominant_pct ?? 0)}%`}
          color={(D.dominant_pct ?? 0) > 50 ? "text-red-400" : "text-slate-200"} />
      </div>
      {entries.length > 0 && (
        <Card>
          <p className="text-xs font-semibold text-slate-400 mb-3">Sector Exposure</p>
          <div className="space-y-2">
            {entries.map(([sector, pct]: [string, any]) => (
              <div key={sector} className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-28 truncate">{sector}</span>
                <div className="flex-1 bg-slate-700/30 rounded-full h-2">
                  <div className={`h-2 rounded-full ${
                    pct > 50 ? "bg-red-500" : pct > 35 ? "bg-yellow-500" : "bg-teal-500"
                  }`} style={{ width: `${Math.min(pct, 100)}%` }} />
                </div>
                <span className={`text-xs font-semibold w-12 text-right ${
                  pct > 50 ? "text-red-400" : "text-slate-300"
                }`}>{fmt(pct)}%</span>
              </div>
            ))}
          </div>
        </Card>
      )}
      <DomainCard d={D} />
    </div>
  );
}

function renderCorrelation(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">No position data for correlation</Card>;

  return (
    <div className="space-y-4">
      <SectionHeader icon={<ArrowRightLeft className="w-4 h-4 text-teal-400" />}
        title="Correlation Risk" sub="Portfolio correlation and diversification analysis" />
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label="Avg Correlation"
          value={fmt(D.avg_correlation ?? 0, 2)}
          color={(D.avg_correlation ?? 0) > 0.65 ? "text-red-400" : "text-emerald-400"}
          sub="0=low, 1=high" />
        <KpiCard label="Diversification Score"
          value={fmt(D.diversification_score ?? 0, 2)}
          color={(D.diversification_score ?? 0) > 0.3 ? "text-emerald-400" : "text-red-400"}
          sub="1=fully diversified" />
        <KpiCard label="Positions Analysed" value={String(D.positions_analysed ?? 0)} />
      </div>
      <DomainCard d={D} />
    </div>
  );
}

function renderStress(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">Portfolio data required for stress tests</Card>;

  const scenarios: StressScenario[] = D.scenarios ?? [];
  return (
    <div className="space-y-4">
      <SectionHeader icon={<Zap className="w-4 h-4 text-teal-400" />}
        title="Scenario Stress Tests"
        sub={`${scenarios.length} scenarios · ${D.severe_count ?? 0} severe · Portfolio: ${fmtCur(D.portfolio_value ?? 0)}`}
      />
      <Card>
        <div className="overflow-x-auto" data-testid="rv-stress-table">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700/50">
                {["Scenario","Shock","Impact (₹)","Value After","Advisory Note"].map(h => (
                  <th key={h} className="pb-2 px-2 text-left text-slate-500 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scenarios.map((sc, i) => (
                <tr key={i} className="border-b border-slate-700/20">
                  <td className="py-2 px-2 font-semibold text-slate-200">{sc.label}</td>
                  <td className={`py-2 px-2 font-semibold ${shockColor(sc.shock_pct)}`}>
                    {sc.shock_pct > 0 ? "+" : ""}{sc.shock_pct}%
                  </td>
                  <td className={`py-2 px-2 ${sc.impact_value < 0 ? "text-red-400" : "text-emerald-400"}`}>
                    {sc.impact_value >= 0 ? "+" : ""}{fmtCur(sc.impact_value)}
                  </td>
                  <td className="py-2 px-2 text-slate-300">{fmtCur(sc.portfolio_value_after)}</td>
                  <td className="py-2 px-2 text-slate-400 max-w-xs">{sc.advisory_note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function renderTail(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">Portfolio value required for tail risk</Card>;

  return (
    <div className="space-y-4">
      <SectionHeader icon={<AlertTriangle className="w-4 h-4 text-teal-400" />}
        title="Tail Risk Estimation" sub="Parametric VaR/CVaR · advisory estimates only" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="95% VaR (1d)"  value={fmtCur(D.var_95_1d ?? 0)}  sub="daily loss at 95% CL" />
        <KpiCard label="99% VaR (1d)"  value={fmtCur(D.var_99_1d ?? 0)}  sub="daily loss at 99% CL" />
        <KpiCard label="99% CVaR (1d)" value={fmtCur(D.cvar_99_1d ?? 0)} sub="expected shortfall"
          color={(D.cvar_99_1d ?? 0) / Math.max(D.portfolio_value ?? 1, 1) > 0.10 ? "text-red-400" : "text-slate-200"} />
        <KpiCard label="5σ Worst Case" value={fmtCur(D.worst_case_5sigma ?? 0)} sub="extreme tail loss" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="India VIX"
          value={D.india_vix ? fmt(D.india_vix, 1) : "—"}
          color={(D.india_vix ?? 0) > 20 ? "text-red-400" : "text-slate-200"} />
        <KpiCard label="Daily Vol"       value={`${fmt(D.daily_volatility_pct ?? 0, 2)}%`} />
        <KpiCard label="Circuit Limit ₹" value={fmtCur(D.circuit_limit_loss ?? 0)} />
        <KpiCard label="Recovery (est.)" value={`~${D.recovery_estimate_days ?? "?"} days`} />
      </div>
      <DomainCard d={D} />
    </div>
  );
}

function renderExecution(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">No execution data available</Card>;

  return (
    <div className="space-y-4">
      <SectionHeader icon={<Activity className="w-4 h-4 text-teal-400" />}
        title="Execution Risk" sub="Slippage, fill rate and paper execution quality" />
      <div className="grid grid-cols-3 gap-3">
        <KpiCard label="Avg Slippage"
          value={`${fmt(D.avg_slippage_bps ?? 0)} bps`}
          color={(D.avg_slippage_bps ?? 0) > 15 ? "text-yellow-400" : "text-emerald-400"} />
        <KpiCard label="Fill Rate"
          value={`${fmt((D.fill_rate ?? 1) * 100)}%`}
          color={(D.fill_rate ?? 1) < 0.85 ? "text-red-400" : "text-emerald-400"} />
        <KpiCard label="Missed Trades"
          value={String(D.missed_trades ?? 0)}
          color={(D.missed_trades ?? 0) > 0 ? "text-yellow-400" : "text-slate-400"} />
      </div>
      <DomainCard d={D} />
    </div>
  );
}

function renderMarket(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">No market data available</Card>;

  return (
    <div className="space-y-4">
      <SectionHeader icon={<Globe className="w-4 h-4 text-teal-400" />}
        title="Market Risk" sub="Regime, VIX, macro and liquidity risk" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Market Risk Score"
          value={`${fmt(D.market_risk_score ?? D.score ?? 0)}%`}
          color={scoreColor(D.market_risk_score ?? D.score ?? 0)} />
        <KpiCard label="India VIX"
          value={D.india_vix ? fmt(D.india_vix, 1) : "—"}
          color={(D.india_vix ?? 0) > 20 ? "text-red-400" : "text-slate-200"} />
        <KpiCard label="Regime"        value={D.regime ?? "UNKNOWN"} />
        <KpiCard label="Macro"         value={D.macro_sentiment ?? "UNKNOWN"} />
      </div>
      <DomainCard d={D} />
    </div>
  );
}

function renderDrift(D: DomainData | undefined) {
  if (!D) return <LoadingView />;
  if (D.status === "DISABLED") return <DisabledView />;
  if (!D.available)
    return <Card className="py-8 text-center text-slate-400 text-sm">No data for drift detection</Card>;

  return (
    <div className="space-y-4">
      <SectionHeader icon={<TrendingDown className="w-4 h-4 text-teal-400" />}
        title="Risk Drift Detection" sub="Exposure, drawdown, concentration and volatility drift" />
      <div className="grid grid-cols-2 gap-3">
        <KpiCard label="Utilisation"
          value={`${fmt(D.utilisation_pct ?? 0)}%`}
          color={(D.utilisation_pct ?? 0) > 80 ? "text-red-400" : "text-slate-200"} />
        <KpiCard label="Drawdown"
          value={`${fmt(D.max_drawdown_pct ?? 0)}%`}
          color={(D.max_drawdown_pct ?? 0) > 10 ? "text-red-400" : "text-emerald-400"} />
      </div>
      <DomainCard d={D} />
    </div>
  );
}

function renderAlerts(A: any) {
  if (!A) return <LoadingView />;
  if (A.status === "DISABLED") return <DisabledView />;

  const all: Issue[] = [
    ...(A.critical ?? []),
    ...(A.warnings ?? []),
    ...(A.info ?? []),
  ];

  return (
    <div className="space-y-4">
      <SectionHeader icon={<AlertCircle className="w-4 h-4 text-teal-400" />}
        title="Risk Alerts"
        sub={`${A.total_critical ?? 0} critical · ${A.total_warnings ?? 0} warnings · ${A.total_info ?? 0} info`}
      />
      {all.length === 0 ? (
        <Card className="py-10 text-center">
          <ShieldCheck className="w-8 h-8 text-emerald-600 mx-auto mb-3" />
          <p className="text-slate-300 text-sm font-medium">No active risk alerts</p>
          <p className="text-slate-500 text-xs mt-1">All risk validation checks are passing.</p>
        </Card>
      ) : (
        <Card data-testid="rv-alerts-card">
          <IssuesTable issues={all} emptyMsg="No alerts" />
        </Card>
      )}
    </div>
  );
}

// ── Pre-trade approval types ───────────────────────────────────────────────────

interface PreTradeApproval {
  trade_id:      string;
  symbol:        string;
  side:          string;
  status:        string;
  decision_ts:   string;
  fill_price:    number;
  quantity:      number;
  verdict:       string;     // "APPROVED" | "APPROVED_WARN" | "REJECTED"
  approved:      boolean;
  reason:        string;
  critical_count: number;
  warning_count:  number;
  issues:        Issue[];
  metrics:       Record<string, any>;
  summary:       Record<string, any>;
}

interface PreTradeLog {
  status:        string;
  available:     boolean;
  generated_at:  string;
  total:         number;
  approvals:     PreTradeApproval[];
}

// ── Trade Approvals tab ────────────────────────────────────────────────────────

function VerdictBadge({ verdict }: { verdict: string }) {
  const cls = verdict === "APPROVED"
    ? "bg-emerald-900/50 text-emerald-300 border-emerald-700/50"
    : verdict === "APPROVED_WARN"
    ? "bg-yellow-900/50 text-yellow-300 border-yellow-700/50"
    : "bg-red-900/50 text-red-300 border-red-700/50";
  const label = verdict === "APPROVED"      ? "✓ APPROVED"
              : verdict === "APPROVED_WARN"  ? "⚠ APPROVED"
              : "✗ REJECTED";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border font-semibold ${cls}`}>
      {label}
    </span>
  );
}

function renderTradeApprovals(log: PreTradeLog | undefined) {
  if (!log) return <LoadingView />;
  if (log.status === "DISABLED") return <DisabledView />;

  const approvals = log.approvals ?? [];
  const approved  = approvals.filter(a => a.verdict === "APPROVED").length;
  const warned    = approvals.filter(a => a.verdict === "APPROVED_WARN").length;
  const rejected  = approvals.filter(a => a.verdict === "REJECTED").length;

  return (
    <div className="space-y-4">
      <SectionHeader
        icon={<Target className="w-4 h-4 text-teal-400" />}
        title="Pre-Trade Risk Approvals"
        sub="Every AI paper BUY passes through the Risk Agent before execution"
      />

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Total Validated" value={String(log.total ?? 0)} />
        <KpiCard label="Approved"
          value={String(approved)}
          color="text-emerald-400" />
        <KpiCard label="Approved with Warnings"
          value={String(warned)}
          color={warned > 0 ? "text-yellow-400" : "text-slate-400"} />
        <KpiCard label="Rejected by Risk Agent"
          value={String(rejected)}
          color={rejected > 0 ? "text-red-400" : "text-emerald-400"} />
      </div>

      {approvals.length === 0 ? (
        <Card className="py-10 text-center">
          <ShieldCheck className="w-8 h-8 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-300 text-sm font-medium">No validated trades yet</p>
          <p className="text-slate-500 text-xs mt-1">
            Pre-trade Risk Agent validation runs automatically before every paper BUY.
            Results appear here after the first scan during market hours.
          </p>
        </Card>
      ) : (
        <Card>
          <p className="text-xs font-semibold text-slate-400 mb-3">
            Last {approvals.length} validated trades (most recent first)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700/50">
                  {["Symbol","Time","Price","Qty","Verdict","Warnings","Rejection Reason"].map(h => (
                    <th key={h} className="pb-2 px-2 text-left text-slate-500 font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {approvals.map((a, i) => (
                  <tr key={i} className={`border-b border-slate-700/20 ${
                    a.verdict === "REJECTED" ? "bg-red-950/20" :
                    a.verdict === "APPROVED_WARN" ? "bg-yellow-950/10" : ""
                  }`}>
                    <td className="py-2 px-2 font-semibold text-slate-200 font-mono">{a.symbol}</td>
                    <td className="py-2 px-2 text-slate-400 whitespace-nowrap">
                      {a.decision_ts ? a.decision_ts.slice(11,19) + " UTC" : "—"}
                    </td>
                    <td className="py-2 px-2 text-slate-300 font-mono">
                      {a.fill_price ? `₹${Number(a.fill_price).toFixed(2)}` : "—"}
                    </td>
                    <td className="py-2 px-2 text-slate-400">{a.quantity ?? "—"}</td>
                    <td className="py-2 px-2"><VerdictBadge verdict={a.verdict} /></td>
                    <td className={`py-2 px-2 ${a.warning_count > 0 ? "text-yellow-400" : "text-slate-500"}`}>
                      {a.warning_count > 0 ? `${a.warning_count} warning${a.warning_count > 1 ? "s" : ""}` : "—"}
                    </td>
                    <td className="py-2 px-2 text-red-300 max-w-xs truncate">
                      {a.reason || (a.verdict === "REJECTED" ? "See issues" : "—")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Expand warnings/issues for the first rejected trade if any */}
          {rejected > 0 && (() => {
            const rej = approvals.find(a => a.verdict === "REJECTED");
            if (!rej) return null;
            return (
              <div className="mt-4 pt-4 border-t border-slate-700/40">
                <p className="text-xs font-semibold text-red-400 mb-2">
                  Most Recent Rejected Trade — {rej.symbol}
                </p>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-3">
                  {rej.metrics?.rr_ratio && (
                    <div className="bg-slate-800/60 rounded-lg p-2">
                      <p className="text-xs text-slate-500">R:R Ratio</p>
                      <p className="text-sm font-bold text-slate-200 font-mono">
                        {Number(rej.metrics.rr_ratio.rr_ratio ?? 0).toFixed(2)}
                        <span className="text-xs text-slate-500 ml-1">
                          (min {rej.metrics.rr_ratio.min_required})
                        </span>
                      </p>
                    </div>
                  )}
                  {rej.metrics?.capital_at_risk && (
                    <div className="bg-slate-800/60 rounded-lg p-2">
                      <p className="text-xs text-slate-500">Capital at Risk</p>
                      <p className="text-sm font-bold text-slate-200 font-mono">
                        {Number(rej.metrics.capital_at_risk.risk_pct ?? 0).toFixed(2)}%
                      </p>
                    </div>
                  )}
                  {rej.metrics?.position_size && (
                    <div className="bg-slate-800/60 rounded-lg p-2">
                      <p className="text-xs text-slate-500">Position Size</p>
                      <p className="text-sm font-bold text-slate-200 font-mono">
                        {Number(rej.metrics.position_size.position_pct ?? 0).toFixed(1)}%
                        <span className="text-xs text-slate-500 ml-1">
                          (max {rej.metrics.position_size.max_allowed_pct}%)
                        </span>
                      </p>
                    </div>
                  )}
                </div>
                <IssuesTable issues={rej.issues ?? []} />
              </div>
            );
          })()}
        </Card>
      )}

      {/* Thresholds reference */}
      <Card>
        <p className="text-xs font-semibold text-slate-400 mb-3">Risk Agent Thresholds</p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
          {[
            { label: "Max Position Size",   value: "20% of portfolio" },
            { label: "Max Capital at Risk",  value: "2% per trade" },
            { label: "Min Reward:Risk Ratio", value: "1.5× or better" },
            { label: "Max Stop Distance",    value: "5% from entry" },
            { label: "Max Utilisation",      value: "92% of portfolio" },
            { label: "Min Cash Buffer",      value: "5% must remain" },
          ].map(({ label, value }) => (
            <div key={label} className="bg-slate-800/40 rounded-lg p-2">
              <p className="text-slate-500">{label}</p>
              <p className="text-slate-300 font-semibold mt-0.5">{value}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function renderExport(enabled: boolean) {
  const downloadUrl = (fmt: string) =>
    `${import.meta.env.BASE_URL}api/risk-validation/export?format=${fmt}`;
  return (
    <div className="space-y-4">
      <SectionHeader icon={<Download className="w-4 h-4 text-teal-400" />}
        title="Export Risk Report" sub="Advisory-only export" />
      <AdvisoryBanner />
      {!enabled ? <DisabledView /> : (
        <div className="grid grid-cols-2 gap-4">
          <Card>
            <p className="text-sm font-semibold text-slate-200 mb-1">JSON Export</p>
            <p className="text-xs text-slate-500 mb-3">Full risk validation bundle.</p>
            <a href={downloadUrl("json")} download="risk_validation_export.json"
               className="block text-center bg-teal-600 hover:bg-teal-500 text-white text-xs py-2 px-3 rounded-lg transition-colors">
              Download JSON
            </a>
          </Card>
          <Card>
            <p className="text-sm font-semibold text-slate-200 mb-1">CSV Export</p>
            <p className="text-xs text-slate-500 mb-3">Domain-level summary table.</p>
            <a href={downloadUrl("csv")} download="risk_validation_export.csv"
               className="block text-center bg-slate-600 hover:bg-slate-500 text-white text-xs py-2 px-3 rounded-lg transition-colors">
              Download CSV
            </a>
          </Card>
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function RiskValidation() {
  const [tab, setTab] = useState<Tab>("overview");

  const summary = useQuery<RVSummary>({
    queryKey: ["rv-summary"],
    queryFn:  () => apiJson("risk-validation/summary"),
    enabled:  tab === "overview",
    refetchInterval: POLL,
  });

  const portfolio = useQuery<DomainData>({
    queryKey: ["rv-portfolio"],
    queryFn:  () => apiJson("risk-validation/portfolio"),
    enabled:  tab === "portfolio" || tab === "positions",
    refetchInterval: POLL,
  });

  const sectors = useQuery<DomainData>({
    queryKey: ["rv-sectors"],
    queryFn:  () => apiJson("risk-validation/sector"),
    enabled:  tab === "sectors",
    refetchInterval: POLL,
  });

  const correlation = useQuery<DomainData>({
    queryKey: ["rv-correlation"],
    queryFn:  () => apiJson("risk-validation/correlation"),
    enabled:  tab === "correlation",
    refetchInterval: POLL,
  });

  const stress = useQuery<DomainData>({
    queryKey: ["rv-stress"],
    queryFn:  () => apiJson("risk-validation/stress"),
    enabled:  tab === "stress",
    refetchInterval: POLL,
  });

  const tail = useQuery<DomainData>({
    queryKey: ["rv-tail"],
    queryFn:  () => apiJson("risk-validation/tail"),
    enabled:  tab === "tail",
    refetchInterval: POLL,
  });

  const execution = useQuery<DomainData>({
    queryKey: ["rv-execution"],
    queryFn:  () => apiJson("risk-validation/execution"),
    enabled:  tab === "execution",
    refetchInterval: POLL,
  });

  const market = useQuery<DomainData>({
    queryKey: ["rv-market"],
    queryFn:  () => apiJson("risk-validation/market"),
    enabled:  tab === "market",
    refetchInterval: POLL,
  });

  const drift = useQuery<DomainData>({
    queryKey: ["rv-drift"],
    queryFn:  () => apiJson("risk-validation/drift"),
    enabled:  tab === "drift",
    refetchInterval: POLL,
  });

  const alerts = useQuery<any>({
    queryKey: ["rv-alerts"],
    queryFn:  () => apiJson("risk-validation/alerts"),
    enabled:  tab === "alerts",
    refetchInterval: POLL,
  });

  const preTradeLog = useQuery<PreTradeLog>({
    queryKey: ["rv-pre-trade-log"],
    queryFn:  () => apiJson("risk-validation/pre-trade-log"),
    enabled:  tab === "trade-approvals",
    refetchInterval: POLL,
  });

  const isEnabled = summary.data?.status !== "DISABLED";

  const tabContent: Record<Tab, () => React.ReactNode> = {
    overview:          () => renderOverview(summary.data),
    "trade-approvals": () => renderTradeApprovals(preTradeLog.data),
    portfolio:         () => renderPortfolio(portfolio.data),
    positions:         () => renderPositions(portfolio.data),
    sectors:           () => renderSectors(sectors.data),
    correlation:       () => renderCorrelation(correlation.data),
    stress:            () => renderStress(stress.data),
    tail:              () => renderTail(tail.data),
    execution:         () => renderExecution(execution.data),
    market:            () => renderMarket(market.data),
    drift:             () => renderDrift(drift.data),
    alerts:            () => renderAlerts(alerts.data),
    export:            () => renderExport(isEnabled),
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <ShieldCheck className="w-6 h-6 text-teal-400" />
        <div>
          <h1 className="text-lg font-bold text-slate-100">Advanced Risk Validation</h1>
          <p className="text-xs text-slate-500">Phase 8.4 · Read-only · Advisory-only</p>
        </div>
        <div className="ml-auto">
          <AdvisoryBanner />
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 overflow-x-auto pb-1 border-b border-slate-700/50">
        {TABS.map(t => (
          <button
            key={t}
            className={`px-3 py-1.5 text-xs font-medium rounded-t whitespace-nowrap transition-colors ${
              tab === t
                ? "bg-slate-700 text-teal-300 border-b-2 border-teal-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="mt-2">{tabContent[tab]()}</div>
    </div>
  );
}
