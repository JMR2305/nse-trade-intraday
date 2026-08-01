import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { Lock, ShieldCheck } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function SecurityWidget({ compact, refreshInterval = 60 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-security"],
    queryFn: () => apiJson<any>("command-center/system"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={2} />;
  if (error) return <WidgetError message="Security data unavailable" />;

  const d = data ?? {};
  const sec_status = d.security_status ?? d.security ?? "UNKNOWN";
  const sec_score  = d.security_score ?? null;

  const isOk = sec_status === "SECURE" || sec_status === "OK" || sec_status === "HEALTHY";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2 py-2 rounded-lg bg-muted/30">
        <div className="flex items-center gap-2">
          {isOk ? (
            <ShieldCheck className="w-4 h-4 text-emerald-500" />
          ) : (
            <Lock className="w-4 h-4 text-amber-500" />
          )}
          <div>
            <p className="text-[9px] text-muted-foreground/50 uppercase">Security</p>
            <p className={cn("text-[12px] font-bold", isOk ? "text-emerald-500" : "text-amber-500")}>
              {sec_status}
            </p>
          </div>
        </div>
        {sec_score !== null && (
          <div className="text-right">
            <p className="text-[9px] text-muted-foreground/50 uppercase">Score</p>
            <p className="text-[12px] font-bold text-foreground/80">{sec_score}/100</p>
          </div>
        )}
      </div>
    </div>
  );
}
