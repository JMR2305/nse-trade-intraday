/**
 * WidgetShell.tsx — Phase 9.4
 * Universal wrapper for every dashboard widget.
 * Handles: header, collapse, pin, resize, settings menu, drag handle.
 * UI only — no business logic.
 */
import React, { useState } from "react";
import { cn } from "@/lib/utils";
import {
  ChevronDown, ChevronRight, Pin, PinOff, X, Settings2,
  Maximize2, Minimize2, GripVertical, RefreshCw, Zap,
} from "lucide-react";
import { getWidget } from "../WidgetRegistry";
import type { WidgetInstance, WidgetSize } from "../WorkspaceManager";

// Size → tailwind col-span
const SIZE_COLS: Record<WidgetSize, string> = {
  sm:   "col-span-12 md:col-span-6 lg:col-span-3",
  md:   "col-span-12 md:col-span-6 lg:col-span-4",
  lg:   "col-span-12 md:col-span-12 lg:col-span-6",
  xl:   "col-span-12 md:col-span-12 lg:col-span-8",
  full: "col-span-12",
};

const ROWS_HEIGHT: Record<number, string> = {
  1: "min-h-[140px]",
  2: "min-h-[260px]",
  3: "min-h-[380px]",
};

const SIZE_CYCLE: WidgetSize[] = ["sm", "md", "lg", "xl", "full"];

interface WidgetShellProps {
  instance: WidgetInstance;
  onUpdate: (updates: Partial<WidgetInstance>) => void;
  onRemove: () => void;
  isDragging?: boolean;
  dragHandleProps?: React.HTMLAttributes<HTMLDivElement>;
  children: React.ReactNode;
  isHighlighted?: boolean;
}

export function WidgetShell({
  instance,
  onUpdate,
  onRemove,
  isDragging,
  dragHandleProps,
  children,
  isHighlighted,
}: WidgetShellProps) {
  const def = getWidget(instance.widgetId);
  const [showSettings, setShowSettings] = useState(false);
  const Icon = def?.icon;

  const cycleSize = () => {
    const idx = SIZE_CYCLE.indexOf(instance.size);
    const next = SIZE_CYCLE[(idx + 1) % SIZE_CYCLE.length];
    onUpdate({ size: next });
  };

  const cycleRows = () => {
    const next = (instance.rows % 3) + 1 as 1 | 2 | 3;
    onUpdate({ rows: next });
  };

  if (!instance.visible) return null;

  return (
    <div
      className={cn(
        SIZE_COLS[instance.size],
        "group relative flex flex-col rounded-xl border transition-all duration-200",
        isDragging
          ? "opacity-50 shadow-2xl scale-[1.02] ring-2 ring-primary/40 z-50"
          : "shadow-sm hover:shadow-md",
        instance.pinned
          ? "border-amber-500/40 bg-amber-500/5"
          : "border-border/60 bg-card",
        isHighlighted && !instance.pinned
          ? "border-primary/40 ring-1 ring-primary/20"
          : "",
      )}
      style={{ gridRow: `span ${instance.rows}` }}
    >
      {/* ── Header ── */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/40 select-none">
        {/* Drag handle */}
        <div
          {...dragHandleProps}
          className="cursor-grab active:cursor-grabbing text-muted-foreground/30 hover:text-muted-foreground/60 transition-colors"
          title="Drag to reorder"
        >
          <GripVertical className="w-3.5 h-3.5" />
        </div>

        {/* Icon + label */}
        {Icon && (
          <Icon className={cn(
            "w-3.5 h-3.5 shrink-0",
            isHighlighted ? "text-primary" : "text-muted-foreground/70"
          )} />
        )}
        <span className={cn(
          "flex-1 text-[12px] font-semibold truncate",
          isHighlighted ? "text-foreground" : "text-muted-foreground/90"
        )}>
          {def?.label ?? instance.widgetId}
        </span>

        {/* Tag badge */}
        {def?.tag && (
          <span className="text-[9px] font-bold tracking-widest bg-muted/60 text-muted-foreground/50 px-1.5 py-0.5 rounded">
            {def.tag}
          </span>
        )}

        {/* Pin indicator */}
        {instance.pinned && (
          <span className="text-amber-500/70">
            <Pin className="w-3 h-3" />
          </span>
        )}

        {/* Highlight indicator */}
        {isHighlighted && (
          <span className="flex items-center gap-1 text-[9px] text-primary/70 bg-primary/10 px-1.5 py-0.5 rounded-full">
            <Zap className="w-2.5 h-2.5" />
            <span>NOW</span>
          </span>
        )}

        {/* Controls — show on hover */}
        <div className="hidden group-hover:flex items-center gap-0.5 ml-1">
          {/* Collapse / Expand */}
          <button
            onClick={() => onUpdate({ collapsed: !instance.collapsed })}
            className="p-1 rounded hover:bg-muted/60 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
            title={instance.collapsed ? "Expand" : "Collapse"}
          >
            {instance.collapsed
              ? <ChevronRight className="w-3 h-3" />
              : <ChevronDown className="w-3 h-3" />}
          </button>

          {/* Resize width */}
          <button
            onClick={cycleSize}
            className="p-1 rounded hover:bg-muted/60 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
            title="Cycle size (S→M→L→XL→Full)"
          >
            <Maximize2 className="w-3 h-3" />
          </button>

          {/* Resize rows */}
          <button
            onClick={cycleRows}
            className="p-1 rounded hover:bg-muted/60 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
            title="Cycle height"
          >
            <Minimize2 className="w-3 h-3 rotate-90" />
          </button>

          {/* Pin / Unpin */}
          <button
            onClick={() => onUpdate({ pinned: !instance.pinned })}
            className={cn(
              "p-1 rounded hover:bg-muted/60 transition-colors",
              instance.pinned
                ? "text-amber-500"
                : "text-muted-foreground/50 hover:text-muted-foreground"
            )}
            title={instance.pinned ? "Unpin" : "Pin widget"}
          >
            {instance.pinned ? <Pin className="w-3 h-3" /> : <PinOff className="w-3 h-3" />}
          </button>

          {/* Settings */}
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="p-1 rounded hover:bg-muted/60 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
            title="Widget settings"
          >
            <Settings2 className="w-3 h-3" />
          </button>

          {/* Remove */}
          <button
            onClick={onRemove}
            className="p-1 rounded hover:bg-red-500/20 text-muted-foreground/50 hover:text-red-400 transition-colors"
            title="Remove widget"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* ── Settings dropdown ── */}
      {showSettings && (
        <WidgetSettingsDropdown
          instance={instance}
          onUpdate={onUpdate}
          onClose={() => setShowSettings(false)}
        />
      )}

      {/* ── Content area ── */}
      {!instance.collapsed && (
        <div className={cn(
          "flex-1 overflow-hidden",
          ROWS_HEIGHT[instance.rows],
          instance.settings.compactMode ? "p-2" : "p-3",
        )}>
          {children}
        </div>
      )}
    </div>
  );
}

