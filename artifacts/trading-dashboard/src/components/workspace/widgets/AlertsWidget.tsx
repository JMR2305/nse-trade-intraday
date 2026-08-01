import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError, WidgetEmpty } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { AlertTriangle, Info, XCircle, CheckCircle } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

const SEVERITY_META: Record<string, { icon: any; color: string; bg: string }> = {
  CRITICAL: { icon: XCircle,       color: "text-red-400",    bg: "bg-red-500/10" },
  WARNING:  { icon: AlertTriangle, color: "text-amber-400",  bg: "bg-amber-500/10" },
  INFO:     { icon: Info,          color: "text-blue-400",   bg: "bg-blue-500/10" },
  OK:       { icon: CheckCircle,   color: "text-emerald-500",bg: "bg-emerald-500/10" },
};

export default function AlertsWidget({ compact, refreshInterval = 15 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-alerts"],
    queryFn: () => apiJson<any>("command-center/alerts"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Alerts unavailable" />;

  const alerts: any[] = data?.alerts ?? data ?? [];
  const critical = alerts.filter((a: any) => a.severity === "CRITICAL" || a.level === "critical");
  const warnings = alerts.filter((a: any) => a.severity === "WARNING" || a.level === "warning");

  if (!alerts.length) return <WidgetEmpty message="No active alerts" />;

  const sorted = [...critical, ...warnings, ...alerts.filter((a: any) =>
    !critical.includes(a) && !warnings.includes(a)
  )];

  const limit = compact ? 3 : 6;

  return (
    <div className="space-y-1">
      {/* Summary bar */}
      <div className="flex gap-2 text-[10px] px-1 mb-1.5">
        {critical.length > 0 && (
          <span className="flex items-center gap-1 text-red-400 font-semibold">
            <XCircle className="w-3 h-3" />{critical.length} critical
          </span>
        )}
        {warnings.length > 0 && (
          <span className="flex items-center gap-1 text-amber-400 font-semibold">
            <AlertTriangle className="w-3 h-3" />{warnings.length} warnings
          </span>
        )}
      </div>

      {sorted.slice(0, limit).map((alert: any, i: number) => {
        const sev  = alert.severity ?? alert.level?.toUpperCase() ?? "INFO";
        const meta = SEVERITY_META[sev] ?? SEVERITY_META.INFO;
        const Icon = meta.icon;
        const msg  = alert.message ?? alert.title ?? alert.description ?? "Alert";
        return (
          <div key={i} className={cn("flex items-start gap-2 px-2 py-1.5 rounded text-[11px]", meta.bg)}>
            <Icon className={cn("w-3 h-3 mt-0.5 shrink-0", meta.color)} />
            <span className="text-foreground/75 truncate">{msg}</span>
          </div>
        );
      })}

      {alerts.length > limit && (
        <p className="text-[10px] text-muted-foreground/40 text-center pt-0.5">
          +{alerts.length - limit} more alerts
        </p>
      )}
    </div>
  );
}
