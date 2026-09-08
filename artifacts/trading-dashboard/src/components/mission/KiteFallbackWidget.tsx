import { useWidgetQuery } from "./Widget";
import { Widget } from "./Widget";
import { Badge } from "@/components/ui/badge";
import { ShieldAlert, ShieldCheck, ArrowRight, Clock, Database, WifiOff, CircleHelp } from "lucide-react";
import { Link } from "wouter";
import type { ActiveIncidentResponse } from "@/hooks/use-market-data-incidents";

export function KiteFallbackWidget() {
  const query = useWidgetQuery<ActiveIncidentResponse>({
    queryKey: ["mc", "kite-fallback-active"],
    path: "market-data/incidents/active",
    refetchInterval: 15_000,
    timeoutMs: 10_000,
  });

  const incident = query.data?.incident;
  const isActive = incident && incident.status === 'ACTIVE';
  const storageUnavailable = query.data?.storage_available === false;
  const authorityVerified = query.data?.authority_state === "VERIFIED_HEALTHY";

  return (
    <Widget
      title="Data Authority"
      icon={isActive ? ShieldAlert : ShieldCheck}
      query={query}
      refreshMs={15_000}
      testId="mc-kite-fallback"
      skeletonClass="h-40"
      headerExtra={
        <Link href="/market-data-incidents" className="text-[10px] text-muted-foreground hover:text-foreground flex items-center gap-1 ml-2 transition-colors">
          History <ArrowRight className="w-3 h-3" />
        </Link>
      }
    >
      {storageUnavailable ? (
        <div className="flex flex-col items-center justify-center py-4 gap-2 text-center h-full" data-testid="mc-kite-fallback-storage-unavailable">
          <div className="w-10 h-10 rounded-full bg-amber-950/30 flex items-center justify-center border border-amber-900/50 mb-1">
            <WifiOff className="w-5 h-5 text-amber-400" />
          </div>
          <p className="text-[12px] font-medium text-amber-400">Incident History Unavailable</p>
          <p className="text-[10px] text-muted-foreground max-w-[200px] leading-tight">
            Durable authority incident storage is not available, so current history cannot be proven.
          </p>
        </div>
      ) : isActive ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px] px-2 py-0.5 border-red-500/40 text-red-400 bg-red-950/20 font-semibold uppercase tracking-wider animate-pulse">
              {incident.severity} INCIDENT
            </Badge>
            <span className="text-[10px] text-red-400/80 font-mono tracking-tight">KITE FALLBACK ACTIVE</span>
          </div>
          
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="rounded-lg bg-red-950/10 border border-red-900/30 p-2">
              <p className="text-red-400/70 text-[10px] uppercase tracking-wider mb-1 flex items-center gap-1">
                <Database className="w-3 h-3" /> Authority
              </p>
              <p className="font-semibold text-red-100 truncate">{incident.current_quote_provider}</p>
              <p className="text-red-400/70 text-[9px] mt-0.5 truncate">{incident.current_quote_freshness}</p>
            </div>
            <div className="rounded-lg bg-red-950/10 border border-red-900/30 p-2">
              <p className="text-red-400/70 text-[10px] uppercase tracking-wider mb-1 flex items-center gap-1">
                <Clock className="w-3 h-3" /> Duration
              </p>
              <p className="font-semibold text-red-100">{incident.duration_s ? `${Math.floor(incident.duration_s / 60)}m ${incident.duration_s % 60}s` : 'Just started'}</p>
              <p className="text-red-400/70 text-[9px] mt-0.5 truncate">Since {new Date(incident.started_at).toLocaleTimeString()}</p>
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[10px]">
              <span className="text-muted-foreground">Kite Coverage</span>
              <span className="font-medium text-red-400">{incident.symbols_on_kite} / {incident.active_universe_count}</span>
            </div>
            <div className="h-1.5 w-full bg-red-950/40 rounded-full overflow-hidden flex">
              <div 
                className="h-full bg-emerald-500/50" 
                style={{ width: `${incident.active_universe_count > 0 ? Math.max(0, Math.min(100, (incident.symbols_on_kite / incident.active_universe_count) * 100)) : 0}%` }}
              />
              <div 
                className="h-full bg-amber-500/50" 
                style={{ width: `${incident.active_universe_count > 0 ? Math.max(0, Math.min(100, (incident.symbols_fallback / incident.active_universe_count) * 100)) : 0}%` }}
              />
            </div>
            <p className="text-[9px] text-red-400/60 text-right">
              {incident.symbols_fallback} symbols on fallback
            </p>
          </div>
        </div>
      ) : authorityVerified ? (
        <div className="flex flex-col items-center justify-center py-4 gap-2 text-center h-full">
          <div className="w-10 h-10 rounded-full bg-emerald-950/30 flex items-center justify-center border border-emerald-900/50 mb-1">
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
          </div>
          <p className="text-[12px] font-medium text-emerald-400">Primary Authority Healthy</p>
          <p className="text-[10px] text-muted-foreground max-w-[200px] leading-tight">
            Kite Connect is providing live quotes for all active universe symbols.
          </p>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-4 gap-2 text-center h-full" data-testid="mc-kite-fallback-awaiting-evidence">
          <div className="w-10 h-10 rounded-full bg-amber-950/30 flex items-center justify-center border border-amber-900/50 mb-1">
            <CircleHelp className="w-5 h-5 text-amber-400" />
          </div>
          <p className="text-[12px] font-medium text-amber-400">Awaiting Authority Evidence</p>
          <p className="text-[10px] text-muted-foreground max-w-[220px] leading-tight">
            No active incident is recorded, but a fresh complete Kite authority observation has not yet been proven.
          </p>
        </div>
      )}
    </Widget>
  );
}
