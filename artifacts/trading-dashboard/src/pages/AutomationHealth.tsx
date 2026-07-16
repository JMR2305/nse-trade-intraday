/**
 * AutomationHealth.tsx — Phase 20: Automation Health.
 * Scheduler health card, validation status panel, and scan history table.
 * PAPER / RESEARCH ONLY — no real orders are placed.
 */

import { Fragment, useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Gauge, RefreshCw, Loader2, CheckCircle2, XCircle, AlertTriangle,
  Clock, TimerReset, ShieldCheck, ChevronDown, ChevronRight, History,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "PAPER / RESEARCH ONLY";

const HEALTH_CLS: Record<string, string> = {
  HEALTHY: "text-emerald-400 border-emerald-700 bg-emerald-950/30",
  DEGRADED: "text-amber-400 border-amber-700 bg-amber-950/30",
  DOWN: "text-red-400 border-red-700 bg-red-950/30",
  DISABLED: "text-slate-400 border-slate-700 bg-slate-900/40",
  UNKNOWN: "text-zinc-400 border-zinc-600 bg-zinc-900/50",
};

const OVERALL_CLS: Record<string, string> = {
  PAPER_READY: "text-emerald-400 border-emerald-700 bg-emerald-950/30",
  DEGRADED: "text-amber-400 border-amber-700 bg-amber-950/30",
  NOT_READY: "text-red-400 border-red-700 bg-red-950/30",
};

function na(v: any, suffix = "") {
  if (v === null || v === undefined || v === "") return "N/A";
  if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "N/A";
  if (typeof v === "number") return `${+v.toFixed(2)}${suffix}`;
  return String(v);
}

function shortId(id: any): string {
  if (!id) return "N/A";
  const s = String(id);
  return s.length > 12 ? `${s.slice(0, 8)}…${s.slice(-4)}` : s;
}

async function safeJson(path: string, init?: RequestInit): Promise<any> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  if (!text.trim()) throw new Error(`Empty response from ${path} (HTTP ${resp.status})`);
  let data: any;
  try { data = JSON.parse(text); } catch { throw new Error(`Invalid JSON from ${path}`); }
  if (!resp.ok || data?.error) throw new Error(String(data?.error ?? `HTTP ${resp.status}`));
  return data;
}

function Field({ label, value, valueCls }: { label: string; value: any; valueCls?: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-zinc-500">{label}</span>
      <span className={cn("text-zinc-200 text-right", valueCls)}>{value}</span>
    </div>
  );
}

