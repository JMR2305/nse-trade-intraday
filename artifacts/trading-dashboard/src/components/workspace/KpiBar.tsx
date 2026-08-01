/**
 * KpiBar.tsx — Phase 9.4
 * Personal KPI Bar: 8–12 favourite KPIs shown as a compact horizontal strip.
 * UI only — reads from existing endpoints, no new APIs.
 */
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Settings2, X, GripVertical, Plus } from "lucide-react";
import { KPI_REGISTRY, KPI_MAP, type KpiDef } from "./WidgetRegistry";
import type { KpiBarConfig } from "./WorkspaceManager";

// ── KPI value fetcher ─────────────────────────────────────────────────────────
// Each KPI reads from a small set of shared endpoints — React Query deduplicates.

const SHARED_ENDPOINT_CACHE_MS = 29_000;

function useEndpointData(endpoint?: string) {
  return useQuery({
    queryKey: ["kpi-bar", endpoint ?? "none"],
    queryFn: () => endpoint ? apiJson<any>(endpoint) : Promise.resolve(null),
    staleTime: SHARED_ENDPOINT_CACHE_MS,
    refetchInterval: 30_000,
    enabled: !!endpoint,
    retry: 1,
  });
}

// Extract a KPI value from response data using common key patterns
function extractValue(kpiId: string, data: any): string | null {
  if (!data) return null;
  const map: Record<string, string[]> = {
    "portfolio-value":  ["portfolio_value", "total_value", "net_value", "value"],
    "today-pnl":        ["today_pnl", "total_pnl", "net_pnl", "day_pnl"],
    "risk-score":       ["risk_score", "score"],
    "ai-confidence":    ["ai_confidence", "confidence"],
    "market-breadth":   ["breadth_pct", "market_breadth", "breadth"],
    "nifty-value":      ["nifty_iep", "nifty_price", "nifty", "iep"],
    "banknifty-value":  ["banknifty_iep", "banknifty_price", "banknifty"],
    "bullish-stocks":   ["bullish_count", "bullish_stocks", "bullish"],
    "open-positions":   ["open_positions", "position_count", "positions"],
    "platform-health":  ["overall_score", "system_score", "health_score", "platform_score"],
    "win-rate":         ["win_rate", "win_pct"],
    "drawdown":         ["max_drawdown_pct", "max_drawdown", "drawdown"],
  };
  const keys = map[kpiId] ?? [];
  for (const k of keys) {
    if (data[k] !== undefined && data[k] !== null) {
      const v = data[k];
      if (typeof v === "number") return v.toLocaleString("en-IN", { maximumFractionDigits: 1 });
      return String(v);
    }
  }
  return null;
}

// ── Single KPI chip ───────────────────────────────────────────────────────────

