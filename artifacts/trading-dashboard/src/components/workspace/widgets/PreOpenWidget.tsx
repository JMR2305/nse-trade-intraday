import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Sunrise } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function PreOpenWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-preopen"],
    queryFn: () => apiJson<any>("preopen/session"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Pre-open data unavailable" />;

  const d = data ?? {};
  const active    = d.is_active ?? d.session_active ?? false;
  const iep_nifty = d.nifty_iep ?? d.iep ?? null;
  const movers    = d.top_movers ?? d.movers ?? [];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/30">
        <Sunrise className={cn("w-4 h-4", active ? "text-amber-400" : "text-muted-foreground/40")} />
        <span className={cn("text-[12px] font-semibold", active ? "text-amber-400" : "text-muted-foreground/60")}>
          {active ? "Pre-Open Active" : "Market Open"}
        </span>
        {iep_nifty && (
          <span className="ml-auto text-[11px] font-bold text-foreground/70">
            IEP: {iep_nifty.toLocaleString("en-IN")}
          </span>
        )}
      </div>

      {!compact && movers.length > 0 && (
        <div className="space-y-1">
          <p className="text-[9px] text-muted-foreground/40 uppercase px-1">Top Movers</p>
          {movers.slice(0, 4).map((m: any, i: number) => (
            <div key={i} className="flex justify-between text-[11px] px-2 py-0.5">
              <span className="font-medium">{m.symbol ?? m.tradingsymbol ?? `SYM-${i}`}</span>
              <span className={cn("font-bold", (m.change ?? 0) >= 0 ? "text-emerald-500" : "text-red-400")}>
                {(m.change ?? 0) >= 0 ? "+" : ""}{(m.change ?? 0).toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
