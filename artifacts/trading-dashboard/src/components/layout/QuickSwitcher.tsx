/**
 * QuickSwitcher.tsx — Phase 9.3
 * Universal search command palette (Ctrl+K).
 *
 * Upgrades over Phase 9.2:
 *  — Grouped result categories: Pages · Agents · Stocks · Strategies · Alerts · Portfolio
 *  — Dynamic data: watchlist symbols, strategies, positions, alerts (lazy-cached)
 *  — Smart Recommendations (context-aware, advisory-only)
 *  — Recent Searches (tracked + clickable to re-run)
 *  — Workflow Shortcuts (Morning / Market Open / Closing)
 *  — Most Used pages (by visit count)
 *  — Workspace Profile quick-switch row
 *
 * Navigation/layout only. Advisory only. No business logic. No API changes.
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import { useLocation } from "wouter";
import {
  Search, Clock, Command, Zap, TrendingUp, Bell,
  Briefcase, BarChart3, BookOpenText, ChevronRight,
  Flame, Workflow, Lightbulb,
} from "lucide-react";
import {
  AGENTS, ALL_PAGES, searchItems, getAgentForPath,
  WORKFLOW_SHORTCUTS, type SearchItem, type Agent,
} from "./AgentConfig";
import {
  getRecentSearches, addRecentSearch, getMostUsed,
  PROFILES, getProfile, setProfile, type WorkspaceProfile,
} from "./WorkspaceStore";
import { apiJson } from "@/lib/api";

// ── Dynamic data cache (module-level, persists across opens) ─────────────────

interface DynamicData {
  stocks:     string[];
  strategies: string[];
  positions:  { symbol: string; qty: number; side: string }[];
  alerts:     { message: string; kind: string; level?: string }[];
  /** Phase 25C: paper trades / orders from the phase20 ledger */
  trades:     { id: string; symbol: string; side: string; status: string; qty: number }[];
  /** Phase 25C: replay sessions (scan snapshots) */
  replays:    { scanId: string; ts: string }[];
  /** Phase 25C: recent pipeline events */
  events:     { id: number; label: string; stage: string; symbol: string | null }[];
  /** Phase 25C: AI recommendations */
  recos:      { symbol: string; action: string }[];
  loaded:     boolean;
}

let _dyn: DynamicData = {
  stocks: [], strategies: [], positions: [], alerts: [],
  trades: [], replays: [], events: [], recos: [], loaded: false,
};
let _fetching = false;

