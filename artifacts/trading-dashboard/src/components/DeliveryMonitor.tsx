/**
 * DeliveryMonitor.tsx — Priority 5 (#31): push/email delivery monitoring.
 * At-a-glance queue counts, last delivery/failure, provider latency,
 * device-token status, and filterable recent delivery history.
 * DELIVERED = provider-confirmed delivery or accepted handoff only.
 */

import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  RefreshCw, Loader2, AlertTriangle, Inbox, Send, CheckCircle2,
  Clock, XCircle, Timer, Smartphone,
} from "lucide-react";
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

const STATUSES = ["QUEUED", "SENDING", "DELIVERED", "RETRY_SCHEDULED", "FAILED", "EXPIRED"];

function fmtTs(ts: any): string {
  if (!ts) return "—";
  const d = new Date(ts);
  return isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
}

function sumCounts(counts: Record<string, Record<string, number>> | undefined,
                   status: string): number {
  if (!counts) return 0;
  return Object.values(counts).reduce((acc, c) => acc + (c[status] ?? 0), 0);
}

const selectCls =
  "rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-300";

export default function DeliveryMonitor() {
  const [stats, setStats] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [severity, setSeverity] = useState("");
  const [destination, setDestination] = useState("");
  const [since, setSince] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (channel) params.set("channel", channel);
      if (status) params.set("status", status);
      if (kind) params.set("kind", kind);
      if (severity) params.set("severity", severity);
      if (destination) params.set("destination", destination);
      if (since) params.set("since", since);
      const [sr, dr] = await Promise.all([
        fetch(`${API_BASE}/notifications/deliveries/stats`),
        fetch(`${API_BASE}/notifications/deliveries?${params.toString()}`),
      ]);
      const sd = JSON.parse(await sr.text());
      const dd = JSON.parse(await dr.text());
      if (!sr.ok || sd.error) throw new Error(sd.error ?? `HTTP ${sr.status}`);
      if (!dr.ok || dd.error) throw new Error(dd.error ?? `HTTP ${dr.status}`);
      setStats(sd);
      setRows(dd.deliveries ?? []);
    } catch (e: any) {
      setError(e.message ?? "Failed to load delivery data");
    } finally {
      setLoading(false);
    }
  }, [channel, status, kind, severity, destination, since]);

  useEffect(() => { load(); }, [load]);

  const kinds = Array.from(new Set(rows.map((r) => r.kind))).sort();
  const severities = Array.from(new Set(rows.map((r) => r.severity))).sort();

  const summary = [
    { label: "Queued", value: sumCounts(stats?.counts, "QUEUED"), icon: Inbox, cls: "text-sky-400" },
    { label: "Sending", value: sumCounts(stats?.counts, "SENDING"), icon: Send, cls: "text-indigo-400" },
    { label: "Delivered", value: sumCounts(stats?.counts, "DELIVERED"), icon: CheckCircle2, cls: "text-emerald-400" },
    { label: "Retry scheduled", value: sumCounts(stats?.counts, "RETRY_SCHEDULED"), icon: Clock, cls: "text-amber-400" },
    { label: "Failed", value: sumCounts(stats?.counts, "FAILED"), icon: XCircle, cls: "text-red-400" },
    { label: "Dead-letter", value: stats?.deadLetterCount ?? 0, icon: AlertTriangle, cls: "text-red-500" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-zinc-500">
          Alert delivery queue (push + email). DELIVERED means the provider confirmed
          delivery or accepted handoff — a send attempt alone is never counted as delivered.
        </p>
        <Button size="sm" variant="outline" onClick={load} disabled={loading} className="gap-2 text-xs">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-red-800 bg-red-950/30 p-3 text-xs text-red-300">
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{error}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {summary.map(({ label, value, icon: Icon, cls }) => (
          <Card key={label} className="border-zinc-800 bg-zinc-900/60">
            <CardContent className="flex items-center gap-2.5 p-3">
              <Icon className={cn("h-4 w-4 shrink-0", cls)} />
              <div>
                <div className="text-sm font-bold text-zinc-200">{value}</div>
                <div className="text-[10px] text-zinc-500">{label}</div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Health strip */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardContent className="p-3">
            <div className="mb-1 flex items-center gap-1.5 text-[10px] text-zinc-500">
              <CheckCircle2 className="h-3 w-3 text-emerald-400" />LAST DELIVERY
            </div>
            <div className="text-[11px] text-zinc-300">
              push: {fmtTs(stats?.lastDelivered?.push)}<br />
              email: {fmtTs(stats?.lastDelivered?.email)}
            </div>
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardContent className="p-3">
            <div className="mb-1 flex items-center gap-1.5 text-[10px] text-zinc-500">
              <XCircle className="h-3 w-3 text-red-400" />LAST FAILURE
            </div>
            <div className="text-[11px] text-zinc-300">
              push: {fmtTs(stats?.lastFailed?.push)}<br />
              email: {fmtTs(stats?.lastFailed?.email)}
            </div>
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardContent className="p-3">
            <div className="mb-1 flex items-center gap-1.5 text-[10px] text-zinc-500">
              <Timer className="h-3 w-3 text-sky-400" />PROVIDER LATENCY
            </div>
            <div className="text-[11px] text-zinc-300">
              avg: {stats?.providerLatency?.avgMs != null ? `${stats.providerLatency.avgMs} ms` : "—"}<br />
              max: {stats?.providerLatency?.maxMs != null ? `${stats.providerLatency.maxMs} ms` : "—"}
            </div>
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardContent className="p-3">
            <div className="mb-1 flex items-center gap-1.5 text-[10px] text-zinc-500">
              <Smartphone className="h-3 w-3 text-violet-400" />DEVICE TOKENS
            </div>
            <div className="text-[11px] text-zinc-300">
              enabled: {stats?.deviceTokens?.enabled ?? 0}<br />
              disabled: {stats?.deviceTokens?.disabled ?? 0}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <select value={channel} onChange={(e) => setChannel(e.target.value)} className={selectCls} aria-label="Channel filter">
          <option value="">All channels</option>
          <option value="push">Push</option>
          <option value="email">Email</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={selectCls} aria-label="Status filter">
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)} className={selectCls} aria-label="Alert type filter">
          <option value="">All alert types</option>
          {kinds.map((k) => <option key={k} value={k}>{String(k).replace(/_/g, " ")}</option>)}
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} className={selectCls} aria-label="Severity filter">
          <option value="">All severities</option>
          {severities.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input type="date" value={since} onChange={(e) => setSince(e.target.value)}
          className={selectCls} aria-label="Since date filter" />
        <input type="text" value={destination} onChange={(e) => setDestination(e.target.value)}
          placeholder="Destination / device…" className={cn(selectCls, "w-44")}
          aria-label="Destination filter" />
      </div>

      {/* History */}
      {rows.length === 0 && !loading ? (
        <Card className="border-zinc-800 bg-zinc-900/60">
          <CardContent className="flex flex-col items-center gap-2 py-12 text-zinc-500">
            <Inbox className="h-8 w-8" />
            <div className="text-sm">No delivery records match these filters</div>
          </CardContent>
        </Card>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full text-left text-[11px]">
            <thead className="bg-zinc-900 text-[10px] uppercase text-zinc-500">
              <tr>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Channel</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Severity</th>
                <th className="px-3 py-2">Title</th>
                <th className="px-3 py-2">Destination</th>
                <th className="px-3 py-2">Attempts</th>
                <th className="px-3 py-2">Latency</th>
                <th className="px-3 py-2">Provider ID</th>
                <th className="px-3 py-2">Created</th>
                <th className="px-3 py-2">Delivered / next retry</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/70">
              {rows.map((r) => (
                <tr key={r.id} className="bg-zinc-900/40 hover:bg-zinc-900/70">
                  <td className="px-3 py-2">
                    <Badge variant="outline" className={cn("text-[10px]", STATUS_STYLE[r.status] ?? "")}>
                      {String(r.status).replace(/_/g, " ")}
                    </Badge>
                    {r.deadLetter && (
                      <Badge variant="outline" className="ml-1 text-[9px] text-red-500 border-red-800">DEAD</Badge>
                    )}
                    {r.critical && (
                      <Badge variant="outline" className="ml-1 text-[9px] text-amber-400 border-amber-800">CRIT</Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-zinc-300">{r.channel}</td>
                  <td className="px-3 py-2 text-zinc-300">{String(r.kind).replace(/_/g, " ")}</td>
                  <td className="px-3 py-2 text-zinc-400">{r.severity}</td>
                  <td className="max-w-[240px] truncate px-3 py-2 text-zinc-300" title={r.title}>{r.title}</td>
                  <td className="max-w-[160px] truncate px-3 py-2 text-zinc-500" title={r.destination}>{r.destination}</td>
                  <td className="px-3 py-2 text-zinc-400">{r.attempts}/{r.maxAttempts}</td>
                  <td className="px-3 py-2 text-zinc-400">{r.latencyMs != null ? `${r.latencyMs} ms` : "—"}</td>
                  <td className="max-w-[120px] truncate px-3 py-2 font-mono text-[10px] text-zinc-500"
                    title={r.providerId ?? undefined}>{r.providerId || "—"}</td>
                  <td className="px-3 py-2 text-zinc-500" title={r.createdAt}>{fmtTs(r.createdAt)}</td>
                  <td className="px-3 py-2 text-zinc-500">
                    {r.status === "DELIVERED" ? fmtTs(r.deliveredAt)
                      : r.status === "RETRY_SCHEDULED" ? `retry ${fmtTs(r.nextAttemptAt)}`
                      : r.lastError ? <span className="text-red-400/80" title={r.lastError}>{String(r.lastError).slice(0, 60)}</span>
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
