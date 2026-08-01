/**
 * WorkspaceSettingsPanel.tsx — Phase 9.4
 * Full workspace customization drawer.
 * Tabs: Profiles | Widgets | KPI Bar | Focus Mode | Notifications | Templates | Session
 * UI only — no business logic.
 */
import React, { useState } from "react";
import { cn } from "@/lib/utils";
import {
  X, Plus, Copy, Trash2, RotateCcw, Check, Palette,
  LayoutDashboard, Bell, Layers, User, Sparkles, BookOpen,
  Monitor, Save, Edit2,
} from "lucide-react";
import {
  getAllProfiles, createProfile, renameProfile, duplicateProfile, deleteProfile,
  applyTemplate, resetLayout, getKpiBar, saveKpiBar, getNotifPrefs, saveNotifPrefs,
  WORKSPACE_TEMPLATES, FOCUS_MODES, type FocusMode, type NotifPrefs,
} from "./WorkspaceManager";
import { WIDGET_REGISTRY, WIDGET_CATEGORIES, type WidgetCategory } from "./WidgetRegistry";
import { FocusModeBar } from "./FocusModeBar";

// ── Tab types ─────────────────────────────────────────────────────────────────

type Tab = "profiles" | "widgets" | "kpi" | "focus" | "notifications" | "templates" | "monitor";

const TABS: { id: Tab; label: string; icon: any }[] = [
  { id: "profiles",      label: "Profiles",      icon: User },
  { id: "widgets",       label: "Widgets",        icon: LayoutDashboard },
  { id: "kpi",           label: "KPI Bar",        icon: Sparkles },
  { id: "focus",         label: "Focus",          icon: Layers },
  { id: "notifications", label: "Alerts",         icon: Bell },
  { id: "templates",     label: "Templates",      icon: BookOpen },
  { id: "monitor",       label: "Multi-Monitor",  icon: Monitor },
];

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
  currentProfileId: string;
  onProfileChange: (id: string) => void;
  activeWidgetIds: string[];
  onAddWidget: (widgetId: string) => void;
  focusMode: FocusMode;
  onFocusModeChange: (mode: FocusMode) => void;
  onResetLayout: () => void;
  onUndo: () => void;
  canUndo: boolean;
}

export function WorkspaceSettingsPanel({
  open,
  onClose,
  currentProfileId,
  onProfileChange,
  activeWidgetIds,
  onAddWidget,
  focusMode,
  onFocusModeChange,
  onResetLayout,
  onUndo,
  canUndo,
}: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("profiles");

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed right-0 top-0 h-full z-50 w-[420px] max-w-full flex flex-col bg-background border-l border-border/60 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/40">
          <div>
            <h2 className="text-[14px] font-bold text-foreground">Workspace Settings</h2>
            <p className="text-[11px] text-muted-foreground/60">Personalise your trading environment</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground/60">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex overflow-x-auto scrollbar-hide px-3 pt-2 gap-0.5 border-b border-border/30">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-[11px] font-medium rounded-t-lg whitespace-nowrap transition-colors",
                activeTab === id
                  ? "bg-muted/60 text-foreground border-b-2 border-primary"
                  : "text-muted-foreground/60 hover:text-muted-foreground hover:bg-muted/30"
              )}
            >
              <Icon className="w-3 h-3" />
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {activeTab === "profiles" && (
            <ProfilesTab
              currentProfileId={currentProfileId}
              onProfileChange={onProfileChange}
              onResetLayout={onResetLayout}
              onUndo={onUndo}
              canUndo={canUndo}
            />
          )}
          {activeTab === "widgets" && (
            <WidgetsTab
              activeWidgetIds={activeWidgetIds}
              onAddWidget={onAddWidget}
            />
          )}
          {activeTab === "kpi" && <KpiBarTab />}
          {activeTab === "focus" && (
            <FocusTab
              focusMode={focusMode}
              onFocusModeChange={onFocusModeChange}
            />
          )}
          {activeTab === "notifications" && <NotificationsTab />}
          {activeTab === "templates" && (
            <TemplatesTab
              currentProfileId={currentProfileId}
              onClose={onClose}
            />
          )}
          {activeTab === "monitor" && <MultiMonitorTab />}
        </div>
      </div>
    </>
  );
}

