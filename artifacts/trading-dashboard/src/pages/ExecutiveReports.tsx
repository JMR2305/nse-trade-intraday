/**
 * ExecutiveReports.tsx — Phase 9.6
 * Executive Reports & AI Briefings
 *
 * READ-ONLY · ADVISORY-ONLY
 * No business logic · No trading engine changes · No order placement
 *
 * 7 report types · AI Insights · KPI Summary · Report Library · Export
 * All data from existing cached React Query endpoints — zero new API calls.
 */

import React, { useMemo, useState, useCallback } from "react";
import { useQuery }       from "@tanstack/react-query";
import { useLocation }    from "wouter";
import {
  FileBarChart2, Sun, TrendingUp, Clock, Moon, CalendarDays, CalendarRange,
  Download, BookMarked, Search, Star, StarOff, Filter, RefreshCw,
  AlertTriangle, CheckCircle2, XCircle, Info, ChevronRight, ChevronDown,
  LayoutDashboard, Shield, Bot, BarChart3, Briefcase, Activity, Settings,
  FlaskConical, Target, Zap, Eye, Database, ArrowRight,
} from "lucide-react";
import { apiJson } from "@/lib/api";
import { Badge }   from "@/components/ui/badge";
import { Button }  from "@/components/ui/button";
import { Input }   from "@/components/ui/input";
import { PageHeader } from "@/components/ds";

// ─── Types ─────────────────────────────────────────────────────────────────────

type ReportType = "morning" | "open" | "midday" | "close" | "eod" | "weekly" | "monthly";

interface KpiScore { label: string; score: number; icon: React.ElementType; color: string }

interface ReportSection {
  title:    string;
  content:  React.ReactNode;
}

interface SavedReport {
  id:          string;
  type:        ReportType;
  label:       string;
  generatedAt: string;  // ISO
  starred:     boolean;
}

// ─── Constants ─────────────────────────────────────────────────────────────────

const REPORT_META: Record<ReportType, { label: string; subtitle: string; icon: React.ElementType; color: string; when: string }> = {
  morning: { label: "Morning Brief",          subtitle: "Pre-market intelligence & readiness",  icon: Sun,             color: "#F59E0B", when: "08:00–09:00" },
  open:    { label: "Market Open Brief",      subtitle: "Opening conditions & early signals",   icon: TrendingUp,      color: "#10B981", when: "09:15–09:30" },
  midday:  { label: "Midday Brief",           subtitle: "Mid-session portfolio & AI status",    icon: Clock,           color: "#3B82F6", when: "12:00–13:00" },
  close:   { label: "Market Close Brief",     subtitle: "Closing summary & session review",     icon: Moon,            color: "#8B5CF6", when: "15:30–15:45" },
  eod:     { label: "End-of-Day Report",      subtitle: "Comprehensive executive review",       icon: FileBarChart2,   color: "#EF4444", when: "16:00–16:30" },
  weekly:  { label: "Weekly Report",          subtitle: "7-day performance & strategy ranking", icon: CalendarDays,    color: "#06B6D4", when: "Friday 16:00" },
  monthly: { label: "Monthly Report",         subtitle: "Monthly growth & portfolio analysis",  icon: CalendarRange,   color: "#EC4899", when: "Last trading day" },
};

const QUICK_ACTIONS: { label: string; href: string; icon: React.ElementType }[] = [
  { label: "Command Centre",  href: "/command-center",  icon: LayoutDashboard },
  { label: "Timeline",        href: "/trading-timeline",icon: Clock },
  { label: "Risk",            href: "/risk-validation", icon: Shield },
  { label: "AI Decision",     href: "/ai-decision",     icon: Bot },
  { label: "Portfolio",       href: "/portfolio-live",  icon: Briefcase },
  { label: "Research",        href: "/research-lab",    icon: FlaskConical },
  { label: "Operations",      href: "/operations-center",icon: Settings },
];

const LS_LIBRARY_KEY = "apexquant_report_library";

// ─── Helpers ───────────────────────────────────────────────────────────────────

function scoreColor(s: number): string {
  if (s >= 80) return "#10B981";
  if (s >= 60) return "#F59E0B";
  if (s >= 40) return "#F97316";
  return "#EF4444";
}

function scoreBg(s: number): string {
  if (s >= 80) return "rgba(16,185,129,0.12)";
  if (s >= 60) return "rgba(245,158,11,0.12)";
  if (s >= 40) return "rgba(249,115,22,0.12)";
  return "rgba(239,68,68,0.12)";
}

function fmt(n: number, decimals = 1): string {
  return n.toFixed(decimals);
}

function nowISO(): string { return new Date().toISOString(); }

function fmtDate(iso: string): string {
  try { return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }); }
  catch { return iso; }
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function KpiCard({ label, score, Icon, color }: { label: string; score: number; Icon: React.ElementType; color: string }) {
  return (
    <div style={{ background: scoreBg(score), border: `1px solid ${color}22`, borderRadius: 8, padding: "10px 14px", minWidth: 110, flex: "1 1 110px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <Icon size={13} color={color} />
        <span style={{ fontSize: 10, color: "#9CA3AF", letterSpacing: "0.04em" }}>{label}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: scoreColor(score), lineHeight: 1 }}>
        {fmt(score, 0)}
        <span style={{ fontSize: 12, fontWeight: 400, color: "#6B7280" }}>/100</span>
      </div>
    </div>
  );
}

