/**
 * WorkspaceStore.ts — Phase 9.3
 * Single localStorage store for workspace intelligence:
 *  — 5 workspace profiles (Intraday / Swing / Research / Paper / Operations)
 *  — Visit counts (drives "Most Used" shortcuts)
 *  — Recent searches
 *  — Smart bookmarks
 *
 * Navigation/layout only. No business logic. No API calls.
 */

// ── Profile types ──────────────────────────────────────────────────────────────

export type WorkspaceProfile =
  | "intraday"
  | "swing"
  | "research"
  | "paper-trading"
  | "operations";

export interface ProfileDef {
  id:           WorkspaceProfile;
  label:        string;
  emoji:        string;
  description:  string;
  color:        string;
  /** Agent ids to auto-expand when this profile is active */
  focusAgents:  string[];
  /** Quick-access hrefs shown at top of sidebar for this profile */
  quickLinks:   string[];
}

export const PROFILES: ProfileDef[] = [
  {
    id: "intraday", label: "Intraday", emoji: "⚡",
    description: "Live data, signals, fast execution",
    color: "#EF4444",
    focusAgents: ["market-data", "stock-monitoring", "execution"],
    quickLinks:  ["/market", "/signals", "/portfolio-live", "/broker-execution"],
  },
  {
    id: "swing", label: "Swing", emoji: "📊",
    description: "Multi-day trends, strategy, research",
    color: "#3B82F6",
    focusAgents: ["strategy", "research", "market-intelligence"],
    quickLinks:  ["/strategy-intelligence", "/research-lab", "/market-intelligence"],
  },
  {
    id: "research", label: "Research", emoji: "🔬",
    description: "Deep analysis, AI performance, backtesting",
    color: "#8B5CF6",
    focusAgents: ["research", "ai-decision", "strategy"],
    quickLinks:  ["/research-lab", "/ai-performance", "/backtest", "/explainable-ai"],
  },
  {
    id: "paper-trading", label: "Paper", emoji: "📄",
    description: "Paper trading, validation, performance",
    color: "#10B981",
    focusAgents: ["execution", "learning", "risk"],
    quickLinks:  ["/portfolio-live", "/paper-analytics", "/risk-validation"],
  },
  {
    id: "operations", label: "Ops", emoji: "🛠",
    description: "System health, data quality, deployment",
    color: "#6B7280",
    focusAgents: ["operations"],
    quickLinks:  ["/operations-center", "/observability", "/data-quality"],
  },
];

// ── localStorage keys ──────────────────────────────────────────────────────────

const K = {
  profile:   "apexquant_workspace_profile",
  visits:    "apexquant_visit_counts",
  searches:  "apexquant_recent_searches",
  bookmarks: "apexquant_bookmarks",
} as const;

// ── Profile ────────────────────────────────────────────────────────────────────

export function getProfile(): WorkspaceProfile {
  try {
    const v = localStorage.getItem(K.profile);
    if (v && PROFILES.some((p) => p.id === v)) return v as WorkspaceProfile;
  } catch {}
  return "intraday";
}

export function setProfile(id: WorkspaceProfile) {
  try { localStorage.setItem(K.profile, id); } catch {}
}

export function getProfileDef(id?: WorkspaceProfile): ProfileDef {
  return PROFILES.find((p) => p.id === (id ?? getProfile())) ?? PROFILES[0];
}

// ── Visit counts (drives "Most Used") ─────────────────────────────────────────

export function getVisitCounts(): Record<string, number> {
  try { return JSON.parse(localStorage.getItem(K.visits) || "{}"); }
  catch { return {}; }
}

export function incrementVisit(href: string) {
  try {
    const counts = getVisitCounts();
    counts[href] = (counts[href] || 0) + 1;
    localStorage.setItem(K.visits, JSON.stringify(counts));
  } catch {}
}

export function getMostUsed(n = 5): string[] {
  const counts = getVisitCounts();
  return Object.entries(counts)
    .sort(([, a], [, b]) => b - a)
    .slice(0, n)
    .map(([href]) => href);
}

// ── Recent searches ────────────────────────────────────────────────────────────

export function getRecentSearches(): string[] {
  try { return JSON.parse(localStorage.getItem(K.searches) || "[]"); }
  catch { return []; }
}

export function addRecentSearch(query: string) {
  const q = query.trim();
  if (!q || q.length < 2) return;
  try {
    const existing = getRecentSearches().filter((s) => s !== q);
    localStorage.setItem(K.searches, JSON.stringify([q, ...existing].slice(0, 8)));
  } catch {}
}

// ── Bookmarks ──────────────────────────────────────────────────────────────────

export interface Bookmark {
  href:        string;
  label:       string;
  timestamp:   number;
  agentColor?: string;
}

export function getBookmarks(): Bookmark[] {
  try { return JSON.parse(localStorage.getItem(K.bookmarks) || "[]"); }
  catch { return []; }
}

export function addBookmark(bm: Bookmark) {
  try {
    const existing = getBookmarks().filter((b) => b.href !== bm.href);
    localStorage.setItem(K.bookmarks, JSON.stringify([bm, ...existing].slice(0, 20)));
  } catch {}
}

export function removeBookmark(href: string) {
  try {
    localStorage.setItem(K.bookmarks, JSON.stringify(getBookmarks().filter((b) => b.href !== href)));
  } catch {}
}

export function isBookmarked(href: string): boolean {
  return getBookmarks().some((b) => b.href === href);
}
