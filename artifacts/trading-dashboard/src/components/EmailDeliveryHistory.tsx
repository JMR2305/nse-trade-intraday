/**
 * EmailDeliveryHistory.tsx — Priority 8 (#49): short history of recent email
 * deliveries (not just the last one). Read-only view over the durable
 * alert_deliveries queue, filtered to the email channel. Recipients are
 * masked server-side; message content is limited to the alert title.
 */

import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RefreshCw, Loader2, Inbox, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */

const STATUS_STYLE: Record<string, string> = {
  QUEUED: "text-sky-400 border-sky-800 bg-sky-950/30",
  SENDING: "text-indigo-400 border-indigo-800 bg-indigo-950/30",
  DELIVERED: "text-emerald-400 border-emerald-800 bg-emerald-950/30",
  RETRY_SCHEDULED: "text-amber-400 border-amber-800 bg-amber-950/30",
  FAILED: "text-red-400 border-red-800 bg-red-950/30",
  EXPIRED: "text-zinc-400 border-zinc-700 bg-zinc-900/50",
};

function fmtTs(ts: any): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
}

export default function EmailDeliveryHistory({ limit = 15 }: { limit?: number }) {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/notifications/deliveries?channel=email&limit=${limit}`);
      const d = JSON.parse(await r.text());
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      setRows(d.deliveries ?? []);
    } catch (e: any) {
      setError(e.message ?? "Failed to load email delivery history");
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[11px] text-zinc-500">
          Recent email deliveries (recipient masked; audit trail from the durable alert queue).
        </p>
        <Button size="sm" variant="ghost" onClick={load} disabled={loading}
          className="h-6 gap-1.5 px-2 text-[10px] text-zinc-400">
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-red-800 bg-red-950/30 p-2 text-[11px] text-red-300">
          <AlertTriangle className="mr-1 inline h-3 w-3" />{error}
        </div>
      )}

      {rows.length === 0 && !loading && !error ? (
        <div className="flex items-center gap-2 rounded border border-zinc-800 px-3 py-3 text-[11px] text-zinc-500">
          <Inbox className="h-3.5 w-3.5" />No email deliveries recorded yet
        </div>
      ) : rows.length > 0 ? (
        <div className="overflow-x-auto rounded border border-zinc-800">
          <table className="w-full text-left text-[11px]">
            <thead className="bg-zinc-900 text-[10px] uppercase text-zinc-500">
              <tr>
                <th className="px-2.5 py-1.5">Time</th>
                <th className="px-2.5 py-1.5">Type</th>
                <th className="px-2.5 py-1.5">Recipient</th>
                <th className="px-2.5 py-1.5">Status</th>
                <th className="px-2.5 py-1.5">Message ID</th>
                <th className="px-2.5 py-1.5">Attempts</th>
                <th className="px-2.5 py-1.5">Delivered / failed</th>
                <th className="px-2.5 py-1.5">Error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/70">
              {rows.map((r) => (
                <tr key={r.id} className="bg-zinc-900/40">
                  <td className="whitespace-nowrap px-2.5 py-1.5 text-zinc-500">{fmtTs(r.createdAt)}</td>
                  <td className="px-2.5 py-1.5 text-zinc-300" title={r.title}>
                    {String(r.kind ?? "").replace(/_/g, " ")}
                  </td>
                  <td className="px-2.5 py-1.5 text-zinc-500">{r.destination ?? "—"}</td>
                  <td className="px-2.5 py-1.5">
                    <Badge variant="outline" className={cn("text-[10px]", STATUS_STYLE[r.status] ?? "")}>
                      {String(r.status).replace(/_/g, " ")}
                    </Badge>
                    {r.deadLetter && (
                      <Badge variant="outline" className="ml-1 text-[9px] text-red-500 border-red-800">DEAD</Badge>
                    )}
                  </td>
                  <td className="max-w-[130px] truncate px-2.5 py-1.5 font-mono text-[10px] text-zinc-500"
                    title={r.providerId ?? undefined}>
                    {r.providerId || "—"}
                  </td>
                  <td className="px-2.5 py-1.5 text-zinc-400">{r.attempts}/{r.maxAttempts}</td>
                  <td className="whitespace-nowrap px-2.5 py-1.5 text-zinc-500">
                    {r.status === "DELIVERED" ? fmtTs(r.deliveredAt)
                      : r.status === "FAILED" || r.status === "EXPIRED" ? fmtTs(r.updatedAt)
                      : r.status === "RETRY_SCHEDULED" ? `retry ${fmtTs(r.nextAttemptAt)}`
                      : "—"}
                  </td>
                  <td className="max-w-[180px] truncate px-2.5 py-1.5 text-red-400/80"
                    title={r.lastError ?? undefined}>
                    {r.lastError ? String(r.lastError).slice(0, 80) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