export default function AutomationHealth() {
  const { toast } = useToast();
  const [scheduler, setScheduler] = useState<any>(null);
  const [validation, setValidation] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setRefreshing(true);
    const errs: string[] = [];
    try { const d = await safeJson("/phase20/scheduler/health"); setScheduler(d.scheduler ?? null); }
    catch (e) { errs.push(`Scheduler: ${e instanceof Error ? e.message : String(e)}`); }
    try { const d = await safeJson("/phase20/validation"); setValidation(d ?? null); }
    catch (e) { errs.push(`Validation: ${e instanceof Error ? e.message : String(e)}`); }
    try { const d = await safeJson("/phase20/scan-history?limit=50"); setHistory(d.runs ?? []); }
    catch (e) { errs.push(`Scan history: ${e instanceof Error ? e.message : String(e)}`); }
    setErrors(errs);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const refresh = async () => {
    await load();
    toast({ title: "Automation health refreshed" });
  };

  const health = scheduler?.health ?? "UNKNOWN";
  const overall = validation?.overall_status ?? "NOT_READY";
  const metrics = validation?.metrics ?? {};
  const checks: any[] = validation?.checks ?? [];

  const metricCards = [
    { label: "Scheduled scans done", val: metrics.scheduled_scans_completed },
    { label: "Failed scans", val: metrics.failed_scans, cls: metrics.failed_scans > 0 ? "text-red-400" : undefined },
    { label: "Fresh-data rate", val: metrics.fresh_data_rate_pct != null ? `${na(metrics.fresh_data_rate_pct)}%` : "N/A" },
    { label: "Quote coverage", val: metrics.quote_coverage_pct != null ? `${na(metrics.quote_coverage_pct)}%` : "N/A" },
    { label: "Entries evaluated", val: metrics.entries_evaluated },
    { label: "Entries passed", val: metrics.entries_passed, cls: "text-emerald-400" },
    { label: "Entries blocked", val: metrics.entries_blocked, cls: "text-amber-400" },
    { label: "Paper trades opened", val: metrics.paper_trades_opened },
    { label: "Exits completed", val: metrics.exits_completed },
    { label: "Unresolved data events", val: metrics.unresolved_data_events, cls: metrics.unresolved_data_events > 0 ? "text-red-400" : undefined },
  ];

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center gap-3 font-mono text-zinc-500">
        <Loader2 className="h-5 w-5 animate-spin" />Loading automation health…
      </div>
    );
  }

  return (
    <div className="space-y-4 font-mono max-w-6xl">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2 flex-wrap">
            <Gauge className="h-5 w-5 text-primary" />
            <h1 className="text-xl font-bold text-foreground">Automation Health</h1>
            <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">{LABEL}</Badge>
          </div>
          <p className="text-xs text-zinc-500">
            Scheduler status, paper-trading readiness validation, and scan run history — research only, no real orders.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={refresh} disabled={refreshing} className="gap-2 text-xs">
          {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </Button>
      </div>

      <DataFreshnessBar variant="none" />

      {errors.map((e) => (
        <p key={e} className="text-[10px] text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
          <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{e}
        </p>
      ))}

      {/* Scheduler health */}
      <Card className="bg-zinc-900 border-zinc-700">
        <CardHeader className="py-2 px-3">
          <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
            <TimerReset className="h-3.5 w-3.5 text-sky-400" />Scheduler Health
            <Badge variant="outline" className={cn("ml-auto text-[10px] px-2", HEALTH_CLS[health] ?? HEALTH_CLS.UNKNOWN)}>
              {health}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-3 pb-3">
          {!scheduler ? (
            <p className="text-[10px] text-zinc-500">No scheduler data available.</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1.5 text-[11px]">
              <Field label="Status" value={na(scheduler.status)} />
              <Field label="Missed count" value={na(scheduler.missed_count)} valueCls={scheduler.missed_count > 0 ? "text-amber-400" : undefined} />
              <Field label="Last attempt" value={na(scheduler.last_attempt_at)} />
              <Field label="Last success" value={na(scheduler.last_success_at)} />
              <Field label="Last scan ID" value={shortId(scheduler.last_scan_id)} />
              <Field label="Next due" value={na(scheduler.next_due_at)} />
            </div>
          )}
          {scheduler?.detail && (
            <p className="mt-2 text-[10px] text-zinc-500 border-t border-zinc-800 pt-1.5">{scheduler.detail}</p>
          )}
        </CardContent>
      </Card>

      {/* Validation status */}
      <Card className="bg-zinc-900 border-zinc-700">
        <CardHeader className="py-2 px-3">
          <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-violet-400" />Validation Status
            {validation?.generated_at && (
              <span className="ml-auto text-[9px] text-zinc-600 font-normal">as of {validation.generated_at}</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="px-3 pb-3 space-y-3">
          {!validation ? (
            <p className="text-[10px] text-zinc-500">No validation data available.</p>
          ) : (
            <>
              <div className="flex items-center gap-3 flex-wrap">
                <Badge variant="outline" className={cn("text-sm font-bold px-4 py-1.5", OVERALL_CLS[overall] ?? OVERALL_CLS.NOT_READY)}>
                  {overall}
                </Badge>
                {validation.config_hash && (
                  <span className="text-[9px] text-zinc-600">config {shortId(validation.config_hash)}</span>
                )}
              </div>

              {/* Checks */}
              {checks.length > 0 && (
                <div className="space-y-1 border-t border-zinc-800 pt-2">
                  {checks.map((c: any, i: number) => (
                    <div key={c.check ?? i} className="flex items-start gap-1.5 text-[10px]">
                      {c.passed
                        ? <CheckCircle2 className="h-3 w-3 text-emerald-400 mt-0.5 shrink-0" />
                        : <XCircle className="h-3 w-3 text-red-400 mt-0.5 shrink-0" />}
                      <span className={c.passed ? "text-zinc-300" : "text-red-300"}>
                        {String(c.check ?? "check").replace(/_/g, " ")}
                        {c.critical && <span className="ml-1 text-[8px] text-amber-500 uppercase">critical</span>}
                      </span>
                      {c.detail && <span className="text-zinc-500">— {c.detail}</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Metrics grid */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2 border-t border-zinc-800 pt-2">
                {metricCards.map(({ label, val, cls }) => (
                  <div key={label} className="border border-zinc-800 rounded px-2 py-1.5">
                    <div className="text-[9px] text-zinc-500">{label}</div>
                    <div className={cn("text-sm font-bold text-zinc-200", cls)}>{val ?? "N/A"}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Scan history */}
      <Card className="bg-zinc-900 border-zinc-700">
        <CardHeader className="py-2 px-3">
          <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
            <History className="h-3.5 w-3.5 text-sky-400" />Scan History
            <span className="ml-auto text-[9px] text-zinc-600 font-normal">{history.length} run(s)</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          {history.length === 0 ? (
            <p className="px-3 text-[10px] text-zinc-500">No scan runs recorded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="text-zinc-500 border-b border-zinc-800">
                    <th className="text-left font-normal px-3 py-1.5 w-6"></th>
                    <th className="text-left font-normal px-2 py-1.5">Time</th>
                    <th className="text-left font-normal px-2 py-1.5">Trigger</th>
                    <th className="text-left font-normal px-2 py-1.5">Scan ID</th>
                    <th className="text-right font-normal px-2 py-1.5">Duration</th>
                    <th className="text-right font-normal px-2 py-1.5">Symbols</th>
                    <th className="text-left font-normal px-2 py-1.5">Provider</th>
                    <th className="text-left font-normal px-2 py-1.5">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((r: any, i: number) => {
                    const key = r.scan_id ?? `run-${i}`;
                    const isOpen = !!expanded[key];
                    const hasDetail = r.error || (r.missing_symbols?.length) || (r.stale_symbols?.length);
                    return (
                      <Fragment key={key}>
                        <tr
                          className={cn("border-b border-zinc-800/60", hasDetail && "cursor-pointer hover:bg-zinc-800/40")}
                          onClick={() => hasDetail && setExpanded((s) => ({ ...s, [key]: !s[key] }))}
                        >
                          <td className="px-3 py-1.5 text-zinc-500">
                            {hasDetail ? (isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />) : null}
                          </td>
                          <td className="px-2 py-1.5 text-zinc-300 whitespace-nowrap">
                            <Clock className="h-3 w-3 inline mr-1 text-zinc-600" />{na(r.started_at)}
                          </td>
                          <td className="px-2 py-1.5">
                            <Badge variant="outline" className={cn("text-[9px] px-1",
                              r.trigger_source === "SCHEDULED" ? "text-sky-400 border-sky-700" : "text-violet-400 border-violet-700")}>
                              {r.trigger_source ?? "N/A"}
                            </Badge>
                          </td>
                          <td className="px-2 py-1.5 text-zinc-400">{shortId(r.scan_id)}</td>
                          <td className="px-2 py-1.5 text-right text-zinc-300">{r.duration_s != null ? `${na(r.duration_s)}s` : "N/A"}</td>
                          <td className="px-2 py-1.5 text-right text-zinc-300">
                            {na(r.symbols_received)}/{na(r.symbols_requested)}
                          </td>
                          <td className="px-2 py-1.5 text-zinc-400">{na(r.provider)}</td>
                          <td className="px-2 py-1.5">
                            <Badge variant="outline" className={cn("text-[9px] px-1",
                              r.status === "SUCCESS" ? "text-emerald-400 border-emerald-700" : "text-red-400 border-red-700")}>
                              {r.status ?? "N/A"}
                            </Badge>
                          </td>
                        </tr>
                        {isOpen && hasDetail && (
                          <tr key={`${key}-detail`} className="border-b border-zinc-800/60 bg-zinc-950/40">
                            <td></td>
                            <td colSpan={7} className="px-2 py-2 space-y-1">
                              {r.error && (
                                <div className="text-[10px] text-red-300">
                                  <AlertTriangle className="h-3 w-3 inline mr-1" />{r.error}
                                </div>
                              )}
                              {r.missing_symbols?.length > 0 && (
                                <div className="text-[10px] text-amber-300">
                                  Missing ({r.missing_symbols.length}): {r.missing_symbols.join(", ")}
                                </div>
                              )}
                              {r.stale_symbols?.length > 0 && (
                                <div className="text-[10px] text-amber-300/80">
                                  Stale ({r.stale_symbols.length}): {r.stale_symbols.join(", ")}
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="text-center text-[10px] text-zinc-600">
        PAPER / RESEARCH ONLY · automation performs simulated paper trades only · no real orders are placed
      </div>
    </div>
  );
}
