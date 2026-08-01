import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { PieChart } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function PaperTradingWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-paper-trading"],
    queryFn: () => apiJson<any>("phase20/health"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={2} />;
  if (error) return <WidgetError message="Paper trading data unavailable" />;

  const d = data ?? {};
  const status     = d.status ?? d.health ?? "UNKNOWN";
  const enabled    = d.auto_entry_enabled ?? d.enabled ?? false;
  const open_pos   = d.open_positions ?? d.position_count ?? 0;
  const total_pnl  = d.total_pnl ?? d.unrealized_pnl ?? 0;

  const statusColor = status === "HEALTHY" ? "text-emerald-500"
    : status === "DEGRADED" ? "text-amber-500"
    : status === "DOWN" ? "text-red-400"
    : "text-muted-foreground/50";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-muted/30">
        <div className="flex items-center gap-2">
          <PieChart className={cn("w-4 h-4", statusColor)} />
          <div>
            <p className="text-[9px] text-muted-foreground/50 uppercase">Status</p>
            <p className={cn("text-[12px] font-bold", statusColor)}>{status}</p>
          </div>
        </div>
        <span className={cn(
          "text-[9px] font-bold px-2 py-0.5 rounded-full",
          enabled ? "bg-emerald-500/20 text-emerald-500" : "bg-muted/40 text-muted-foreground/50"
        )}>
          {enabled ? "AUTO ON" : "MANUAL"}
        </span>
      </div>

      {!compact && (
        <div className="grid grid-cols-2 gap-1.5">
          <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
            <p className="text-[9px] text-muted-foreground/50 uppercase">Positions</p>
            <p className="text-[12px] font-bold text-foreground/80">{open_pos}</p>
          </div>
          <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
            <p className="text-[9px] text-muted-foreground/50 uppercase">P&L</p>
            <p className={cn("text-[12px] font-bold", total_pnl >= 0 ? "text-emerald-500" : "text-red-400")}>
              {total_pnl >= 0 ? "+" : ""}₹{Math.abs(total_pnl).toFixed(0)}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
