/**
 * Phase15SystemHealth.tsx — Phase 15: Production Hardening & Stabilization
 * Global stale-scan banner + System Health panel (readiness, consistency,
 * data quality, diagnostics). PAPER / RESEARCH ONLY.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertTriangle, CheckCircle2, XCircle, ShieldCheck, Gauge, Loader2,
  RefreshCw, ClipboardCheck, Scale,
} from "lucide-react";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

const STATUS_CLS: Record<string, string> = {
  PASS: "text-emerald-400 border-emerald-700",
  WARN: "text-amber-400 border-amber-700",
  FAIL: "text-red-400 border-red-700",
};

const BAND_CLS: Record<string, string> = {
  EXCELLENT: "text-emerald-400 border-emerald-700",
  GOOD: "text-sky-400 border-sky-700",
  WARNING: "text-amber-400 border-amber-700",
  DO_NOT_TRADE: "text-red-400 border-red-700",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "PASS") return <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />;
  if (status === "WARN") return <AlertTriangle className="h-3 w-3 text-amber-400 shrink-0" />;
  return <XCircle className="h-3 w-3 text-red-400 shrink-0" />;
}

/** Global banner shown on every page when the canonical scan is stale. */
export function StaleScanBanner() {
  const { data } = useQuery({
    queryKey: ["/api/phase15/staleness"],
    queryFn: () => apiJson<any>("/phase15/staleness"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  });
  if (!data?.stale) return null;
  return (
    <div
      className="flex items-center gap-2 px-4 py-1.5 bg-warn-surface border-b border-warn text-warn text-[11px] font-mono z-20"
      data-testid="banner-stale-scan"
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      <span>
        Scan data is stale ({data.scan_age_human ?? "unknown age"} old — limit 90m).
        BUY recommendations are disabled until a fresh scan runs.
      </span>
    </div>
  );
}

/** Phase 15 System Health panel: readiness, consistency, quality, diagnostics. */
export function Phase15SystemHealthPanel() {
  const [checking, setChecking] = useState(false);
  const readiness = useQuery({
    queryKey: ["/api/phase15/readiness"],
    queryFn: () => apiJson<any>("/phase15/readiness"),
    staleTime: 120_000,
  });
  const consistency = useQuery({
    queryKey: ["/api/phase15/consistency"],
    queryFn: () => apiJson<any>("/phase15/consistency"),
    staleTime: 120_000,
  });
  const quality = useQuery({
    queryKey: ["/api/phase15/quality"],
    queryFn: () => apiJson<any>("/phase15/quality"),
    staleTime: 120_000,
  });
  const diagnostics = useQuery({
    queryKey: ["/api/phase15/diagnostics"],
    queryFn: () => apiJson<any>("/phase15/diagnostics"),
    staleTime: 120_000,
  });

  const rerun = async () => {
    setChecking(true);
    try {
      await Promise.all([
        readiness.refetch(), consistency.refetch(),
        quality.refetch(), diagnostics.refetch(),
      ]);
    } finally { setChecking(false); }
  };

  const rr = readiness.data;
  const cr = consistency.data;
  const qr = quality.data;
  const dg = diagnostics.data;

  return (
    <div className="space-y-2" data-testid="panel-phase15-health">
      <div className="flex items-center gap-2">
        <Gauge className="h-4 w-4 text-violet-400" />
        <h2 className="text-[12px] font-mono font-bold text-zinc-100">
          System Health — Phase 15 Production Readiness
        </h2>
        <Badge variant="outline" className="text-[9px] font-mono text-amber-400 border-amber-700 px-1.5">
          PAPER / RESEARCH ONLY
        </Badge>
        <Button size="sm" variant="outline" className="h-6 px-2 font-mono text-[10px] ml-auto"
          onClick={() => void rerun()} disabled={checking} data-testid="button-phase15-recheck">
          {checking ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <RefreshCw className="h-3 w-3 mr-1" />}
          Re-run Checks
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        {/* Readiness report */}
        <Card className="bg-zinc-900 border-zinc-700" data-testid="card-readiness">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <ClipboardCheck className="h-3.5 w-3.5 text-violet-400" />
              Production Readiness Report
              {rr?.verdict && (
                <Badge variant="outline" className={cn("text-[9px] font-mono px-1 ml-auto",
                  rr.verdict === "READY" ? STATUS_CLS.PASS
                    : rr.verdict === "READY_WITH_WARNINGS" ? STATUS_CLS.WARN : STATUS_CLS.FAIL)}>
                  {String(rr.verdict).replace(/_/g, " ")}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1 font-mono text-[10px]">
            {readiness.isLoading && <p className="text-zinc-500">Running readiness checks…</p>}
            {readiness.isError && <p className="text-red-400">Readiness check failed: {String((readiness.error as Error)?.message)}</p>}
            {(rr?.items ?? []).map((it: any) => (
              <div key={it.item} className="flex items-start gap-1.5">
                <span className="mt-0.5"><StatusIcon status={it.status} /></span>
                <span className={it.status === "FAIL" ? "text-red-300" : it.status === "WARN" ? "text-amber-300" : "text-zinc-300"}>
                  {String(it.item).replace(/_/g, " ")}
                </span>
                <span className="text-zinc-500 truncate">— {it.detail}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Consistency */}
        <Card className="bg-zinc-900 border-zinc-700" data-testid="card-consistency">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <Scale className="h-3.5 w-3.5 text-sky-400" />
              Cross-Page Consistency
              {cr?.verdict && (
                <Badge variant="outline" className={cn("text-[9px] font-mono px-1 ml-auto", STATUS_CLS[cr.verdict] ?? STATUS_CLS.FAIL)}>
                  {cr.verdict}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1.5 font-mono text-[10px]">
            {consistency.isLoading && <p className="text-zinc-500">Comparing modules against canonical scan…</p>}
            {consistency.isError && <p className="text-red-400">Consistency check failed: {String((consistency.error as Error)?.message)}</p>}
            {cr?.available && (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
                  {[
                    { label: "Checks", val: cr.checks_performed, cls: "text-zinc-200" },
                    { label: "Hard mismatches", val: cr.hard_mismatch_count, cls: cr.hard_mismatch_count > 0 ? "text-red-400" : "text-emerald-400" },
                    { label: "Out-of-sync values", val: cr.stale_source_count, cls: cr.stale_source_count > 0 ? "text-amber-400" : "text-zinc-400" },
                    { label: "Scan ID", val: cr.scan_id, cls: "text-zinc-400" },
                  ].map(({ label, val, cls }) => (
                    <div key={label} className="border border-zinc-800 rounded px-1.5 py-1">
                      <div className="text-zinc-500 text-[9px]">{label}</div>
                      <div className={cn("font-bold truncate", cls)}>{val ?? "N/A"}</div>
                    </div>
                  ))}
                </div>
                <p className="text-zinc-500 leading-snug">{cr.note}</p>
                {(cr.mismatches ?? []).slice(0, 5).map((m: any, i: number) => (
                  <div key={i} className="flex items-start gap-1.5">
                    {m.severity === "STALE_SOURCE"
                      ? <AlertTriangle className="h-3 w-3 text-amber-400 mt-0.5 shrink-0" />
                      : <XCircle className="h-3 w-3 text-red-400 mt-0.5 shrink-0" />}
                    <span className="text-zinc-400">
                      {m.symbol} · {m.field}: {m.source} {m.source_value} vs canonical {m.canonical_value}
                    </span>
                  </div>
                ))}
                {(cr.mismatches?.length ?? 0) > 5 && (
                  <p className="text-zinc-600">…and {cr.mismatches.length - 5} more (all flagged in report)</p>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        {/* Data quality */}
        <Card className="bg-zinc-900 border-zinc-700" data-testid="card-quality">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
              Data Quality Scores
              {qr?.avg_score != null && (
                <span className="text-[10px] text-zinc-500 ml-auto">avg {qr.avg_score}</span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1.5 font-mono text-[10px]">
            {quality.isLoading && <p className="text-zinc-500">Scoring data quality…</p>}
            {quality.isError && <p className="text-red-400">Quality check failed: {String((quality.error as Error)?.message)}</p>}
            {qr?.available && (
              <>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(qr.band_counts ?? {}).map(([band, n]) => (
                    <Badge key={band} variant="outline" className={cn("text-[9px] font-mono px-1", BAND_CLS[band] ?? "text-zinc-400 border-zinc-600")}>
                      {band.replace(/_/g, " ")}: {String(n)}
                    </Badge>
                  ))}
                </div>
                {(qr.symbols ?? []).filter((s: any) => s.band === "DO_NOT_TRADE" || s.band === "WARNING").slice(0, 6).map((s: any) => (
                  <div key={s.symbol} className="flex items-center gap-1.5">
                    <Badge variant="outline" className={cn("text-[9px] font-mono px-1", BAND_CLS[s.band])}>
                      {s.data_quality_score}
                    </Badge>
                    <span className="text-zinc-300">{s.symbol}</span>
                    <span className="text-zinc-500 truncate">
                      {(s.components ?? []).filter((c: any) => !c.ok).map((c: any) => c.issue || c.component).join("; ")}
                    </span>
                  </div>
                ))}
                {(qr.symbols ?? []).every((s: any) => s.band === "EXCELLENT" || s.band === "GOOD") && (
                  <p className="text-emerald-400">All symbols scored EXCELLENT or GOOD.</p>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Diagnostics */}
        <Card className="bg-zinc-900 border-zinc-700" data-testid="card-diagnostics">
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-[11px] font-mono text-zinc-200 flex items-center gap-1.5">
              <Gauge className="h-3.5 w-3.5 text-sky-400" />
              System Diagnostics
              {dg?.system_health && (
                <Badge variant="outline" className={cn("text-[9px] font-mono px-1 ml-auto",
                  dg.system_health === "OK" ? STATUS_CLS.PASS : STATUS_CLS.WARN)}>
                  {dg.system_health}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1.5 font-mono text-[10px]">
            {diagnostics.isLoading && <p className="text-zinc-500">Collecting diagnostics…</p>}
            {diagnostics.isError && <p className="text-red-400">Diagnostics failed: {String((diagnostics.error as Error)?.message)}</p>}
            {dg && (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
                  {[
                    { label: "Version", val: dg.version },
                    { label: "API", val: dg.api_status },
                    { label: "Memory", val: dg.memory_usage_mb != null ? `${dg.memory_usage_mb} MB` : "N/A" },
                    { label: "Context latency", val: dg.context_build_latency_ms != null ? `${dg.context_build_latency_ms} ms` : "N/A" },
                  ].map(({ label, val }) => (
                    <div key={label} className="border border-zinc-800 rounded px-1.5 py-1">
                      <div className="text-zinc-500 text-[9px]">{label}</div>
                      <div className="text-zinc-200 font-bold truncate">{val ?? "N/A"}</div>
                    </div>
                  ))}
                </div>
                {(dg.cache_status ?? []).map((c: any) => (
                  <div key={c.file} className="flex items-center gap-1.5">
                    {c.exists
                      ? <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />
                      : <XCircle className="h-3 w-3 text-red-400 shrink-0" />}
                    <span className="text-zinc-300">{c.file}</span>
                    <span className="text-zinc-500 ml-auto">
                      {c.exists ? `${Math.round((c.age_seconds ?? 0) / 60)}m old · ${((c.size_bytes ?? 0) / 1024).toFixed(1)} KB` : "missing"}
                    </span>
                  </div>
                ))}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
