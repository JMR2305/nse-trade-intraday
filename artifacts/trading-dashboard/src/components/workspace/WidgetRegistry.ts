/**
 * WidgetRegistry.ts — Phase 9.4
 * Canonical registry of all 21 widgets.
 * UI metadata only — no business logic, no API calls.
 */

import type { LucideIcon } from "lucide-react";
import {
  Globe2, Briefcase, TrendingUp, Eye, Shield, Brain,
  Radar, Sunrise, Bell, BookOpen, PieChart, Zap,
  GraduationCap, BarChart3, Settings2, Lock, Rocket,
  Activity, Clock, Sparkles, StickyNote,
} from "lucide-react";

export type WidgetCategory =
  | "market"
  | "portfolio"
  | "risk"
  | "ai"
  | "research"
  | "execution"
  | "learning"
  | "operations"
  | "personal";

export interface WidgetDef {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
  category: WidgetCategory;
  /** Default size on grid */
  defaultSize: "sm" | "md" | "lg" | "xl" | "full";
  /** Default row height */
  defaultRows: 1 | 2 | 3;
  /** API endpoint to fetch (path only, no /api/ prefix) */
  endpoint?: string;
  /** Available per-widget metric keys for the "Visible metrics" setting */
  metricKeys?: string[];
  /** Brief tag shown on widget chip */
  tag?: string;
}