async function warmCache(): Promise<DynamicData> {
  if (_dyn.loaded) return _dyn;
  if (_fetching) return _dyn;
  _fetching = true;

  const [watchRes, stratRes, posRes, alertRes, ledgerRes, replayRes, eventRes, recoRes] = await Promise.allSettled([
    apiJson("preopen/watchlist"),
    apiJson("strategy/rankings"),
    apiJson("phase20/positions"),
    apiJson("command-center/alerts"),
    apiJson("phase20/ledger?limit=100"),
    apiJson("replay/sessions"),
    apiJson("pipeline/events?limit=60&newest_first=true"),
    apiJson("phase11/recommendations", undefined, 30_000),
  ]);

  // Watchlist / stocks
  const stocks: string[] = [];
  if (watchRes.status === "fulfilled" && watchRes.value) {
    const v = watchRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.symbols ?? v?.watchlist ?? v?.data ?? []);
    raw.forEach((s: any) => {
      if (typeof s === "string") stocks.push(s);
      else if (s?.symbol) stocks.push(s.symbol);
      else if (s?.ticker) stocks.push(s.ticker);
    });
  }

  // Strategies
  const strategies: string[] = [];
  if (stratRes.status === "fulfilled" && stratRes.value) {
    const v = stratRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.rankings ?? v?.strategies ?? v?.data ?? []);
    raw.forEach((s: any) => {
      const name = typeof s === "string" ? s : (s?.strategy ?? s?.name ?? "");
      if (name) strategies.push(name);
    });
  }

  // Positions
  const positions: DynamicData["positions"] = [];
  if (posRes.status === "fulfilled" && posRes.value) {
    const v = posRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.positions ?? v?.data ?? []);
    raw.forEach((p: any) => {
      if (p?.symbol) positions.push({ symbol: p.symbol, qty: p.qty ?? p.quantity ?? 0, side: p.side ?? "BUY" });
    });
  }

  // Alerts
  const alerts: DynamicData["alerts"] = [];
  if (alertRes.status === "fulfilled" && alertRes.value) {
    const v = alertRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.alerts ?? v?.data ?? []);
    raw.forEach((a: any) => {
      if (a?.message) alerts.push({ message: a.message, kind: a.kind ?? "info", level: a.level ?? a.severity });
    });
  }

  // Trades / orders (phase20 ledger)
  const trades: DynamicData["trades"] = [];
  if (ledgerRes.status === "fulfilled" && ledgerRes.value) {
    const v = ledgerRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.ledger ?? v?.trades ?? v?.data ?? []);
    raw.forEach((t: any) => {
      if (t?.symbol) trades.push({
        id: String(t.trade_id ?? t.id ?? `${t.symbol}-${t.created_at ?? ""}`),
        symbol: t.symbol, side: t.side ?? "BUY",
        status: t.status ?? "UNKNOWN", qty: t.quantity ?? t.qty ?? 0,
      });
    });
  }

  // Replay sessions
  const replays: DynamicData["replays"] = [];
  if (replayRes.status === "fulfilled" && replayRes.value) {
    const v = replayRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.sessions ?? v?.data ?? []);
    raw.forEach((s: any) => {
      const scanId = s?.scan_id ?? s?.scanId ?? (typeof s === "string" ? s : null);
      if (scanId) replays.push({ scanId: String(scanId), ts: String(s?.snapshot_ts ?? s?.ts ?? "") });
    });
  }

  // Pipeline events
  const events: DynamicData["events"] = [];
  if (eventRes.status === "fulfilled" && eventRes.value) {
    const v = eventRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.events ?? v?.data ?? []);
    raw.forEach((e: any) => {
      if (e?.event_type) events.push({
        id: e.id ?? 0, label: String(e.event_type),
        stage: String(e.stage ?? ""), symbol: e.symbol ?? null,
      });
    });
  }

  // AI recommendations
  const recos: DynamicData["recos"] = [];
  if (recoRes.status === "fulfilled" && recoRes.value) {
    const v = recoRes.value as any;
    const raw: any[] = Array.isArray(v) ? v : (v?.recommendations ?? v?.queue ?? v?.data ?? []);
    raw.forEach((r: any) => {
      const symbol = r?.symbol ?? r?.ticker;
      if (symbol) recos.push({ symbol: String(symbol), action: String(r?.action ?? r?.side ?? r?.recommendation ?? "") });
    });
  }

  _dyn = { stocks, strategies, positions, alerts, trades, replays, events, recos, loaded: true };
  _fetching = false;
  return _dyn;
}

// ── Smart recommendations (advisory-only, context-aware) ────────────────────

interface Rec {
  icon:    string;
  message: string;
  href:    string;
  badge?:  string;
}

