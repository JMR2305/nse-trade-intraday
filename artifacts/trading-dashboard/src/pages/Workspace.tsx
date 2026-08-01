/**
 * Workspace.tsx — Phase 9.4
 * Personalized Workspace: drag-and-drop widget grid, KPI bar,
 * focus mode, profile management, session memory, smart dashboard.
 *
 * UI/UX only — no business logic, no API changes, no calculations.
 */
import React, { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  Settings2, RotateCcw, Undo2, LayoutDashboard, Zap,
  SunMedium, Plus, ChevronDown,
} from "lucide-react";
import { DashboardGrid }          from "@/components/workspace/DashboardGrid";
import { KpiBar }                 from "@/components/workspace/KpiBar";
import { FocusModeBar, FocusModeBanner } from "@/components/workspace/FocusModeBar";
import { WorkspaceSettingsPanel } from "@/components/workspace/WorkspaceSettingsPanel";
import {
  getLayout, saveLayout, resetLayout, popUndo, canUndo,
  getKpiBar, saveKpiBar, getFocusMode, setFocusMode,
  getSession, saveSession, getAllProfiles,
  addWidget, removeWidget, updateWidget, reorderWidgets,
  type WorkspaceLayout, type WidgetInstance, type FocusMode,
} from "@/components/workspace/WorkspaceManager";
import { getProfile, setProfile } from "@/components/layout/WorkspaceStore";
import { getMarketSession }  from "@/components/workspace/SmartDashboard";
import type { KpiBarConfig } from "@/components/workspace/WorkspaceManager";

// ── Custom hook: all workspace state ─────────────────────────────────────────

function useWorkspace() {
  const [profileId, setProfileIdState]  = useState<string>(() => getProfile());
  const [layout,    setLayoutState]     = useState<WorkspaceLayout>(() => getLayout(getProfile()));
  const [kpiConfig, setKpiConfigState]  = useState<KpiBarConfig>(() => getKpiBar());
  const [focusMode, setFocusModeState]  = useState<FocusMode>(() => getFocusMode());
  const [undoPossible, setUndoPossible] = useState<boolean>(() => canUndo(getProfile()));

  const persistLayout = useCallback((l: WorkspaceLayout) => {
    setLayoutState(l);
    saveLayout(l);
    setUndoPossible(canUndo(l.profileId));
  }, []);

  const switchProfile = useCallback((id: string) => {
    setProfile(id as any);
    setProfileIdState(id);
    const l = getLayout(id);
    setLayoutState(l);
    setUndoPossible(canUndo(id));
    saveSession({ lastProfile: id, lastActiveWorkspace: id });
  }, []);

  const handleReorder = useCallback((from: number, to: number) => {
    persistLayout(reorderWidgets(layout, from, to));
  }, [layout, persistLayout]);

  const handleUpdate = useCallback((instanceId: string, updates: Partial<WidgetInstance>) => {
    persistLayout(updateWidget(layout, instanceId, updates));
  }, [layout, persistLayout]);

  const handleRemove = useCallback((instanceId: string) => {
    persistLayout(removeWidget(layout, instanceId));
  }, [layout, persistLayout]);

  const handleAdd = useCallback((widgetId: string) => {
    persistLayout(addWidget(layout, widgetId));
  }, [layout, persistLayout]);

  const handleReset = useCallback(() => {
    const fresh = resetLayout(profileId);
    setLayoutState(fresh);
    setUndoPossible(false);
  }, [profileId]);

  const handleUndo = useCallback(() => {
    const prev = popUndo(profileId);
    if (prev) {
      setLayoutState(prev);
      setUndoPossible(canUndo(profileId));
    }
  }, [profileId]);

  const handleFocusMode = useCallback((mode: FocusMode) => {
    setFocusModeState(mode);
    setFocusMode(mode);
  }, []);

  const handleKpiSave = useCallback((config: KpiBarConfig) => {
    setKpiConfigState(config);
    saveKpiBar(config);
  }, []);

  return {
    profileId, switchProfile,
    layout, handleReorder, handleUpdate, handleRemove, handleAdd,
    kpiConfig, handleKpiSave,
    focusMode, handleFocusMode,
    handleReset, handleUndo, undoPossible,
  };
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Workspace() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const session = getMarketSession();
  const profiles = getAllProfiles();

  const {
    profileId, switchProfile,
    layout, handleReorder, handleUpdate, handleRemove, handleAdd,
    kpiConfig, handleKpiSave,
    focusMode, handleFocusMode,
    handleReset, handleUndo, undoPossible,
  } = useWorkspace();

  // Restore session on mount
  useEffect(() => {
    const saved = getSession();
    saveSession({ lastPath: "/workspace" });
  }, []);

  const activeProfile = profiles.find((p) => p.id === profileId) ?? profiles[0];
  const activeWidgetIds = layout.widgets.map((w) => w.widgetId);

  return (
    <div className="flex flex-col h-full min-h-0 bg-background">

      {/* ── Top bar ── */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border/40 bg-card/50 shrink-0 flex-wrap gap-y-2">

        {/* Profile selector */}
        <ProfileSelector
          profiles={profiles}
          activeId={profileId}
          onSelect={switchProfile}
        />

        {/* Divider */}
        <div className="hidden md:block w-px h-5 bg-border/40" />

        {/* Focus mode (compact on small screens) */}
        <div className="hidden sm:block">
          <FocusModeBar active={focusMode} onChange={handleFocusMode} />
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Market session badge */}
        <SessionBadge session={session} />

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={handleUndo}
            disabled={!undoPossible}
            title="Undo last layout change"
            className="p-2 rounded-lg text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/50 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Undo2 className="w-4 h-4" />
          </button>

          <button
            onClick={() => { if (confirm("Reset to default layout?")) handleReset(); }}
            title="Reset layout to defaults"
            className="p-2 rounded-lg text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/50 transition-colors"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          <button
            onClick={() => setSettingsOpen(true)}
            title="Workspace settings"
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors",
              settingsOpen
                ? "bg-primary/20 text-primary"
                : "bg-muted/40 text-muted-foreground/70 hover:bg-muted/60 hover:text-foreground"
            )}
          >
            <Settings2 className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Customise</span>
          </button>
        </div>
      </div>

      {/* ── KPI Bar ── */}
      <div className="px-4 border-b border-border/30 bg-card/30 shrink-0">
        <KpiBar config={kpiConfig} onSave={handleKpiSave} />
      </div>

      {/* ── Focus mode banner + smart session banner ── */}
      <div className="px-4 py-2 space-y-1.5 shrink-0">
        {focusMode !== "none" && (
          <FocusModeBanner mode={focusMode} onClose={() => handleFocusMode("none")} />
        )}
        {session.banner && focusMode === "none" && (
          <SessionBanner session={session} />
        )}
      </div>

      {/* ── Main grid ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-4 pb-6">
          <DashboardGrid
            instances={layout.widgets}
            focusMode={focusMode}
            onReorder={handleReorder}
            onUpdate={handleUpdate}
            onRemove={handleRemove}
          />
        </div>
      </div>

      {/* ── Settings panel ── */}
      <WorkspaceSettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        currentProfileId={profileId}
        onProfileChange={switchProfile}
        activeWidgetIds={activeWidgetIds}
        onAddWidget={handleAdd}
        focusMode={focusMode}
        onFocusModeChange={handleFocusMode}
        onResetLayout={handleReset}
        onUndo={handleUndo}
        canUndo={undoPossible}
      />
    </div>
  );
}