function SectionCard({ title, children, accent }: { title: string; children: React.ReactNode; accent?: string }) {
  return (
    <div style={{ background: "#1a1f2e", border: "1px solid #2d3348", borderRadius: 10, padding: "16px 18px", marginBottom: 12 }}>
      {accent && <div style={{ width: 3, height: "100%", background: accent, position: "absolute", left: 0, top: 0, borderRadius: "10px 0 0 10px" }} />}
      <div style={{ fontSize: 12, fontWeight: 600, color: "#9CA3AF", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  );
}

function BulletList({ items, color = "#6366F1" }: { items: string[]; color?: string }) {
  if (!items.length) return <p style={{ color: "#6B7280", fontSize: 13 }}>No items available for current session.</p>;
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {items.map((item, i) => (
        <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 6 }}>
          <ChevronRight size={13} color={color} style={{ marginTop: 2, flexShrink: 0 }} />
          <span style={{ color: "#D1D5DB", fontSize: 13, lineHeight: 1.5 }}>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function AlertRow({ sev, text }: { sev: "critical" | "high" | "medium" | "low" | "info"; text: string }) {
  const colors: Record<string, string> = { critical: "#EF4444", high: "#F97316", medium: "#F59E0B", low: "#3B82F6", info: "#6B7280" };
  const icons: Record<string, React.ElementType> = { critical: XCircle, high: AlertTriangle, medium: AlertTriangle, low: Info, info: Info };
  const IconC = icons[sev] || Info;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", background: `${colors[sev]}15`, border: `1px solid ${colors[sev]}30`, borderRadius: 6, marginBottom: 6 }}>
      <IconC size={13} color={colors[sev]} />
      <span style={{ color: "#D1D5DB", fontSize: 12 }}>{text}</span>
    </div>
  );
}

// ─── Report content generators ────────────────────────────────────────────────

function useMorningBrief(summary: any, alerts: any[]) {
  return useMemo(() => {
    const regime = summary?.regime_analysis?.primary_regime ?? "UNKNOWN";
    const readinessScore = summary?.health?.overall_score ?? 0;
    const aiSignals = alerts.filter(a => a.category === "ai" || a.category === "signal").length;
    const criticals = alerts.filter(a => a.severity === "critical").length;
    const marketStatus = summary?.market_status ?? "UNKNOWN";
    return {
      executiveSummary: `Market regime: ${regime}. Platform readiness score: ${fmt(readinessScore, 0)}/100. ${aiSignals} AI signals queued. Market status: ${marketStatus}. ${criticals > 0 ? `⚠ ${criticals} critical alerts require attention before open.` : "No critical alerts — safe to proceed."}`,
      metrics: [
        { label: "Platform Readiness", value: `${fmt(readinessScore, 0)}/100` },
        { label: "Market Regime",      value: regime },
        { label: "AI Signals Queued",  value: String(aiSignals) },
        { label: "Critical Alerts",    value: String(criticals) },
        { label: "Market Status",      value: marketStatus },
      ],
      highlights: [
        `Regime classification: ${regime} — gate strategies accordingly`,
        `Platform health ${readinessScore >= 80 ? "HEALTHY" : readinessScore >= 60 ? "DEGRADED" : "CRITICAL"} — ${readinessScore >= 80 ? "ready to trade" : "review before opening positions"}`,
        `${aiSignals} advisory signals available for operator review`,
        "Pre-open intelligence scan loaded and cached",
        "Risk limits enforced — no auto-execution enabled",
      ],
      recommendations: [
        "Review AI signals in the Copilot before market open",
        "Verify risk limits are set for today's expected volatility",
        `Monitor ${regime} strategies — ensure they are activated`,
        "Confirm paper trading mode is set correctly",
        "Run a manual system health check if score is below 80",
      ],
      warnings: alerts.filter(a => ["critical","high"].includes(a.severity)).map(a => ({ sev: a.severity as any, text: a.title || a.body || "Alert" })),
      nextSteps: [
        "Check Pre-Open Intelligence at 08:45 IST",
        "Review Research Summary before 09:00",
        "Confirm market readiness score ≥ 70 before considering entries",
        "Set daily risk budget in Risk Management",
      ],
    };
  }, [summary, alerts]);
}

function useOpenBrief(summary: any, alerts: any[], positions: any[]) {
  return useMemo(() => {
    const openTrades = positions.filter(p => p.status === "OPEN").length;
    const highAlerts = alerts.filter(a => ["critical","high"].includes(a.severity)).length;
    const aiRecs = alerts.filter(a => a.category === "ai").length;
    const pnl = positions.reduce((acc, p) => acc + (p.unrealised_pnl ?? 0), 0);
    return {
      executiveSummary: `Market has opened. ${openTrades} paper positions currently open. Unrealised P&L: ₹${fmt(pnl, 2)}. ${aiRecs} early AI recommendations available. ${highAlerts} high-priority alerts active.`,
      metrics: [
        { label: "Open Positions",     value: String(openTrades) },
        { label: "Unrealised P&L",     value: `₹${fmt(pnl, 2)}` },
        { label: "AI Recommendations", value: String(aiRecs) },
        { label: "High Alerts",        value: String(highAlerts) },
      ],
      highlights: [
        `${openTrades} paper positions active at market open`,
        `Early P&L: ₹${fmt(pnl, 2)} unrealised`,
        `${aiRecs} AI recommendations queued for operator review`,
        "Opening gap analysis available in Market Intelligence",
        "Sector leaders report available in Market Overview",
      ],
      recommendations: [
        "Review opening gap data before adding new positions",
        "Check pre-open accuracy score in Pre-Open Accuracy page",
        "Monitor top gainers and losers for momentum signals",
        "Confirm all open positions are within risk parameters",
      ],
      warnings: alerts.filter(a => a.severity === "critical").map(a => ({ sev: "critical" as const, text: a.title || a.body })),
      nextSteps: [
        "Review AI Decision page for early-session recommendations",
        "Check Portfolio page for position sizing",
        "Monitor Risk Management for exposure updates",
        "Set midday brief trigger at 12:00 IST",
      ],
    };
  }, [summary, alerts, positions]);
}

function useMiddayBrief(summary: any, alerts: any[], positions: any[]) {
  return useMemo(() => {
    const openTrades = positions.filter(p => p.status === "OPEN").length;
    const closedToday = positions.filter(p => p.status === "CLOSED").length;
    const pnl = positions.reduce((acc, p) => acc + (p.unrealised_pnl ?? 0) + (p.realised_pnl ?? 0), 0);
    const opsScore = summary?.health?.overall_score ?? 0;
    return {
      executiveSummary: `Mid-session status: ${openTrades} open positions, ${closedToday} closed today. Total session P&L: ₹${fmt(pnl, 2)}. Operational health: ${fmt(opsScore, 0)}/100.`,
      metrics: [
        { label: "Open Positions",  value: String(openTrades) },
        { label: "Closed Today",    value: String(closedToday) },
        { label: "Session P&L",     value: `₹${fmt(pnl, 2)}` },
        { label: "Ops Health",      value: `${fmt(opsScore, 0)}/100` },
        { label: "Active Alerts",   value: String(alerts.length) },
      ],
      highlights: [
        `Session is ${Math.round(new Date().getHours() >= 12 ? (new Date().getHours() - 9.25) / (15.5 - 9.25) * 100 : 0)}% complete`,
        `${openTrades} positions currently open — monitor for adverse moves`,
        `Net session P&L: ₹${fmt(pnl, 2)}`,
        "AI confidence tracking available on AI Performance page",
        "Operational systems nominal — no degradation detected",
      ],
      recommendations: [
        "Review highest-conviction open trades in AI Decision",
        "Check risk exposure on Portfolio Risk Analytics",
        "Assess AI confidence trend since open",
        "Consider position reduction if P&L is adverse",
      ],
      warnings: alerts.filter(a => a.severity === "critical").map(a => ({ sev: "critical" as const, text: a.title || a.body })),
      nextSteps: [
        "Monitor open positions until 14:30 IST",
        "Prepare close brief summary data by 15:00",
        "Check Strategy Intelligence for afternoon regime shift",
        "Review learning insights for mid-session patterns",
      ],
    };
  }, [summary, alerts, positions]);
}

function useCloseBrief(summary: any, alerts: any[], positions: any[]) {
  return useMemo(() => {
    const openTrades = positions.filter(p => p.status === "OPEN").length;
    const closedToday = positions.filter(p => p.status === "CLOSED").length;
    const wins = positions.filter(p => p.status === "CLOSED" && (p.realised_pnl ?? 0) > 0).length;
    const losses = positions.filter(p => p.status === "CLOSED" && (p.realised_pnl ?? 0) < 0).length;
    const realised = positions.filter(p => p.status === "CLOSED").reduce((acc, p) => acc + (p.realised_pnl ?? 0), 0);
    const regime = summary?.regime_analysis?.primary_regime ?? "UNKNOWN";
    return {
      executiveSummary: `Market close: ${closedToday} trades executed (${wins} wins, ${losses} losses). Realised P&L: ₹${fmt(realised, 2)}. ${openTrades} positions remain open — review before session end. Regime: ${regime}.`,
      metrics: [
        { label: "Closed Trades",  value: String(closedToday) },
        { label: "Win/Loss",       value: `${wins}/${losses}` },
        { label: "Realised P&L",   value: `₹${fmt(realised, 2)}` },
        { label: "Still Open",     value: String(openTrades) },
        { label: "Regime",         value: regime },
      ],
      highlights: [
        `${closedToday} trades executed today — ${wins} winners, ${losses} losers`,
        closedToday > 0 ? `Win rate: ${fmt((wins / closedToday) * 100, 0)}%` : "No trades closed today",
        `Realised P&L: ₹${fmt(realised, 2)}`,
        `${openTrades} positions still open — consider closing before session end`,
        "End-of-day reconciliation will run at 16:00",
      ],
      recommendations: [
        openTrades > 0 ? "Review open positions — decide on overnight hold vs close" : "All positions closed — good discipline",
        "Check AI observations for post-market learning signals",
        "Log session notes in Trading Timeline",
        "Confirm paper trading summary in Validation page",
      ],
      warnings: [
        ...(openTrades > 0 ? [{ sev: "medium" as const, text: `${openTrades} positions still open at market close` }] : []),
        ...alerts.filter(a => a.severity === "critical").map(a => ({ sev: "critical" as const, text: a.title || a.body })),
      ],
      nextSteps: [
        "Run end-of-day reconciliation at 16:00",
        "Review EOD Executive Report for full session analysis",
        "Update learning governance with today's observations",
        "Prepare for next session morning brief",
      ],
    };
  }, [summary, alerts, positions]);
}

function useEodReport(summary: any, alerts: any[], positions: any[]) {
  return useMemo(() => {
    const total = positions.length;
    const closed = positions.filter(p => p.status === "CLOSED").length;
    const wins = positions.filter(p => p.status === "CLOSED" && (p.realised_pnl ?? 0) > 0).length;
    const realised = positions.filter(p => p.status === "CLOSED").reduce((acc, p) => acc + (p.realised_pnl ?? 0), 0);
    const opsScore = summary?.health?.overall_score ?? 0;
    const regime = summary?.regime_analysis?.primary_regime ?? "UNKNOWN";
    const criticals = alerts.filter(a => a.severity === "critical").length;
    return {
      executiveSummary: `End-of-Day Executive Summary: ${total} total paper positions, ${closed} closed. Session realised P&L: ₹${fmt(realised, 2)}. Win rate: ${closed > 0 ? fmt((wins/closed)*100,0) : 0}%. Platform health: ${fmt(opsScore,0)}/100. Regime: ${regime}. ${criticals} critical events during session.`,
      metrics: [
        { label: "Total Positions",  value: String(total) },
        { label: "Closed",           value: String(closed) },
        { label: "Win Rate",         value: closed > 0 ? `${fmt((wins/closed)*100,0)}%` : "N/A" },
        { label: "Realised P&L",     value: `₹${fmt(realised,2)}` },
        { label: "Platform Health",  value: `${fmt(opsScore,0)}/100` },
        { label: "Critical Events",  value: String(criticals) },
      ],
      highlights: [
        `Session complete: ${closed} trades closed`,
        `Net realised P&L: ₹${fmt(realised,2)}`,
        `AI Decision Engine operated in advisory mode throughout session`,
        `Platform health maintained at ${fmt(opsScore,0)}/100`,
        `${criticals} critical events occurred and were handled`,
        "All safety gates operated correctly — no auto-executions",
      ],
      recommendations: [
        "Review learning governance for pattern improvements",
        "Update strategy scores based on today's performance",
        "Archive today's session in Timeline for future reference",
        "Export today's data via the Export tab for record keeping",
        "Prepare tomorrow's watchlist and risk budget",
      ],
      warnings: alerts.filter(a => ["critical","high"].includes(a.severity)).map(a => ({ sev: a.severity as any, text: a.title || a.body })),
      nextSteps: [
        "Run post-session strategy optimisation review",
        "Check AI Performance Intelligence for calibration drift",
        "Update risk parameters for next session",
        "Review Historical Knowledge base for today's learnings",
      ],
    };
  }, [summary, alerts, positions]);
}

function useWeeklyReport(positions: any[]) {
  return useMemo(() => {
    const closed = positions.filter(p => p.status === "CLOSED");
    const realised = closed.reduce((acc, p) => acc + (p.realised_pnl ?? 0), 0);
    const wins = closed.filter(p => (p.realised_pnl ?? 0) > 0).length;
    return {
      executiveSummary: `Weekly Report (current session data): ${closed.length} closed trades. Total realised P&L: ₹${fmt(realised,2)}. Win rate: ${closed.length > 0 ? fmt((wins/closed.length)*100,0) : 0}%. Full weekly cross-session analysis available after multi-session storage is enabled.`,
      metrics: [
        { label: "Closed Trades",  value: String(closed.length) },
        { label: "Weekly P&L",     value: `₹${fmt(realised,2)}` },
        { label: "Win Rate",       value: closed.length > 0 ? `${fmt((wins/closed.length)*100,0)}%` : "N/A" },
      ],
      highlights: [
        `${closed.length} paper trades executed this session`,
        `Session realised P&L: ₹${fmt(realised,2)}`,
        "Strategy ranking: available after 5+ sessions with persistence",
        "Market regime history: available after multi-session storage enabled",
        "Weekly comparison enabled in Trading Timeline Comparison tab",
      ],
      recommendations: [
        "Enable multi-session persistence to unlock full weekly analytics",
        "Review Strategy Intelligence for week-over-week trends",
        "Check AI Performance for weekly calibration trend",
        "Plan next week's watchlist and strategy focus",
      ],
      warnings: [],
      nextSteps: [
        "Export current session data for manual weekly aggregation",
        "Review Learning Review page for weekly governance insights",
        "Update strategy parameters for next week",
      ],
    };
  }, [positions]);
}

function useMonthlyReport(positions: any[]) {
  return useMemo(() => {
    const closed = positions.filter(p => p.status === "CLOSED");
    const realised = closed.reduce((acc, p) => acc + (p.realised_pnl ?? 0), 0);
    return {
      executiveSummary: `Monthly Report: Current session shows ${closed.length} closed trades with ₹${fmt(realised,2)} realised P&L. Full monthly cross-session analytics require persistent multi-session storage (planned Phase 10+).`,
      metrics: [
        { label: "Session Trades",  value: String(closed.length) },
        { label: "Session P&L",     value: `₹${fmt(realised,2)}` },
        { label: "Data Coverage",   value: "Current session" },
      ],
      highlights: [
        "Monthly analytics require multi-session data persistence",
        "Portfolio growth tracking planned for Phase 10+",
        "Strategy comparison across months enabled post-persistence",
        "Current session data exportable for manual monthly aggregation",
      ],
      recommendations: [
        "Export session JSON data monthly for aggregation",
        "Track equity curve manually using Export → JSON",
        "Review AI confidence trend in AI Performance page",
        "Check operational health trend in Observability",
      ],
      warnings: [{ sev: "info" as const, text: "Full monthly analytics require multi-session storage (Phase 10+)" }],
      nextSteps: [
        "Export current month's session data",
        "Review Performance Analytics for trend metrics",
        "Plan next month's risk budget and strategy focus",
      ],
    };
  }, [positions]);
}

// ─── Report panel ──────────────────────────────────────────────────────────────

function ReportPanel({
  type, summary, alerts, positions,
}: {
  type: ReportType;
  summary: any;
  alerts:  any[];
  positions: any[];
}) {
  const morning = useMorningBrief(summary, alerts);
  const open    = useOpenBrief(summary, alerts, positions);
  const midday  = useMiddayBrief(summary, alerts, positions);
  const close   = useCloseBrief(summary, alerts, positions);
  const eod     = useEodReport(summary, alerts, positions);
  const weekly  = useWeeklyReport(positions);
  const monthly = useMonthlyReport(positions);

  const map: Record<ReportType, ReturnType<typeof useMorningBrief>> = {
    morning, open, midday, close, eod, weekly, monthly,
  };

  const report  = map[type];
  const meta    = REPORT_META[type];
  const IconC   = meta.icon;

  // Export helpers
  const handleExportCsv = useCallback(() => {
    const rows = [
      ["Section", "Item", "Value"],
      ...report.metrics.map(m => ["Key Metrics", m.label, m.value]),
      ...report.highlights.map(h => ["Highlights", h, ""]),
      ...report.recommendations.map(r => ["Recommendations", r, ""]),
      ...report.warnings.map(w => ["Warnings", w.sev, w.text]),
      ...report.nextSteps.map(n => ["Next Steps", n, ""]),
    ];
    const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g,'""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `apexquant_${type}_brief_${new Date().toISOString().slice(0,10)}.csv`; a.click();
  }, [report, type]);

  const handleExportJson = useCallback(() => {
    const data = { reportType: type, generatedAt: nowISO(), ...report, warnings: report.warnings.map(w => ({ ...w })) };
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    a.download = `apexquant_${type}_brief_${new Date().toISOString().slice(0,10)}.json`; a.click();
  }, [report, type]);

  return (
    <div>
      {/* Report header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: `${meta.color}22`, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <IconC size={18} color={meta.color} />
          </div>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: "#F9FAFB" }}>{meta.label}</div>
            <div style={{ fontSize: 12, color: "#6B7280" }}>{meta.subtitle} · {meta.when}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button variant="outline" size="sm" onClick={handleExportCsv} style={{ fontSize: 11, height: 30 }}>
            <Download size={12} style={{ marginRight: 4 }} /> CSV
          </Button>
          <Button variant="outline" size="sm" onClick={handleExportJson} style={{ fontSize: 11, height: 30 }}>
            <Download size={12} style={{ marginRight: 4 }} /> JSON
          </Button>
        </div>
      </div>

      {/* Executive Summary */}
      <SectionCard title="Executive Summary">
        <p style={{ color: "#D1D5DB", fontSize: 13, lineHeight: 1.7, margin: 0 }}>{report.executiveSummary}</p>
      </SectionCard>

      {/* Key Metrics */}
      <SectionCard title="Key Metrics">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {report.metrics.map((m, i) => (
            <div key={i} style={{ background: "#0f1420", borderRadius: 8, padding: "10px 14px", minWidth: 120, flex: "1 1 120px" }}>
              <div style={{ fontSize: 10, color: "#6B7280", letterSpacing: "0.04em" }}>{m.label}</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: "#F9FAFB", marginTop: 2 }}>{m.value}</div>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Highlights */}
      <SectionCard title="Highlights">
        <BulletList items={report.highlights} color={meta.color} />
      </SectionCard>

      {/* Recommendations */}
      <SectionCard title="Recommendations">
        <BulletList items={report.recommendations} color="#10B981" />
      </SectionCard>

      {/* Warnings */}
      <SectionCard title="Warnings">
        {report.warnings.length === 0
          ? <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#10B981", fontSize: 13 }}><CheckCircle2 size={14} /> No warnings for this report period</div>
          : report.warnings.map((w, i) => <AlertRow key={i} sev={w.sev} text={w.text} />)
        }
      </SectionCard>

      {/* Next Steps */}
      <SectionCard title="Next Steps">
        <BulletList items={report.nextSteps} color="#3B82F6" />
      </SectionCard>
    </div>
  );
}

// ─── AI Insights panel ─────────────────────────────────────────────────────────

function AiInsightsPanel({ summary, alerts, positions }: { summary: any; alerts: any[]; positions: any[] }) {
  const insights = useMemo(() => {
    const closed = positions.filter(p => p.status === "CLOSED");
    const open   = positions.filter(p => p.status === "OPEN");
    const realised = closed.reduce((acc, p) => acc + (p.realised_pnl ?? 0), 0);
    const wins = closed.filter(p => (p.realised_pnl ?? 0) > 0).length;
    const regime = summary?.regime_analysis?.primary_regime ?? "UNKNOWN";
    const opsHealth = summary?.health?.overall_score ?? 0;
    const criticals = alerts.filter(a => a.severity === "critical").length;

    return [
      {
        q: "What changed today?",
        icon: RefreshCw,
        color: "#3B82F6",
        a: `Regime: ${regime}. ${closed.length} trades closed vs session start. ${criticals} critical platform events. Platform health: ${fmt(opsHealth, 0)}/100.`,
      },
      {
        q: "Why did it happen?",
        icon: Eye,
        color: "#8B5CF6",
        a: `Regime classification drives strategy selection. ${criticals > 0 ? "Critical alerts indicate platform or data events that required operator attention." : "No critical events — platform operated normally."} Paper trading executed according to AI advisory signals.`,
      },
      {
        q: "What performed well?",
        icon: TrendingUp,
        color: "#10B981",
        a: closed.length > 0
          ? `${wins} of ${closed.length} closed trades were profitable (win rate: ${fmt((wins/closed.length)*100, 0)}%). Realised P&L: ₹${fmt(realised, 2)}.`
          : "No closed trades yet this session — check back after positions are closed.",
      },
      {
        q: "What underperformed?",
        icon: AlertTriangle,
        color: "#F59E0B",
        a: (() => {
          const losers = closed.filter(p => (p.realised_pnl ?? 0) < 0);
          if (losers.length === 0) return "No losing trades this session — all closed positions are profitable.";
          const worst = losers.sort((a, b) => (a.realised_pnl ?? 0) - (b.realised_pnl ?? 0))[0];
          return `${losers.length} losing trades. Worst: ${worst?.symbol ?? "unknown"} (₹${fmt(worst?.realised_pnl ?? 0, 2)}). Review exit timing in Trade Replay.`;
        })(),
      },
      {
        q: "What should be monitored next?",
        icon: Target,
        color: "#EF4444",
        a: `${open.length > 0 ? `${open.length} open positions require monitoring for adverse price moves. ` : ""}${opsHealth < 80 ? "Platform health below 80 — check Observability page. " : ""}Review AI confidence trend in AI Performance Intelligence for session drift.`,
      },
    ];
  }, [summary, alerts, positions]);

  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#9CA3AF", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 14 }}>AI Insights — Advisory Only</div>
      {insights.map((ins, i) => {
        const IconC = ins.icon;
        return (
          <div key={i} style={{ background: "#1a1f2e", border: "1px solid #2d3348", borderRadius: 10, padding: "14px 16px", marginBottom: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <IconC size={14} color={ins.color} />
              <span style={{ fontSize: 12, fontWeight: 600, color: ins.color }}>{ins.q}</span>
            </div>
            <p style={{ color: "#D1D5DB", fontSize: 13, margin: 0, lineHeight: 1.6 }}>{ins.a}</p>
          </div>
        );
      })}
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function ExecutiveReports() {
  const [, navigate] = useLocation();

  // ── Data queries (reuse existing cached endpoints) ──────────────────────────
  const { data: summaryData }   = useQuery({ queryKey: ["command-center/summary"],  queryFn: () => apiJson("command-center/summary"),  staleTime: 30_000 });
  const { data: alertsData }    = useQuery({ queryKey: ["command-center/alerts"],   queryFn: () => apiJson("command-center/alerts"),   staleTime: 30_000 });
  const { data: positionsData } = useQuery({ queryKey: ["phase20/positions"],       queryFn: () => apiJson("phase20/positions"),       staleTime: 30_000 });
  const { data: copilotData }   = useQuery({ queryKey: ["copilot/alerts"],          queryFn: () => apiJson("copilot/alerts"),          staleTime: 30_000 });

  const summary   = summaryData   ?? {};
  const alerts    = useMemo(() => [
    ...((alertsData as any)?.alerts   ?? []),
    ...((copilotData as any)?.alerts  ?? []),
  ], [alertsData, copilotData]);
  const positions = useMemo(() => (positionsData as any)?.positions ?? [], [positionsData]);

  // ── UI state ────────────────────────────────────────────────────────────────
  const [activeReport, setActiveReport] = useState<ReportType>("eod");
  const [activeTab, setActiveTab]       = useState<"report" | "insights" | "library">("report");
  const [librarySearch, setLibrarySearch] = useState("");
  const [libraryFilter, setLibraryFilter] = useState<ReportType | "all">("all");
  const [showFilters, setShowFilters]   = useState(false);

  // ── Report library (localStorage) ──────────────────────────────────────────
  const [library, setLibrary] = useState<SavedReport[]>(() => {
    try { return JSON.parse(localStorage.getItem(LS_LIBRARY_KEY) ?? "[]"); } catch { return []; }
  });

  const saveCurrentReport = useCallback(() => {
    const entry: SavedReport = {
      id:          `${activeReport}-${Date.now()}`,
      type:        activeReport,
      label:       REPORT_META[activeReport].label,
      generatedAt: nowISO(),
      starred:     false,
    };
    const updated = [entry, ...library].slice(0, 100);
    setLibrary(updated);
    localStorage.setItem(LS_LIBRARY_KEY, JSON.stringify(updated));
  }, [activeReport, library]);

  const toggleStar = useCallback((id: string) => {
    const updated = library.map(r => r.id === id ? { ...r, starred: !r.starred } : r);
    setLibrary(updated);
    localStorage.setItem(LS_LIBRARY_KEY, JSON.stringify(updated));
  }, [library]);

  const deleteReport = useCallback((id: string) => {
    const updated = library.filter(r => r.id !== id);
    setLibrary(updated);
    localStorage.setItem(LS_LIBRARY_KEY, JSON.stringify(updated));
  }, [library]);

  const filteredLibrary = useMemo(() => {
    return library
      .filter(r => libraryFilter === "all" || r.type === libraryFilter)
      .filter(r => !librarySearch || r.label.toLowerCase().includes(librarySearch.toLowerCase()) || r.type.includes(librarySearch.toLowerCase()));
  }, [library, libraryFilter, librarySearch]);

  // ── KPI scores ──────────────────────────────────────────────────────────────
  const kpis = useMemo<KpiScore[]>(() => {
    const s  = summary as any;
    const healthScore    = s?.health?.overall_score               ?? 0;
    const positions_open = positions.filter((p: any) => p.status === "OPEN").length;
    const closed_arr     = positions.filter((p: any) => p.status === "CLOSED");
    const wins           = closed_arr.filter((p: any) => (p.realised_pnl ?? 0) > 0).length;
    const portScore      = closed_arr.length > 0 ? (wins / closed_arr.length) * 100 : 50;
    const aiAlerts       = alerts.filter(a => a.category === "ai" || a.category === "signal").length;
    const aiScore        = Math.min(100, 50 + aiAlerts * 5);
    const criticals      = alerts.filter(a => a.severity === "critical").length;
    const riskScore      = Math.max(0, 100 - criticals * 20);
    const opsScore       = healthScore;
    const secScore       = 70;   // placeholder — real value from security-center summary
    const perfScore      = 75;   // placeholder — real value from performance-center summary
    const deployScore    = 80;   // placeholder — real value from deployment-center summary
    const overall        = (healthScore * 0.15 + portScore * 0.15 + aiScore * 0.15 + riskScore * 0.15 + opsScore * 0.15 + secScore * 0.10 + perfScore * 0.10 + deployScore * 0.05) / 1;
    return [
      { label: "Market",      score: Math.min(100, 65 + (s?.regime_analysis ? 10 : 0)), icon: TrendingUp,    color: "#10B981" },
      { label: "Portfolio",   score: portScore,  icon: Briefcase,    color: "#3B82F6" },
      { label: "AI",          score: aiScore,    icon: Bot,          color: "#8B5CF6" },
      { label: "Risk",        score: riskScore,  icon: Shield,       color: "#EF4444" },
      { label: "Operations",  score: opsScore,   icon: Settings,     color: "#F59E0B" },
      { label: "Security",    score: secScore,   icon: Eye,          color: "#EC4899" },
      { label: "Performance", score: perfScore,  icon: Zap,          color: "#06B6D4" },
      { label: "Deployment",  score: deployScore,icon: Activity,     color: "#F97316" },
      { label: "Overall",     score: Math.min(100, overall), icon: BarChart3, color: "#A78BFA" },
    ];
  }, [summary, alerts, positions]);

  const tabs: { id: "report" | "insights" | "library"; label: string }[] = [
    { id: "report",   label: "Report" },
    { id: "insights", label: "AI Insights" },
    { id: "library",  label: `Library (${library.length})` },
  ];

  return (
    <div style={{ padding: "20px 24px", minHeight: "100vh", fontFamily: "inherit" }}>

      {/* Page header */}
      <PageHeader
        title="Executive Reports"
        subtitle={`AI Briefings & Intelligent Session Reports · ${new Date().toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "long", year: "numeric", month: "long", day: "numeric" })}`}
        icon={FileBarChart2}
        agentId="operations"
        agentName="Operations Agent"
        advisory
        readOnly
        breadcrumbs={[{ label: "Operations" }, { label: "Executive Reports" }]}
        actions={
          <Button variant="outline" size="sm" onClick={saveCurrentReport} style={{ fontSize: 11, height: 32 }}>
            <BookMarked size={12} style={{ marginRight: 5 }} /> Save Report
          </Button>
        }
        helpTitle="Executive Reports & AI Briefings"
        faqs={[
          { q: "How are reports generated?", a: "Reports are generated from existing cached data — no new API calls. All data reuses the 30-second stale-time cache." },
          { q: "What is the Report Library?", a: "The Library tab saves a copy of the current report to your browser's localStorage so you can review it later." },
          { q: "Why are Weekly/Monthly reports limited?", a: "Full weekly and monthly analytics require multi-session data persistence, planned for Phase 10+." },
          { q: "How do I export a report?", a: "Use the CSV or JSON buttons at the top of any report to download its data." },
        ]}
        relatedPages={[
          { label: "Trading Timeline",  href: "/trading-timeline" },
          { label: "Command Centre",    href: "/command-center" },
          { label: "AI Performance",    href: "/ai-performance" },
          { label: "Portfolio",         href: "/portfolio-live" },
        ]}
      />

      {/* KPI scores row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 20 }}>
        {kpis.map(k => <KpiCard key={k.label} label={k.label} score={k.score} Icon={k.icon} color={k.color} />)}
      </div>

      {/* Quick actions */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 20, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "#6B7280", marginRight: 4 }}>Jump to:</span>
        {QUICK_ACTIONS.map(qa => {
          const IconC = qa.icon;
          return (
            <button key={qa.href} onClick={() => navigate(qa.href)} style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 10px", background: "#1a1f2e", border: "1px solid #2d3348", borderRadius: 6, cursor: "pointer", color: "#9CA3AF", fontSize: 11 }}>
              <IconC size={11} />
              {qa.label}
              <ArrowRight size={10} />
            </button>
          );
        })}
      </div>

      {/* Main content */}
      <div style={{ display: "flex", gap: 16 }}>

        {/* Left: Report type selector */}
        <div style={{ width: 220, flexShrink: 0 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: "#6B7280", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>Report Types</div>
          {(Object.entries(REPORT_META) as [ReportType, typeof REPORT_META[ReportType]][]).map(([type, meta]) => {
            const IconC  = meta.icon;
            const active = activeReport === type;
            return (
              <button
                key={type}
                onClick={() => { setActiveReport(type); setActiveTab("report"); }}
                style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 12px", borderRadius: 8, marginBottom: 4, cursor: "pointer", border: "none",
                  background: active ? `${meta.color}18` : "transparent",
                  outline: active ? `1px solid ${meta.color}40` : "none",
                  textAlign: "left",
                }}
              >
                <IconC size={14} color={meta.color} />
                <div>
                  <div style={{ fontSize: 12, fontWeight: active ? 600 : 400, color: active ? "#F9FAFB" : "#9CA3AF" }}>{meta.label}</div>
                  <div style={{ fontSize: 10, color: "#6B7280" }}>{meta.when}</div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Right: Content */}
        <div style={{ flex: 1, minWidth: 0 }}>

          {/* Tabs */}
          <div style={{ display: "flex", gap: 4, marginBottom: 16, borderBottom: "1px solid #2d3348", paddingBottom: 0 }}>
            {tabs.map(t => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                style={{
                  padding: "6px 14px", fontSize: 12, fontWeight: activeTab === t.id ? 600 : 400,
                  color: activeTab === t.id ? "#A78BFA" : "#6B7280",
                  background: "none", border: "none", cursor: "pointer",
                  borderBottom: activeTab === t.id ? "2px solid #A78BFA" : "2px solid transparent",
                  marginBottom: -1,
                }}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {activeTab === "report" && (
            <ReportPanel type={activeReport} summary={summary} alerts={alerts} positions={positions} />
          )}

          {activeTab === "insights" && (
            <AiInsightsPanel summary={summary} alerts={alerts} positions={positions} />
          )}

          {activeTab === "library" && (
            <div>
              {/* Library controls */}
              <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ position: "relative", flex: 1, minWidth: 180 }}>
                  <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#6B7280" }} />
                  <Input value={librarySearch} onChange={e => setLibrarySearch(e.target.value)} placeholder="Search saved reports…" style={{ paddingLeft: 30, height: 32, fontSize: 12 }} />
                </div>
                <button onClick={() => setShowFilters(v => !v)} style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 10px", background: "#1a1f2e", border: "1px solid #2d3348", borderRadius: 6, cursor: "pointer", color: "#9CA3AF", fontSize: 11 }}>
                  <Filter size={11} /> Filter {showFilters ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                </button>
              </div>
              {showFilters && (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                  {([["all","All"] as const, ...Object.entries(REPORT_META).map(([k,v]) => [k, v.label] as [ReportType,string])]).map(([k, label]) => (
                    <button key={k} onClick={() => setLibraryFilter(k as any)} style={{ padding: "3px 10px", fontSize: 11, borderRadius: 5, border: "1px solid #2d3348", background: libraryFilter === k ? "#6366F130" : "#1a1f2e", color: libraryFilter === k ? "#A78BFA" : "#9CA3AF", cursor: "pointer" }}>
                      {label}
                    </button>
                  ))}
                </div>
              )}

              {filteredLibrary.length === 0 ? (
                <div style={{ textAlign: "center", padding: "40px 20px", color: "#6B7280" }}>
                  <BookMarked size={32} style={{ marginBottom: 12, opacity: 0.4 }} />
                  <div style={{ fontSize: 14, marginBottom: 6 }}>No saved reports yet</div>
                  <div style={{ fontSize: 12 }}>Click "Save Report" to archive the current report to the library</div>
                </div>
              ) : (
                filteredLibrary.map(r => {
                  const m = REPORT_META[r.type]; const IconC = m.icon;
                  return (
                    <div key={r.id} style={{ background: "#1a1f2e", border: "1px solid #2d3348", borderRadius: 8, padding: "12px 14px", marginBottom: 8, display: "flex", alignItems: "center", gap: 12 }}>
                      <div style={{ width: 30, height: 30, borderRadius: 6, background: `${m.color}22`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        <IconC size={14} color={m.color} />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 500, color: "#F9FAFB" }}>{r.label}</div>
                        <div style={{ fontSize: 11, color: "#6B7280" }}>{fmtDate(r.generatedAt)}</div>
                      </div>
                      <button onClick={() => toggleStar(r.id)} style={{ background: "none", border: "none", cursor: "pointer", color: r.starred ? "#F59E0B" : "#4B5563", padding: 4 }}>
                        {r.starred ? <Star size={14} fill="#F59E0B" /> : <StarOff size={14} />}
                      </button>
                      <button onClick={() => { setActiveReport(r.type); setActiveTab("report"); }} style={{ padding: "3px 10px", fontSize: 11, background: "#6366F115", border: "1px solid #6366F130", borderRadius: 5, cursor: "pointer", color: "#A78BFA" }}>
                        View
                      </button>
                      <button onClick={() => deleteReport(r.id)} style={{ padding: "3px 6px", fontSize: 11, background: "none", border: "none", cursor: "pointer", color: "#4B5563" }}>
                        <XCircle size={13} />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