export const WIDGET_REGISTRY: WidgetDef[] = [
  // ── Market ──────────────────────────────────────────────────────────────────
  {
    id: "market-overview",
    label: "Market Overview",
    description: "NIFTY, Bank NIFTY, breadth, volume & sector trends",
    icon: Globe2,
    category: "market",
    defaultSize: "lg",
    defaultRows: 2,
    endpoint: "command-center/system",
    metricKeys: ["nifty", "banknifty", "breadth", "advance-decline", "volume"],
    tag: "LIVE",
  },
  {
    id: "watchlist",
    label: "Watchlist",
    description: "Your tracked symbols with live price & signal status",
    icon: Eye,
    category: "market",
    defaultSize: "md",
    defaultRows: 2,
    endpoint: "preopen/watchlist",
    metricKeys: ["price", "change", "signal", "volume"],
    tag: "LIVE",
  },
  {
    id: "pre-open",
    label: "Pre-Open Intelligence",
    description: "Pre-open session: IEP, order book, top movers",
    icon: Sunrise,
    category: "market",
    defaultSize: "md",
    defaultRows: 2,
    endpoint: "preopen/session",
    metricKeys: ["iep", "order-book", "top-movers"],
    tag: "PRE",
  },
  {
    id: "market-intelligence",
    label: "Market Intelligence",
    description: "Regime, macro signals, sector rotation, breadth",
    icon: Radar,
    category: "market",
    defaultSize: "lg",
    defaultRows: 2,
    endpoint: "market-intelligence/overview",
    metricKeys: ["regime", "breadth", "sector", "macro"],
    tag: "INTEL",
  },
  // ── Portfolio ───────────────────────────────────────────────────────────────
  {
    id: "portfolio",
    label: "Portfolio",
    description: "Open positions, allocation, sector exposure",
    icon: Briefcase,
    category: "portfolio",
    defaultSize: "lg",
    defaultRows: 2,
    endpoint: "phase20/positions",
    metricKeys: ["value", "pnl", "positions", "exposure"],
    tag: "PORT",
  },
  {
    id: "today-pnl",
    label: "Today's P&L",
    description: "Intraday P&L, realised vs unrealised, trade breakdown",
    icon: TrendingUp,
    category: "portfolio",
    defaultSize: "sm",
    defaultRows: 1,
    endpoint: "portfolio-performance/summary",
    metricKeys: ["total-pnl", "realised", "unrealised", "trade-count"],
    tag: "P&L",
  },
  {
    id: "performance",
    label: "Performance",
    description: "Win rate, Sharpe, max drawdown, equity curve",
    icon: BarChart3,
    category: "portfolio",
    defaultSize: "lg",
    defaultRows: 2,
    endpoint: "portfolio-performance/summary",
    metricKeys: ["win-rate", "sharpe", "drawdown", "trades"],
    tag: "PERF",
  },
  {
    id: "paper-trading",
    label: "Paper Trading",
    description: "Auto paper trading status, open positions, P&L",
    icon: PieChart,
    category: "portfolio",
    defaultSize: "md",
    defaultRows: 1,
    endpoint: "phase20/health",
    metricKeys: ["status", "positions", "pnl", "trades"],
    tag: "PAPER",
  },
  // ── Risk ────────────────────────────────────────────────────────────────────
  {
    id: "risk-summary",
    label: "Risk Summary",
    description: "VaR, exposure, drawdown, capital utilisation",
    icon: Shield,
    category: "risk",
    defaultSize: "md",
    defaultRows: 1,
    endpoint: "command-center/risk",
    metricKeys: ["var", "exposure", "drawdown", "capital"],
    tag: "RISK",
  },
  // ── AI ──────────────────────────────────────────────────────────────────────
  {
    id: "ai-summary",
    label: "AI Summary",
    description: "AI confidence, accuracy, active signals, regime",
    icon: Brain,
    category: "ai",
    defaultSize: "md",
    defaultRows: 1,
    endpoint: "command-center/summary",
    metricKeys: ["confidence", "accuracy", "signals", "regime"],
    tag: "AI",
  },
  {
    id: "ai-daily-briefing",
    label: "AI Daily Briefing",
    description: "AI-generated daily market briefing and recommendations",
    icon: Sparkles,
    category: "ai",
    defaultSize: "xl",
    defaultRows: 2,
    endpoint: "command-center/summary",
    metricKeys: ["briefing", "recommendations", "regime"],
    tag: "BRIEF",
  },
  // ── Research ────────────────────────────────────────────────────────────────
  {
    id: "research-feed",
    label: "Research Feed",
    description: "Active hypotheses, research signals, strategy insights",
    icon: BookOpen,
    category: "research",
    defaultSize: "md",
    defaultRows: 2,
    endpoint: "research-lab/hypotheses",
    metricKeys: ["hypotheses", "signals", "insights"],
    tag: "RSCH",
  },
  // ── Execution ───────────────────────────────────────────────────────────────
  {
    id: "alerts",
    label: "Alerts",
    description: "System alerts, risk breaches, signal notifications",
    icon: Bell,
    category: "execution",
    defaultSize: "md",
    defaultRows: 2,
    endpoint: "command-center/alerts",
    metricKeys: ["critical", "warning", "info"],
    tag: "ALERT",
  },
  {
    id: "execution",
    label: "Execution",
    description: "Broker connection, order flow, execution quality",
    icon: Zap,
    category: "execution",
    defaultSize: "md",
    defaultRows: 1,
    endpoint: "broker/status",
    metricKeys: ["broker", "latency", "fill-rate"],
    tag: "EXEC",
  },
  {
    id: "trading-timeline",
    label: "Trading Timeline",
    description: "Today's trade events, session markers, P&L points",
    icon: Clock,
    category: "execution",
    defaultSize: "full",
    defaultRows: 1,
    endpoint: "command-center/timeline",
    metricKeys: ["events", "trades", "markers"],
    tag: "HIST",
  },
  // ── Learning ────────────────────────────────────────────────────────────────
  {
    id: "learning",
    label: "Learning",
    description: "AI learning progress, model improvement, insights",
    icon: GraduationCap,
    category: "learning",
    defaultSize: "md",
    defaultRows: 1,
    endpoint: "command-center/summary",
    metricKeys: ["accuracy-trend", "improvement", "insights"],
    tag: "LEARN",
  },
  // ── Operations ──────────────────────────────────────────────────────────────
  {
    id: "operations",
    label: "Operations",
    description: "Scheduler, data quality, automation, task status",
    icon: Settings2,
    category: "operations",
    defaultSize: "md",
    defaultRows: 1,
    endpoint: "observability/health",
    metricKeys: ["scheduler", "data-quality", "automation"],
    tag: "OPS",
  },
  {
    id: "security",
    label: "Security",
    description: "Auth, API security, compliance score, secret status",
    icon: Lock,
    category: "operations",
    defaultSize: "sm",
    defaultRows: 1,
    endpoint: "command-center/system",
    metricKeys: ["auth", "api-security", "compliance"],
    tag: "SEC",
  },
  {
    id: "deployment",
    label: "Deployment",
    description: "Deployment readiness, backup, infra health",
    icon: Rocket,
    category: "operations",
    defaultSize: "sm",
    defaultRows: 1,
    endpoint: "command-center/system",
    metricKeys: ["readiness", "backup", "infra"],
    tag: "DEPLOY",
  },
  {
    id: "system-health",
    label: "System Health",
    description: "API server, database, scheduler, memory, CPU",
    icon: Activity,
    category: "operations",
    defaultSize: "md",
    defaultRows: 1,
    endpoint: "command-center/system",
    metricKeys: ["api", "db", "scheduler", "memory", "cpu"],
    tag: "SYS",
  },
  // ── Personal ────────────────────────────────────────────────────────────────
  {
    id: "quick-notes",
    label: "Quick Notes",
    description: "Personal trading notes, reminders, observations",
    icon: StickyNote,
    category: "personal",
    defaultSize: "sm",
    defaultRows: 2,
    // No endpoint — localStorage only
    metricKeys: [],
    tag: "NOTES",
  },
];