// ── Profile selector ──────────────────────────────────────────────────────────

function ProfileSelector({
  profiles, activeId, onSelect,
}: {
  profiles: ReturnType<typeof getAllProfiles>;
  activeId: string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const active = profiles.find((p) => p.id === activeId) ?? profiles[0];

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border/40 bg-card hover:bg-muted/30 transition-colors text-[12px] font-semibold"
        style={{ borderLeftColor: active.color, borderLeftWidth: "2px" }}
      >
        <span>{active.emoji}</span>
        <span className="text-foreground/85 hidden sm:inline">{active.label}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted-foreground/50" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 z-40 w-52 rounded-xl border border-border/60 bg-card shadow-xl py-1">
            {profiles.map((p) => (
              <button
                key={p.id}
                onClick={() => { onSelect(p.id); setOpen(false); }}
                className={cn(
                  "w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-muted/40 transition-colors",
                  p.id === activeId ? "bg-muted/30" : ""
                )}
              >
                <span style={{ color: p.color }}>{p.emoji}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-semibold text-foreground/85">{p.label}</p>
                  <p className="text-[10px] text-muted-foreground/50 truncate">{p.description}</p>
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ── Market session badge ───────────────────────────────────────────────────────

function SessionBadge({ session }: { session: ReturnType<typeof getMarketSession> }) {
  return (
    <div
      className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-semibold"
      style={{
        borderColor: session.color + "40",
        color: session.color,
        backgroundColor: session.color + "12",
      }}
    >
      <span>{session.emoji}</span>
      <span>{session.label}</span>
    </div>
  );
}

// ── Smart session banner ───────────────────────────────────────────────────────

function SessionBanner({ session }: { session: ReturnType<typeof getMarketSession> }) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed || !session.banner) return null;
  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] border"
      style={{
        borderColor: session.color + "40",
        backgroundColor: session.color + "10",
        color: session.color,
      }}
    >
      <SunMedium className="w-3.5 h-3.5 shrink-0" />
      <span className="flex-1">{session.banner}</span>
      <button
        onClick={() => setDismissed(true)}
        className="text-[9px] opacity-60 hover:opacity-100 transition-opacity underline shrink-0"
      >
        Dismiss
      </button>
    </div>
  );
}
