import { useState } from "react";
import { useIncidentsHistory, useIncidentDetail } from "@/hooks/use-market-data-incidents";
import { Badge } from "@/components/ui/badge";
import { ShieldAlert, ShieldCheck, Filter, ChevronRight, XCircle, ActivitySquare, AlertTriangle, AlertCircle, Database } from "lucide-react";

function formatIst(value: string | null | undefined, includeDate = true): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    dateStyle: includeDate ? "medium" : undefined,
    timeStyle: "short",
  });
}

function formatDuration(durationS: number | null | undefined, recovered: boolean): string {
  if (durationS == null) return recovered ? "—" : "Ongoing";
  return `${Math.floor(durationS / 60)}m ${Math.round(durationS % 60)}s`;
}

function IncidentDetailView({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, isLoading, isError } = useIncidentDetail(id);
  const incident = data?.incident;

  if (isLoading) {
    return (
      <div className="p-6 bg-card border-l border-border h-full flex flex-col items-center justify-center animate-pulse">
        <ActivitySquare className="w-8 h-8 text-muted-foreground/30 mb-4 animate-spin-slow" />
        <p className="text-sm text-muted-foreground">Loading incident details...</p>
      </div>
    );
  }

  if (isError || !incident) {
    return (
      <div className="p-6 bg-card border-l border-border h-full flex flex-col items-center justify-center">
        <AlertTriangle className="w-8 h-8 text-red-400 mb-4" />
        <p className="text-sm text-red-400">Failed to load incident details.</p>
        <button onClick={onClose} className="mt-4 text-xs text-muted-foreground hover:text-foreground">Close</button>
      </div>
    );
  }

  const isActive = incident.status === 'ACTIVE';

  return (
    <div className="bg-card border-l border-border h-full flex flex-col overflow-y-auto">
      <div className="p-4 border-b border-border flex items-center justify-between sticky top-0 bg-card/95 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className={`text-xs px-2.5 py-0.5 font-semibold tracking-wider ${isActive ? 'border-red-500/40 text-red-400 bg-red-950/20 animate-pulse' : 'border-emerald-500/40 text-emerald-400 bg-emerald-950/20'}`}>
            {incident.status}
          </Badge>
          <span className="text-xs text-muted-foreground font-mono">ID: {incident.id.split('-')[0]}</span>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted/50 transition-colors">
          <XCircle className="w-5 h-5" />
        </button>
      </div>

      <div className="p-6 space-y-8">
        <div className="space-y-2">
          <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            {isActive ? <ShieldAlert className="w-6 h-6 text-red-400" /> : <ShieldCheck className="w-6 h-6 text-emerald-400" />}
            {incident.severity} Fallback Incident
          </h2>
          <div className="grid grid-cols-2 gap-4 pt-4">
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Started</p>
              <p className="text-sm font-medium">{formatIst(incident.started_at)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Recovered</p>
              <p className="text-sm font-medium">{formatIst(incident.recovered_at)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Duration</p>
              <p className="text-sm font-medium">{formatDuration(incident.duration_s, !isActive)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Detection Count</p>
              <p className="text-sm font-medium">{incident.detection_count}</p>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <h3 className="text-sm font-medium uppercase tracking-wider text-muted-foreground border-b border-border/50 pb-2">Authority Impact</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className={`p-4 rounded-xl border ${isActive ? 'bg-red-950/10 border-red-900/30' : 'bg-muted/20 border-border/50'}`}>
              <p className="text-xs text-muted-foreground mb-1">Current Quote Provider</p>
              <p className={`text-base font-semibold ${isActive ? 'text-red-100' : 'text-foreground'}`}>{incident.current_quote_provider}</p>
              <p className="text-xs mt-1 text-muted-foreground">{incident.current_quote_freshness}</p>
            </div>
            <div className="p-4 rounded-xl bg-muted/20 border border-border/50">
              <p className="text-xs text-muted-foreground mb-1">Affected Symbols</p>
              <p className="text-base font-semibold text-amber-400">{incident.symbols_fallback} / {incident.active_universe_count}</p>
              <p className="text-xs mt-1 text-muted-foreground">relying on fallback pricing</p>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <h3 className="text-sm font-medium uppercase tracking-wider text-muted-foreground border-b border-border/50 pb-2">Symbol Distribution</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
            <div className="p-3 bg-muted/20 rounded-lg border border-border/40">
              <p className="text-[10px] text-muted-foreground uppercase mb-1">Kite</p>
              <p className="text-lg font-mono text-emerald-400">{incident.symbols_on_kite}</p>
            </div>
            <div className="p-3 bg-muted/20 rounded-lg border border-border/40">
              <p className="text-[10px] text-muted-foreground uppercase mb-1">Fallback</p>
              <p className="text-lg font-mono text-amber-400">{incident.symbols_fallback}</p>
            </div>
            <div className="p-3 bg-muted/20 rounded-lg border border-border/40">
              <p className="text-[10px] text-muted-foreground uppercase mb-1">Stale</p>
              <p className="text-lg font-mono text-orange-400">{incident.symbols_stale}</p>
            </div>
            <div className="p-3 bg-muted/20 rounded-lg border border-border/40">
              <p className="text-[10px] text-muted-foreground uppercase mb-1">Unavailable</p>
              <p className="text-lg font-mono text-red-400">{incident.symbols_unavailable}</p>
            </div>
          </div>
        </div>

        {incident.recovery_summary && (
          <div className="space-y-4">
            <h3 className="text-sm font-medium uppercase tracking-wider text-muted-foreground border-b border-border/50 pb-2">Recovery Summary</h3>
            <div className="p-4 bg-emerald-950/10 border border-emerald-900/30 rounded-xl">
              <p className="text-sm text-emerald-100/80 leading-relaxed">{incident.recovery_summary}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function MarketDataIncidents() {
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useIncidentsHistory(statusFilter, severityFilter);

  const incidents = data?.incidents || [];
  const total = data?.total || 0;

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      {/* Main List Area */}
      <div className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${selectedIncidentId ? 'lg:w-2/3 lg:flex-none' : 'w-full'}`}>
        <div className="p-6 border-b border-border flex items-center justify-between sticky top-0 bg-background/95 backdrop-blur z-10 shrink-0">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground flex items-center gap-2">
              Authority Incidents
              <Badge variant="secondary" className="ml-2 bg-muted/50 font-mono text-xs">{total}</Badge>
            </h1>
            <p className="text-sm text-muted-foreground mt-1">Read-only history of Kite fallback events and degraded market data authority.</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 bg-muted/20 border border-border/50 rounded-lg p-1">
              <Filter className="w-4 h-4 text-muted-foreground ml-2" />
              <select 
                value={statusFilter} 
                onChange={(e) => setStatusFilter(e.target.value)}
                className="bg-transparent text-sm text-foreground focus:outline-none border-none py-1.5 px-2 pr-6 appearance-none cursor-pointer"
              >
                <option value="ALL">All Statuses</option>
                <option value="ACTIVE">Active</option>
                <option value="RECOVERED">Recovered</option>
              </select>
              <div className="w-px h-4 bg-border/50 mx-1" />
              <select 
                value={severityFilter} 
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="bg-transparent text-sm text-foreground focus:outline-none border-none py-1.5 px-2 pr-6 appearance-none cursor-pointer"
              >
                <option value="ALL">All Severities</option>
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="WARNING">Warning</option>
              </select>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="h-20 bg-muted/20 rounded-xl border border-border/40 animate-pulse skeleton" />
              ))}
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <AlertCircle className="w-12 h-12 text-red-400 mb-4" />
              <p className="text-lg font-medium text-red-400">Failed to load incidents</p>
              <p className="text-sm text-red-400/70 mt-1">{(error as Error)?.message || "An unknown error occurred."}</p>
            </div>
          ) : data?.storage_available === false ? (
            <div className="flex flex-col items-center justify-center py-20 text-center" data-testid="market-data-incidents-storage-unavailable">
              <Database className="w-12 h-12 text-amber-400 mb-4" />
              <p className="text-lg font-medium text-amber-400">Incident history is unavailable</p>
              <p className="text-sm text-muted-foreground mt-1">Durable incident storage has not been configured, so a healthy history cannot be claimed.</p>
            </div>
          ) : incidents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <ShieldCheck className="w-16 h-16 text-emerald-400/20 mb-4" />
              <p className="text-lg font-medium text-foreground">No incident records found</p>
              <p className="text-sm text-muted-foreground mt-1">
                {statusFilter !== "ALL" || severityFilter !== "ALL"
                  ? "Try adjusting your filters."
                  : "Absence of records is not proof of current authority health; check Mission Control for the latest evidence."}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {incidents.map((incident) => {
                const isActive = incident.status === 'ACTIVE';
                const isSelected = selectedIncidentId === incident.id;
                return (
                  <div 
                    key={incident.id}
                    onClick={() => setSelectedIncidentId(incident.id)}
                    className={`flex items-center gap-4 p-4 rounded-xl border cursor-pointer transition-all ${
                      isSelected 
                        ? 'bg-muted/40 border-primary/40 shadow-sm' 
                        : 'bg-card border-border/60 hover:border-primary/30 hover:bg-muted/10'
                    }`}
                  >
                    <div className="shrink-0 flex items-center justify-center w-10 h-10 rounded-full bg-muted/40 border border-border/50">
                      {isActive ? <ShieldAlert className="w-5 h-5 text-red-400 animate-pulse" /> : <ShieldCheck className="w-5 h-5 text-emerald-400" />}
                    </div>
                    
                    <div className="flex-1 min-w-0 grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
                      <div className="col-span-1 md:col-span-2">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-semibold text-sm truncate">{incident.severity} Fallback Incident</span>
                          {isActive && (
                            <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-red-500/40 text-red-400 bg-red-950/20 uppercase">
                              Active
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground truncate">
                          Provider: <span className="text-foreground/80">{incident.current_quote_provider}</span>
                        </p>
                      </div>

                      <div className="hidden md:block col-span-1">
                        <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Impact</p>
                        <p className="text-sm font-medium font-mono text-amber-400">
                          {incident.symbols_fallback} <span className="text-xs text-muted-foreground font-sans">symbols</span>
                        </p>
                      </div>

                      <div className="hidden md:block col-span-1 text-right">
                        <p className="text-xs text-muted-foreground mb-1 uppercase tracking-wider">Started</p>
                        <p className="text-sm font-medium">
                          {formatIst(incident.started_at, false)}
                        </p>
                        <p className="text-[10px] text-muted-foreground">IST</p>
                      </div>
                    </div>
                    
                    <div className="shrink-0 ml-2">
                      <ChevronRight className={`w-5 h-5 transition-transform ${isSelected ? 'text-primary translate-x-1' : 'text-muted-foreground'}`} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Slide-out Detail Area */}
      {selectedIncidentId && (
        <div className="hidden lg:block w-1/3 shrink-0 border-l border-border h-full shadow-2xl z-20 animate-in slide-in-from-right-8 fade-in">
          <IncidentDetailView id={selectedIncidentId} onClose={() => setSelectedIncidentId(null)} />
        </div>
      )}
      
      {/* Mobile Detail Overlay */}
      {selectedIncidentId && (
        <div className="lg:hidden fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-lg h-[85vh] rounded-t-2xl sm:rounded-2xl shadow-2xl overflow-hidden animate-in slide-in-from-bottom-8">
            <IncidentDetailView id={selectedIncidentId} onClose={() => setSelectedIncidentId(null)} />
          </div>
        </div>
      )}
    </div>
  );
}
