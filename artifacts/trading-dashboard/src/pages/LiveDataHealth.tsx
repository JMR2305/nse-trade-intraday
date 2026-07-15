/**
 * LiveDataHealth.tsx — Phase 7: Live Market Intelligence
 * Dedicated panel showing data-provider health, symbol coverage, scan audit,
 * gate results, paper-execution eligibility, and Phase 7 validation report.
 *
 * PAPER / LIVE DATA VALIDATION — strictly research only.
 * No real broker orders are placed by this system.
 */
import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2, RefreshCw, Download, ShieldCheck, AlertTriangle, CheckCircle2,
  XCircle, Wifi, WifiOff, Activity, Clock, Database, FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { useLiveStream } from "@/hooks/useLiveStream";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "PAPER / LIVE DATA VALIDATION";

async function safeJson(path: string, init?: RequestInit): Promise<any> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  if (!text.trim()) throw new Error(`Empty response from ${path} (HTTP ${resp.status})`);
  let data: any;
  try { data = JSON.parse(text); } catch { throw new Error(`Invalid JSON from ${path}`); }
  if (!resp.ok) throw new Error(String(data?.error ?? `HTTP ${resp.status}`));
  return data;
}

function na(v: any, suffix = "") {
  if (v === null || v === undefined || v === "") return "N/A";
  if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "N/A";
  if (typeof v === "number") return `${+v.toFixed(2)}${suffix}`;
  return String(v);
}

const QUALITY_CLS: Record<string, string> = {
  LIVE: "text-emerald-400 border-emerald-700",
  NEAR_LIVE: "text-sky-400 border-sky-700",
  STALE: "text-amber-400 border-amber-700",
  UNAVAILABLE: "text-red-400 border-red-700",
};

const CONN_CLS: Record<string, string> = {
  CONNECTED: "text-emerald-400",
  DEGRADED: "text-amber-400",
  ERROR: "text-red-400",
  NOT_TESTED: "text-zinc-500",
};

const VERDICT_CLS: Record<string, string> = {
  PASS: "text-emerald-400 border-emerald-700",
  PARTIAL: "text-amber-400 border-amber-700",
  FAIL: "text-red-400 border-red-700",
};

function ConnIcon({ status }: { status: string }) {
  if (status === "CONNECTED") return <Wifi className="h-4 w-4 text-emerald-400" />;
  if (status === "DEGRADED") return <Activity className="h-4 w-4 text-amber-400" />;
  return <WifiOff className="h-4 w-4 text-red-400" />;
}

function GateRow({ label, passed, reason }: { label: string; passed: boolean; reason?: string }) {
  return (
    <div className="flex items-start gap-1.5 text-[10px] font-mono">
      {passed
        ? <CheckCircle2 className="h-3 w-3 text-emerald-400 mt-0.5 shrink-0" />
        : <XCircle className="h-3 w-3 text-red-400 mt-0.5 shrink-0" />}
      <span className={passed ? "text-zinc-300" : "text-red-300"}>{label}</span>
      {reason && <span className="text-zinc-500">— {reason}</span>}
    </div>
  );
}

