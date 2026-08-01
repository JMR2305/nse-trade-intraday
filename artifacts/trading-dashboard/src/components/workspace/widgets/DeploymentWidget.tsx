import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Rocket } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function DeploymentWidget({ compact, refreshInterval = 60 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-deployment"],
    queryFn: () => apiJson<any>("command-center/system"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={2} />;
  if (error) return <WidgetError message="Deployment data unavailable" />;

  const d = data ?? {};
  const deploy_status = d.deployment_status ?? d.deploy ?? "UNKNOWN";
  const readiness     = d.deployment_readiness ?? d.readiness_score ?? null;
  const isReady       = deploy_status === "READY" || deploy_status === "OK" || deploy_status === "RUNNING";

  return (
    <div className="flex items-center justify-between px-2 py-2 rounded-lg bg-muted/30">
      <div className="flex items-center gap-2">
        <Rocket className={cn("w-4 h-4", isReady ? "text-blue-400" : "text-amber-500")} />
        <div>
          <p className="text-[9px] text-muted-foreground/50 uppercase">Deployment</p>
          <p className={cn("text-[12px] font-bold", isReady ? "text-blue-400" : "text-amber-500")}>
            {deploy_status}
          </p>
        </div>
      </div>
      {readiness !== null && (
        <div className="text-right">
          <p className="text-[9px] text-muted-foreground/50 uppercase">Readiness</p>
          <p className="text-[12px] font-bold text-foreground/80">{readiness}%</p>
        </div>
      )}
    </div>
  );
}
