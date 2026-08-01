/**
 * AppLayout — Phase 9.2 — Multi-Agent Workspace
 *
 * Navigation/layout/UX only — zero business logic changes.
 * NO API changes. NO calculation changes.
 *
 * What changed from Phase 9.1:
 *  - Module-based nav → 10 Agent groups (collapsible, colour-coded)
 *  - Command Centre as pinned top-level home button
 *  - ★ Starred / Favourites group (localStorage)
 *  - Agent context header bar (coloured strip below top bar)
 *  - Ctrl+K QuickSwitcher (global keyboard shortcut)
 *  - Recent pages tracked in localStorage
 *  - Responsive: mobile drawer preserves all agent groups
 *
 * Preserved unchanged:
 *  - useReconciliationBadge hook
 *  - LiveMarketTicker, StaleScanBanner, CopilotPanel
 *  - All hrefs / wouter Route config
 *  - Theme toggle
 */
import React, { useState, useEffect, useCallback, useRef } from "react";
import { Link, useLocation } from "wouter";
import { useReconciliationBadge } from "@/hooks/useReconciliationBadge";
import {
  Moon, Sun, Menu, X, ChevronLeft, ChevronDown, ChevronRight,
  Star, StarOff, Search, Command, Home, Sparkles,
} from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import CopilotPanel from "@/components/CopilotPanel";
import LiveMarketTicker from "@/components/LiveMarketTicker";
import { StaleScanBanner } from "@/components/Phase15SystemHealth";
import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import {
  AGENTS, getAgentForPath, getRelatedPages, KEYBOARD_JUMP_MAP,
  type Agent, type AgentPage,
} from "./AgentConfig";
import { QuickSwitcher } from "./QuickSwitcher";
import {
  incrementVisit, getProfile, setProfile, getMostUsed, PROFILES, getProfileDef,
  type WorkspaceProfile,
} from "./WorkspaceStore";

// ── localStorage helpers ───────────────────────────────────────────────────────

const FAV_KEY      = "apexquant_favourites";        // string[] of hrefs
const EXPAND_KEY   = "apexquant_agents_expanded";   // string[] of agent ids
const RECENT_KEY   = "apexquant_recent_pages";

function readFavourites(): string[] {
  try { return JSON.parse(localStorage.getItem(FAV_KEY) || "[]"); }
  catch { return []; }
}
function writeFavourites(hrefs: string[]) {
  try { localStorage.setItem(FAV_KEY, JSON.stringify(hrefs)); }
  catch {}
}
function readExpanded(fallbackAgentId?: string): string[] {
  try {
    const stored = JSON.parse(localStorage.getItem(EXPAND_KEY) || "null");
    if (Array.isArray(stored)) return stored;
  } catch {}
  return fallbackAgentId ? [fallbackAgentId] : [];
}
function writeExpanded(ids: string[]) {
  try { localStorage.setItem(EXPAND_KEY, JSON.stringify(ids)); }
  catch {}
}
function recordRecent(href: string, label: string, color: string) {
  try {
    const existing = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    const filtered = existing.filter((r: any) => r.href !== href);
    localStorage.setItem(
      RECENT_KEY,
      JSON.stringify([{ href, label, agentColor: color }, ...filtered].slice(0, 8))
    );
  } catch {}
}

// ── Component ──────────────────────────────────────────────────────────────────

