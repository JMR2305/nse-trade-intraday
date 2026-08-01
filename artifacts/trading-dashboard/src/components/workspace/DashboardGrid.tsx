/**
 * DashboardGrid.tsx — Phase 9.4
 * Drag-and-drop, resizable, sortable widget grid using @dnd-kit.
 * UI/UX only — no business logic.
 */
import React, { useState, useCallback } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
  DragOverlay,
} from "@dnd-kit/core";
import { isWidgetVisibleInFocusMode, type FocusMode } from "./WorkspaceManager";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  rectSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "@/lib/utils";
import { WidgetShell } from "./widgets/WidgetShell";
import type { WidgetInstance } from "./WorkspaceManager";
import { getWidget } from "./WidgetRegistry";
import { getHighlightedWidgets } from "./SmartDashboard";

// ── Widget renderer ───────────────────────────────────────────────────────────
// Lazy-loads the right widget component for each widget id

import MarketOverviewWidget     from "./widgets/MarketOverviewWidget";
import PortfolioWidget          from "./widgets/PortfolioWidget";
import TodaysPnlWidget          from "./widgets/TodaysPnlWidget";
import WatchlistWidget          from "./widgets/WatchlistWidget";
import RiskSummaryWidget        from "./widgets/RiskSummaryWidget";
import AiSummaryWidget          from "./widgets/AiSummaryWidget";
import MarketIntelligenceWidget from "./widgets/MarketIntelligenceWidget";
import PreOpenWidget            from "./widgets/PreOpenWidget";
import AlertsWidget             from "./widgets/AlertsWidget";
import ResearchFeedWidget       from "./widgets/ResearchFeedWidget";
import PaperTradingWidget       from "./widgets/PaperTradingWidget";
import ExecutionWidget          from "./widgets/ExecutionWidget";
import LearningWidget           from "./widgets/LearningWidget";
import PerformanceWidget        from "./widgets/PerformanceWidget";
import OperationsWidget         from "./widgets/OperationsWidget";
import SecurityWidget           from "./widgets/SecurityWidget";
import DeploymentWidget         from "./widgets/DeploymentWidget";
import SystemHealthWidget       from "./widgets/SystemHealthWidget";
import TradingTimelineWidget    from "./widgets/TradingTimelineWidget";
import AiDailyBriefingWidget    from "./widgets/AiDailyBriefingWidget";
import QuickNotesWidget         from "./widgets/QuickNotesWidget";

const WIDGET_COMPONENTS: Record<string, React.ComponentType<{ compact?: boolean; refreshInterval?: number }>> = {
  "market-overview":      MarketOverviewWidget,
  "portfolio":            PortfolioWidget,
  "today-pnl":            TodaysPnlWidget,
  "watchlist":            WatchlistWidget,
  "risk-summary":         RiskSummaryWidget,
  "ai-summary":           AiSummaryWidget,
  "market-intelligence":  MarketIntelligenceWidget,
  "pre-open":             PreOpenWidget,
  "alerts":               AlertsWidget,
  "research-feed":        ResearchFeedWidget,
  "paper-trading":        PaperTradingWidget,
  "execution":            ExecutionWidget,
  "learning":             LearningWidget,
  "performance":          PerformanceWidget,
  "operations":           OperationsWidget,
  "security":             SecurityWidget,
  "deployment":           DeploymentWidget,
  "system-health":        SystemHealthWidget,
  "trading-timeline":     TradingTimelineWidget,
  "ai-daily-briefing":    AiDailyBriefingWidget,
  "quick-notes":          QuickNotesWidget,
};

// ── Sortable widget item ──────────────────────────────────────────────────────

interface SortableWidgetProps {
  instance: WidgetInstance;
  onUpdate: (instanceId: string, updates: Partial<WidgetInstance>) => void;
  onRemove: (instanceId: string) => void;
  highlighted: boolean;
}

