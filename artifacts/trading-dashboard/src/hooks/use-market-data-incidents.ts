import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";

export interface FallbackIncident {
  id: string;
  status: 'ACTIVE' | 'RECOVERED';
  severity: string;
  started_at: string;
  last_detected_at: string;
  recovered_at?: string | null;
  latest_scan_id?: string | null;
  active_universe_count: number;
  symbols_on_kite: number;
  symbols_fallback: number;
  symbols_stale: number;
  symbols_unavailable: number;
  symbols_synthetic: number;
  current_quote_provider: string;
  current_quote_freshness: string;
  detection_count: number;
  duration_s?: number | null;
  recovery_summary?: string | null;
  read_only: true;
}

export interface IncidentCollection {
  incidents: FallbackIncident[];
  total: number;
  storage_available?: boolean;
  read_only?: boolean;
}

export interface ActiveIncidentResponse {
  incident: FallbackIncident | null;
  storage_available?: boolean;
  authority_state?: "VERIFIED_HEALTHY" | "AWAITING_DURABLE_INCIDENT_EVIDENCE";
  read_only?: boolean;
}

export function useActiveIncident(opts?: { refetchInterval?: number }) {
  return useQuery<ActiveIncidentResponse>({
    queryKey: ["market-data", "incidents", "active"],
    queryFn: () => apiJson("market-data/incidents/active"),
    refetchInterval: opts?.refetchInterval ?? 30000,
  });
}

export function useIncidentsHistory(status?: string, severity?: string) {
  const queryParams = new URLSearchParams();
  if (status && status !== "ALL") queryParams.append("status", status);
  if (severity && severity !== "ALL") queryParams.append("severity", severity);
  queryParams.append("limit", "50");

  const queryStr = queryParams.toString();
  const path = queryStr ? `market-data/incidents?${queryStr}` : `market-data/incidents`;

  return useQuery<IncidentCollection>({
    queryKey: ["market-data", "incidents", "history", status, severity],
    queryFn: () => apiJson(path),
    refetchInterval: 60000,
  });
}

export function useIncidentDetail(id: string) {
  return useQuery<{ incident: FallbackIncident | null }>({
    queryKey: ["market-data", "incidents", "detail", id],
    queryFn: () => apiJson(`market-data/incidents/${id}`),
    enabled: !!id,
    refetchInterval: 30000,
  });
}
