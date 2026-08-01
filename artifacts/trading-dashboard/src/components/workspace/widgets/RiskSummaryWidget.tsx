import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function RiskSummaryWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-risk"],
    queryFn: () => apiJson<any>("command-center/risk"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Risk data unavailable" />;

  const r = data ?? {};
  const score = r.risk_score ?? r.score ?? null;
  const grade = r.risk_grade ?? r.grade ?? "—";
  const exposure = r.total_exposure_pct ?? r.exposure_pct ?? null;
  const drawdown = r.current_drawdown_pct ?? r.drawdown_pct ?? null;

  const gradeColor = grade === "A" || grade === "A+" ? "text-emerald-500"
    : grade === "B" ? "text-blue-400"
    : grade === "C" ? "text-amber-500"
    : "text-red-400";

  return (
    <div className="space-y-2">
      {/* Grade row */}
      <div className="flex items-center justify-between px-2 py-2 rounded-lg bg-muted/30">
        <div>
          <p className="text-[9px] text-muted-foreground/50 uppercase">Risk Grade</p>
          <p className={cn("text-2xl font-black", gradeColor)}>{grade}</p>
        </div>
        {score !== null && (
          <div className="text-right">
            <p className="text-[9px] text-muted-foreground/50 uppercase">Score</p>
            <p className="text-base font-bold text-foreground">{score}/100</p>
          </div>
        )}
      </div>

      {!compact && (
        <div className="grid grid-cols-2 gap-1.5">
          <MetricTile label="Exposure" value={exposure !== null ? `${exposure.toFixed(1)}%` : "—"} warn={exposure !== null && exposure > 80} />
          <MetricTile label="Drawdown" value={drawdown !== null ? `${drawdown.toFixed(1)}%` : "—"} warn={drawdown !== null && drawdown > 10} />
        </div>
      )}
    </div>
  );
}

function MetricTile({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className={cn("rounded px-2 py-1.5 text-center", warn ? "bg-amber-500/10" : "bg-muted/20")}>
      <p className="text-[9px] text-muted-foreground/50 uppercase">{label}</p>
      <p className={cn("text-[12px] font-bold", warn ? "text-amber-500" : "text-foreground/80")}>{value}</p>
    </div>
  );
}
