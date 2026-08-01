import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Settings2, CheckCircle, XCircle, AlertTriangle } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function OperationsWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-operations"],
    queryFn: () => apiJson<any>("observability/health"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Operations data unavailable" />;

  const d = data ?? {};
  const status      = d.status ?? d.health ?? "UNKNOWN";
  const scheduler   = d.scheduler ?? null;
  const data_quality = d.data_quality ?? null;
  const automations  = d.automation_count ?? null;

  const StatusIcon = status === "HEALTHY" ? CheckCircle
    : status === "DEGRADED" ? AlertTriangle
    : XCircle;
  const statusColor = status === "HEALTHY" ? "text-emerald-500"
    : status === "DEGRADED" ? "text-amber-500"
    : "text-red-400";

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-muted/30">
        <StatusIcon className={cn("w-4 h-4", statusColor)} />
        <div className="flex-1">
          <p className="text-[9px] text-muted-foreground/50 uppercase">Operations</p>
          <p className={cn("text-[12px] font-bold", statusColor)}>{status}</p>
        </div>
        {automations !== null && (
          <span className="text-[10px] text-muted-foreground/50">{automations} tasks</span>
        )}
      </div>

      {!compact && (
        <div className="grid grid-cols-2 gap-1.5">
          {scheduler !== null && (
            <StatusChip label="Scheduler" status={scheduler} />
          )}
          {data_quality !== null && (
            <StatusChip label="Data Quality" status={data_quality} />
          )}
        </div>
      )}
    </div>
  );
}

function StatusChip({ label, status }: { label: string; status: string }) {
  const isOk = status === "RUNNING" || status === "HEALTHY" || status === "OK";
  return (
    <div className="rounded bg-muted/20 px-2 py-1.5">
      <p className="text-[9px] text-muted-foreground/50 uppercase">{label}</p>
      <p className={cn("text-[11px] font-bold", isOk ? "text-emerald-500" : "text-amber-500")}>{status}</p>
    </div>
  );
}