function KpiChip({ kpi, editMode, onRemove }: {
  kpi: KpiDef;
  editMode: boolean;
  onRemove: () => void;
}) {
  const { data, isLoading } = useEndpointData(kpi.endpoint);
  const rawValue = extractValue(kpi.id, data);
  const value = rawValue ? `${rawValue}${kpi.unit ?? ""}` : "—";

  // Special formatting for currency
  const displayValue = kpi.unit === "₹" && rawValue
    ? `₹${parseFloat(rawValue.replace(/,/g, "")).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
    : value;

  const isPositiveKpi = ["portfolio-value", "today-pnl", "ai-confidence", "win-rate", "bullish-stocks", "platform-health"].includes(kpi.id);
  const isNegativeKpi = ["drawdown", "risk-score"].includes(kpi.id);

  return (
    <div
      className={cn(
        "relative flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all duration-200 whitespace-nowrap",
        editMode
          ? "bg-muted/50 border-dashed border-border/60 cursor-default"
          : "bg-card border-border/40 hover:bg-muted/30",
        isLoading ? "opacity-50" : "",
      )}
      style={{ borderLeftColor: kpi.color, borderLeftWidth: "2px" }}
    >
      <div>
        <p className="text-[9px] text-muted-foreground/50 uppercase tracking-wide leading-none mb-0.5">
          {kpi.shortLabel}
        </p>
        <p className={cn(
          "text-[12px] font-bold leading-none",
          isLoading ? "text-muted-foreground/40" : "text-foreground",
        )}>
          {isLoading ? "…" : displayValue}
        </p>
      </div>

      {editMode && (
        <button
          onClick={onRemove}
          className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500 flex items-center justify-center text-white hover:bg-red-600 transition-colors z-10"
        >
          <X className="w-2.5 h-2.5" />
        </button>
      )}
    </div>
  );
}

// ── KpiBar component ──────────────────────────────────────────────────────────

interface KpiBarProps {
  config: KpiBarConfig;
  onSave: (config: KpiBarConfig) => void;
}

export function KpiBar({ config, onSave }: KpiBarProps) {
  const [editMode, setEditMode]   = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const currentKpis = config.kpis.filter((id) => KPI_MAP.has(id));

  const removeKpi = (id: string) => {
    onSave({ kpis: currentKpis.filter((k) => k !== id) });
  };

  const addKpi = (id: string) => {
    if (currentKpis.includes(id)) return;
    if (currentKpis.length >= 12) return;
    onSave({ kpis: [...currentKpis, id] });
    setShowPicker(false);
  };

  const available = KPI_REGISTRY.filter((k) => !currentKpis.includes(k.id));

  return (
    <div className="relative">
      <div className="flex items-center gap-2 overflow-x-auto scrollbar-hide py-2 px-1">
        {/* KPI chips */}
        {currentKpis.map((kpiId) => {
          const kpi = KPI_MAP.get(kpiId);
          if (!kpi) return null;
          return (
            <KpiChip
              key={kpiId}
              kpi={kpi}
              editMode={editMode}
              onRemove={() => removeKpi(kpiId)}
            />
          );
        })}

        {/* Add button (edit mode) */}
        {editMode && currentKpis.length < 12 && (
          <button
            onClick={() => setShowPicker(!showPicker)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-dashed border-primary/40 text-primary/60 hover:text-primary hover:border-primary/60 transition-colors whitespace-nowrap text-[11px] font-medium"
          >
            <Plus className="w-3 h-3" />
            Add KPI
          </button>
        )}

        {/* Divider + Edit toggle */}
        <div className="ml-auto shrink-0 flex items-center gap-1.5 pl-2 border-l border-border/30">
          <button
            onClick={() => { setEditMode(!editMode); setShowPicker(false); }}
            className={cn(
              "p-1.5 rounded-lg transition-colors",
              editMode
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted/50"
            )}
            title="Customize KPI bar"
          >
            <Settings2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* KPI picker dropdown */}
      {showPicker && (
        <div className="absolute top-full right-0 z-50 mt-1 w-72 rounded-xl border border-border/60 bg-card shadow-xl p-3">
          <p className="text-[11px] font-semibold text-foreground/70 mb-2">Add KPI ({currentKpis.length}/12)</p>
          <div className="grid grid-cols-2 gap-1.5 max-h-64 overflow-y-auto">
            {available.map((kpi) => (
              <button
                key={kpi.id}
                onClick={() => addKpi(kpi.id)}
                className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-left hover:bg-muted/50 transition-colors"
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: kpi.color }}
                />
                <span className="text-[11px] text-foreground/80 truncate">{kpi.label}</span>
              </button>
            ))}
            {available.length === 0 && (
              <p className="col-span-2 text-[10px] text-muted-foreground/40 italic text-center py-2">
                All KPIs added
              </p>
            )}
          </div>
          <button onClick={() => setShowPicker(false)} className="mt-2 text-[10px] text-muted-foreground/50 hover:text-muted-foreground">
            Close
          </button>
        </div>
      )}
    </div>
  );
}