export default function LiveDataHealth() {
  const { toast } = useToast();
  const [health, setHealth] = useState<any>(null);
  const [scan, setScan] = useState<any>(null);
  const [healthV2, setHealthV2] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const stream = useLiveStream();

  const load = useCallback(async () => {
    setLoading(true);
    const errs: string[] = [];
    try { setHealth(await safeJson("/live-data/health")); }
    catch (e) { errs.push(`Health: ${e instanceof Error ? e.message : String(e)}`); }
    try { setScan(await safeJson("/live-data/scan")); }
    catch (e) { errs.push(`Scan: ${e instanceof Error ? e.message : String(e)}`); }
    try { setHealthV2(await safeJson("/live-data/health-v2")); }
    catch (e) { errs.push(`Live health: ${e instanceof Error ? e.message : String(e)}`); }
    setErrors(errs);
    setLoading(false);
  }, []);

  async function forceReconnect() {
    setReconnecting(true);
    try {
      const r = await safeJson("/stream/reconnect", { method: "POST" });
      toast({ title: "Live data refreshed", description: r?.last_error ? `Last error: ${r.last_error}` : `Last refresh: ${r?.last_refresh ?? "N/A"}` });
      void load();
    } catch (e) {
      toast({ title: "Reconnect failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally { setReconnecting(false); }
  }

  async function downloadBundle(kind: "json" | "csv") {
    setExporting(true);
    try {
      const resp = await fetch(`${API_BASE}/live-data/diagnostic-bundle/download?file=${kind}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      if (blob.size === 0) throw new Error("Empty bundle file");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = kind === "json" ? "phase11_diagnostic_bundle.json" : "phase11_summary.csv";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: `Diagnostic ${kind.toUpperCase()} downloaded` });
    } catch (e) {
      toast({ title: "Bundle download failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally { setExporting(false); }
  }

  useEffect(() => { void load(); }, [load]);

  async function runScan() {
    setRunning(true);
    try {
      const r = await safeJson("/live-data/scan/run", { method: "POST" });
      setScan(r);
      toast({ title: "Fresh scan complete", description: `Scan ID: ${r?.scan_id}` });
    } catch (e) {
      toast({ title: "Scan failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally { setRunning(false); void load(); }
  }

  async function downloadReport(kind: "json" | "csv" | "html") {
    setExporting(true);
    try {
      const resp = await fetch(`${API_BASE}/live-data/report?file=${kind}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      if (blob.size === 0) throw new Error("Empty report file");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `phase7_report.${kind}`;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast({ title: `Phase 7 ${kind.toUpperCase()} downloaded` });
    } catch (e) {
      toast({ title: "Download failed", description: String(e instanceof Error ? e.message : e), variant: "destructive" });
    } finally { setExporting(false); }
  }

  const ph = health?.provider_health ?? scan?.provider_health ?? {};
  const audit = health?.scan_audit ?? scan?.scan_audit ?? {};
  const summary = health?.summary ?? scan?.summary ?? {};
  const recs: any[] = scan?.recommendations ?? [];
  const cacheAge = scan?._cache_age_s;

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-500 py-6">
        <Loader2 className="h-4 w-4 animate-spin" />Loading live data health…
      </div>
    );
  }

  return (
    <div className="space-y-3 max-w-6xl">
      {/* Header */}
      <div className="flex items-center gap-2 flex-wrap">
        <Activity className="h-4 w-4 text-sky-400" />
        <h1 className="text-sm font-mono font-bold text-zinc-100">Live Data Health</h1>
        <Badge variant="outline" className="text-[9px] font-mono text-amber-400 border-amber-700 px-1.5">{LABEL}</Badge>
        {scan?.scan_id && (
          <span className="text-[10px] font-mono text-zinc-500">
            Scan ID: {scan.scan_id} · {scan.snapshot_ts}
            {cacheAge !== undefined && ` · cache age ${cacheAge}s`}
          </span>
        )}
        <div className="ml-auto flex gap-1.5 flex-wrap">
          <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px]" onClick={() => void load()} disabled={loading || running}>
            <RefreshCw className="h-3 w-3 mr-1" />Refresh
          </Button>
          <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px] text-sky-300 border-sky-700" onClick={() => void runScan()} disabled={running}>
            {running ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Activity className="h-3 w-3 mr-1" />}
            Run Fresh Scan
          </Button>
          {(["json", "csv"] as const).map(k => (
            <Button key={k} size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px]" disabled={exporting} onClick={() => void downloadReport(k)}>
              <Download className="h-3 w-3 mr-1" />{k.toUpperCase()}
            </Button>
          ))}
          <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px] text-violet-300 border-violet-700" disabled={exporting} onClick={() => void downloadReport("html")}>
            <FileText className="h-3 w-3 mr-1" />Phase 7 Report
          </Button>
          <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px] text-emerald-300 border-emerald-700" disabled={reconnecting} onClick={() => void forceReconnect()} data-testid="button-force-reconnect">
            {reconnecting ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Wifi className="h-3 w-3 mr-1" />}
            Force Reconnect
          </Button>
          {(["json", "csv"] as const).map(k => (
            <Button key={`bundle-${k}`} size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px] text-amber-300 border-amber-700" disabled={exporting} onClick={() => void downloadBundle(k)} data-testid={`button-bundle-${k}`}>
              <Download className="h-3 w-3 mr-1" />Diagnostics {k.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>

      <p className="text-[9px] font-mono text-amber-400/90 bg-amber-500/5 border border-amber-500/20 rounded px-2 py-1">
        <ShieldCheck className="h-3 w-3 inline mr-1" />
        Paper trading and research only. No real broker API is called. No real money is at risk.
        Meta-Learning and Strategy Evolution findings do not affect live decisions unless a future human-approved phase enables them.
      </p>

      {errors.map(e => (
        <p key={e} className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">{e}</p>
      ))}

      {/* Phase 11 — Live Stream & Market Hours */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Card className="bg-zinc-900 border-zinc-700" data-testid="card-live-stream">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              {stream.connection === "connected"
                ? <Wifi className="h-3.5 w-3.5 text-emerald-400" />
                : <WifiOff className="h-3.5 w-3.5 text-red-400" />}
              Live Stream (SSE)
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1.5 font-mono text-[10px]">
            <div className="flex justify-between">
              <span className="text-zinc-500">Connection</span>
              <span className={stream.connection === "connected" ? "text-emerald-400"
                : stream.connection === "reconnecting" ? "text-amber-400" : "text-red-400"}>
                {stream.connection.toUpperCase()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Last event</span>
              <span className="text-zinc-300">{na(stream.lastEventTs)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Stream error</span>
              <span className={stream.lastError ? "text-red-400" : "text-zinc-400"}>{stream.lastError ?? "None"}</span>
            </div>
            {Object.entries(stream.quotes).map(([sym, q]: [string, any]) => (
              <div key={sym} className="flex justify-between">
                <span className="text-zinc-500">{sym}</span>
                <span className="text-zinc-200">
                  {q?.ltp != null
                    ? `${q.ltp} (${q.change_pct != null ? `${q.change_pct >= 0 ? "+" : ""}${q.change_pct}%` : "N/A"}) · ${q.quality ?? "N/A"}${q.from_cache ? ` · cached ${q.cache_age_s}s` : ""}`
                    : "Unavailable"}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="bg-zinc-900 border-zinc-700" data-testid="card-market-hours">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-sky-400" />Market Hours (Asia/Kolkata)
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1.5 font-mono text-[10px]">
            <div className="flex justify-between items-center">
              <span className="text-zinc-500">State</span>
              <Badge variant="outline" className={cn("text-[9px] font-mono px-1",
                healthV2?.market?.state === "OPEN" ? "text-emerald-400 border-emerald-700"
                  : healthV2?.market?.state === "PRE_OPEN" ? "text-sky-400 border-sky-700"
                  : "text-amber-400 border-amber-700")}>
                {healthV2?.market?.state ?? stream.market?.state ?? "N/A"}
              </Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">IST now</span>
              <span className="text-zinc-300">{na(healthV2?.market?.now_ist ?? stream.market?.now_ist)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Holiday today</span>
              <span className="text-zinc-300">
                {(healthV2?.market?.holiday_today ?? stream.market?.holiday_today)?.name ?? "No"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Next transition</span>
              <span className="text-zinc-300">
                {(() => {
                  const nt = healthV2?.market?.next_transition ?? stream.market?.next_transition;
                  return nt ? `${nt.event} · ${nt.at_ist}` : "N/A";
                })()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Quote provider</span>
              <span className="text-zinc-300">{na(healthV2?.quote_provider?.provider)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Circuit breaker</span>
              <span className={healthV2?.quote_provider?.circuit_breaker === "OPEN" ? "text-red-400" : "text-emerald-400"}>
                {healthV2?.quote_provider?.circuit_breaker === "OPEN" ? "OPEN (cooling down)"
                  : healthV2?.quote_provider?.circuit_breaker === "CLOSED" ? "Closed (healthy)" : "N/A"}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Provider + Connection */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <Card className="bg-zinc-900 border-zinc-700">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <ConnIcon status={ph.connection_status ?? "NOT_TESTED"} />
              Provider Status
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1.5 font-mono text-[10px]">
            <div className="flex justify-between">
              <span className="text-zinc-500">Provider</span>
              <span className="text-zinc-200">{na(ph.provider)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Connection</span>
              <span className={cn(CONN_CLS[ph.connection_status] ?? "text-zinc-400")}>
                {ph.connection_status ?? "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Last successful fetch</span>
              <span className="text-zinc-300">{na(ph.last_successful_fetch)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Retry events</span>
              <span className={ph.retry_events > 0 ? "text-amber-400" : "text-zinc-300"}>{na(ph.retry_events)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Avg latency</span>
              <span className="text-zinc-300">{na(ph.avg_latency_ms)}ms · max {na(ph.max_latency_ms)}ms</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-zinc-500">Paper execution eligible</span>
              {ph.paper_execution_eligible
                ? <Badge variant="outline" className="text-[9px] font-mono text-emerald-400 border-emerald-700 px-1">YES</Badge>
                : <Badge variant="outline" className="text-[9px] font-mono text-red-400 border-red-700 px-1">NO</Badge>}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-zinc-900 border-zinc-700">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <Database className="h-3.5 w-3.5 text-sky-400" />Symbol Coverage
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1.5 font-mono text-[10px]">
            <div className="flex justify-between">
              <span className="text-zinc-500">Requested</span>
              <span className="text-zinc-200">{na(ph.symbols_requested)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Succeeded</span>
              <span className="text-emerald-400">{na(ph.symbols_succeeded)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Stale</span>
              <span className={ph.symbols_stale > 0 ? "text-amber-400" : "text-zinc-400"}>{na(ph.symbols_stale)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Unavailable</span>
              <span className={ph.symbols_unavailable > 0 ? "text-red-400" : "text-zinc-400"}>{na(ph.symbols_unavailable)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Coverage</span>
              <span className={ph.symbol_coverage_pct >= 80 ? "text-emerald-400" : "text-amber-400"}>
                {na(ph.symbol_coverage_pct)}%
              </span>
            </div>
            {/* Quality breakdown */}
            {ph.quality_summary && Object.keys(ph.quality_summary).length > 0 && (
              <div className="pt-1 border-t border-zinc-800 flex flex-wrap gap-1">
                {Object.entries(ph.quality_summary as Record<string, number>).map(([q, n]) => (
                  <Badge key={q} variant="outline" className={cn("text-[9px] font-mono px-1", QUALITY_CLS[q] ?? "text-zinc-400 border-zinc-600")}>
                    {q}: {n}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Scan Audit */}
      <Card className="bg-zinc-900 border-zinc-700">
        <CardHeader className="py-2 px-3">
          <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-violet-400" />Scan Audit — Snapshot Consistency
          </CardTitle>
        </CardHeader>
        <CardContent className="px-3 pb-3 font-mono text-[10px] space-y-1">
          <GateRow label="All items share same scan_id"
            passed={audit.all_items_share_same_scan_id !== false}
            reason={`${na(audit.distinct_scan_id_count)} distinct ID(s)`} />
          <GateRow label="All items share same snapshot_ts"
            passed={audit.all_items_share_same_snapshot_ts !== false}
            reason={`${na(audit.distinct_snapshot_ts_count)} distinct timestamp(s)`} />
          <GateRow label="Data fetched before analysis"
            passed={audit.data_fetched_before_analysis !== false}
            reason="Enforced by design — batch fetch then analyse" />
          <div className="flex items-center gap-1.5 pt-1">
            <span className="text-zinc-500">Audit verdict:</span>
            <Badge variant="outline" className={cn("text-[9px] font-mono px-1",
              audit.audit_verdict === "PASS" ? "text-emerald-400 border-emerald-700" : "text-red-400 border-red-700")}>
              {audit.audit_verdict ?? "N/A"}
            </Badge>
          </div>
          {audit.no_lookahead && <p className="text-zinc-500 text-[9px] mt-1">{audit.no_lookahead}</p>}
        </CardContent>
      </Card>

      {/* Decision Summary */}
      <Card className="bg-zinc-900 border-zinc-700">
        <CardHeader className="py-2 px-3">
          <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
            <Activity className="h-3.5 w-3.5 text-sky-400" />Decision Summary
          </CardTitle>
        </CardHeader>
        <CardContent className="px-3 pb-3 font-mono text-[10px]">
          {!summary || Object.keys(summary).length === 0
            ? <p className="text-zinc-500">No scan data yet — run a scan to populate.</p>
            : <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {[
                { label: "STRONG BUY", val: summary.strong_buy_count, cls: "text-emerald-400" },
                { label: "BUY", val: summary.buy_count, cls: "text-sky-400" },
                { label: "WATCH", val: summary.watch_count, cls: "text-amber-400" },
                { label: "IGNORE", val: summary.ignore_count, cls: "text-zinc-500" },
                { label: "Paper eligible", val: summary.paper_eligible_count, cls: "text-violet-400" },
                { label: "All gates passed", val: summary.all_gates_passed_count, cls: "text-sky-300" },
                { label: "Symbols with errors", val: summary.symbols_with_errors, cls: summary.symbols_with_errors > 0 ? "text-red-400" : "text-zinc-500" },
                { label: "Avg score", val: na(summary.avg_opportunity_score), cls: "text-zinc-200" },
              ].map(({ label, val, cls }) => (
                <div key={label} className="border border-zinc-800 rounded px-2 py-1.5">
                  <div className="text-zinc-500">{label}</div>
                  <div className={cn("text-sm font-bold", cls)}>{val ?? "N/A"}</div>
                </div>
              ))}
            </div>}
          {summary.duration_s !== undefined && (
            <p className="text-zinc-500 mt-1.5">Scan took {summary.duration_s}s · universe {summary.universe_size} symbols</p>
          )}
        </CardContent>
      </Card>

      {/* Stale & Unavailable symbols */}
      {(ph.stale_symbols?.length > 0 || ph.unavailable_symbols?.length > 0) && (
        <Card className="bg-zinc-900 border-zinc-700">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />Data Quality Warnings
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 font-mono text-[10px] space-y-1.5">
            {ph.stale_symbols?.length > 0 && (
              <div>
                <span className="text-amber-400">Stale ({ph.stale_symbols.length}): </span>
                <span className="text-zinc-400">{ph.stale_symbols.join(", ")}</span>
                <span className="text-zinc-600"> — capped at WATCH</span>
              </div>
            )}
            {ph.unavailable_symbols?.length > 0 && (
              <div>
                <span className="text-red-400">Unavailable ({ph.unavailable_symbols.length}): </span>
                <span className="text-zinc-400">{ph.unavailable_symbols.join(", ")}</span>
                <span className="text-zinc-600"> — capped at IGNORE</span>
              </div>
            )}
            {ph.errors?.slice(0, 5).map((e: any) => (
              <div key={e.symbol} className="text-zinc-500">{e.symbol}: {e.error}</div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Notes */}
      {ph.notes?.length > 0 && (
        <div className="space-y-1">
          {ph.notes.map((n: string) => (
            <p key={n} className="text-[9px] font-mono text-zinc-500 bg-zinc-800/50 rounded px-2 py-1">{n}</p>
          ))}
        </div>
      )}

      {/* Per-symbol quality table */}
      {recs.length > 0 && (
        <div>
          <h3 className="text-[11px] font-mono font-bold text-zinc-200 mb-1">Symbol-Level Quality & Gates</h3>
          <div className="border border-zinc-700 rounded overflow-x-auto">
            <table className="w-full font-mono text-[10px]">
              <thead>
                <tr className="text-zinc-500 text-[9px] uppercase border-b border-zinc-700">
                  {["#", "Symbol", "Sector", "Quality", "Age(d)", "Latest bar", "Bars",
                    "Action", "Price gate", "Quality gate", "RR gate", "Vol gate", "Paper?", "Error"].map(h => (
                    <th key={h} className="text-left px-2 py-1.5">{h}</th>))}
                </tr>
              </thead>
              <tbody>
                {recs.map((r: any) => (
                  <tr key={r.symbol} className="border-b border-zinc-800 hover:bg-zinc-800/30">
                    <td className="px-2 py-1 text-zinc-600">{r.rank}</td>
                    <td className="px-2 py-1 text-zinc-100 font-medium">{r.symbol}</td>
                    <td className="px-2 py-1 text-zinc-500">{r.sector}</td>
                    <td className="px-2 py-1">
                      <Badge variant="outline" className={cn("text-[9px] font-mono px-1", QUALITY_CLS[r.data_quality] ?? "text-zinc-400 border-zinc-600")}>
                        {r.data_quality}
                      </Badge>
                    </td>
                    <td className="px-2 py-1 text-zinc-400">{na(r.data_age_days)}</td>
                    <td className="px-2 py-1 text-zinc-400">{na(r.latest_bar_date)}</td>
                    <td className="px-2 py-1 text-zinc-400">{na(r.bars_available)}</td>
                    <td className={cn("px-2 py-1 font-medium",
                      r.final_action === "STRONG BUY" ? "text-emerald-400"
                        : r.final_action === "BUY" ? "text-sky-400"
                        : r.final_action === "WATCH" ? "text-amber-400" : "text-zinc-500")}>
                      {r.final_action}
                    </td>
                    {(["gate_price", "gate_data_quality", "gate_rr", "gate_volume"] as const).map(gk => (
                      <td key={gk} className="px-2 py-1" title={(r[gk] as any)?.reason ?? ""}>
                        {(r[gk] as any)?.passed
                          ? <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                          : <XCircle className="h-3 w-3 text-red-400" />}
                      </td>
                    ))}
                    <td className="px-2 py-1">
                      {r.paper_eligible
                        ? <CheckCircle2 className="h-3 w-3 text-violet-400" />
                        : <span className="text-zinc-600">—</span>}
                    </td>
                    <td className="px-2 py-1 text-red-400 text-[9px] max-w-24 truncate" title={r.error ?? ""}>{r.error ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
