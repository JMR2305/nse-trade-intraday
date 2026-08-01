import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError, WidgetEmpty } from "./WidgetShell";
import { cn } from "@/lib/utils";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function WatchlistWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-watchlist"],
    queryFn: () => apiJson<any>("preopen/watchlist"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 3 : 5} />;
  if (error) return <WidgetError message="Watchlist unavailable" />;

  const items: any[] = Array.isArray(data) ? data : (data?.watchlist ?? data?.symbols ?? []);
  if (!items.length) return <WidgetEmpty message="Watchlist is empty" />;

  const limit = compact ? 4 : 8;

  return (
    <div className="space-y-1">
      {items.slice(0, limit).map((item: any, i: number) => {
        const symbol = item.symbol ?? item.tradingsymbol ?? `SYM-${i}`;
        const signal = item.signal ?? item.direction ?? null;
        const signalColor = signal === "BUY" ? "text-emerald-500" : signal === "SELL" ? "text-red-400" : "text-muted-foreground/40";
        return (
          <div key={i} className="flex items-center justify-between px-2 py-1 rounded text-[11px] hover:bg-muted/30 transition-colors">
            <span className="font-semibold text-foreground/80 w-24 truncate">{symbol}</span>
            <span className="text-muted-foreground/50 flex-1 text-center">{item.sector ?? "—"}</span>
            <span className={cn("font-bold w-10 text-right", signalColor)}>
              {signal ?? "—"}
            </span>
          </div>
        );
      })}
      {items.length > limit && (
        <p className="text-[10px] text-muted-foreground/40 text-center pt-0.5">
          +{items.length - limit} more symbols
        </p>
      )}
    </div>
  );
}