export function AppLayout({ children }: { children: React.ReactNode }) {
  const [location, navigate] = useLocation();
  const { theme, setTheme } = useTheme();
  const reconciliationBadgeCount = useReconciliationBadge();

  const [mobileOpen,  setMobileOpen]  = useState(false);
  const [collapsed,   setCollapsed]   = useState(false);
  const [quickOpen,   setQuickOpen]   = useState(false);
  const [favourites,  setFavourites]  = useState<string[]>(() => readFavourites());
  const [activeProfile, setActiveProfile] = useState<WorkspaceProfile>(() => getProfile());

  // Active agent derived from current route
  const activeAgent = getAgentForPath(location);

  // Expanded agent groups — auto-expand active agent on first visit
  const [expanded, setExpanded] = useState<string[]>(() =>
    readExpanded(activeAgent?.id)
  );

  // When route changes: track visit, auto-expand agent, record recent page
  useEffect(() => {
    incrementVisit(location);
    const agent = getAgentForPath(location);
    if (agent && !expanded.includes(agent.id)) {
      const next = [...expanded, agent.id];
      setExpanded(next);
      writeExpanded(next);
    }
    // Record recent
    if (agent) {
      const page = agent.pages.find((p) => p.href === location);
      if (page) recordRecent(location, page.label, agent.color);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location]);

  // Ctrl+K / Ctrl+1-5 global shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      // Ctrl+K — open search
      if (e.key === "k") { e.preventDefault(); setQuickOpen(true); return; }
      // Ctrl+1-5 — jump to agent first page; skip when typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      const jumpHref = KEYBOARD_JUMP_MAP[e.key];
      if (jumpHref) { e.preventDefault(); navigate(jumpHref); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Favourites helpers ───────────────────────────────────────────────────
  const isFav = useCallback((href: string) => favourites.includes(href), [favourites]);
  const toggleFav = useCallback((href: string) => {
    setFavourites((prev) => {
      const next = prev.includes(href) ? prev.filter((h) => h !== href) : [href, ...prev];
      writeFavourites(next);
      return next;
    });
  }, []);

  // ── Toggle agent group ───────────────────────────────────────────────────
  const toggleAgent = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      writeExpanded(next);
      return next;
    });
  }, []);

  // ── Shared nav render ─────────────────────────────────────────────────────
  const SidebarNav = ({ onNav }: { onNav?: () => void }) => {
    // Starred pages (lookup full page info from agents)
    const starredPages = favourites.flatMap((href) => {
      const agent = getAgentForPath(href);
      if (!agent) return [];
      const page  = agent.pages.find((p) => p.href === href);
      if (!page)  return [];
      return [{ page, agent }];
    });

    return (
      <nav className="flex-1 overflow-y-auto min-h-0 px-2 py-2 space-y-0.5">

        {/* ── Command Centre (pinned top) ── */}
        <Link
          href="/command-center"
          onClick={onNav}
          className={cn(
            "group flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-[13px] font-semibold transition-all duration-150 mb-2",
            collapsed ? "justify-center px-0" : "",
            location === "/command-center"
              ? "bg-primary/10 text-primary ring-1 ring-inset ring-primary/20"
              : "text-muted-foreground/80 hover:bg-sidebar-accent/60 hover:text-foreground",
          )}
        >
          <Home className={cn(
            "h-4 w-4 shrink-0",
            location === "/command-center" ? "text-primary" : "text-muted-foreground/60 group-hover:text-foreground",
          )} />
          {!collapsed && <span className="flex-1 truncate">Command Centre</span>}
          {!collapsed && location === "/command-center" && (
            <span className="text-[9px] bg-primary/20 text-primary px-1.5 py-0.5 rounded-full font-bold">HOME</span>
          )}
        </Link>

        {/* ── Divider ── */}
        {!collapsed && <div className="border-t border-border/40 mx-2 my-2" />}

        {/* ── Starred / Favourites group ── */}
        {!collapsed && starredPages.length > 0 && (
          <AgentGroup
            label="Starred"
            emoji="★"
            color="#F59E0B"
            items={starredPages.map(({ page, agent }) => ({ page, agentColor: agent.color }))}
            isExpanded={expanded.includes("__starred__")}
            onToggle={() => toggleAgent("__starred__")}
            activeHref={location}
            isFav={isFav}
            onToggleFav={toggleFav}
            onNav={onNav}
            reconciliationBadgeCount={reconciliationBadgeCount}
            collapsed={collapsed}
            isStarredGroup
          />
        )}

        {/* ── 10 Agent groups ── */}
        {AGENTS.map((agent) => (
          <AgentGroup
            key={agent.id}
            label={collapsed ? "" : `${agent.emoji} ${agent.name}`}
            emoji={agent.emoji}
            color={agent.color}
            items={agent.pages.map((page) => ({ page, agentColor: agent.color }))}
            isExpanded={expanded.includes(agent.id) || !!collapsed}
            onToggle={() => toggleAgent(agent.id)}
            activeHref={location}
            isFav={isFav}
            onToggleFav={toggleFav}
            onNav={onNav}
            reconciliationBadgeCount={reconciliationBadgeCount}
            collapsed={collapsed}
            hasActive={agent.pages.some((p) => p.href === location)}
          />
        ))}

        {/* ── Related Pages (siblings in same agent) ── */}
        {!collapsed && (() => {
          const related = getRelatedPages(location);
          if (related.length === 0) return null;
          const ownerAgent = getAgentForPath(location);
          return (
            <div className="mx-2 mt-3 mb-1">
              <p className="px-1 pb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/30">
                See also in {ownerAgent?.shortName}
              </p>
              <ul className="space-y-0.5">
                {related.slice(0, 3).map((p) => {
                  const Icon = p.icon;
                  return (
                    <li key={p.href}>
                      <Link
                        href={p.href}
                        onClick={onNav}
                        className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[11.5px] text-muted-foreground/50 hover:text-muted-foreground/90 hover:bg-sidebar-accent/40 transition-colors"
                      >
                        <Icon className="w-3 h-3 flex-shrink-0" style={{ color: p.agentColor + "99" }} />
                        <span className="truncate">{p.label}</span>
                        <ChevronRight className="w-2.5 h-2.5 ml-auto flex-shrink-0 opacity-40" />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })()}
      </nav>
    );
  };

  // ── Agent context bar (shown above content, below header) ─────────────────
  const AgentContextBar = () => {
    if (!activeAgent) return null;
    const activePage = activeAgent.pages.find((p) => p.href === location);
    return (
      <div
        className="hidden md:flex items-center gap-2 px-5 py-1.5 border-b border-white/5 text-[11px]"
        style={{ background: activeAgent.color + "12", borderTop: `1px solid ${activeAgent.color}25` }}
      >
        {/* Breadcrumb: Home › Agent › Page */}
        <span className="text-muted-foreground/35 text-[10px]">🏠</span>
        <ChevronRight className="w-2.5 h-2.5 text-muted-foreground/25 flex-shrink-0" />
        <span className="font-semibold" style={{ color: activeAgent.color }}>
          {activeAgent.emoji} {activeAgent.shortName}
        </span>
        <ChevronRight className="w-2.5 h-2.5 text-muted-foreground/25 flex-shrink-0" />
        <span className="text-muted-foreground/70">{activePage?.label ?? "—"}</span>
        <span className="ml-auto flex items-center gap-3">
          <span className="text-muted-foreground/35">Advisory only</span>
          <span className="text-muted-foreground/35">·</span>
          <span className="text-muted-foreground/35">Read-only</span>
        </span>
      </div>
    );
  };

  // ── Desktop sidebar ────────────────────────────────────────────────────────
  const DesktopSidebar = () => (
    <aside className={cn(
      "glass-strong relative z-30 hidden md:flex h-full flex-col border-r border-border/60 transition-[width] duration-300 ease-in-out",
      collapsed ? "w-[60px]" : "w-[252px]",
    )}>
      {/* Logo + collapse */}
      <div className={cn(
        "flex h-14 shrink-0 items-center border-b border-border/60 px-3",
        collapsed ? "justify-center" : "justify-between",
      )}>
        <Logo showWordmark={!collapsed} size={26} />
        <button
          onClick={() => setCollapsed((c) => !c)}
          className={cn(
            "grid h-7 w-7 place-items-center rounded-lg text-muted-foreground/60 hover:bg-sidebar-accent hover:text-foreground transition",
            collapsed ? "absolute -right-3.5 top-5 z-50 border border-border bg-background shadow-sm" : "",
          )}
          aria-label="Toggle sidebar"
        >
          <ChevronLeft className={cn("h-4 w-4 transition-transform duration-300", collapsed && "rotate-180")} />
        </button>
      </div>

      {/* Ctrl+K search hint (when expanded) */}
      {!collapsed && (
        <button
          onClick={() => setQuickOpen(true)}
          className="mx-2 my-2 flex items-center gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground/60 hover:bg-muted/50 hover:text-muted-foreground transition-colors"
        >
          <Search className="w-3.5 h-3.5" />
          <span className="flex-1 text-left">Search…</span>
          <span className="flex items-center gap-0.5 text-[10px] opacity-60">
            <kbd className="bg-muted/60 px-1 rounded">⌘</kbd>
            <kbd className="bg-muted/60 px-1 rounded">K</kbd>
          </span>
        </button>
      )}
      {collapsed && (
        <button
          onClick={() => setQuickOpen(true)}
          className="mx-auto mt-2 mb-1 grid h-8 w-8 place-items-center rounded-lg text-muted-foreground/50 hover:bg-sidebar-accent hover:text-foreground transition"
          title="Search (⌘K)"
        >
          <Search className="w-3.5 h-3.5" />
        </button>
      )}

      <SidebarNav />

      {/* Workspace Profile Switcher */}
      {!collapsed && (
        <div className="px-3 pb-2 border-t border-border/40 pt-2">
          <p className="text-[9px] uppercase tracking-wider text-muted-foreground/30 mb-1.5 px-1">Workspace</p>
          <div className="flex flex-wrap gap-1">
            {PROFILES.map((p) => {
              const active = activeProfile === p.id;
              return (
                <button
                  key={p.id}
                  onClick={() => { setProfile(p.id); setActiveProfile(p.id); }}
                  title={p.description}
                  className={cn(
                    "flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium transition-all",
                    active ? "ring-1 ring-inset" : "opacity-40 hover:opacity-70",
                  )}
                  style={active ? { backgroundColor: p.color + "20", color: p.color } : {}}
                >
                  {p.emoji} {p.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className={cn(
        "flex shrink-0 items-center gap-2 border-t border-border/60 px-4 py-3",
        collapsed ? "justify-center" : "justify-between",
      )}>
        {!collapsed && (
          <span className="text-[10px] text-muted-foreground/40 font-mono truncate">ApexQuant AI</span>
        )}
        <Button
          variant="ghost" size="icon"
          className="h-8 w-8 shrink-0 text-muted-foreground/70 hover:text-foreground"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          data-testid="button-toggle-theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </aside>
  );

  // ── Mobile drawer ──────────────────────────────────────────────────────────
  const MobileDrawer = () => (
    <>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-foreground/20 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-[260px] flex flex-col border-r border-border/60 bg-sidebar shadow-pop animate-[fade-in-up_0.2s_ease-out_both]">
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-border/60 px-4">
              <Logo showWordmark size={26} />
              <button
                onClick={() => setMobileOpen(false)}
                className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground/60 hover:bg-sidebar-accent hover:text-foreground transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Search */}
            <button
              onClick={() => { setMobileOpen(false); setQuickOpen(true); }}
              className="mx-2 my-2 flex items-center gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-[12px] text-muted-foreground/60"
            >
              <Search className="w-3.5 h-3.5" />
              <span>Search…</span>
            </button>

            <SidebarNav onNav={() => setMobileOpen(false)} />

            <div className="flex shrink-0 items-center justify-between border-t border-border/60 px-4 py-3">
              <span className="text-[10px] text-muted-foreground/50 font-mono" data-testid="text-engine-version">ApexQuant AI</span>
              <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground/70"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")} data-testid="button-toggle-theme">
                {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </Button>
            </div>
          </aside>
        </div>
      )}
    </>
  );

  // ── Root layout ────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground selection:bg-primary/15 selection:text-foreground">
      {/* Ambient background */}
      <div className="pointer-events-none absolute inset-0 -z-10 bg-mesh" />
      <div className="pointer-events-none absolute inset-0 -z-10 opacity-40 bg-grid-faint [background-size:56px_56px]" />

      <DesktopSidebar />
      <MobileDrawer />

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">

        {/* Mobile top bar */}
        <div className="flex md:hidden h-12 shrink-0 items-center gap-2 border-b border-border/60 bg-background/80 backdrop-blur-sm px-4 z-20">
          <button
            onClick={() => setMobileOpen(true)}
            className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground transition"
          >
            <Menu className="h-4 w-4" />
          </button>
          <Logo showWordmark size={22} />
          <span className="shrink-0 inline-flex items-center rounded-full border border-warn px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest bg-warn-surface text-warn">
            Paper
          </span>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground/70"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")} data-testid="button-toggle-theme">
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        {/* Desktop top bar */}
        <header className="glass-strong hidden md:flex h-13 shrink-0 items-center gap-3 border-b border-border/60 px-5 z-20">
          {/* Search button (opens QuickSwitcher) */}
          <button
            onClick={() => setQuickOpen(true)}
            className="relative flex items-center gap-2 h-8 flex-1 max-w-xs rounded-lg border border-border bg-card/60 px-3 text-[12px] text-muted-foreground/50 hover:border-primary/40 hover:bg-card/80 transition-colors"
          >
            <Search className="w-3.5 h-3.5 flex-shrink-0" />
            <span className="flex-1 text-left">Search pages, symbols, strategies…</span>
            <span className="hidden lg:flex items-center gap-0.5 text-[10px] opacity-60 flex-shrink-0">
              <kbd className="bg-muted/60 px-1 rounded">⌘</kbd>
              <kbd className="bg-muted/60 px-1 rounded">K</kbd>
            </span>
          </button>

          <div className="flex-1" />

          {/* Market status */}
          <div className="hidden lg:flex items-center gap-2 rounded-lg border border-border bg-card/60 px-2.5 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-[pulse-soft_2.8s_ease-in-out_infinite]" />
            <span className="text-[11px] font-medium text-muted-foreground">NSE</span>
            <span className="text-[11px] text-muted-foreground/40">·</span>
            <span className="text-[11px] font-semibold text-green-600 dark:text-green-400">OPEN</span>
          </div>

          {/* AI status */}
          <div className="hidden xl:flex items-center gap-1.5 rounded-lg border border-primary/20 bg-primary/8 px-2.5 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-[pulse-soft_2.8s_ease-in-out_infinite]" />
            <span className="text-[11px] font-medium text-primary">AI Advisory Active</span>
          </div>

          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground/70 hover:text-foreground"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")} data-testid="button-toggle-theme">
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </header>

        {/* Agent context bar */}
        <AgentContextBar />

        {/* Live tickers and banners */}
        <LiveMarketTicker />
        <StaleScanBanner />

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 relative z-10">
          <div className="mx-auto max-w-[1440px]">
            {children}
          </div>
        </main>

        <CopilotPanel />
      </div>

      {/* QuickSwitcher modal */}
      <QuickSwitcher open={quickOpen} onClose={() => setQuickOpen(false)} currentPath={location} />
    </div>
  );
}

// ── AgentGroup sub-component ───────────────────────────────────────────────────

interface AgentGroupProps {
  label:     string;
  emoji:     string;
  color:     string;
  items:     { page: AgentPage; agentColor: string }[];
  isExpanded: boolean;
  onToggle:  () => void;
  activeHref: string;
  isFav:     (href: string) => boolean;
  onToggleFav: (href: string) => void;
  onNav?:    () => void;
  reconciliationBadgeCount: number;
  collapsed: boolean;
  hasActive?: boolean;
  isStarredGroup?: boolean;
}

function AgentGroup({
  label, emoji, color, items, isExpanded, onToggle,
  activeHref, isFav, onToggleFav, onNav,
  reconciliationBadgeCount, collapsed, hasActive, isStarredGroup,
}: AgentGroupProps) {
  const [hoveredHref, setHoveredHref] = useState<string | null>(null);
  const hasAnyActive = items.some((i) => i.page.href === activeHref);

  if (collapsed) {
    // Icon-only mode: show just the emoji as a section separator dot
    return (
      <div className="flex justify-center py-1">
        <div
          className={cn(
            "w-7 h-7 rounded-lg flex items-center justify-center text-[13px] cursor-pointer transition-all",
            hasAnyActive
              ? "ring-1 ring-inset"
              : "opacity-50 hover:opacity-100",
          )}
          style={hasAnyActive ? { backgroundColor: color + "25" } : {}}
          title={label}
        >
          {emoji}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-0.5">
      {/* Agent group header */}
      <button
        onClick={onToggle}
        className={cn(
          "group flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-[11px] font-semibold transition-all duration-150",
          hasAnyActive
            ? "text-foreground/90"
            : "text-muted-foreground/60 hover:text-muted-foreground/80",
          isStarredGroup ? "opacity-80" : "",
        )}
      >
        {/* Colour dot */}
        <span
          className="w-1.5 h-1.5 rounded-full flex-shrink-0 transition-all"
          style={{
            backgroundColor: hasAnyActive ? color : color + "80",
            boxShadow: hasAnyActive ? `0 0 6px ${color}80` : "none",
          }}
        />
        <span
          className="flex-1 truncate uppercase tracking-[0.12em] text-[10px]"
          style={hasAnyActive ? { color: color + "cc" } : {}}
        >
          {label}
        </span>
        <span className="text-[9px] text-muted-foreground/30 mr-0.5">{items.length}</span>
        {isExpanded
          ? <ChevronDown className="h-3 w-3 text-muted-foreground/40 flex-shrink-0" />
          : <ChevronRight className="h-3 w-3 text-muted-foreground/30 flex-shrink-0" />}
      </button>

      {/* Pages list */}
      {isExpanded && (
        <ul className="space-y-0.5 mb-1">
          {items.map(({ page, agentColor }) => {
            const Icon        = page.icon;
            const isActive    = activeHref === page.href;
            const isBroker    = page.href === "/broker-execution";
            const badgeCount  = isBroker ? reconciliationBadgeCount : 0;
            const isHovered   = hoveredHref === page.href;
            const starred     = isFav(page.href);

            return (
              <li key={page.href}>
                <div
                  className="relative flex items-center"
                  onMouseEnter={() => setHoveredHref(page.href)}
                  onMouseLeave={() => setHoveredHref(null)}
                >
                  <Link
                    href={page.href}
                    onClick={onNav}
                    data-testid={`link-nav-${page.label.toLowerCase().replace(/\s/g, "-")}`}
                    className={cn(
                      "group relative flex flex-1 min-w-0 items-center gap-2.5 rounded-xl px-3 py-1.5 text-[12.5px] font-medium transition-all duration-100",
                      isActive
                        ? "text-foreground"
                        : "text-muted-foreground/75 hover:text-foreground hover:bg-sidebar-accent/50",
                      // Pad right when hovered to make room for star
                      isHovered ? "pr-7" : "",
                    )}
                  >
                    {/* Active: left accent + tinted bg */}
                    {isActive && (
                      <>
                        <span
                          className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r-full"
                          style={{ backgroundColor: agentColor }}
                        />
                        <span
                          className="absolute inset-0 rounded-xl ring-1 ring-inset"
                          style={{
                            backgroundColor: agentColor + "14",
                            outlineColor:    agentColor + "30",
                          }}
                        />
                      </>
                    )}

                    <Icon
                      className={cn("relative h-[15px] w-[15px] shrink-0 transition-colors")}
                      style={isActive ? { color: agentColor } : {}}
                    />
                    <span className="relative flex-1 truncate">{page.label}</span>

                    {/* Reconciliation badge */}
                    {badgeCount > 0 && (
                      <span className="relative ml-auto shrink-0 inline-flex items-center justify-center h-4 min-w-[1rem] rounded-full bg-red-500 text-[10px] font-bold text-white leading-none px-1"
                        data-testid="badge-reconciliation-count">
                        {badgeCount > 99 ? "99+" : badgeCount}
                      </span>
                    )}
                  </Link>

                  {/* Star / favourite button (shown on hover) */}
                  {isHovered && (
                    <button
                      onClick={(e) => { e.preventDefault(); onToggleFav(page.href); }}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded transition-colors text-muted-foreground/40 hover:text-amber-400"
                      title={starred ? "Remove from starred" : "Star this page"}
                    >
                      {starred
                        ? <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                        : <Star className="w-3 h-3" />}
                    </button>
                  )}
                  {/* Persistent star indicator when starred and not hovered */}
                  {!isHovered && starred && (
                    <span className="absolute right-2.5 top-1/2 -translate-y-1/2 w-1 h-1 rounded-full bg-amber-400/60" />
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
