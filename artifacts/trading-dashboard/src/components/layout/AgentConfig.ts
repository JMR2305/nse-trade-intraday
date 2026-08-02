/**
 * AgentConfig.ts — Phase 9.2
 * Defines the 10 AI Agents, their colours, and which pages belong to each.
 *
 * Navigation/layout data only — no business logic, no API calls.
 * Import from here to keep agent metadata in one canonical place.
 */
import {
  Globe2, Wifi, Radar, Eye, Clock, Sunrise,
  BookOpenText, FlaskConical, TestTubes, CalendarDays, Globe,
  TrendingUp, Target, Gauge, BarChart3, Activity,
  Database, Brain, Zap, Lightbulb, GraduationCap,
  Shield, ShieldCheck,
  ShieldAlert, Briefcase, PieChart, History, RotateCcw, LayoutDashboard,
  Monitor, Rocket, Settings2, Radio, Dna, Microscope, GitCompare,
  Route, Layers, ChevronRight, Bot, Bell,
} from "lucide-react";

// Re-export LucideIcon type alias for consumers
import type { LucideIcon } from "lucide-react";
export type { LucideIcon };

export interface AgentPage {
  href:  string;
  label: string;
  icon:  LucideIcon;
  /** Optional short alias for search */
  tags?: string[];
}

export interface Agent {
  id:          string;
  num:         number;
  emoji:       string;
  name:        string;
  shortName:   string;
  description: string;
  /** Hex colour — used for dot, active accent, header strip */
  color:       string;
  pages:       AgentPage[];
}

// ── Agent definitions ──────────────────────────────────────────────────────────
// Spec colours: Blue · Green · Purple · Orange · Red · Amber · Indigo · Teal · Cyan · Grey

