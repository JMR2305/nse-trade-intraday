/**
 * WorkspaceManager.ts — Phase 9.4
 * Personalized Workspace: profiles, widget layouts, KPI bar, focus mode,
 * notification prefs, session memory, workspace templates, undo stack.
 *
 * UI/UX only — no business logic, no API calls, no calculations.
 * All state lives in localStorage.
 */

// ── Types ─────────────────────────────────────────────────────────────────────

export type WidgetSize = "sm" | "md" | "lg" | "xl" | "full";
export type WidgetRows = 1 | 2 | 3;

export interface WidgetSettings {
  refreshInterval: 15 | 30 | 60 | 120 | 300; // seconds
  compactMode: boolean;
  theme: "default" | "accent" | "minimal";
  visibleMetrics: string[];  // widget-specific metric keys to show
}

export interface WidgetInstance {
  instanceId: string;     // unique per grid slot
  widgetId: string;       // references WidgetRegistry
  size: WidgetSize;       // horizontal span
  rows: WidgetRows;       // vertical span
  pinned: boolean;
  collapsed: boolean;
  visible: boolean;
  settings: WidgetSettings;
}

export interface WorkspaceLayout {
  profileId: string;
  widgets: WidgetInstance[];  // ordered array = display order in grid
}

// Built-in + custom profiles
export interface WorkspaceProfileFull {
  id: string;
  label: string;
  emoji: string;
  color: string;
  description: string;
  isBuiltIn: boolean;
}

export type FocusMode =
  | "none"
  | "live-trading"
  | "research"
  | "review"
  | "learning"
  | "operations";

export interface NotifPrefs {
  style: "popup" | "banner" | "sidebar" | "silent";
  enabledKinds: string[];  // alert kind ids
}

export interface KpiBarConfig {
  kpis: string[];  // 8–12 kpi ids, ordered
}

