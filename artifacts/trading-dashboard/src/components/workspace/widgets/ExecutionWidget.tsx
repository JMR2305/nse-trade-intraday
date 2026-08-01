import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Zap } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function ExecutionWidget({ compact, refreshInterval = 15 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-execution"],
    queryFn: () => apiJson<any>("command-center/system"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={2} />;
  if (error) return <WidgetError message="Execution data unavailable" />;

  const d = data ?? {};
  const broker_status = d.broker_status ?? d.broker ?? "UNKNOWN";
  const connected     = broker_status === "CONNECTED" || broker_status === "OK";
  const latency       = d.broker_latency_ms ?? d.latency_ms ?? null;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2 py-2 rounded-lg bg-muted/30">
        <div className="flex items-center gap-2">
          <span className={cn(
            "w-2 h-2 rounded-full",
            connected ? "bg-emerald-500 shadow-[0_0_6px_#10b981]" : "bg-red-500"
          )} />
          <div>
            <p className="text-[9px] text-muted-foreground/50 uppercase">Broker</p>
            <p className={cn("text-[12px] font-bold", connected ? "text-emerald-500" : "text-red-400")}>
              {connected ? "Connected" : broker_status}
            </p>
          </div>
        </div>
        {latency !== null && (
          <div className="text-right">
            <p className="text-[9px] text-muted-foreground/50 uppercase">Latency</p>
            <p className="text-[12px] font-semibold text-foreground/70">{latency}ms</p>
          </div>
        )}
      </div>
    </div>
  );
}
