import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError, WidgetEmpty } from "./WidgetShell";
import { cn } from "@/lib/utils";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function PortfolioWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-portfolio"],
    queryFn: () => apiJson<any>("phase20/positions"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Portfolio data unavailable" />;

  const positions: any[] = data?.positions ?? data ?? [];
  if (!positions.length) return <WidgetEmpty message="No open positions" />;

  const total_pnl = positions.reduce((s: number, p: any) => s + (p.unrealized_pnl ?? p.pnl ?? 0), 0);

  return (
    <div className="space-y-2">
      {/* Summary row */}
      <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-muted/30">
        <span className="text-[11px] text-muted-foreground/70">{positions.length} positions</span>
        <span className={cn("text-[12px] font-bold", total_pnl >= 0 ? "text-emerald-500" : "text-red-400")}>
          {total_pnl >= 0 ? "+" : ""}₹{Math.abs(total_pnl).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
        </span>
      </div>

      {/* Position rows */}
      {!compact && (
        <div className="space-y-1 max-h-40 overflow-y-auto">
          {positions.slice(0, 6).map((p: any, i: number) => {
            const symbol = p.symbol ?? p.tradingsymbol ?? `POS-${i}`;
            const pnl    = p.unrealized_pnl ?? p.pnl ?? 0;
            const qty    = p.quantity ?? p.qty ?? 0;
            return (
              <div key={i} className="flex items-center justify-between text-[11px] px-2 py-1 rounded bg-muted/20 hover:bg-muted/40 transition-colors">
                <span className="font-medium text-foreground/80 truncate max-w-[80px]">{symbol}</span>
                <span className="text-muted-foreground/60 mx-1">{qty} qty</span>
                <span className={cn("font-semibold ml-auto", pnl >= 0 ? "text-emerald-500" : "text-red-400")}>
                  {pnl >= 0 ? "+" : ""}₹{Math.abs(pnl).toFixed(0)}
                </span>
              </div>
            );
          })}
          {positions.length > 6 && (
            <p className="text-[10px] text-muted-foreground/40 text-center pt-1">
              +{positions.length - 6} more positions
            </p>
          )}
        </div>
      )}
    </div>
  );
}