export interface WorkspaceSession {
  lastProfile: string;
  lastPath: string;
  openSections: string[];
  pinnedWidgets: string[];
  lastActiveWorkspace: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

export const BUILT_IN_PROFILES: WorkspaceProfileFull[] = [
  { id: "intraday",      label: "Intraday",  emoji: "⚡", color: "#EF4444", description: "Live data, signals, fast execution",              isBuiltIn: true },
  { id: "swing",         label: "Swing",     emoji: "📊", color: "#3B82F6", description: "Multi-day trends, strategy, research",            isBuiltIn: true },
  { id: "research",      label: "Research",  emoji: "🔬", color: "#8B5CF6", description: "Deep analysis, AI performance, backtesting",      isBuiltIn: true },
  { id: "paper-trading", label: "Paper",     emoji: "📄", color: "#10B981", description: "Paper trading, validation, performance tracking", isBuiltIn: true },
  { id: "operations",    label: "Ops",       emoji: "🛠", color: "#6B7280", description: "System health, data quality, deployment",         isBuiltIn: true },
];

export const FOCUS_MODES: { id: FocusMode; label: string; emoji: string; description: string; }[] = [
  { id: "none",          label: "Normal",      emoji: "🖥",  description: "All widgets visible" },
  { id: "live-trading",  label: "Live Trading",emoji: "⚡",  description: "Market, P&L, execution, alerts" },
  { id: "research",      label: "Research",    emoji: "🔬",  description: "Market intel, AI, research feed" },
  { id: "review",        label: "Review",      emoji: "📋",  description: "Performance, timeline, portfolio" },
  { id: "learning",      label: "Learning",    emoji: "🎓",  description: "Learning, performance, AI summary" },
  { id: "operations",    label: "Operations",  emoji: "🛠",  description: "Ops, security, deployment, health" },
];

// Widgets visible per focus mode (if not in list, hidden)
export const FOCUS_MODE_WIDGETS: Record<FocusMode, string[]> = {
  "none": [],  // empty = all visible
  "live-trading":  ["market-overview", "portfolio", "today-pnl", "watchlist", "execution", "alerts", "risk-summary", "ai-summary", "trading-timeline"],
  "research":      ["market-intelligence", "pre-open", "ai-summary", "research-feed", "ai-daily-briefing", "market-overview", "watchlist"],
  "review":        ["performance", "portfolio", "trading-timeline", "today-pnl", "ai-daily-briefing", "paper-trading"],
  "learning":      ["learning", "performance", "ai-summary", "research-feed", "ai-daily-briefing"],
  "operations":    ["operations", "security", "deployment", "system-health"],
};

// Default KPI bar
export const DEFAULT_KPI_BAR: string[] = [
  "portfolio-value", "today-pnl", "risk-score", "ai-confidence",
  "nifty-value", "banknifty-value", "open-positions", "platform-health",
];

// Workspace templates
export interface WorkspaceTemplate {
  id: string;
  label: string;
  emoji: string;
  description: string;
  profileId: string;
  widgetIds: string[];  // ordered widget ids for the template layout
  kpis: string[];
}

export const WORKSPACE_TEMPLATES: WorkspaceTemplate[] = [
  {
    id: "professional-trader",
    label: "Professional Trader",
    emoji: "📈",
    description: "Full trading station: market data, execution, risk, P&L",
    profileId: "intraday",
    widgetIds: ["market-overview", "today-pnl", "watchlist", "portfolio", "alerts", "execution", "risk-summary", "ai-summary", "trading-timeline"],
    kpis: ["portfolio-value", "today-pnl", "risk-score", "nifty-value", "banknifty-value", "open-positions", "ai-confidence", "market-breadth"],
  },
  {
    id: "research-analyst",
    label: "Research Analyst",
    emoji: "🔬",
    description: "Deep research: intelligence, AI, research feed, performance",
    profileId: "research",
    widgetIds: ["ai-daily-briefing", "market-intelligence", "research-feed", "pre-open", "ai-summary", "market-overview", "performance", "watchlist"],
    kpis: ["ai-confidence", "bullish-stocks", "market-breadth", "platform-health", "portfolio-value", "win-rate", "today-pnl", "drawdown"],
  },
  {
    id: "risk-manager",
    label: "Risk Manager",
    emoji: "🛡",
    description: "Risk focus: risk summary, portfolio, alerts, performance",
    profileId: "swing",
    widgetIds: ["risk-summary", "portfolio", "today-pnl", "alerts", "performance", "market-overview", "trading-timeline", "paper-trading"],
    kpis: ["risk-score", "portfolio-value", "drawdown", "open-positions", "today-pnl", "ai-confidence", "platform-health", "win-rate"],
  },
  {
    id: "ai-analyst",
    label: "AI Analyst",
    emoji: "🤖",
    description: "AI-first view: AI summary, briefing, performance, market intel",
    profileId: "research",
    widgetIds: ["ai-daily-briefing", "ai-summary", "ai-performance-widget", "market-intelligence", "pre-open", "research-feed", "performance", "market-overview"],
    kpis: ["ai-confidence", "win-rate", "platform-health", "bullish-stocks", "market-breadth", "portfolio-value", "today-pnl", "risk-score"],
  },
  {
    id: "executive-view",
    label: "Executive View",
    emoji: "👔",
    description: "High-level overview: portfolio, P&L, AI, system health",
    profileId: "swing",
    widgetIds: ["portfolio", "today-pnl", "ai-summary", "system-health", "performance", "risk-summary", "ai-daily-briefing", "operations"],
    kpis: ["portfolio-value", "today-pnl", "ai-confidence", "platform-health", "risk-score", "open-positions", "win-rate", "drawdown"],
  },
];

// ── localStorage keys ─────────────────────────────────────────────────────────

const K = {
  layouts:    "apexquant_widget_layouts",
  custom:     "apexquant_custom_profiles",
  kpiBar:     "apexquant_kpi_bar",
  focusMode:  "apexquant_focus_mode",
  notifPrefs: "apexquant_notif_prefs",
  session:    "apexquant_session",
  undoStack:  "apexquant_layout_undo",
} as const;

// ── Helpers ────────────────────────────────────────────────────────────────────

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    if (v) return JSON.parse(v) as T;
  } catch {}
  return fallback;
}

