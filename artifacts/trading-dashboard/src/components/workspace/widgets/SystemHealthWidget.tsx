import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Activity } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

const DOT_COLOR: Record<string, string> = {
  HEALTHY: "bg-emerald-500",
  RUNNING: "bg-emerald-500",
  OK:      "bg-emerald-500",
  DEGRADED:"bg-amber-500",
  WARN:    "bg-amber-500",
  DOWN:    "bg-red-500",
  ERROR:   "bg-red-500",
  UNKNOWN: "bg-gray-500",
};

export default function SystemHealthWidget({ compact, refreshInterval = 15 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-system-health"],
    queryFn: () => apiJson<any>("command-center/system"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 5} />;
  if (error) return <WidgetError message="System health unavailable" />;

  const d = data ?? {};
  const overall = d.overall_health ?? d.system_health ?? "UNKNOWN";
  const score   = d.overall_score ?? d.system_score ?? null;

  // Subsystem statuses
  const subsystems = [
    { label: "API Server",  status: d.api_status   ?? d.api    ?? "UNKNOWN" },
    { label: "Database",    status: d.db_status     ?? d.db     ?? "UNKNOWN" },
    { label: "Scheduler",   status: d.sched_status  ?? d.scheduler ?? "UNKNOWN" },
    { label: "Data Feed",   status: d.feed_status   ?? d.feed   ?? "UNKNOWN" },
  ];

  return (
    <div className="space-y-2">
      {/* Overall health */}
      <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-muted/30">
        <div className="flex items-center gap-2">
          <Activity className={cn("w-4 h-4",
            overall === "HEALTHY" ? "text-emerald-500"
            : overall === "DEGRADED" ? "text-amber-500"
            : "text-red-400"
          )} />
          <p className={cn("text-[12px] font-bold",
            overall === "HEALTHY" ? "text-emerald-500"
            : overall === "DEGRADED" ? "text-amber-500"
            : "text-red-400"
          )}>{overall}</p>
        </div>
        {score !== null && (
          <span className="text-[11px] font-semibold text-foreground/60">{score}%</span>
        )}
      </div>

      {/* Subsystems */}
      {!compact && (
        <div className="space-y-1">
          {subsystems.map(({ label, status }) => (
            <div key={label} className="flex items-center justify-between text-[11px] px-2">
              <span className="text-muted-foreground/60">{label}</span>
              <div className="flex items-center gap-1.5">
                <span className={cn(
                  "w-1.5 h-1.5 rounded-full",
                  DOT_COLOR[status] ?? "bg-gray-500"
                )} />
                <span className="text-foreground/70 font-medium">{status}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
