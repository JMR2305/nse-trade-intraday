import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { GraduationCap, TrendingUp } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function LearningWidget({ compact, refreshInterval = 60 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-learning"],
    queryFn: () => apiJson<any>("command-center/summary"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={2} />;
  if (error) return <WidgetError message="Learning data unavailable" />;

  const d = data ?? {};
  const accuracy     = d.ai_accuracy   ?? d.accuracy   ?? null;
  const improvement  = d.accuracy_trend ?? d.trend     ?? null;
  const learning_on  = d.learning_enabled ?? true;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-muted/30">
        <div className="flex items-center gap-2">
          <GraduationCap className="w-4 h-4 text-violet-400" />
          <span className="text-[12px] font-semibold text-foreground/80">AI Learning</span>
        </div>
        <span className={cn(
          "text-[9px] font-bold px-2 py-0.5 rounded-full",
          learning_on ? "bg-violet-500/20 text-violet-400" : "bg-muted/40 text-muted-foreground/50"
        )}>
          {learning_on ? "ACTIVE" : "PAUSED"}
        </span>
      </div>

      {!compact && (
        <div className="grid grid-cols-2 gap-1.5">
          <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
            <p className="text-[9px] text-muted-foreground/50 uppercase">Accuracy</p>
            <p className="text-[12px] font-bold text-foreground/80">
              {accuracy !== null ? `${accuracy.toFixed(1)}%` : "—"}
            </p>
          </div>
          <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
            <p className="text-[9px] text-muted-foreground/50 uppercase">Trend</p>
            <p className={cn("text-[12px] font-bold flex items-center justify-center gap-0.5",
              improvement > 0 ? "text-emerald-500" : improvement < 0 ? "text-red-400" : "text-muted-foreground/60"
            )}>
              {improvement !== null ? (
                <><TrendingUp className="w-3 h-3" />{improvement > 0 ? "+" : ""}{improvement.toFixed(1)}%</>
              ) : "—"}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
