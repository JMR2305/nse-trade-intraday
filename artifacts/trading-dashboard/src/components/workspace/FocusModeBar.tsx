/**
 * FocusModeBar.tsx — Phase 9.4
 * Focus mode selector: 5 modes that hide non-essential widgets.
 * UI only — no business logic.
 */
import React from "react";
import { cn } from "@/lib/utils";
import { Monitor, LayoutDashboard } from "lucide-react";
import { FOCUS_MODES, type FocusMode } from "./WorkspaceManager";

interface FocusModeBarProps {
  active: FocusMode;
  onChange: (mode: FocusMode) => void;
  compact?: boolean;
}

export function FocusModeBar({ active, onChange, compact }: FocusModeBarProps) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {!compact && (
        <span className="text-[10px] text-muted-foreground/40 uppercase tracking-widest mr-1 flex items-center gap-1">
          <LayoutDashboard className="w-3 h-3" />
          Focus
        </span>
      )}
      {FOCUS_MODES.map((mode) => {
        const isActive = active === mode.id;
        return (
          <button
            key={mode.id}
            onClick={() => onChange(mode.id)}
            title={mode.description}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all duration-150",
              isActive
                ? "bg-primary/15 text-primary border border-primary/30 shadow-sm"
                : "text-muted-foreground/60 hover:text-foreground hover:bg-muted/50 border border-transparent"
            )}
          >
            <span className={compact ? "text-sm" : "text-xs"}>{mode.emoji}</span>
            {!compact && <span>{mode.label}</span>}
          </button>
        );
      })}
    </div>
  );
}

// ── Focus mode banner (shown at top of dashboard when a mode is active) ────────

interface FocusModeBannerProps {
  mode: FocusMode;
  onClose: () => void;
}

export function FocusModeBanner({ mode, onClose }: FocusModeBannerProps) {
  if (mode === "none") return null;
  const def = FOCUS_MODES.find((m) => m.id === mode);
  if (!def) return null;
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary/10 border border-primary/20 text-[11px]">
      <span>{def.emoji}</span>
      <span className="font-semibold text-primary/80">{def.label} Mode</span>
      <span className="text-muted-foreground/50">— {def.description}</span>
      <button
        onClick={onClose}
        className="ml-auto text-muted-foreground/50 hover:text-muted-foreground transition-colors text-[10px] underline"
      >
        Exit focus
      </button>
    </div>
  );
}
