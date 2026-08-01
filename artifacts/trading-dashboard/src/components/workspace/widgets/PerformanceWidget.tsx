import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { BarChart3 } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function PerformanceWidget({ compact, refreshInterval = 60 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-performance"],
    queryFn: () => apiJson<any>("portfolio-performance/summary"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Performance data unavailable" />;

  const s = data ?? {};
  const win_rate   = s.win_rate   ?? null;
  const sharpe     = s.sharpe_ratio ?? s.sharpe ?? null;
  const drawdown   = s.max_drawdown_pct ?? s.max_drawdown ?? null;
  const total_pnl  = s.total_pnl ?? s.net_pnl ?? null;

  return (
    <div className="space-y-2">
      {/* Overall stat */}
      {total_pnl !== null && (
        <div className={cn(
          "flex items-center gap-2 px-2 py-1.5 rounded-lg",
          total_pnl >= 0 ? "bg-emerald-500/10" : "bg-red-500/10"
        )}>
          <BarChart3 className={cn("w-4 h-4", total_pnl >= 0 ? "text-emerald-500" : "text-red-400")} />
          <div>
            <p className="text-[9px] text-muted-foreground/50 uppercase">Total P&L</p>
            <p className={cn("text-sm font-bold", total_pnl >= 0 ? "text-emerald-500" : "text-red-400")}>
              {total_pnl >= 0 ? "+" : ""}₹{Math.abs(total_pnl).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </p>
          </div>
        </div>
      )}

      {!compact && (
        <div className="grid grid-cols-3 gap-1.5">
          <MetricTile label="Win Rate" value={win_rate !== null ? `${win_rate.toFixed(1)}%` : "—"} />
          <MetricTile label="Sharpe"   value={sharpe   !== null ? sharpe.toFixed(2)           : "—"} />
          <MetricTile label="Drawdown" value={drawdown !== null ? `${drawdown.toFixed(1)}%`   : "—"} warn={drawdown !== null && drawdown > 10} />
        </div>
      )}
    </div>
  );
}

function MetricTile({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className={cn("rounded px-2 py-1.5 text-center", warn ? "bg-red-500/10" : "bg-muted/20")}>
      <p className="text-[9px] text-muted-foreground/50 uppercase">{label}</p>
      <p className={cn("text-[11px] font-bold", warn ? "text-red-400" : "text-foreground/80")}>{value}</p>
    </div>
  );
}
