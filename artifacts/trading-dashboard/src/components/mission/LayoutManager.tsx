/**
 * LayoutManager.tsx — Phase 25.1 Part 11: dashboard customization.
 *
 * Lightweight localStorage-backed layout preference system for Mission Control.
 * NO drag-n-drop dependency: reordering is via up/down buttons, plus pin/hide.
 *
 * Storage: localStorage key "mc-layout-v1" → ordered list of section prefs:
 *   [{ id, hidden, pinned }]
 * Unknown/new section ids default to visible+unpinned and append at the end,
 * so adding a widget later never breaks a saved layout.
 *
 * <SectionShell> wraps each major dashboard region. In "customize" mode it
 * renders a small hover header (label + pin / hide / move-up / move-down).
 * Hidden sections collapse to a one-line restore chip. Pinned sections sort
 * first. Ordering is applied by the page (via useLayoutManager.order) before
 * render — this file only owns the persistence + per-section chrome.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ChevronUp, ChevronDown, Pin, PinOff, Eye, EyeOff, GripVertical, RotateCcw,
} from "lucide-react";

const STORAGE_KEY = "mc-layout-v1";

export interface SectionPref { id: string; hidden: boolean; pinned: boolean }

/** A section definition — stable id + human label. Order here = default order. */
export interface SectionDef { id: string; label: string }

// ── Persistence helpers ───────────────────────────────────────────────────────

function loadPrefs(): SectionPref[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((p) => p && typeof p.id === "string")
      .map((p) => ({ id: p.id, hidden: !!p.hidden, pinned: !!p.pinned }));
  } catch {
    return [];
  }
}

function savePrefs(prefs: SectionPref[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    /* storage unavailable — non-fatal, layout falls back to defaults */
  }
}

/**
 * Merge stored prefs with the canonical section defs:
 *  - keep stored order for known sections,
 *  - append any new sections (not in storage) in their default order,
 *  - drop stored ids that no longer exist.
 */
function reconcile(defs: SectionDef[], stored: SectionPref[]): SectionPref[] {
  const known = new Set(defs.map((d) => d.id));
  const byId = new Map(stored.map((p) => [p.id, p]));
  const out: SectionPref[] = [];
  // 1. stored order (only still-known ids)
  for (const p of stored) {
    if (known.has(p.id) && !out.find((x) => x.id === p.id)) out.push(p);
  }
  // 2. append new defs not present in storage
  for (const d of defs) {
    if (!byId.has(d.id)) out.push({ id: d.id, hidden: false, pinned: false });
  }
  return out;
}

// ── Hook ───────────────────────────────────────────────────────────────────────

export interface LayoutManager {
  /** Section ids in applied render order (pinned first, then stored order). */
  order: string[];
  prefs: Record<string, SectionPref>;
  customizing: boolean;
  setCustomizing: (v: boolean) => void;
  toggleCustomizing: () => void;
  isHidden: (id: string) => boolean;
  isPinned: (id: string) => boolean;
  togglePin: (id: string) => void;
  toggleHide: (id: string) => void;
  moveUp: (id: string) => void;
  moveDown: (id: string) => void;
  reset: () => void;
  /** All sections (id+label) in applied order — for the restore-chip strip. */
  sections: SectionDef[];
  hiddenSections: SectionDef[];
}

export function useLayoutManager(defs: SectionDef[]): LayoutManager {
  const defsKey = defs.map((d) => d.id).join("|");
  const [list, setList] = useState<SectionPref[]>(() => reconcile(defs, loadPrefs()));
  const [customizing, setCustomizing] = useState(false);

  // Re-reconcile if the section set changes (e.g. hot reload / new widget).
  useEffect(() => {
    setList((prev) => reconcile(defs, prev));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsKey]);

  useEffect(() => { savePrefs(list); }, [list]);

  const prefs = useMemo(() => {
    const m: Record<string, SectionPref> = {};
    for (const p of list) m[p.id] = p;
    return m;
  }, [list]);

  const labelById = useMemo(() => {
    const m = new Map<string, string>();
    for (const d of defs) m.set(d.id, d.label);
    return m;
  }, [defs]);

  // Applied order: stored order but pinned sections float to the top
  // (stable within pinned / unpinned groups).
  const order = useMemo(() => {
    const pinned = list.filter((p) => p.pinned).map((p) => p.id);
    const rest = list.filter((p) => !p.pinned).map((p) => p.id);
    return [...pinned, ...rest];
  }, [list]);

  const mutate = useCallback((fn: (prev: SectionPref[]) => SectionPref[]) => {
    setList((prev) => fn(prev));
  }, []);

  const togglePin = useCallback((id: string) => {
    mutate((prev) => prev.map((p) => (p.id === id ? { ...p, pinned: !p.pinned } : p)));
  }, [mutate]);

  const toggleHide = useCallback((id: string) => {
    mutate((prev) => prev.map((p) => (p.id === id ? { ...p, hidden: !p.hidden } : p)));
  }, [mutate]);

  const moveUp = useCallback((id: string) => {
    mutate((prev) => {
      const i = prev.findIndex((p) => p.id === id);
      if (i <= 0) return prev;
      const next = [...prev];
      [next[i - 1], next[i]] = [next[i], next[i - 1]];
      return next;
    });
  }, [mutate]);

  const moveDown = useCallback((id: string) => {
    mutate((prev) => {
      const i = prev.findIndex((p) => p.id === id);
      if (i < 0 || i >= prev.length - 1) return prev;
      const next = [...prev];
      [next[i + 1], next[i]] = [next[i], next[i + 1]];
      return next;
    });
  }, [mutate]);

  const reset = useCallback(() => {
    const fresh = defs.map((d) => ({ id: d.id, hidden: false, pinned: false }));
    setList(fresh);
  }, [defs]);

  const sections = useMemo(
    () => order.map((id) => ({ id, label: labelById.get(id) ?? id })),
    [order, labelById],
  );
  const hiddenSections = useMemo(
    () => sections.filter((s) => prefs[s.id]?.hidden),
    [sections, prefs],
  );

  return {
    order, prefs, customizing, setCustomizing,
    toggleCustomizing: () => setCustomizing((v) => !v),
    isHidden: (id) => !!prefs[id]?.hidden,
    isPinned: (id) => !!prefs[id]?.pinned,
    togglePin, toggleHide, moveUp, moveDown, reset,
    sections, hiddenSections,
  };
}

