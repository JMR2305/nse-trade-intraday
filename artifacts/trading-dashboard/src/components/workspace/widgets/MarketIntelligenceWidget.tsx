import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function MarketIntelligenceWidget({ compact, refreshInterval = 60 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-market-intelligence"],
    queryFn: () => apiJson<any>("market-intelligence/overview"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Market intelligence unavailable" />;

  const d = data ?? {};
  const regime   = d.regime ?? d.market_regime ?? "—";
  const breadth  = d.breadth_pct ?? d.market_breadth ?? null;
  const trend    = d.trend ?? d.direction ?? "—";
  const signals  = d.signal_count ?? d.signals ?? null;

  const regimeColor = regime.includes("BULL") ? "text-emerald-500"
    : regime.includes("BEAR") ? "text-red-400"
    : "text-amber-500";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2 py-2 rounded-lg bg-muted/30">
        <div>
          <p className="text-[9px] text-muted-foreground/50 uppercase">Regime</p>
          <p className={cn("text-sm font-bold truncate max-w-[120px]", regimeColor)}>{regime}</p>
        </div>
        <div className="text-right">
          <p className="text-[9px] text-muted-foreground/50 uppercase">Trend</p>
          <p className="text-sm font-semibold text-foreground/80">{trend}</p>
        </div>
      </div>
      {!compact && (
        <div className="grid grid-cols-2 gap-1.5">
          <Chip label="Breadth" value={breadth !== null ? `${breadth.toFixed(0)}%` : "—"} />
          <Chip label="Signals" value={signals !== null ? String(signals) : "—"} />
        </div>
      )}
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
      <p className="text-[9px] text-muted-foreground/50 uppercase">{label}</p>
      <p className="text-[11px] font-bold text-foreground/80">{value}</p>
    </div>
  );
}