// ── Widget settings mini-panel ────────────────────────────────────────────────

function WidgetSettingsDropdown({
  instance,
  onUpdate,
  onClose,
}: {
  instance: WidgetInstance;
  onUpdate: (u: Partial<WidgetInstance>) => void;
  onClose: () => void;
}) {
  const INTERVALS = [15, 30, 60, 120, 300] as const;
  const SIZES: WidgetSize[] = ["sm", "md", "lg", "xl", "full"];

  return (
    <div className="border-b border-border/40 bg-muted/20 px-3 py-2.5 space-y-2.5 text-[11px]">
      {/* Refresh interval */}
      <div className="flex items-center gap-2">
        <RefreshCw className="w-3 h-3 text-muted-foreground/60" />
        <span className="text-muted-foreground/70 w-20">Refresh</span>
        <div className="flex gap-1">
          {INTERVALS.map((s) => (
            <button
              key={s}
              onClick={() => onUpdate({ settings: { ...instance.settings, refreshInterval: s } })}
              className={cn(
                "px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors",
                instance.settings.refreshInterval === s
                  ? "bg-primary/20 text-primary"
                  : "bg-muted/60 text-muted-foreground/60 hover:text-muted-foreground"
              )}
            >
              {s < 60 ? `${s}s` : `${s/60}m`}
            </button>
          ))}
        </div>
      </div>

      {/* Size */}
      <div className="flex items-center gap-2">
        <Maximize2 className="w-3 h-3 text-muted-foreground/60" />
        <span className="text-muted-foreground/70 w-20">Size</span>
        <div className="flex gap-1">
          {SIZES.map((sz) => (
            <button
              key={sz}
              onClick={() => onUpdate({ size: sz })}
              className={cn(
                "px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors uppercase",
                instance.size === sz
                  ? "bg-primary/20 text-primary"
                  : "bg-muted/60 text-muted-foreground/60 hover:text-muted-foreground"
              )}
            >
              {sz}
            </button>
          ))}
        </div>
      </div>

      {/* Compact mode */}
      <div className="flex items-center gap-2">
        <Minimize2 className="w-3 h-3 text-muted-foreground/60" />
        <span className="text-muted-foreground/70 w-20">Compact</span>
        <button
          onClick={() => onUpdate({ settings: { ...instance.settings, compactMode: !instance.settings.compactMode } })}
          className={cn(
            "px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors",
            instance.settings.compactMode
              ? "bg-primary/20 text-primary"
              : "bg-muted/60 text-muted-foreground/60"
          )}
        >
          {instance.settings.compactMode ? "ON" : "OFF"}
        </button>
      </div>

      <button
        onClick={onClose}
        className="text-muted-foreground/50 hover:text-muted-foreground transition-colors"
      >
        Close settings
      </button>
    </div>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

export function WidgetSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-6 bg-muted/50 rounded" style={{ width: `${70 + i * 10}%` }} />
      ))}
    </div>
  );
}

// ── Error state ───────────────────────────────────────────────────────────────

export function WidgetError({ message }: { message?: string }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground/60 h-full">
      <span className="text-amber-500/60">⚠</span>
      <span>{message ?? "Data unavailable"}</span>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

export function WidgetEmpty({ message }: { message?: string }) {
  return (
    <div className="flex items-center justify-center h-full text-[11px] text-muted-foreground/40 italic">
      {message ?? "No data"}
    </div>
  );
}