// ── SectionShell ─────────────────────────────────────────────────────────────

interface SectionShellProps {
  id: string;
  label: string;
  mgr: LayoutManager;
  children: ReactNode;
}

/**
 * Wraps a dashboard region. When not customizing, renders children plainly
 * (unless hidden). When customizing, shows a hover header with controls; hidden
 * sections collapse to a one-line restore chip.
 */
export function SectionShell({ id, label, mgr, children }: SectionShellProps) {
  const hidden = mgr.isHidden(id);
  const pinned = mgr.isPinned(id);

  // Not customizing + hidden → render nothing.
  if (hidden && !mgr.customizing) return null;

  // Hidden while customizing → one-line restore chip.
  if (hidden && mgr.customizing) {
    return (
      <div
        className="flex items-center gap-2 rounded-lg border border-dashed border-border/60 bg-muted/10 px-3 py-1.5 text-[10px] text-muted-foreground"
        data-testid={`mc-section-hidden-${id}`}
      >
        <EyeOff className="w-3 h-3" />
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground/60">hidden</span>
        <button
          onClick={() => mgr.toggleHide(id)}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-border/60 px-1.5 py-0.5 hover:bg-muted/30 text-teal-400"
          data-testid={`mc-section-restore-${id}`}
        >
          <Eye className="w-3 h-3" /> Restore
        </button>
      </div>
    );
  }

  // Visible.
  if (!mgr.customizing) {
    return <div data-testid={`mc-section-${id}`}>{children}</div>;
  }

  // Visible + customizing → controls header.
  return (
    <div
      className={`group relative rounded-xl border-2 border-dashed p-1 transition-colors ${
        pinned ? "border-teal-500/50 bg-teal-500/5" : "border-border/50"
      }`}
      data-testid={`mc-section-${id}`}
    >
      <div className="flex items-center gap-1.5 px-1 pb-1 text-[10px] text-muted-foreground">
        <GripVertical className="w-3 h-3 opacity-60" />
        <span className="font-medium uppercase tracking-wide">{label}</span>
        {pinned && (
          <span className="rounded-full border border-teal-500/40 text-teal-300 px-1.5 py-0 text-[8px]">PINNED</span>
        )}
        <span className="ml-auto flex items-center gap-1">
          <IconBtn title="Move up" onClick={() => mgr.moveUp(id)} testId={`mc-section-up-${id}`}>
            <ChevronUp className="w-3 h-3" />
          </IconBtn>
          <IconBtn title="Move down" onClick={() => mgr.moveDown(id)} testId={`mc-section-down-${id}`}>
            <ChevronDown className="w-3 h-3" />
          </IconBtn>
          <IconBtn
            title={pinned ? "Unpin" : "Pin to top"}
            onClick={() => mgr.togglePin(id)}
            testId={`mc-section-pin-${id}`}
            active={pinned}
          >
            {pinned ? <PinOff className="w-3 h-3" /> : <Pin className="w-3 h-3" />}
          </IconBtn>
          <IconBtn title="Hide" onClick={() => mgr.toggleHide(id)} testId={`mc-section-hide-${id}`}>
            <EyeOff className="w-3 h-3" />
          </IconBtn>
        </span>
      </div>
      {children}
    </div>
  );
}

function IconBtn({
  children, title, onClick, testId, active,
}: {
  children: ReactNode; title: string; onClick: () => void; testId?: string; active?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      data-testid={testId}
      className={`inline-flex items-center justify-center rounded-md border px-1 py-0.5 transition-colors ${
        active
          ? "border-teal-500/50 text-teal-300 bg-teal-500/10"
          : "border-border/60 text-muted-foreground hover:bg-muted/30 hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

// ── Customize toggle button + reset ──────────────────────────────────────────

export function CustomizeControls({ mgr }: { mgr: LayoutManager }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        type="button"
        onClick={mgr.toggleCustomizing}
        className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] transition-colors ${
          mgr.customizing
            ? "border-teal-500/50 text-teal-300 bg-teal-500/10"
            : "border-border text-muted-foreground hover:bg-muted/30"
        }`}
        data-testid="mc-customize-toggle"
      >
        <GripVertical className="w-3 h-3" />
        {mgr.customizing ? "Done" : "Customize"}
      </button>
      {mgr.customizing && (
        <button
          type="button"
          onClick={mgr.reset}
          className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-[10px] text-muted-foreground hover:bg-muted/30"
          data-testid="mc-customize-reset"
        >
          <RotateCcw className="w-3 h-3" /> Reset layout
        </button>
      )}
    </span>
  );
}