function write(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

// ── Default widget instance factory ───────────────────────────────────────────

export function makeWidgetInstance(widgetId: string, overrides?: Partial<WidgetInstance>): WidgetInstance {
  return {
    instanceId: uid(),
    widgetId,
    size: "md",
    rows: 1,
    pinned: false,
    collapsed: false,
    visible: true,
    settings: {
      refreshInterval: 30,
      compactMode: false,
      theme: "default",
      visibleMetrics: [],
    },
    ...overrides,
  };
}

// ── Default layouts per profile ───────────────────────────────────────────────

const PROFILE_DEFAULT_WIDGETS: Record<string, string[]> = {
  "intraday":      ["market-overview", "today-pnl", "watchlist", "portfolio", "alerts", "execution", "risk-summary", "ai-summary", "trading-timeline", "system-health"],
  "swing":         ["market-overview", "portfolio", "today-pnl", "risk-summary", "ai-summary", "market-intelligence", "research-feed", "performance", "trading-timeline"],
  "research":      ["ai-daily-briefing", "market-intelligence", "research-feed", "pre-open", "ai-summary", "performance", "market-overview", "watchlist"],
  "paper-trading": ["portfolio", "today-pnl", "paper-trading", "performance", "risk-summary", "alerts", "ai-summary", "trading-timeline"],
  "operations":    ["system-health", "operations", "security", "deployment", "alerts", "platform-health-widget", "ai-daily-briefing"],
};

function buildDefaultLayout(profileId: string): WorkspaceLayout {
  const widgetIds = PROFILE_DEFAULT_WIDGETS[profileId] ?? PROFILE_DEFAULT_WIDGETS["intraday"];
  return {
    profileId,
    widgets: widgetIds.map((wid) => makeWidgetInstance(wid)),
  };
}

// ── Layout CRUD ────────────────────────────────────────────────────────────────

export function getLayout(profileId: string): WorkspaceLayout {
  const all = read<Record<string, WorkspaceLayout>>(K.layouts, {});
  return all[profileId] ?? buildDefaultLayout(profileId);
}

export function saveLayout(layout: WorkspaceLayout) {
  // Push undo before saving
  pushUndo(layout.profileId);
  const all = read<Record<string, WorkspaceLayout>>(K.layouts, {});
  all[layout.profileId] = layout;
  write(K.layouts, all);
}

export function resetLayout(profileId: string): WorkspaceLayout {
  const fresh = buildDefaultLayout(profileId);
  const all = read<Record<string, WorkspaceLayout>>(K.layouts, {});
  all[profileId] = fresh;
  write(K.layouts, all);
  return fresh;
}

// ── Undo stack ─────────────────────────────────────────────────────────────────

export function pushUndo(profileId: string) {
  const all = read<Record<string, WorkspaceLayout[]>>(K.undoStack, {});
  const current = getLayout(profileId);
  const stack = all[profileId] ?? [];
  all[profileId] = [current, ...stack].slice(0, 10);
  write(K.undoStack, all);
}

export function popUndo(profileId: string): WorkspaceLayout | null {
  const all = read<Record<string, WorkspaceLayout[]>>(K.undoStack, {});
  const stack = all[profileId] ?? [];
  if (!stack.length) return null;
  const [prev, ...rest] = stack;
  all[profileId] = rest;
  write(K.undoStack, all);
  // Save the restored layout (without re-pushing undo)
  const layouts = read<Record<string, WorkspaceLayout>>(K.layouts, {});
  layouts[profileId] = prev;
  write(K.layouts, layouts);
  return prev;
}

export function canUndo(profileId: string): boolean {
  const all = read<Record<string, WorkspaceLayout[]>>(K.undoStack, {});
  return (all[profileId] ?? []).length > 0;
}

// ── Custom profiles ────────────────────────────────────────────────────────────

export function getCustomProfiles(): WorkspaceProfileFull[] {
  return read<WorkspaceProfileFull[]>(K.custom, []);
}

export function getAllProfiles(): WorkspaceProfileFull[] {
  return [...BUILT_IN_PROFILES, ...getCustomProfiles()];
}

export function createProfile(partial: { label: string; emoji: string; color: string; description?: string }): WorkspaceProfileFull {
  const profile: WorkspaceProfileFull = {
    id: `custom-${uid()}`,
    label: partial.label,
    emoji: partial.emoji,
    color: partial.color,
    description: partial.description ?? "",
    isBuiltIn: false,
  };
  const customs = getCustomProfiles();
  write(K.custom, [...customs, profile]);
  return profile;
}

export function renameProfile(id: string, label: string) {
  const customs = getCustomProfiles().map((p) =>
    p.id === id ? { ...p, label } : p
  );
  write(K.custom, customs);
}

export function duplicateProfile(sourceId: string, newLabel: string): WorkspaceProfileFull | null {
  const source = getAllProfiles().find((p) => p.id === sourceId);
  if (!source) return null;
  const newProfile = createProfile({ label: newLabel, emoji: source.emoji, color: source.color, description: source.description });
  // Copy layout
  const sourceLayout = getLayout(sourceId);
  saveLayout({ ...sourceLayout, profileId: newProfile.id });
  return newProfile;
}

export function deleteProfile(id: string): boolean {
  const customs = getCustomProfiles();
  if (!customs.some((p) => p.id === id)) return false;  // can't delete built-in
  write(K.custom, customs.filter((p) => p.id !== id));
  // Also remove layout
  const all = read<Record<string, WorkspaceLayout>>(K.layouts, {});
  delete all[id];
  write(K.layouts, all);
  return true;
}

export function applyTemplate(templateId: string, profileId: string) {
  const template = WORKSPACE_TEMPLATES.find((t) => t.id === templateId);
  if (!template) return;
  const layout: WorkspaceLayout = {
    profileId,
    widgets: template.widgetIds.map((wid) => makeWidgetInstance(wid)),
  };
  pushUndo(profileId);
  const all = read<Record<string, WorkspaceLayout>>(K.layouts, {});
  all[profileId] = layout;
  write(K.layouts, all);
  saveKpiBar({ kpis: template.kpis });
}

// ── KPI Bar ────────────────────────────────────────────────────────────────────

export function getKpiBar(): KpiBarConfig {
  return read<KpiBarConfig>(K.kpiBar, { kpis: DEFAULT_KPI_BAR });
}

export function saveKpiBar(config: KpiBarConfig) {
  write(K.kpiBar, config);
}

// ── Focus Mode ─────────────────────────────────────────────────────────────────

export function getFocusMode(): FocusMode {
  return read<FocusMode>(K.focusMode, "none");
}

export function setFocusMode(mode: FocusMode) {
  write(K.focusMode, mode);
}

// ── Notification Prefs ─────────────────────────────────────────────────────────

const DEFAULT_NOTIF_PREFS: NotifPrefs = {
  style: "banner",
  enabledKinds: ["CRITICAL", "WARNING", "EXECUTION", "RISK", "SYSTEM"],
};

export function getNotifPrefs(): NotifPrefs {
  return read<NotifPrefs>(K.notifPrefs, DEFAULT_NOTIF_PREFS);
}

export function saveNotifPrefs(prefs: NotifPrefs) {
  write(K.notifPrefs, prefs);
}

// ── Session Memory ─────────────────────────────────────────────────────────────

const DEFAULT_SESSION: WorkspaceSession = {
  lastProfile: "intraday",
  lastPath: "/",
  openSections: [],
  pinnedWidgets: [],
  lastActiveWorkspace: "intraday",
};

export function getSession(): WorkspaceSession {
  return read<WorkspaceSession>(K.session, DEFAULT_SESSION);
}

export function saveSession(partial: Partial<WorkspaceSession>) {
  const current = getSession();
  write(K.session, { ...current, ...partial });
}

// ── Widget helpers ─────────────────────────────────────────────────────────────

export function isWidgetVisibleInFocusMode(widgetId: string, mode: FocusMode): boolean {
  if (mode === "none") return true;
  return FOCUS_MODE_WIDGETS[mode]?.includes(widgetId) ?? false;
}

export function updateWidget(layout: WorkspaceLayout, instanceId: string, updates: Partial<WidgetInstance>): WorkspaceLayout {
  return {
    ...layout,
    widgets: layout.widgets.map((w) =>
      w.instanceId === instanceId ? { ...w, ...updates } : w
    ),
  };
}

export function removeWidget(layout: WorkspaceLayout, instanceId: string): WorkspaceLayout {
  return { ...layout, widgets: layout.widgets.filter((w) => w.instanceId !== instanceId) };
}

export function addWidget(layout: WorkspaceLayout, widgetId: string): WorkspaceLayout {
  return { ...layout, widgets: [...layout.widgets, makeWidgetInstance(widgetId)] };
}

export function reorderWidgets(layout: WorkspaceLayout, fromIndex: number, toIndex: number): WorkspaceLayout {
  const widgets = [...layout.widgets];
  const [moved] = widgets.splice(fromIndex, 1);
  widgets.splice(toIndex, 0, moved);
  return { ...layout, widgets };
}
