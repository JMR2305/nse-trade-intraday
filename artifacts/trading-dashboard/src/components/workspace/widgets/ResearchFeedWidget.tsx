import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError, WidgetEmpty } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { FlaskConical } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function ResearchFeedWidget({ compact, refreshInterval = 60 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-research-feed"],
    queryFn: () => apiJson<any>("research-lab/hypotheses"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Research feed unavailable" />;

  const hypotheses: any[] = data?.hypotheses ?? data?.results ?? data ?? [];
  if (!hypotheses.length) return <WidgetEmpty message="No active hypotheses" />;

  const limit = compact ? 2 : 4;

  return (
    <div className="space-y-1.5">
      {hypotheses.slice(0, limit).map((h: any, i: number) => {
        const name       = h.name ?? h.title ?? h.hypothesis ?? `Hypothesis ${i + 1}`;
        const status     = h.status ?? h.state ?? "ACTIVE";
        const confidence = h.confidence ?? null;
        const statusColor = status === "VALIDATED" ? "text-emerald-500"
          : status === "REJECTED" ? "text-red-400"
          : "text-blue-400";
        return (
          <div key={i} className="px-2 py-1.5 rounded bg-muted/20 hover:bg-muted/30 transition-colors">
            <div className="flex items-center justify-between gap-1">
              <span className="text-[11px] font-medium text-foreground/80 truncate">{name}</span>
              <span className={cn("text-[9px] font-bold shrink-0", statusColor)}>{status}</span>
            </div>
            {confidence !== null && !compact && (
              <div className="mt-1 h-1 bg-muted/40 rounded-full overflow-hidden">
                <div className="h-full bg-blue-500/60 rounded-full" style={{ width: `${confidence}%` }} />
              </div>
            )}
          </div>
        );
      })}
      {hypotheses.length > limit && (
        <p className="text-[10px] text-muted-foreground/40 text-center">
          +{hypotheses.length - limit} more hypotheses
        </p>
      )}
    </div>
  );
}