export const AGENTS: Agent[] = [
  // ── Agent 1 — Market Data ──────────────────────────────────────────────────
  {
    id: "market-data", num: 1,
    emoji: "📡", name: "Market Data Agent", shortName: "Market Data",
    description: "Live feeds, NSE data, breadth, volume, watchlists",
    color: "#3B82F6",      // blue-500
    pages: [
      { href: "/market",               label: "Market Overview",       icon: Globe2,   tags: ["nse", "index", "overview"] },
      { href: "/market-scanner",       label: "Market Scanner",        icon: Radar,    tags: ["scan", "live"] },
      { href: "/live-data-health",     label: "Live Data Health",      icon: Wifi,     tags: ["feed", "zerodha", "ohlc"] },
      { href: "/watchlist",            label: "Watchlist",             icon: Eye,      tags: ["watch"] },
      { href: "/preopen-intelligence", label: "Pre-Open Intelligence", icon: Sunrise,  tags: ["preopen", "ipo"] },
      { href: "/market-replay",        label: "Market Replay",         icon: Clock,    tags: ["replay", "history"] },
    ],
  },

  // ── Agent 2 — Research ────────────────────────────────────────────────────
  {
    id: "research", num: 2,
    emoji: "📰", name: "Research Agent", shortName: "Research",
    description: "News, macro events, announcements, research sources",
    color: "#10B981",      // emerald-500
    pages: [
      { href: "/research-lab",         label: "Research Lab",        icon: FlaskConical,  tags: ["lab", "research"] },
      { href: "/research-intelligence",label: "Research Intelligence",icon: Brain,         tags: ["intel"] },
      { href: "/research-notebook",    label: "Research Notebook",   icon: BookOpenText,  tags: ["notes", "notebook"] },
      { href: "/event-intelligence",   label: "Event Intelligence",  icon: CalendarDays,  tags: ["events", "news", "announcements"] },
      { href: "/macro-intelligence",   label: "Macro Intelligence",  icon: Globe,         tags: ["macro", "economy", "rbi"] },
      { href: "/experiments",          label: "Research Factory",    icon: TestTubes,     tags: ["factory", "experiments"] },
    ],
  },

  // ── Agent 3 — Market Intelligence ────────────────────────────────────────
  {
    id: "market-intelligence", num: 3,
    emoji: "📈", name: "Market Intelligence Agent", shortName: "Market Intel",
    description: "Regime, trend, sector rotation, volatility, breadth",
    color: "#8B5CF6",      // violet-500
    pages: [
      { href: "/market-intelligence", label: "Market Intelligence Hub", icon: TrendingUp, tags: ["regime", "sector", "breadth"] },
      { href: "/preopen-accuracy",    label: "Pre-Open Accuracy",       icon: Target,     tags: ["accuracy", "iep"] },
      { href: "/execution-quality",   label: "Execution Quality",       icon: Gauge,      tags: ["execution", "quality"] },
      { href: "/signal-validation",   label: "Signal Validation",       icon: Activity,   tags: ["signal", "validate"] },
      { href: "/performance-analytics",label: "Performance Analytics",  icon: BarChart3,  tags: ["analytics", "perf"] },
    ],
  },

  // ── Agent 4 — Stock Monitoring ────────────────────────────────────────────
  {
    id: "stock-monitoring", num: 4,
    emoji: "👁", name: "Stock Monitoring Agent", shortName: "Monitoring",
    description: "Signals, breakouts, momentum, volume alerts",
    color: "#F97316",      // orange-500
    pages: [
      { href: "/signals",           label: "Signals",          icon: Activity,  tags: ["signal", "alert"] },
      { href: "/signal-history",    label: "Signal History",   icon: History,   tags: ["history"] },
      { href: "/trade-intelligence",label: "Trade Intelligence",icon: Database,  tags: ["intelligence"] },
      { href: "/ai-decision",       label: "AI Decision",      icon: Brain,     tags: ["decision", "ai"] },
    ],
  },

  // ── Agent 5 — Strategy ────────────────────────────────────────────────────
  {
    id: "strategy", num: 5,
    emoji: "🎯", name: "Strategy Agent", shortName: "Strategy",
    description: "Breakout, VWAP, ORB, mean reversion, momentum strategies",
    color: "#EF4444",      // red-500
    pages: [
      { href: "/strategy-intelligence", label: "Strategy Intelligence",  icon: Zap,        tags: ["strategy", "intel"] },
      { href: "/strategy-optimisation", label: "Strategy Optimisation",  icon: Target,     tags: ["optimise"] },
      { href: "/strategy-lab",          label: "Strategy Lab",           icon: GitCompare, tags: ["lab", "compare"] },
      { href: "/strategy-evolution",    label: "Strategy Evolution",     icon: Dna,        tags: ["evolution"] },
      { href: "/backtest",              label: "Backtest",               icon: FlaskConical,tags: ["test", "backtest"] },
      { href: "/optimizer",             label: "Optimizer",              icon: Settings2,  tags: ["optimise", "params"] },
      { href: "/walk-forward",          label: "Walk-Forward Validation",icon: Route,      tags: ["wfv", "validate"] },
      { href: "/paper-basket-test",     label: "Paper Basket Test",      icon: Layers,     tags: ["basket", "paper"] },
      { href: "/validate",              label: "Validate",               icon: ShieldCheck,tags: ["validate"] },
      { href: "/pattern-quality",       label: "Pattern Quality",        icon: Gauge,      tags: ["pattern", "quality"] },
    ],
  },

  // ── Agent 6 — Risk ────────────────────────────────────────────────────────
  {
    id: "risk", num: 6,
    emoji: "⚠", name: "Risk Agent", shortName: "Risk",
    description: "Portfolio risk, sector risk, correlation, stress testing",
    color: "#F59E0B",      // amber-500
    pages: [
      { href: "/portfolio-risk",   label: "Portfolio Risk",   icon: ShieldCheck, tags: ["risk", "portfolio"] },
      { href: "/risk-optimisation",label: "Risk Optimisation",icon: Shield,      tags: ["optimise", "risk"] },
      { href: "/risk-validation",  label: "Risk Validation",  icon: ShieldAlert, tags: ["validate", "risk"] },
      { href: "/risk",             label: "Risk Management",  icon: Shield,      tags: ["management", "risk"] },
    ],
  },

  // ── Agent 7 — AI Decision ─────────────────────────────────────────────────
  {
    id: "ai-decision", num: 7,
    emoji: "🤖", name: "AI Decision Agent", shortName: "AI Decision",
    description: "AI dashboard, explainability, optimisation, confidence, drift",
    color: "#6366F1",      // indigo-500
    pages: [
      { href: "/ai-performance",     label: "AI Performance",      icon: Brain,         tags: ["ai", "performance"] },
      { href: "/ai-optimisation",    label: "AI Optimisation",     icon: Zap,           tags: ["ai", "optimise"] },
      { href: "/explainable-ai",     label: "Explainable AI",      icon: Lightbulb,     tags: ["xai", "explain"] },
      { href: "/ai-copilot",         label: "AI Copilot",          icon: Bot,           tags: ["copilot", "chat"] },
      { href: "/feature-importance", label: "Feature Importance",  icon: BarChart3,     tags: ["features", "shap"] },
      { href: "/learning-insights",  label: "Learning Insights",   icon: Brain,         tags: ["learning", "insights"] },
      { href: "/learning-review",    label: "Learning Review",     icon: GraduationCap, tags: ["review"] },
      { href: "/learning",           label: "Learning & Governance",icon: GraduationCap,tags: ["governance"] },
      { href: "/historical-knowledge",label:"Historical Knowledge",icon: BookOpenText,  tags: ["history", "knowledge"] },
      { href: "/phase12",            label: "Phase 12 Intelligence",icon: Microscope,   tags: ["phase12"] },
      { href: "/phase13",            label: "Phase 13 · Inst. AI", icon: Microscope,   tags: ["phase13"] },
    ],
  },

  // ── Agent 8 — Execution ───────────────────────────────────────────────────
  {
    id: "execution", num: 8,
    emoji: "💼", name: "Execution Agent", shortName: "Execution",
    description: "Paper orders, positions, order history, execution status",
    color: "#14B8A6",      // teal-500
    pages: [
      { href: "/",                    label: "Trade Decisions",      icon: Target,         tags: ["trade", "decision"] },
      { href: "/portfolio-live",      label: "Portfolio",            icon: PieChart,       tags: ["portfolio", "live"] },
      { href: "/portfolio-manager",   label: "Portfolio Manager",    icon: Briefcase,      tags: ["manager"] },
      { href: "/broker-execution",    label: "Broker & Execution",   icon: ShieldAlert,    tags: ["broker", "execution"] },
      { href: "/trades",              label: "All Trades",           icon: History,        tags: ["trades", "history"] },
      { href: "/portfolio-performance",label:"Portfolio Performance",icon: TrendingUp,     tags: ["performance", "pnl"] },
      { href: "/trade-replay",        label: "Trade Replay",         icon: RotateCcw,      tags: ["replay"] },
      { href: "/dashboard",           label: "Dashboard",            icon: LayoutDashboard,tags: ["dashboard"] },
      { href: "/executive-dashboard", label: "Executive Dashboard",  icon: LayoutDashboard,tags: ["executive"] },
    ],
  },

  // ── Agent 9 — Learning ────────────────────────────────────────────────────
  {
    id: "learning", num: 9,
    emoji: "📚", name: "Learning Agent", shortName: "Learning",
    description: "Paper analytics, trade replay, historical learning, AI performance",
    color: "#06B6D4",      // cyan-500
    pages: [
      { href: "/paper-analytics",  label: "Paper Analytics",  icon: BarChart3,     tags: ["paper", "analytics"] },
    ],
  },

  // ── Agent 10 — Operations ─────────────────────────────────────────────────
  {
    id: "operations", num: 10,
    emoji: "🛠", name: "Operations Agent", shortName: "Operations",
    description: "Infrastructure, observability, data quality, security, deployment",
    color: "#6B7280",      // slate-500
    pages: [
      { href: "/workspace",          label: "My Workspace",              icon: LayoutDashboard, tags: ["workspace", "dashboard", "widgets", "personalise"] },
      { href: "/trading-timeline",   label: "Trading Day Timeline",      icon: Clock,           tags: ["timeline", "session", "playback", "review", "history"] },
      { href: "/operations-center",  label: "Operations Centre",         icon: Monitor,    tags: ["ops"] },
      { href: "/observability",      label: "Observability",             icon: Activity,   tags: ["observe"] },
      { href: "/data-quality",       label: "Data Quality",              icon: ShieldCheck,tags: ["data", "quality"] },
      { href: "/security-center",    label: "Security & Compliance",     icon: ShieldCheck,tags: ["security"] },
      { href: "/performance-center", label: "Performance Centre",        icon: Zap,        tags: ["performance"] },
      { href: "/deployment-center",  label: "Deployment & DR",           icon: Rocket,     tags: ["deploy", "dr"] },
      { href: "/live-readiness",     label: "Live Readiness",            icon: Activity,   tags: ["readiness"] },
      { href: "/notifications",      label: "Notifications",             icon: Bell,       tags: ["alerts", "notify"] },
      { href: "/kite-connect",       label: "Kite Connect",              icon: Radio,      tags: ["kite", "zerodha"] },
      { href: "/settings",           label: "Settings",                  icon: Settings2,  tags: ["config", "settings"] },
      { href: "/system-validation",  label: "System Validation",         icon: ShieldCheck,tags: ["validate", "system"] },
      { href: "/validation",         label: "Paper Trading Validation",  icon: ShieldCheck,tags: ["paper", "validate"] },
      { href: "/phase4a-session",    label: "Phase 4A Operations",       icon: Activity,   tags: ["phase4"] },
      { href: "/operator-status",    label: "Operator Status",           icon: Monitor,    tags: ["operator"] },
      { href: "/automation",         label: "Automation Health",         icon: Gauge,      tags: ["automation"] },
    ],
  },
];

