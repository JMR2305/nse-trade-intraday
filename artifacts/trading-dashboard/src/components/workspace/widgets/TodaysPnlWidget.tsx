import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function TodaysPnlWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-pnl"],
    queryFn: () => apiJson<any>("portfolio-performance/summary"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={2} />;
  if (error) return <WidgetError message="P&L data unavailable" />;

  const s = data ?? {};
  const total  = s.total_pnl ?? s.net_pnl ?? 0;
  const trades = s.total_trades ?? s.trade_count ?? 0;
  const wins   = s.win_count ?? 0;
  const isPos  = total >= 0;
  const Icon   = total > 0 ? TrendingUp : total < 0 ? TrendingDown : Minus;

  return (
    <div className="space-y-2">
      {/* Big P&L number */}
      <div className={cn(
        "flex items-center gap-2 px-2 py-2 rounded-lg",
        isPos ? "bg-emerald-500/10" : total < 0 ? "bg-red-500/10" : "bg-muted/20"
      )}>
        <Icon className={cn("w-5 h-5", isPos ? "text-emerald-500" : total < 0 ? "text-red-400" : "text-muted-foreground")} />
        <div>
          <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wide">Today's P&L</p>
          <p className={cn("text-xl font-bold", isPos ? "text-emerald-500" : total < 0 ? "text-red-400" : "text-foreground")}>
            {isPos ? "+" : ""}₹{Math.abs(total).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
          </p>
        </div>
      </div>

      {/* Sub-metrics */}
      {!compact && (
        <div className="grid grid-cols-2 gap-1.5 text-[11px]">
          <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
            <p className="text-muted-foreground/50 text-[9px] uppercase">Trades</p>
            <p className="font-bold text-foreground/80">{trades}</p>
          </div>
          <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
            <p className="text-muted-foreground/50 text-[9px] uppercase">Wins</p>
            <p className="font-bold text-emerald-500">{wins}</p>
          </div>
        </div>
      )}
    </div>
  );
}