function buildRecommendations(currentPath: string, dyn: DynamicData): Rec[] {
  const recs: Rec[] = [];
  const agent = getAgentForPath(currentPath);

  // Agent-specific context suggestions
  if (agent?.id === "risk") {
    recs.push({ icon: "⚠", message: "Stress tests validate exposure — run Risk Validation", href: "/risk-validation", badge: "advisory" });
    recs.push({ icon: "📊", message: "Correlation check available in Portfolio Risk", href: "/portfolio-risk" });
  } else if (agent?.id === "strategy") {
    recs.push({ icon: "📈", message: "Verify regime before switching strategies", href: "/market-intelligence", badge: "advisory" });
    recs.push({ icon: "🎯", message: "Strategy Optimisation has parameter suggestions", href: "/strategy-optimisation" });
  } else if (agent?.id === "market-data") {
    recs.push({ icon: "🌅", message: "Pre-Open Intelligence ready for today's session", href: "/preopen-intelligence" });
    recs.push({ icon: "📡", message: "Live Data Health shows feed status", href: "/live-data-health" });
  } else if (agent?.id === "ai-decision") {
    recs.push({ icon: "🤖", message: "Check AI confidence trends in AI Performance", href: "/ai-performance" });
    recs.push({ icon: "💡", message: "Explainable AI shows latest decision rationale", href: "/explainable-ai" });
  } else if (agent?.id === "execution") {
    recs.push({ icon: "💼", message: "Broker & Execution for reconciliation status", href: "/broker-execution" });
    recs.push({ icon: "📋", message: "Paper Analytics tracks paper-trade performance", href: "/paper-analytics" });
  } else {
    recs.push({ icon: "🏠", message: "Command Centre has the real-time platform snapshot", href: "/command-center" });
    recs.push({ icon: "📈", message: "Market Intelligence Hub for regime & sector view", href: "/market-intelligence" });
  }

  // Dynamic alert count (if data loaded)
  if (dyn.loaded && dyn.alerts.length > 0) {
    const critical = dyn.alerts.filter((a) => a.level === "critical" || a.level === "error").length;
    if (critical > 0) {
      recs.unshift({ icon: "🔔", message: `${critical} critical alert${critical > 1 ? "s" : ""} require attention`, href: "/notifications", badge: "critical" });
    } else {
      recs.push({ icon: "🔔", message: `${dyn.alerts.length} system notification${dyn.alerts.length > 1 ? "s" : ""} available`, href: "/notifications" });
    }
  }

  // Open positions hint
  if (dyn.loaded && dyn.positions.length > 0) {
    recs.push({ icon: "💼", message: `${dyn.positions.length} open position${dyn.positions.length > 1 ? "s" : ""} in portfolio`, href: "/portfolio-live" });
  }

  return recs.slice(0, 3);
}

// ── Categorised search results ───────────────────────────────────────────────

interface CatResults {
  pages:      SearchItem[];
  agents:     SearchItem[];
  stocks:     string[];
  strategies: string[];
  alerts:     { message: string; kind: string }[];
  positions:  { symbol: string; qty: number; side: string }[];
  trades:     DynamicData["trades"];
  replays:    DynamicData["replays"];
  events:     DynamicData["events"];
  recos:      DynamicData["recos"];
}

function categorise(query: string, dyn: DynamicData): CatResults {
  const all = searchItems(query);
  const q   = query.toLowerCase().trim();
  return {
    pages:      all.filter((r) => r.kind === "page").slice(0, 8),
    agents:     all.filter((r) => r.kind === "agent").slice(0, 4),
    stocks:     dyn.stocks.filter((s) => s.toLowerCase().includes(q)).slice(0, 6),
    strategies: dyn.strategies.filter((s) => s.toLowerCase().includes(q)).slice(0, 4),
    alerts:     dyn.alerts.filter((a) => a.message.toLowerCase().includes(q)).slice(0, 3),
    positions:  dyn.positions.filter((p) => p.symbol.toLowerCase().includes(q)).slice(0, 3),
    trades:     dyn.trades.filter((t) =>
                  t.symbol.toLowerCase().includes(q) || t.status.toLowerCase().includes(q) || t.side.toLowerCase() === q,
                ).slice(0, 4),
    replays:    dyn.replays.filter((r) =>
                  r.scanId.toLowerCase().includes(q) || r.ts.toLowerCase().includes(q) || "replay".includes(q),
                ).slice(0, 3),
    events:     dyn.events.filter((e) =>
                  e.label.toLowerCase().includes(q) || e.stage.toLowerCase().includes(q) ||
                  (e.symbol ?? "").toLowerCase().includes(q),
                ).slice(0, 4),
    recos:      dyn.recos.filter((r) =>
                  r.symbol.toLowerCase().includes(q) || r.action.toLowerCase().includes(q),
                ).slice(0, 3),
  };
}

// ── Component ────────────────────────────────────────────────────────────────

interface QuickSwitcherProps {
  open:        boolean;
  onClose:     () => void;
  currentPath: string;
}

const RECENT_KEY = "apexquant_recent_pages";
const MAX_RECENT = 8;

function getRecentPages(): { href: string; label: string; agentColor: string }[] {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); }
  catch { return []; }
}
function recordRecentPage(href: string, label: string, color: string) {
  try {
    const existing = getRecentPages().filter((r) => r.href !== href);
    localStorage.setItem(RECENT_KEY, JSON.stringify([{ href, label, agentColor: color }, ...existing].slice(0, MAX_RECENT)));
  } catch {}
}

