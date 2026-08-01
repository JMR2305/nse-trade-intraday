import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Sparkles, Bot } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function AiDailyBriefingWidget({ compact, refreshInterval = 120 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-briefing"],
    queryFn: () => apiJson<any>("command-center/summary"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 3 : 6} />;
  if (error) return <WidgetError message="AI briefing unavailable" />;

  const s = data ?? {};
  const briefing   = s.daily_briefing ?? s.briefing ?? s.summary ?? null;
  const regime     = s.regime ?? s.market_regime ?? null;
  const confidence = s.ai_confidence ?? s.confidence ?? null;
  const recs: any[] = s.recommendations ?? s.top_recommendations ?? [];

  return (
    <div className="space-y-3">
      {/* Header row */}
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded-full bg-violet-500/20 flex items-center justify-center">
          <Bot className="w-3.5 h-3.5 text-violet-400" />
        </div>
        <div>
          <p className="text-[11px] font-semibold text-foreground/80">AI Daily Briefing</p>
          {regime && (
            <p className="text-[9px] text-muted-foreground/50">Regime: {regime}</p>
          )}
        </div>
        {confidence !== null && (
          <span className="ml-auto text-[10px] font-bold text-violet-400 bg-violet-500/10 px-2 py-0.5 rounded-full">
            {confidence.toFixed(0)}% conf
          </span>
        )}
      </div>

      {/* Briefing text */}
      {briefing && (
        <div className="px-3 py-2 rounded-lg bg-muted/30 border border-border/30">
          <p className="text-[11px] text-foreground/70 leading-relaxed line-clamp-4">{briefing}</p>
        </div>
      )}

      {/* Recommendations */}
      {!compact && recs.length > 0 && (
        <div className="space-y-1">
          <p className="text-[9px] text-muted-foreground/40 uppercase px-1 flex items-center gap-1">
            <Sparkles className="w-2.5 h-2.5" />
            Recommendations
          </p>
          {recs.slice(0, 3).map((rec: any, i: number) => {
            const text = typeof rec === "string" ? rec : rec.message ?? rec.recommendation ?? String(rec);
            return (
              <div key={i} className="flex items-start gap-2 text-[11px] px-2 py-1 rounded bg-violet-500/5">
                <span className="text-violet-400/60 mt-0.5">•</span>
                <span className="text-foreground/65 leading-relaxed">{text}</span>
              </div>
            );
          })}
        </div>
      )}

      {!briefing && recs.length === 0 && (
        <p className="text-[11px] text-muted-foreground/40 italic">
          AI briefing will be available after the morning scan completes.
        </p>
      )}
    </div>
  );
}
