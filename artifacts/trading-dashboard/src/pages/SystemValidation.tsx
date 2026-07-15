/**
 * SystemValidation.tsx — Phase 17: Automated QA, Regression Testing & Release Validation
 *
 * One-click complete system validation: runs every backend test suite,
 * API/data-store/paper-trading/AI/performance/export checks, benchmarks,
 * error detection and cross-page consistency. Shows release checklist,
 * release dashboard, validation history and downloadable reports.
 *
 * Feature-freeze phase: this page only VALIDATES — nothing is changed.
 * PAPER TRADING / RESEARCH ONLY. Honest markers: anything not checkable
 * server-side is listed as such, never faked.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2, RefreshCw, Download, ShieldCheck, AlertTriangle, CheckCircle2,
  XCircle, ClipboardCheck, PlayCircle, History, Gauge, FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "AUTOMATED QA & RELEASE VALIDATION — PAPER / RESEARCH ONLY";

async function safeJson(path: string, init?: RequestInit): Promise<any> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  if (!text.trim()) throw new Error(`Empty response from ${path} (HTTP ${resp.status})`);
  let data: any;
  try { data = JSON.parse(text); } catch { throw new Error(`Invalid JSON from ${path}`); }
  if (!resp.ok) throw new Error(String(data?.error ?? `HTTP ${resp.status}`));
  return data;
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "PASS" ? "text-emerald-400 border-emerald-700" :
    status === "FAIL" ? "text-red-400 border-red-700" :
    status === "WARN" ? "text-amber-400 border-amber-700" :
    "text-zinc-400 border-zinc-700";
  const Icon = status === "PASS" ? CheckCircle2 : status === "FAIL" ? XCircle : AlertTriangle;
  return (
    <Badge variant="outline" className={cn("gap-1 font-mono text-[10px]", cls)}>
      <Icon className="h-3 w-3" /> {status}
    </Badge>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={cn("text-sm font-mono", cls ?? "text-zinc-200")}>{String(value ?? "Not Available")}</div>
    </div>
  );
}

const REPORT_FILES = [
  "Validation_Report.pdf", "Validation_Report.xlsx", "Validation_Report.csv",
  "System_Health.json", "Release_Readiness.json", "Regression_Report.csv",
];

export default function SystemValidation() {
  const { toast } = useToast();
  const [dashboard, setDashboard] = useState<any>(null);
  const [lastRun, setLastRun] = useState<any>(null);
  const [history, setHistory] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState("");
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, l, h] = await Promise.all([
        safeJson("/phase17/dashboard"),
        safeJson("/phase17/last"),
        safeJson("/phase17/history"),
      ]);
      setDashboard(d);
      setLastRun(l);
      setHistory(h);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load validation data");
    } finally {
      setLoading(false);
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const pollStatus = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await safeJson("/phase17/run/status");
        setStage(s.stage ?? "");
        setElapsed(s.elapsed_seconds ?? null);
        if (s.status === "done") {
          stopPolling();
          setRunning(false);
          toast({ title: "Validation complete", description: "Complete system validation finished." });
          await load();
        } else if (s.status === "error") {
          stopPolling();
          setRunning(false);
          toast({ title: "Validation failed", description: s.error ?? "Unknown error", variant: "destructive" });
          await load();
        }
      } catch { /* transient poll failure — keep polling */ }
    }, 4000);
  }, [load, stopPolling, toast]);

  const runValidation = useCallback(async () => {
    setRunning(true);
    setStage("Starting…");
    setElapsed(0);
    try {
      await safeJson("/phase17/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      pollStatus();
    } catch (e: any) {
      setRunning(false);
      toast({ title: "Could not start validation", description: e?.message, variant: "destructive" });
    }
  }, [pollStatus, toast]);

  useEffect(() => {
    load();
    // resume polling if a run is already in progress (page reload)
    safeJson("/phase17/run/status").then((s) => {
      if (s.status === "running") { setRunning(true); setStage(s.stage ?? ""); pollStatus(); }
    }).catch(() => undefined);
    return stopPolling;
  }, [load, pollStatus, stopPolling]);

  const report = lastRun?.available ? lastRun : null;
  const sections: [string, any][] = report ? Object.entries(report.sections ?? {}) : [];

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <ClipboardCheck className="h-5 w-5 text-sky-400" /> System Validation
          </h1>
          <p className="text-xs text-zinc-500">{LABEL}</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={load} disabled={loading || running}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="ml-1">Refresh</span>
          </Button>
          <Button size="sm" onClick={runValidation} disabled={running}>
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
            <span className="ml-1">{running ? "Running…" : "Run Complete Validation"}</span>
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-red-800 bg-red-950/30">
          <CardContent className="p-3 text-sm text-red-300">{error}</CardContent>
        </Card>
      )}

      {running && (
        <Card className="border-sky-800 bg-sky-950/20">
          <CardContent className="flex items-center gap-3 p-3 text-sm text-sky-300">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>{stage || "Running complete validation…"}</span>
            {elapsed !== null && <span className="font-mono text-xs text-sky-500">{elapsed}s elapsed</span>}
          </CardContent>
        </Card>
      )}

      {/* Release dashboard */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Gauge className="h-4 w-4 text-sky-400" /> Release Dashboard
          </CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Version" value={dashboard?.current_version} />
          <Stat label="Build #" value={dashboard?.build_number} />
          <Stat label="Environment" value={dashboard?.environment} />
          <Stat
            label="Production Readiness"
            value={dashboard?.production_readiness}
            cls={
              dashboard?.production_readiness === "READY" ? "text-emerald-400"
                : dashboard?.production_readiness === "NOT READY" ? "text-red-400"
                : "text-amber-400"
            }
          />
          <Stat label="Release Score" value={dashboard?.release_score} />
          <Stat label="Open Issues (last run)" value={dashboard?.open_issues} />
          <Stat label="Last Successful Validation" value={dashboard?.last_successful_validation} />
          <Stat label="Last Failed Validation" value={dashboard?.last_failed_validation} />
        </CardContent>
      </Card>

      {/* Last run summary + checklist */}
      {report ? (
        <>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-emerald-400" /> Last Validation Run
                </span>
                <StatusBadge status={report.verdict ?? "WARN"} />
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                <Stat
                  label="System Health Score"
                  value={report.health_score !== null && report.health_score !== undefined ? `${report.health_score} / 100` : "Insufficient Data"}
                  cls={
                    typeof report.health_score === "number"
                      ? report.health_score >= 90 ? "text-emerald-400"
                        : report.health_score >= 70 ? "text-amber-400" : "text-red-400"
                      : undefined
                  }
                />
                <Stat label="Checks Passed" value={report.passed} cls="text-emerald-400" />
                <Stat label="Failed" value={report.failed} cls={report.failed ? "text-red-400" : "text-zinc-200"} />
                <Stat label="Warnings" value={report.warnings} cls={report.warnings ? "text-amber-400" : "text-zinc-200"} />
                <Stat label="Duration" value={`${report.duration_seconds ?? "?"}s`} />
              </div>
              <p className="text-[11px] text-zinc-500">{report.score_note}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <ClipboardCheck className="h-4 w-4 text-sky-400" /> Release Checklist
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {(report.release_checklist ?? []).map((item: any) => (
                <div key={item.item} className="flex items-center justify-between rounded border border-zinc-800 bg-zinc-900/40 px-3 py-1.5">
                  <span className={cn("text-xs", item.item === "Production Ready" && "font-semibold")}>{item.item}</span>
                  <div className="flex items-center gap-3">
                    <span className="hidden text-[10px] text-zinc-500 md:inline">{item.detail}</span>
                    <StatusBadge status={item.status} />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Per-section detail */}
          {sections.map(([key, sec]) => (
            <Card key={key}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center justify-between text-sm">
                  <span>{sec.section}</span>
                  <span className="font-mono text-[10px] text-zinc-500">
                    {sec.passed}/{sec.total} passed · {sec.failed} failed · {sec.warnings} warning(s)
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {(sec.checks ?? []).map((c: any, i: number) => (
                  <div key={`${c.check}-${i}`} className="flex items-start justify-between gap-2 rounded border border-zinc-800/60 bg-zinc-900/30 px-2 py-1">
                    <div className="min-w-0">
                      <div className="truncate text-xs text-zinc-200">{c.check}</div>
                      {c.detail && <div className="text-[10px] text-zinc-500">{c.detail}</div>}
                    </div>
                    <StatusBadge status={c.status} />
                  </div>
                ))}
                {sec.not_checkable?.length > 0 && (
                  <div className="rounded border border-zinc-800 bg-zinc-900/40 p-2 text-[10px] text-zinc-500">
                    <span className="font-semibold text-zinc-400">Not checkable server-side (honest disclosure): </span>
                    {sec.not_checkable.join("; ")}
                  </div>
                )}
                {sec.note && <p className="text-[10px] text-zinc-500">{sec.note}</p>}
                {sec.insufficient_data?.length > 0 && (
                  <p className="text-[10px] text-amber-500/80">
                    Insufficient Data: {sec.insufficient_data.join(", ")}
                  </p>
                )}
              </CardContent>
            </Card>
          ))}

          {/* Reports */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <FileText className="h-4 w-4 text-sky-400" /> Automated Reports
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {REPORT_FILES.map((f) => (
                <Button key={f} size="sm" variant="outline" asChild>
                  <a href={`${API_BASE}/phase17/reports/${f}`} download>
                    <Download className="mr-1 h-3 w-3" /> {f}
                  </a>
                </Button>
              ))}
            </CardContent>
          </Card>
        </>
      ) : (
        !loading && (
          <Card>
            <CardContent className="p-4 text-sm text-zinc-400">
              No validation run yet. Click <span className="font-semibold text-zinc-200">Run Complete Validation</span> to
              execute every test suite, API check, data-integrity check and benchmark (takes a few minutes).
            </CardContent>
          </Card>
        )
      )}

      {/* History */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <History className="h-4 w-4 text-sky-400" /> Validation History
          </CardTitle>
        </CardHeader>
        <CardContent>
          {history?.runs?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-[10px] uppercase text-zinc-500">
                    <th className="py-1 pr-2">Run</th>
                    <th className="py-1 pr-2">Timestamp (UTC)</th>
                    <th className="py-1 pr-2">Verdict</th>
                    <th className="py-1 pr-2">Score</th>
                    <th className="py-1 pr-2">Passed</th>
                    <th className="py-1 pr-2">Failed</th>
                    <th className="py-1 pr-2">Warnings</th>
                    <th className="py-1 pr-2">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {history.runs.map((r: any) => (
                    <tr key={r.run_id} className="border-b border-zinc-900">
                      <td className="py-1 pr-2 font-mono">{r.run_id}</td>
                      <td className="py-1 pr-2 text-zinc-400">{r.generated_at}</td>
                      <td className="py-1 pr-2"><StatusBadge status={r.verdict} /></td>
                      <td className="py-1 pr-2 font-mono">{r.health_score ?? "—"}</td>
                      <td className="py-1 pr-2 text-emerald-400">{r.passed}</td>
                      <td className={cn("py-1 pr-2", r.failed ? "text-red-400" : "text-zinc-400")}>{r.failed}</td>
                      <td className={cn("py-1 pr-2", r.warnings ? "text-amber-400" : "text-zinc-400")}>{r.warnings}</td>
                      <td className="py-1 pr-2 text-zinc-400">{r.duration_seconds}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-zinc-500">No validation runs recorded yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