export function QuickSwitcher({ open, onClose, currentPath }: QuickSwitcherProps) {
  const [, navigate]   = useLocation();
  const [query, setQuery]         = useState("");
  const [selected, setSelected]   = useState(0);
  const [dynData, setDynData]     = useState<DynamicData>(_dyn);
  const [activeProfile, setActiveProfile] = useState<WorkspaceProfile>(getProfile);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef  = useRef<HTMLDivElement>(null);

  // Warm cache on open
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelected(0);
    setActiveProfile(getProfile());
    setTimeout(() => inputRef.current?.focus(), 50);
    if (!_dyn.loaded) {
      warmCache().then((d) => setDynData({ ...d }));
    }
  }, [open]);

  const recentPages   = getRecentPages();
  const recentSearches = getRecentSearches();
  const mostUsedHrefs  = getMostUsed(4);
  const recs           = buildRecommendations(currentPath, dynData);
  const catResults     = query.trim() ? categorise(query, dynData) : null;

  const goTo = useCallback(
    (href: string, label: string, color: string) => {
      recordRecentPage(href, label, color);
      navigate(href);
      onClose();
    },
    [navigate, onClose],
  );

  const runQuery = useCallback(
    (q: string) => {
      if (q.trim().length >= 2) addRecentSearch(q.trim());
    },
    [],
  );

  // Build flat navigable items list for keyboard nav
  type NavItem = { href: string; label: string; color: string };
  const navItems: NavItem[] = [];

  if (catResults) {
    catResults.pages.forEach((r) => {
      if (r.kind === "page") navItems.push({ href: r.page.href, label: r.page.label, color: r.page.agentColor });
    });
    catResults.agents.forEach((r) => {
      if (r.kind === "agent") {
        const first = r.agent.pages[0];
        if (first) navItems.push({ href: first.href, label: r.agent.name, color: r.agent.color });
      }
    });
    catResults.stocks.forEach((s) =>
      navItems.push({ href: "/watchlist", label: s, color: "#3B82F6" }),
    );
    catResults.strategies.forEach((s) =>
      navItems.push({ href: "/strategy-intelligence", label: s, color: "#EF4444" }),
    );
    catResults.alerts.forEach((a) =>
      navItems.push({ href: "/notifications", label: a.message, color: "#F59E0B" }),
    );
    catResults.positions.forEach((p) =>
      navItems.push({ href: "/portfolio-live", label: p.symbol, color: "#14B8A6" }),
    );
    catResults.trades.forEach((t) =>
      navItems.push({ href: "/trades", label: `${t.side} ${t.symbol}`, color: "#14B8A6" }),
    );
    catResults.recos.forEach((r) =>
      navItems.push({ href: "/paper-trading-recommendations", label: r.symbol, color: "#6366F1" }),
    );
    catResults.replays.forEach((r) =>
      navItems.push({ href: "/replay", label: r.scanId, color: "#8B5CF6" }),
    );
    catResults.events.forEach((e) =>
      navItems.push({ href: "/mission-control", label: e.label, color: "#06B6D4" }),
    );
  } else {
    recs.forEach((r) => navItems.push({ href: r.href, label: r.message, color: "#6366F1" }));
    recentPages.forEach((r) => navItems.push({ href: r.href, label: r.label, color: r.agentColor }));
    recentSearches.forEach((s) => navItems.push({ href: "#search:" + s, label: s, color: "#6B7280" }));
    WORKFLOW_SHORTCUTS.forEach((w) => {
      if (w.pages[0]) navItems.push({ href: w.pages[0].href, label: w.label, color: "#8B5CF6" });
    });
    mostUsedHrefs.forEach((href) => {
      const page = ALL_PAGES.find((p) => p.href === href);
      if (page) navItems.push({ href: page.href, label: page.label, color: page.agentColor });
    });
    AGENTS.forEach((a) => {
      if (a.pages[0]) navItems.push({ href: a.pages[0].href, label: a.name, color: a.color });
    });
  }

  const totalItems = navItems.length;

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setSelected((s) => Math.min(s + 1, totalItems - 1)); }
      if (e.key === "ArrowUp")   { e.preventDefault(); setSelected((s) => Math.max(s - 1, 0)); }
      if (e.key === "Enter") {
        e.preventDefault();
        const item = navItems[selected];
        if (!item) return;
        if (item.href.startsWith("#search:")) {
          const q = item.href.slice(8);
          setQuery(q);
          setSelected(0);
        } else {
          if (query.trim()) runQuery(query);
          goTo(item.href, item.label, item.color);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, query, selected, navItems, totalItems, goTo, onClose, runQuery]);

  // Scroll selected into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${selected}"]`) as HTMLElement | null;
    el?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  if (!open) return null;

  // ── Helpers ────────────────────────────────────────────────────────────────

  const Dot = ({ color }: { color: string }) => (
    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
  );

  const SectionHeader = ({ label, icon: Icon }: { label: string; icon?: any }) => (
    <div className="flex items-center gap-1.5 px-4 pt-3 pb-1">
      {Icon && <Icon className="w-3 h-3 text-muted-foreground/40" />}
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/40">{label}</p>
    </div>
  );

  let globalIdx = 0;

  const Row = ({
    icon: Icon, label, sub, color, href, badge, agentLabel,
  }: {
    icon: any; label: string; sub?: string;
    color: string; href: string; badge?: string; agentLabel?: string;
  }) => {
    const idx = globalIdx++;
    const isActive = selected === idx;
    const handleClick = () => {
      if (href.startsWith("#search:")) {
        setQuery(href.slice(8)); setSelected(0); return;
      }
      if (query.trim()) runQuery(query);
      goTo(href, label, color);
    };
    return (
      <button
        data-idx={idx}
        onClick={handleClick}
        onMouseEnter={() => setSelected(idx)}
        className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
          isActive ? "bg-white/8" : "hover:bg-white/5"
        }`}
      >
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-[13px]"
          style={{ backgroundColor: color + "22", border: `1px solid ${color}44` }}
        >
          {typeof Icon === "string"
            ? Icon
            : <Icon className="w-3.5 h-3.5" style={{ color }} />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{label}</p>
          {sub && <p className="text-xs text-muted-foreground truncate">{sub}</p>}
        </div>
        {badge && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0"
            style={{
              color: badge === "critical" ? "#EF4444" : badge === "advisory" ? "#F59E0B" : color,
              borderColor: (badge === "critical" ? "#EF4444" : badge === "advisory" ? "#F59E0B" : color) + "55",
              backgroundColor: (badge === "critical" ? "#EF4444" : badge === "advisory" ? "#F59E0B" : color) + "15",
            }}
          >
            {badge}
          </span>
        )}
        {agentLabel && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0"
            style={{ color, borderColor: color + "55", backgroundColor: color + "15" }}
          >
            {agentLabel}
          </span>
        )}
        {isActive && (
          <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-muted-foreground flex-shrink-0">↵</kbd>
        )}
      </button>
    );
  };

  // ── Profile chips ──────────────────────────────────────────────────────────
  const ProfileChips = () => (
    <div className="flex items-center gap-1 px-4 py-2 border-b border-white/8 overflow-x-auto">
      <span className="text-[10px] text-muted-foreground/40 mr-1 shrink-0">Profile:</span>
      {PROFILES.map((p) => {
        const active = activeProfile === p.id;
        return (
          <button
            key={p.id}
            onClick={() => {
              setProfile(p.id);
              setActiveProfile(p.id);
            }}
            title={p.description}
            className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium transition-all shrink-0 ${
              active ? "ring-1 ring-inset" : "opacity-50 hover:opacity-80"
            }`}
            style={active ? { backgroundColor: p.color + "20", color: p.color } : {}}
          >
            {p.emoji} {p.label}
          </button>
        );
      })}
    </div>
  );

  // ── Search results ─────────────────────────────────────────────────────────
  const renderSearchResults = () => {
    if (!catResults) return null;
    const totalCount =
      catResults.pages.length + catResults.agents.length +
      catResults.stocks.length + catResults.strategies.length +
      catResults.alerts.length + catResults.positions.length +
      catResults.trades.length + catResults.replays.length +
      catResults.events.length + catResults.recos.length;

    if (totalCount === 0) {
      return (
        <p className="px-4 py-6 text-center text-sm text-muted-foreground">
          No results for &ldquo;{query}&rdquo;
        </p>
      );
    }

    return (
      <>
        {catResults.pages.length > 0 && (
          <>
            <SectionHeader label="Pages" icon={BookOpenText} />
            {catResults.pages.map((r) => {
              if (r.kind !== "page") return null;
              return (
                <Row key={r.page.href} icon={r.page.icon} label={r.page.label}
                  sub={r.page.agentName} color={r.page.agentColor} href={r.page.href}
                  agentLabel={r.page.agentName} />
              );
            })}
          </>
        )}
        {catResults.agents.length > 0 && (
          <>
            <SectionHeader label="Agents" icon={Zap} />
            {catResults.agents.map((r) => {
              if (r.kind !== "agent") return null;
              const first = r.agent.pages[0];
              return (
                <Row key={r.agent.id} icon={r.agent.emoji} label={r.agent.name}
                  sub={r.agent.description} color={r.agent.color}
                  href={first?.href ?? "/"} agentLabel="Agent" />
              );
            })}
          </>
        )}
        {catResults.stocks.length > 0 && (
          <>
            <SectionHeader label="Stocks" icon={TrendingUp} />
            {catResults.stocks.map((s) => (
              <Row key={s} icon={TrendingUp} label={s} sub="Open in Watchlist"
                color="#3B82F6" href="/watchlist" />
            ))}
          </>
        )}
        {catResults.strategies.length > 0 && (
          <>
            <SectionHeader label="Strategies" icon={BarChart3} />
            {catResults.strategies.map((s) => (
              <Row key={s} icon={BarChart3} label={s} sub="Strategy Intelligence"
                color="#EF4444" href="/strategy-intelligence" />
            ))}
          </>
        )}
        {catResults.positions.length > 0 && (
          <>
            <SectionHeader label="Portfolio" icon={Briefcase} />
            {catResults.positions.map((p) => (
              <Row key={p.symbol} icon={Briefcase} label={p.symbol}
                sub={`${p.side} · ${p.qty} shares`}
                color="#14B8A6" href="/portfolio-live" />
            ))}
          </>
        )}
        {catResults.trades.length > 0 && (
          <>
            <SectionHeader label="Trades & Orders" icon={Briefcase} />
            {catResults.trades.map((t) => (
              <Row key={t.id} icon={Briefcase} label={`${t.side} ${t.symbol}`}
                sub={`${t.qty} · ${t.status} — open in All Trades`}
                color="#14B8A6" href="/trades" />
            ))}
          </>
        )}
        {catResults.recos.length > 0 && (
          <>
            <SectionHeader label="Recommendations" icon={Lightbulb} />
            {catResults.recos.map((r, i) => (
              <Row key={`${r.symbol}-${i}`} icon={Lightbulb} label={r.symbol}
                sub={`${r.action || "recommendation"} — open queue`}
                color="#6366F1" href="/paper-trading-recommendations" />
            ))}
          </>
        )}
        {catResults.replays.length > 0 && (
          <>
            <SectionHeader label="Replay Sessions" icon={Clock} />
            {catResults.replays.map((r) => (
              <Row key={r.scanId} icon={Clock} label={r.scanId}
                sub={r.ts ? `Snapshot ${r.ts} — open Replay Mode` : "Open Replay Mode"}
                color="#8B5CF6" href="/replay" />
            ))}
          </>
        )}
        {catResults.events.length > 0 && (
          <>
            <SectionHeader label="Pipeline Events" icon={Zap} />
            {catResults.events.map((e) => (
              <Row key={e.id} icon={Zap} label={e.label}
                sub={`${e.stage}${e.symbol ? ` · ${e.symbol}` : ""} — Mission Control feed`}
                color="#06B6D4" href="/mission-control" />
            ))}
          </>
        )}
        {catResults.alerts.length > 0 && (
          <>
            <SectionHeader label="Alerts" icon={Bell} />
            {catResults.alerts.map((a, i) => (
              <Row key={i} icon={Bell} label={a.message} sub={a.kind}
                color="#F59E0B" href="/notifications" />
            ))}
          </>
        )}
      </>
    );
  };

  // ── Empty state ────────────────────────────────────────────────────────────
  const renderEmptyState = () => (
    <>
      {/* Recommendations */}
      {recs.length > 0 && (
        <>
          <SectionHeader label="Recommendations" icon={Lightbulb} />
          {recs.map((r, i) => (
            <Row key={i} icon={r.icon} label={r.message}
              color="#6366F1" href={r.href} badge={r.badge} />
          ))}
        </>
      )}

      {/* Recent */}
      {(recentPages.length > 0 || recentSearches.length > 0) && (
        <>
          <SectionHeader label="Recent" icon={Clock} />
          {recentPages.slice(0, 4).map((r) => {
            const page = ALL_PAGES.find((p) => p.href === r.href);
            return (
              <Row key={r.href} icon={page?.icon ?? Clock} label={r.label}
                color={r.agentColor} href={r.href} />
            );
          })}
          {recentSearches.slice(0, 3).map((s) => (
            <Row key={s} icon={Search} label={s} sub="Recent search"
              color="#6B7280" href={`#search:${s}`} />
          ))}
        </>
      )}

      {/* Workflows */}
      <SectionHeader label="Workflows" icon={Workflow} />
      {WORKFLOW_SHORTCUTS.map((w) => {
        const first = w.pages[0];
        if (!first) return null;
        return (
          <Row key={w.id} icon={w.emoji} label={w.label}
            sub={w.description} color="#8B5CF6" href={first.href} />
        );
      })}

      {/* Most Used */}
      {mostUsedHrefs.length > 0 && (
        <>
          <SectionHeader label="Most Used" icon={Flame} />
          {mostUsedHrefs.map((href) => {
            const page = ALL_PAGES.find((p) => p.href === href);
            if (!page) return null;
            return (
              <Row key={href} icon={page.icon} label={page.label}
                sub={page.agentName} color={page.agentColor} href={href} />
            );
          })}
        </>
      )}

      {/* Agents */}
      <SectionHeader label="Agents" icon={Zap} />
      {AGENTS.map((a) => {
        const first = a.pages[0];
        if (!first) return null;
        return (
          <Row key={a.id} icon={a.emoji} label={`${a.name}`}
            sub={a.description} color={a.color} href={first.href} />
        );
      })}
    </>
  );

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="fixed inset-0 z-[200] flex items-start justify-center pt-[12vh]">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-full max-w-[580px] mx-4 bg-[#0f1117] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">

        {/* Search bar */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-white/8">
          <Search className="w-4 h-4 text-muted-foreground flex-shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSelected(0); }}
            onKeyDown={(e) => { if (e.key === "Enter" && query.trim()) runQuery(query); }}
            placeholder="Search pages, stocks, strategies, alerts…"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
          />
          {query && (
            <button onClick={() => { setQuery(""); setSelected(0); }}
              className="text-[10px] text-muted-foreground/40 hover:text-muted-foreground px-1.5 py-0.5 rounded border border-white/10">
              clear
            </button>
          )}
          <kbd className="hidden sm:flex items-center gap-1 text-[10px] text-muted-foreground/50">
            <span className="text-xs">esc</span>
          </kbd>
        </div>

        {/* Profile chips */}
        <ProfileChips />

        {/* Results */}
        <div ref={listRef} className="max-h-[420px] overflow-y-auto py-1">
          {query.trim() ? renderSearchResults() : renderEmptyState()}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2 border-t border-white/8 text-[10px] text-muted-foreground/40">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> open</span>
          <span><kbd className="font-mono">esc</kbd> close</span>
          <span className="ml-auto flex items-center gap-1.5">
            {!dynData.loaded && (
              <span className="text-muted-foreground/30 italic">loading live data…</span>
            )}
            {dynData.loaded && (
              <span className="text-muted-foreground/20">
                {dynData.stocks.length} stocks · {dynData.strategies.length} strategies · {dynData.positions.length} positions
              </span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
