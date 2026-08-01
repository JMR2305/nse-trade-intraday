/**
 * QuickSwitcher.tsx — Phase 9.2
 * Ctrl+K global search modal — navigate pages and agents instantly.
 *
 * Navigation/layout only — no business logic, no API calls.
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import { useLocation } from "wouter";
import { Search, Clock, Command } from "lucide-react";
import { AGENTS, ALL_PAGES, searchItems, type SearchItem, type Agent } from "./AgentConfig";

const STORAGE_KEY = "apexquant_recent_pages";
const MAX_RECENT  = 8;

function getRecent(): { href: string; label: string; agentColor: string }[] {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

function recordRecent(href: string, label: string, color: string) {
  try {
    const existing = getRecent().filter((r) => r.href !== href);
    const next = [{ href, label, agentColor: color }, ...existing].slice(0, MAX_RECENT);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {}
}

// ── Props ──────────────────────────────────────────────────────────────────────
interface QuickSwitcherProps {
  open:    boolean;
  onClose: () => void;
}

export function QuickSwitcher({ open, onClose }: QuickSwitcherProps) {
  const [, navigate] = useLocation();
  const [query,    setQuery]    = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef  = useRef<HTMLInputElement>(null);
  const listRef   = useRef<HTMLDivElement>(null);

  const recent  = getRecent();
  const results = query.trim() ? searchItems(query) : [];

  // Items to render (search results or recent pages when no query)
  const showRecent = !query.trim() && recent.length > 0;

  const totalItems = query.trim()
    ? results.length
    : recent.length + AGENTS.length;

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const goTo = useCallback(
    (href: string, label: string, color: string) => {
      recordRecent(href, label, color);
      navigate(href);
      onClose();
    },
    [navigate, onClose]
  );

  // Keyboard navigation
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelected((s) => Math.min(s + 1, totalItems - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelected((s) => Math.max(s - 1, 0));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        // Determine which item is selected
        if (query.trim()) {
          const item = results[selected];
          if (!item) return;
          if (item.kind === "agent") {
            const first = item.agent.pages[0];
            if (first) goTo(first.href, first.label, item.agent.color);
          } else {
            goTo(item.page.href, item.page.label, item.page.agentColor);
          }
        } else {
          // recent first, then agents
          if (selected < recent.length) {
            const r = recent[selected];
            goTo(r.href, r.label, r.agentColor);
          } else {
            const agent = AGENTS[selected - recent.length];
            if (agent && agent.pages[0]) goTo(agent.pages[0].href, agent.pages[0].label, agent.color);
          }
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, query, results, selected, recent, goTo, onClose, totalItems]);

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${selected}"]`) as HTMLElement | null;
    el?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  if (!open) return null;

  const Dot = ({ color }: { color: string }) => (
    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
  );

  const ItemRow = ({
    idx, icon: Icon, label, sub, color, href, agentLabel,
  }: {
    idx: number; icon: any; label: string; sub?: string;
    color: string; href: string; agentLabel?: string;
  }) => {
    const isActive = selected === idx;
    return (
      <button
        data-idx={idx}
        onClick={() => goTo(href, label, color)}
        onMouseEnter={() => setSelected(idx)}
        className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
          isActive ? "bg-white/8" : "hover:bg-white/5"
        }`}
      >
        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: color + "22", border: `1px solid ${color}44` }}>
          <Icon className="w-3.5 h-3.5" style={{ color }} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{label}</p>
          {sub && <p className="text-xs text-muted-foreground truncate">{sub}</p>}
        </div>
        {agentLabel && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0"
            style={{ color, borderColor: color + "55", backgroundColor: color + "15" }}>
            {agentLabel}
          </span>
        )}
        {isActive && (
          <kbd className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-muted-foreground flex-shrink-0">↵</kbd>
        )}
      </button>
    );
  };

  let globalIdx = 0;

  return (
    <div className="fixed inset-0 z-[200] flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-[560px] mx-4 bg-[#0f1117] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">

        {/* Search bar */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-white/8">
          <Search className="w-4 h-4 text-muted-foreground flex-shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSelected(0); }}
            placeholder="Search agents, pages, strategies…"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none"
          />
          <kbd className="hidden sm:flex items-center gap-1 text-[10px] text-muted-foreground/50">
            <span className="text-xs">esc</span>
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[400px] overflow-y-auto py-1">

          {/* Search results */}
          {query.trim() ? (
            results.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-muted-foreground">No results for "{query}"</p>
            ) : (
              <>
                {results.map((item, i) => {
                  const idx = globalIdx++;
                  if (item.kind === "agent") {
                    const firstPage = item.agent.pages[0];
                    return (
                      <ItemRow key={item.agent.id} idx={idx}
                        icon={firstPage?.icon ?? Command}
                        label={item.agent.name}
                        sub={item.agent.description}
                        color={item.agent.color}
                        href={firstPage?.href ?? "/"}
                        agentLabel="Agent" />
                    );
                  } else {
                    return (
                      <ItemRow key={item.page.href} idx={idx}
                        icon={item.page.icon}
                        label={item.page.label}
                        sub={item.page.agentName}
                        color={item.page.agentColor}
                        href={item.page.href}
                        agentLabel={item.page.agentName} />
                    );
                  }
                })}
              </>
            )
          ) : (
            <>
              {/* Recent pages */}
              {showRecent && (
                <div>
                  <p className="px-4 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">
                    Recent
                  </p>
                  {recent.map((r) => {
                    const page = ALL_PAGES.find((p) => p.href === r.href);
                    const idx  = globalIdx++;
                    return (
                      <ItemRow key={r.href} idx={idx}
                        icon={page?.icon ?? Clock}
                        label={r.label}
                        color={r.agentColor}
                        href={r.href} />
                    );
                  })}
                </div>
              )}

              {/* All agents */}
              <div>
                <p className="px-4 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">
                  Agents
                </p>
                {AGENTS.map((a) => {
                  const idx  = globalIdx++;
                  const first = a.pages[0];
                  return (
                    <ItemRow key={a.id} idx={idx}
                      icon={first?.icon ?? Command}
                      label={`${a.emoji} ${a.name}`}
                      sub={a.description}
                      color={a.color}
                      href={first?.href ?? "/"} />
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2 border-t border-white/8 text-[10px] text-muted-foreground/40">
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> open</span>
          <span><kbd className="font-mono">esc</kbd> close</span>
          <span className="ml-auto flex items-center gap-1">
            <Command className="w-2.5 h-2.5" />K to open anywhere
          </span>
        </div>
      </div>
    </div>
  );
}