export const WIDGET_MAP = new Map<string, WidgetDef>(
  WIDGET_REGISTRY.map((w) => [w.id, w])
);

export function getWidget(id: string): WidgetDef | undefined {
  return WIDGET_MAP.get(id);
}

export function getWidgetsByCategory(category: WidgetCategory): WidgetDef[] {
  return WIDGET_REGISTRY.filter((w) => w.category === category);
}

// All widget categories in display order
export const WIDGET_CATEGORIES: { id: WidgetCategory; label: string; emoji: string }[] = [
  { id: "market",     label: "Market",    emoji: "📡" },
  { id: "portfolio",  label: "Portfolio", emoji: "💼" },
  { id: "risk",       label: "Risk",      emoji: "🛡" },
  { id: "ai",         label: "AI",        emoji: "🤖" },
  { id: "research",   label: "Research",  emoji: "🔬" },
  { id: "execution",  label: "Execution", emoji: "⚡" },
  { id: "learning",   label: "Learning",  emoji: "🎓" },
  { id: "operations", label: "Ops",       emoji: "🛠" },
  { id: "personal",   label: "Personal",  emoji: "📝" },
];

// KPI definitions for personal KPI bar
export interface KpiDef {
  id: string;
  label: string;
  shortLabel: string;
  unit?: string;
  endpoint?: string;
  /** JSON path into response to find the value */
  valuePath?: string;
  color?: string;
}

export const KPI_REGISTRY: KpiDef[] = [
  { id: "portfolio-value",  label: "Portfolio Value",  shortLabel: "Portfolio",  unit: "₹",  endpoint: "phase20/summary",              color: "#3B82F6" },
  { id: "today-pnl",        label: "Today's P&L",      shortLabel: "P&L",        unit: "₹",  endpoint: "portfolio-performance/summary", color: "#10B981" },
  { id: "risk-score",       label: "Risk Score",       shortLabel: "Risk",       unit: "/100",endpoint: "command-center/risk",          color: "#EF4444" },
  { id: "ai-confidence",    label: "AI Confidence",    shortLabel: "AI Conf",    unit: "%",  endpoint: "command-center/summary",        color: "#8B5CF6" },
  { id: "market-breadth",   label: "Market Breadth",   shortLabel: "Breadth",    unit: "%",  endpoint: "market-intelligence/overview",  color: "#F59E0B" },
  { id: "nifty-value",      label: "NIFTY 50",         shortLabel: "NIFTY",      unit: "pts",endpoint: "preopen/session",               color: "#06B6D4" },
  { id: "banknifty-value",  label: "Bank NIFTY",       shortLabel: "BNIFTY",     unit: "pts",endpoint: "preopen/session",               color: "#F97316" },
  { id: "bullish-stocks",   label: "Bullish Stocks",   shortLabel: "Bulls",      unit: "",   endpoint: "preopen/watchlist",             color: "#10B981" },
  { id: "open-positions",   label: "Open Positions",   shortLabel: "Positions",  unit: "",   endpoint: "phase20/positions",             color: "#3B82F6" },
  { id: "platform-health",  label: "Platform Health",  shortLabel: "Health",     unit: "%",  endpoint: "command-center/system",         color: "#10B981" },
  { id: "win-rate",         label: "Win Rate",         shortLabel: "Win%",       unit: "%",  endpoint: "portfolio-performance/summary", color: "#8B5CF6" },
  { id: "drawdown",         label: "Max Drawdown",     shortLabel: "Drawdown",   unit: "%",  endpoint: "portfolio-performance/summary", color: "#EF4444" },
];

export const KPI_MAP = new Map<string, KpiDef>(KPI_REGISTRY.map((k) => [k.id, k]));
