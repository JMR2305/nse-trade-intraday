import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError, WidgetEmpty } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Clock } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function TradingTimelineWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-timeline"],
    queryFn: () => apiJson<any>("command-center/timeline"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Timeline unavailable" />;

  const events: any[] = data?.events ?? data?.timeline ?? data ?? [];
  if (!events.length) return <WidgetEmpty message="No events today" />;

  const limit = compact ? 3 : 6;
  const sorted = [...events].sort((a: any, b: any) =>
    (b.timestamp ?? b.ts ?? 0) - (a.timestamp ?? a.ts ?? 0)
  );

  return (
    <div className="space-y-1.5">
      {sorted.slice(0, limit).map((ev: any, i: number) => {
        const msg  = ev.message ?? ev.title ?? ev.description ?? `Event ${i}`;
        const time = ev.time ?? ev.timestamp_str ?? "";
        const kind = ev.kind ?? ev.type ?? "INFO";
        const dotColor = kind === "TRADE" ? "bg-blue-500"
          : kind === "SIGNAL" ? "bg-violet-500"
          : kind === "ALERT"  ? "bg-amber-500"
          : "bg-muted-foreground/40";
        return (
          <div key={i} className="flex items-start gap-2 text-[11px]">
            <div className={cn("w-1.5 h-1.5 rounded-full mt-1.5 shrink-0", dotColor)} />
            <div className="flex-1 min-w-0">
              <p className="text-foreground/75 truncate">{msg}</p>
              {time && <p className="text-[9px] text-muted-foreground/40">{time}</p>}
            </div>
          </div>
        );
      })}
      {events.length > limit && (
        <p className="text-[10px] text-muted-foreground/40 text-center">
          +{events.length - limit} more events
        </p>
      )}
    </div>
  );
}
