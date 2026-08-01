import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Sparkles } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function AiSummaryWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-ai-summary"],
    queryFn: () => apiJson<any>("command-center/summary"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="AI data unavailable" />;

  const s = data ?? {};
  const confidence = s.ai_confidence ?? s.confidence ?? null;
  const accuracy   = s.ai_accuracy   ?? s.accuracy   ?? null;
  const signals    = s.active_signals ?? s.signal_count ?? null;
  const regime     = s.regime ?? s.market_regime ?? null;

  return (
    <div className="space-y-2">
      {/* Confidence bar */}
      {confidence !== null && (
        <div>
          <div className="flex justify-between text-[10px] mb-1">
            <span className="text-muted-foreground/60 flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-violet-400" />
              AI Confidence
            </span>
            <span className="font-bold text-violet-400">{confidence.toFixed(1)}%</span>
          </div>
          <div className="h-1.5 bg-muted/40 rounded-full overflow-hidden">
            <div className="h-full bg-violet-500 rounded-full transition-all" style={{ width: `${confidence}%` }} />
          </div>
        </div>
      )}

      {!compact && (
        <div className="grid grid-cols-3 gap-1.5">
          <Chip label="Accuracy" value={accuracy !== null ? `${accuracy.toFixed(0)}%` : "—"} />
          <Chip label="Signals" value={signals !== null ? String(signals) : "—"} />
          <Chip label="Regime" value={regime ?? "—"} small />
        </div>
      )}
    </div>
  );
}

function Chip({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
      <p className="text-[9px] text-muted-foreground/50 uppercase">{label}</p>
      <p className={cn("font-bold text-foreground/80", small ? "text-[9px]" : "text-[11px]")}>{value}</p>
    </div>
  );
}