// ── Tab: Profiles ─────────────────────────────────────────────────────────────

function ProfilesTab({
  currentProfileId, onProfileChange, onResetLayout, onUndo, canUndo
}: {
  currentProfileId: string;
  onProfileChange: (id: string) => void;
  onResetLayout: () => void;
  onUndo: () => void;
  canUndo: boolean;
}) {
  const [profiles, setProfiles] = useState(() => getAllProfiles());
  const [creating, setCreating] = useState(false);
  const [newLabel, setNewLabel]  = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState("");

  const reload = () => setProfiles(getAllProfiles());

  const handleCreate = () => {
    const label = newLabel.trim();
    if (!label) return;
    createProfile({ label, emoji: "⭐", color: "#6366F1", description: "Custom profile" });
    setNewLabel("");
    setCreating(false);
    reload();
  };

  const handleDelete = (id: string) => {
    if (!confirm(`Delete profile "${profiles.find(p => p.id === id)?.label}"?`)) return;
    deleteProfile(id);
    if (currentProfileId === id) onProfileChange("intraday");
    reload();
  };

  const handleDuplicate = (id: string) => {
    const src = profiles.find(p => p.id === id);
    if (!src) return;
    duplicateProfile(id, `${src.label} (copy)`);
    reload();
  };

  const handleRename = (id: string) => {
    if (editLabel.trim()) {
      renameProfile(id, editLabel.trim());
      reload();
    }
    setEditingId(null);
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-[12px] font-semibold text-foreground/80 mb-3">Workspace Profiles</h3>
        <div className="space-y-2">
          {profiles.map((p) => {
            const isActive = p.id === currentProfileId;
            return (
              <div
                key={p.id}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-xl border transition-all cursor-pointer",
                  isActive
                    ? "border-primary/40 bg-primary/5"
                    : "border-border/40 hover:bg-muted/30"
                )}
                onClick={() => onProfileChange(p.id)}
              >
                <span className="text-base shrink-0" style={{ color: p.color }}>{p.emoji}</span>
                <div className="flex-1 min-w-0">
                  {editingId === p.id && !p.isBuiltIn ? (
                    <input
                      autoFocus
                      value={editLabel}
                      onChange={(e) => setEditLabel(e.target.value)}
                      onBlur={() => handleRename(p.id)}
                      onKeyDown={(e) => e.key === "Enter" && handleRename(p.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="text-[12px] bg-muted/50 border border-border/60 rounded px-2 py-0.5 w-full focus:outline-none focus:ring-1 focus:ring-primary/40"
                    />
                  ) : (
                    <p className="text-[12px] font-semibold text-foreground/85 truncate">{p.label}</p>
                  )}
                  <p className="text-[10px] text-muted-foreground/50 truncate">{p.description}</p>
                </div>
                {isActive && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
                {!isActive && (
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
                    {!p.isBuiltIn && (
                      <>
                        <button
                          onClick={(e) => { e.stopPropagation(); setEditingId(p.id); setEditLabel(p.label); }}
                          className="p-1 rounded hover:bg-muted/60 text-muted-foreground/50"
                        >
                          <Edit2 className="w-3 h-3" />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(p.id); }}
                          className="p-1 rounded hover:bg-red-500/20 text-muted-foreground/50 hover:text-red-400"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </>
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDuplicate(p.id); }}
                      className="p-1 rounded hover:bg-muted/60 text-muted-foreground/50"
                    >
                      <Copy className="w-3 h-3" />
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Create new profile */}
      {creating ? (
        <div className="flex gap-2">
          <input
            autoFocus
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            placeholder="Profile name…"
            className="flex-1 text-[12px] bg-muted/40 border border-border/60 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-primary/40"
          />
          <button onClick={handleCreate} className="px-3 py-1.5 rounded-lg bg-primary/20 text-primary text-[11px] font-semibold hover:bg-primary/30 transition-colors">
            Create
          </button>
          <button onClick={() => setCreating(false)} className="px-2 py-1.5 rounded-lg bg-muted/40 text-muted-foreground/60 text-[11px] hover:bg-muted/60 transition-colors">
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-2 text-[12px] text-primary/70 hover:text-primary transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Create new profile
        </button>
      )}

      {/* Layout actions */}
      <div className="border-t border-border/30 pt-4 space-y-2">
        <h3 className="text-[11px] font-semibold text-muted-foreground/60 uppercase tracking-wide">Layout Actions</h3>
        <div className="flex gap-2">
          <button
            onClick={onUndo}
            disabled={!canUndo}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted/40 text-[11px] text-muted-foreground/70 hover:bg-muted/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <RotateCcw className="w-3 h-3" />
            Undo
          </button>
          <button
            onClick={() => { if (confirm("Reset layout to defaults?")) onResetLayout(); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted/40 text-[11px] text-muted-foreground/70 hover:bg-muted/60 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            Reset Layout
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Widgets ──────────────────────────────────────────────────────────────

function WidgetsTab({ activeWidgetIds, onAddWidget }: {
  activeWidgetIds: string[];
  onAddWidget: (id: string) => void;
}) {
  const [filterCategory, setFilterCategory] = useState<WidgetCategory | "all">("all");

  const filtered = WIDGET_REGISTRY.filter((w) =>
    filterCategory === "all" || w.category === filterCategory
  );

  return (
    <div className="space-y-3">
      <h3 className="text-[12px] font-semibold text-foreground/80">Add Widgets</h3>

      {/* Category filter */}
      <div className="flex flex-wrap gap-1.5">
        <CategoryChip id="all" label="All" emoji="🧩" active={filterCategory === "all"} onClick={() => setFilterCategory("all")} />
        {WIDGET_CATEGORIES.map((cat) => (
          <CategoryChip
            key={cat.id}
            id={cat.id}
            label={cat.label}
            emoji={cat.emoji}
            active={filterCategory === cat.id}
            onClick={() => setFilterCategory(cat.id as any)}
          />
        ))}
      </div>

      {/* Widget list */}
      <div className="space-y-1.5">
        {filtered.map((w) => {
          const alreadyAdded = activeWidgetIds.includes(w.id);
          const Icon = w.icon;
          return (
            <div key={w.id} className="flex items-center gap-3 px-3 py-2 rounded-xl border border-border/30 hover:bg-muted/20 transition-colors">
              <Icon className="w-4 h-4 text-muted-foreground/60 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-[12px] font-semibold text-foreground/80 truncate">{w.label}</p>
                <p className="text-[10px] text-muted-foreground/50 truncate">{w.description}</p>
              </div>
              <button
                onClick={() => onAddWidget(w.id)}
                disabled={alreadyAdded}
                className={cn(
                  "shrink-0 px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-colors",
                  alreadyAdded
                    ? "bg-muted/30 text-muted-foreground/30 cursor-default"
                    : "bg-primary/15 text-primary hover:bg-primary/25"
                )}
              >
                {alreadyAdded ? "Added" : "+ Add"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CategoryChip({ id, label, emoji, active, onClick }: {
  id: string; label: string; emoji: string; active: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-colors",
        active ? "bg-primary/20 text-primary" : "bg-muted/40 text-muted-foreground/60 hover:bg-muted/60"
      )}
    >
      <span>{emoji}</span>
      <span>{label}</span>
    </button>
  );
}

// ── Tab: KPI Bar ──────────────────────────────────────────────────────────────

function KpiBarTab() {
  return (
    <div className="space-y-3">
      <h3 className="text-[12px] font-semibold text-foreground/80">KPI Bar</h3>
      <p className="text-[11px] text-muted-foreground/60">
        Customise the KPI strip at the top of your workspace. Click the ⚙ icon on the KPI bar to add or remove metrics.
      </p>
      <p className="text-[11px] text-muted-foreground/50 bg-muted/30 rounded-lg px-3 py-2">
        You can pin 8–12 KPIs. The KPI bar updates every 30 seconds using existing API data — no additional server load.
      </p>
    </div>
  );
}

// ── Tab: Focus Mode ───────────────────────────────────────────────────────────

function FocusTab({ focusMode, onFocusModeChange }: {
  focusMode: FocusMode;
  onFocusModeChange: (m: FocusMode) => void;
}) {
  return (
    <div className="space-y-4">
      <h3 className="text-[12px] font-semibold text-foreground/80">Focus Mode</h3>
      <p className="text-[11px] text-muted-foreground/60">
        Each mode hides non-essential widgets so you can concentrate on what matters.
      </p>
      <div className="space-y-2">
        {FOCUS_MODES.map((mode) => (
          <button
            key={mode.id}
            onClick={() => onFocusModeChange(mode.id)}
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-left transition-all",
              focusMode === mode.id
                ? "border-primary/40 bg-primary/5"
                : "border-border/30 hover:bg-muted/30"
            )}
          >
            <span className="text-xl">{mode.emoji}</span>
            <div className="flex-1">
              <p className="text-[12px] font-semibold text-foreground/85">{mode.label}</p>
              <p className="text-[10px] text-muted-foreground/55">{mode.description}</p>
            </div>
            {focusMode === mode.id && <Check className="w-3.5 h-3.5 text-primary shrink-0" />}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Tab: Notifications ────────────────────────────────────────────────────────

function NotificationsTab() {
  const [prefs, setPrefs] = useState<NotifPrefs>(() => getNotifPrefs());

  const save = (updates: Partial<NotifPrefs>) => {
    const next = { ...prefs, ...updates };
    setPrefs(next);
    saveNotifPrefs(next);
  };

  const STYLES = ["popup", "banner", "sidebar", "silent"] as const;
  const KINDS = ["CRITICAL", "WARNING", "EXECUTION", "RISK", "SYSTEM", "SIGNAL", "PAPER", "LEARNING"];

  return (
    <div className="space-y-4">
      <h3 className="text-[12px] font-semibold text-foreground/80">Notification Preferences</h3>

      {/* Alert style */}
      <div>
        <p className="text-[11px] text-muted-foreground/70 mb-2 font-medium">Alert Display Style</p>
        <div className="grid grid-cols-2 gap-1.5">
          {STYLES.map((s) => (
            <button
              key={s}
              onClick={() => save({ style: s })}
              className={cn(
                "px-3 py-2 rounded-lg border text-[11px] font-medium capitalize transition-colors text-left",
                prefs.style === s
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border/30 text-muted-foreground/70 hover:bg-muted/30"
              )}
            >
              {s === "popup" ? "🔔 Popup" : s === "banner" ? "📢 Banner" : s === "sidebar" ? "📋 Sidebar" : "🔇 Silent"}
            </button>
          ))}
        </div>
      </div>

      {/* Enabled kinds */}
      <div>
        <p className="text-[11px] text-muted-foreground/70 mb-2 font-medium">Alert Types</p>
        <div className="space-y-1.5">
          {KINDS.map((kind) => {
            const enabled = prefs.enabledKinds.includes(kind);
            return (
              <button
                key={kind}
                onClick={() => {
                  const next = enabled
                    ? prefs.enabledKinds.filter((k) => k !== kind)
                    : [...prefs.enabledKinds, kind];
                  save({ enabledKinds: next });
                }}
                className={cn(
                  "w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-[11px] transition-colors",
                  enabled ? "bg-muted/40 text-foreground/80" : "bg-muted/20 text-muted-foreground/50"
                )}
              >
                <span>{kind}</span>
                <span className={cn(
                  "w-4 h-4 rounded border flex items-center justify-center",
                  enabled ? "bg-primary border-primary" : "border-border/50"
                )}>
                  {enabled && <Check className="w-2.5 h-2.5 text-white" />}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Tab: Templates ────────────────────────────────────────────────────────────

function TemplatesTab({ currentProfileId, onClose }: { currentProfileId: string; onClose: () => void }) {
  return (
    <div className="space-y-4">
      <h3 className="text-[12px] font-semibold text-foreground/80">Workspace Templates</h3>
      <p className="text-[11px] text-muted-foreground/60">
        Apply a template to instantly configure widgets and KPI bar for a role.
      </p>
      <div className="space-y-2">
        {WORKSPACE_TEMPLATES.map((tmpl) => (
          <div key={tmpl.id} className="px-3 py-3 rounded-xl border border-border/40 hover:bg-muted/20 transition-colors">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <span className="text-lg">{tmpl.emoji}</span>
                <p className="text-[12px] font-semibold text-foreground/85">{tmpl.label}</p>
              </div>
              <button
                onClick={() => {
                  if (confirm(`Apply "${tmpl.label}" template? This will replace your current widget layout.`)) {
                    applyTemplate(tmpl.id, currentProfileId);
                    onClose();
                  }
                }}
                className="px-2.5 py-1 rounded-lg bg-primary/15 text-primary text-[10px] font-semibold hover:bg-primary/25 transition-colors"
              >
                Apply
              </button>
            </div>
            <p className="text-[10px] text-muted-foreground/55">{tmpl.description}</p>
            <p className="text-[9px] text-muted-foreground/35 mt-1">
              {tmpl.widgetIds.length} widgets · {tmpl.kpis.length} KPIs
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Tab: Multi-Monitor ────────────────────────────────────────────────────────

function MultiMonitorTab() {
  const LAYOUTS = [
    { id: "command", label: "Monitor 1 — Command Centre",   emoji: "🖥", desc: "Home, alerts, overview, AI briefing" },
    { id: "scanner", label: "Monitor 2 — Live Scanner",     emoji: "📡", desc: "Market scanner, watchlist, signals, execution" },
    { id: "research",label: "Monitor 3 — Research",         emoji: "🔬", desc: "Research feed, analytics, AI performance" },
  ];

  return (
    <div className="space-y-4">
      <h3 className="text-[12px] font-semibold text-foreground/80">Multi-Monitor Layouts</h3>
      <p className="text-[11px] text-muted-foreground/60">
        Open the workspace in a new browser window and it will remember which monitor layout was last used.
      </p>
      <div className="space-y-2">
        {LAYOUTS.map((layout) => (
          <div key={layout.id} className="px-3 py-3 rounded-xl border border-border/40">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-lg">{layout.emoji}</span>
              <p className="text-[12px] font-semibold text-foreground/85">{layout.label}</p>
            </div>
            <p className="text-[10px] text-muted-foreground/55">{layout.desc}</p>
            <button
              onClick={() => {
                const base = window.location.origin + window.location.pathname.replace(/\/$/, "");
                const url = `${base}/workspace?monitor=${layout.id}`;
                window.open(url, `apexquant_${layout.id}`, "width=1920,height=1080");
              }}
              className="mt-2 flex items-center gap-1.5 text-[10px] text-primary/70 hover:text-primary transition-colors"
            >
              <Monitor className="w-3 h-3" />
              Open in new window
            </button>
          </div>
        ))}
      </div>
      <p className="text-[10px] text-muted-foreground/40 italic">
        Monitor layout preferences are saved per browser window.
      </p>
    </div>
  );
}