// ── Lookup helpers ─────────────────────────────────────────────────────────────

/** Flat list of all pages across all agents — for search */
export const ALL_PAGES: (AgentPage & { agentId: string; agentName: string; agentColor: string })[] =
  AGENTS.flatMap((a) =>
    a.pages.map((p) => ({
      ...p,
      agentId:    a.id,
      agentName:  a.shortName,
      agentColor: a.color,
    }))
  );

/** Find the agent that owns a given href */
export function getAgentForPath(path: string): Agent | undefined {
  return AGENTS.find((a) => a.pages.some((p) => p.href === path));
}

/** All searchable items: agents + pages */
export type SearchItem =
  | { kind: "agent"; agent: Agent }
  | { kind: "page";  page: (typeof ALL_PAGES)[number] };

export function searchItems(query: string): SearchItem[] {
  const q = query.toLowerCase().trim();
  if (!q) return [];

  const results: SearchItem[] = [];

  // Agents
  AGENTS.forEach((a) => {
    if (
      a.name.toLowerCase().includes(q) ||
      a.shortName.toLowerCase().includes(q) ||
      a.description.toLowerCase().includes(q)
    ) {
      results.push({ kind: "agent", agent: a });
    }
  });

  // Pages
  ALL_PAGES.forEach((p) => {
    if (
      p.label.toLowerCase().includes(q) ||
      p.href.includes(q) ||
      p.tags?.some((t) => t.includes(q))
    ) {
      results.push({ kind: "page", page: p });
    }
  });

  return results.slice(0, 20);
}

