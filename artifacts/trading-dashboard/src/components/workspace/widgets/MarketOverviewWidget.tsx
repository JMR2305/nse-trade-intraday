import React from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { WidgetSkeleton, WidgetError } from "./WidgetShell";
import { cn } from "@/lib/utils";
import { TrendingUp, TrendingDown } from "lucide-react";

interface Props { compact?: boolean; refreshInterval?: number; }

export default function MarketOverviewWidget({ compact, refreshInterval = 30 }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["widget-market-overview"],
    queryFn: () => apiJson<any>("command-center/system"),
    staleTime: (refreshInterval - 1) * 1000,
    refetchInterval: refreshInterval * 1000,
    retry: 1,
  });

  if (isLoading) return <WidgetSkeleton rows={compact ? 2 : 4} />;
  if (error) return <WidgetError message="Market data unavailable" />;

  const sys = data ?? {};
  const health = sys.overall_health ?? sys.system_health ?? "UNKNOWN";
  const score  = sys.overall_score ?? sys.system_score ?? null;

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <KpiTile label="NIFTY 50" value="—" change={null} />
        <KpiTile label="Bank NIFTY" value="—" change={null} />
      </div>
      {!compact && (
        <div className="grid grid-cols-3 gap-1.5 mt-1">
          <SmallTile label="System" value={health} color={health === "HEALTHY" ? "green" : "amber"} />
          <SmallTile label="Score" value={score !== null ? `${score}%` : "—"} color="blue" />
          <SmallTile label="Session" value="Live" color="green" />
        </div>
      )}
      <p className="text-[10px] text-muted-foreground/40 italic">
        Real-time index data requires live Kite session
      </p>
    </div>
  );
}

function KpiTile({ label, value, change }: { label: string; value: string; change: number | null }) {
  const positive = change !== null && change >= 0;
  return (
    <div className="rounded-lg bg-muted/30 px-2.5 py-2">
      <p className="text-[10px] text-muted-foreground/60 font-medium uppercase tracking-wide">{label}</p>
      <p className="text-base font-bold text-foreground mt-0.5">{value}</p>
      {change !== null && (
        <p className={cn("flex items-center gap-0.5 text-[11px] font-medium mt-0.5", positive ? "text-emerald-500" : "text-red-400")}>
          {positive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
          {Math.abs(change).toFixed(2)}%
        </p>
      )}
    </div>
  );
}

function SmallTile({ label, value, color }: { label: string; value: string; color: "green" | "amber" | "blue" | "red" }) {
  const colors = { green: "text-emerald-500", amber: "text-amber-500", blue: "text-blue-400", red: "text-red-400" };
  return (
    <div className="rounded bg-muted/20 px-2 py-1.5 text-center">
      <p className="text-[9px] text-muted-foreground/50 uppercase">{label}</p>
      <p className={cn("text-[11px] font-bold", colors[color])}>{value}</p>
    </div>
  );
}