function SortableWidget({ instance, onUpdate, onRemove, highlighted }: SortableWidgetProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: instance.instanceId });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const WidgetComponent = WIDGET_COMPONENTS[instance.widgetId];

  return (
    <div ref={setNodeRef} style={style} className="contents">
      <WidgetShell
        instance={instance}
        onUpdate={(updates) => onUpdate(instance.instanceId, updates)}
        onRemove={() => onRemove(instance.instanceId)}
        isDragging={isDragging}
        dragHandleProps={{ ...attributes, ...listeners }}
        isHighlighted={highlighted}
      >
        {WidgetComponent ? (
          <WidgetComponent
            compact={instance.settings.compactMode}
            refreshInterval={instance.settings.refreshInterval}
          />
        ) : (
          <div className="text-[11px] text-muted-foreground/40 italic flex items-center justify-center h-full">
            Widget "{instance.widgetId}" not found
          </div>
        )}
      </WidgetShell>
    </div>
  );
}

// ── Ghost overlay for active drag ─────────────────────────────────────────────

function DragGhost({ instance }: { instance: WidgetInstance | null }) {
  if (!instance) return null;
  const def = getWidget(instance.widgetId);
  const Icon = def?.icon;
  return (
    <div className="bg-card border border-primary/40 rounded-xl shadow-2xl ring-2 ring-primary/30 p-3 opacity-90 w-48">
      <div className="flex items-center gap-2">
        {Icon && <Icon className="w-4 h-4 text-primary/70" />}
        <span className="text-[12px] font-semibold text-foreground/80 truncate">{def?.label ?? instance.widgetId}</span>
      </div>
    </div>
  );
}

// ── DashboardGrid component ───────────────────────────────────────────────────

interface DashboardGridProps {
  instances: WidgetInstance[];
  focusMode: string;
  onReorder: (fromIndex: number, toIndex: number) => void;
  onUpdate: (instanceId: string, updates: Partial<WidgetInstance>) => void;
  onRemove: (instanceId: string) => void;
}

export function DashboardGrid({
  instances,
  focusMode,
  onReorder,
  onUpdate,
  onRemove,
}: DashboardGridProps) {
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },  // require 8px drag before activating
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const highlightedWidgets = getHighlightedWidgets();

  const handleDragStart = useCallback((event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  }, []);

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const fromIndex = instances.findIndex((w) => w.instanceId === active.id);
    const toIndex   = instances.findIndex((w) => w.instanceId === over.id);
    if (fromIndex !== -1 && toIndex !== -1) {
      onReorder(fromIndex, toIndex);
    }
  }, [instances, onReorder]);

  // Filter by focus mode
  const visible = instances.filter((inst) => {
    if (focusMode === "none") return inst.visible;
    return inst.visible && isWidgetVisibleInFocusMode(inst.widgetId, focusMode as FocusMode);
  });

  const activeInstance = activeId
    ? instances.find((w) => w.instanceId === activeId) ?? null
    : null;

  const sortableIds = visible.map((w) => w.instanceId);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={sortableIds} strategy={rectSortingStrategy}>
        <div className={cn(
          "grid gap-3",
          "grid-cols-12",
        )}>
          {visible.map((instance) => (
            <SortableWidget
              key={instance.instanceId}
              instance={instance}
              onUpdate={onUpdate}
              onRemove={onRemove}
              highlighted={highlightedWidgets.includes(instance.widgetId)}
            />
          ))}

          {visible.length === 0 && (
            <div className="col-span-12 flex flex-col items-center justify-center py-16 text-center">
              <p className="text-4xl mb-3">🧩</p>
              <p className="text-base font-semibold text-foreground/60">No widgets visible</p>
              <p className="text-[13px] text-muted-foreground/50 mt-1">
                Add widgets from the settings panel or change the focus mode.
              </p>
            </div>
          )}
        </div>
      </SortableContext>

      <DragOverlay>
        <DragGhost instance={activeInstance} />
      </DragOverlay>
    </DndContext>
  );
}