// ── Related pages ──────────────────────────────────────────────────────────────

/** Pages in the same agent as href, excluding href itself (max 4) */
export function getRelatedPages(
  href: string,
): (AgentPage & { agentId: string; agentName: string; agentColor: string })[] {
  const agent = getAgentForPath(href);
  if (!agent) return [];
  return agent.pages
    .filter((p) => p.href !== href)
    .slice(0, 4)
    .map((p) => ({ ...p, agentId: agent.id, agentName: agent.shortName, agentColor: agent.color }));
}

// ── Workflow shortcuts ─────────────────────────────────────────────────────────

export interface WorkflowShortcut {
  id:          string;
  label:       string;
  emoji:       string;
  description: string;
  pages:       { href: string; label: string }[];
}

export const WORKFLOW_SHORTCUTS: WorkflowShortcut[] = [
  {
    id: "morning", label: "Morning Workflow", emoji: "🌅",
    description: "Start-of-day market checks",
    pages: [
      { href: "/preopen-intelligence", label: "Pre-Open Intelligence" },
      { href: "/market-intelligence",  label: "Market Intelligence" },
      { href: "/signals",              label: "Signals" },
      { href: "/command-center",       label: "Command Centre" },
    ],
  },
  {
    id: "market-open", label: "Market Open", emoji: "🔔",
    description: "Market open execution checklist",
    pages: [
      { href: "/market",               label: "Market Overview" },
      { href: "/portfolio-live",       label: "Portfolio" },
      { href: "/broker-execution",     label: "Broker & Execution" },
      { href: "/risk-validation",      label: "Risk Validation" },
    ],
  },
  {
    id: "closing", label: "Closing Workflow", emoji: "🌆",
    description: "End-of-day review and reconciliation",
    pages: [
      { href: "/portfolio-performance",label: "Portfolio Performance" },
      { href: "/paper-analytics",      label: "Paper Analytics" },
      { href: "/broker-execution",     label: "Broker & Execution" },
      { href: "/ai-performance",       label: "AI Performance" },
    ],
  },
];

// ── Keyboard jump map (Ctrl/⌘ + 1-5) ──────────────────────────────────────────

export const KEYBOARD_JUMP_MAP: Record<string, string> = {
  "1": "/command-center",
  "2": "/market",           // Market Data Agent
  "3": "/research-lab",     // Research Agent
  "4": "/portfolio-risk",   // Risk Agent
  "5": "/ai-performance",   // AI Decision Agent
};
