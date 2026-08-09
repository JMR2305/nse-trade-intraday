/**
 * SystemReadiness.tsx — Phase 27F: System Readiness Dashboard.
 *
 * "Is ApexQuant AI ready to safely run the next/current paper session?"
 * Deterministic READY / WARNING / BLOCKED / UNKNOWN fold over canonical
 * health sources. Missing evidence renders UNKNOWN — never READY.
 * READ-ONLY · PAPER TRADING / RESEARCH ONLY.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ShieldCheck, ShieldAlert, ShieldX, HelpCircle, RefreshCw, Clock,
  AlertTriangle, CheckCircle2, History,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

const REPORT_KEY = ["system-readiness", "report"];

type Status = "READY" | "WARNING" | "BLOCKED" | "UNKNOWN";

const STATUS_META: Record<Status, { cls: string; dot: string; icon: any }> = {
  READY:   { cls: "border-emerald-800 text-emerald-400", dot: "bg-emerald-500", icon: CheckCircle2 },
  WARNING: { cls: "border-amber-800 text-amber-400",     dot: "bg-amber-500",   icon: AlertTriangle },
  BLOCKED: { cls: "border-rose-800 text-rose-400",       dot: "bg-rose-500",    icon: ShieldX },
  UNKNOWN: { cls: "border-zinc-700 text-zinc-400",       dot: "bg-zinc-500",    icon: HelpCircle },
};

function StatusBadge({ status }: { status?: string }) {
  const m = STATUS_META[(status as Status) ?? "UNKNOWN"] ?? STATUS_META.UNKNOWN;
  return (
    <Badge variant="outline" className={cn("text-[10px] font-mono", m.cls)}
      data-testid={`status-${status}`}>
      {status ?? "UNKNOWN"}
    </Badge>
  );
}

function ago(s?: number | null): string {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  return `${(s / 3600).toFixed(1)}h ago`;
}

function OverallBanner({ d, onRun, running }: { d: any; onRun: () => void; running: boolean }) {
  const overall: Status = d?.overall ?? "UNKNOWN";
  const Icon = overall === "READY" ? ShieldCheck
    : overall === "WARNING" ? ShieldAlert
    : overall === "BLOCKED" ? ShieldX : HelpCircle;
  const bg = overall === "READY" ? "border-emerald-900 bg-emerald-950/30"
    : overall === "WARNING" ? "border-amber-900 bg-amber-950/30"
    : overall === "BLOCKED" ? "border-rose-900 bg-rose-950/30"
    : "border-zinc-800 bg-zinc-950";
  const headline = overall === "READY"
    ? "System is READY for the next paper trading session"
    : overall === "WARNING"
    ? "System is usable, but with WARNINGS — review before the session"
    : overall === "BLOCKED"
    ? "System is BLOCKED — a blocking check failed"
    : "Readiness UNKNOWN — a blocking check has no evidence (fail-safe: not READY)";
  const c = d?.counts ?? {};
  return (
    <div className={cn("flex flex-wrap items-center gap-4 rounded-lg border p-4", bg)}
      data-testid="overall-banner">
      <Icon className={cn("h-8 w-8", STATUS_META[overall]?.cls?.split(" ")[1])} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <StatusBadge status={overall} />
          <span className="text-sm font-semibold text-zinc-200">{headline}</span>
        </div>
        <div className="mt-1 text-[11px] text-zinc-500">
          {c.READY ?? 0} ready · {c.WARNING ?? 0} warnings · {c.BLOCKED ?? 0} blocked · {c.UNKNOWN ?? 0} unknown
          {d?.generated_at && <> · evaluated {new Date(d.generated_at).toLocaleTimeString()}</>}
          {" · "}market {String(d?.market?.state ?? "—")}
        </div>
      </div>
      <Button size="sm" variant="outline" onClick={onRun} disabled={running}
        data-testid="button-run-check">
        <RefreshCw className={cn("mr-1 h-3 w-3", running && "animate-spin")} />
        Run readiness check
      </Button>
    </div>
  );
}

function CheckRow({ c }: { c: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-[11px]">
      <button className="flex w-full flex-wrap items-center gap-2 text-left"
        onClick={() => setOpen(!open)} data-testid={`check-${c.id}`}>
        <span className={cn("h-2 w-2 shrink-0 rounded-full",
          STATUS_META[(c.status as Status)]?.dot ?? "bg-zinc-500")} />
        <span className="font-medium text-zinc-200">{c.label}</span>
        <StatusBadge status={c.status} />
        {c.blocking && (
          <Badge variant="outline" className="border-zinc-700 text-[9px] text-zinc-500">
            BLOCKING
          </Badge>
        )}
        <span className="ml-auto flex items-center gap-1 text-zinc-600">
          <Clock className="h-3 w-3" />
          {c.checked_at ? new Date(c.checked_at).toLocaleTimeString() : "—"}
        </span>
      </button>
      <div className="mt-1 grid gap-0.5 pl-4 text-zinc-500">
        <div><span className="text-zinc-600">Expected:</span> {c.expected}</div>
        <div><span className="text-zinc-600">Actual:</span>{" "}
          <span className={c.status === "READY" ? "text-zinc-400" : STATUS_META[(c.status as Status)]?.cls?.split(" ")[1]}>
            {c.actual}
          </span>
        </div>
        {c.remediation && (
          <div className="text-amber-500/90">
            <span className="text-zinc-600">Fix:</span> {c.remediation}
          </div>
        )}
        {open && c.evidence && Object.keys(c.evidence).length > 0 && (
          <pre className="mt-1 overflow-x-auto rounded bg-zinc-900 p-2 text-[10px] text-zinc-400">
            {JSON.stringify(c.evidence, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

function DomainCard({ d }: { d: any }) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-sm text-zinc-200">
          <span>{d.domain}</span>
          <StatusBadge status={d.status} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {(d.checks ?? []).map((c: any) => <CheckRow key={c.id} c={c} />)}
      </CardContent>
    </Card>
  );
}

function FreshnessCard({ rows }: { rows: any[] }) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-zinc-200">Data Freshness</CardTitle>
        <div className="text-[10px] text-zinc-600">
          budgets come from existing platform thresholds — none defined here
        </div>
      </CardHeader>
      <CardContent>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-zinc-600">
              <th className="pb-1 pr-2 font-normal">Source</th>
              <th className="pb-1 pr-2 font-normal">Age</th>
              <th className="pb-1 pr-2 font-normal">Budget</th>
              <th className="pb-1 font-normal">Status</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((f: any) => (
              <tr key={f.name} className="border-t border-zinc-800/60">
                <td className="py-1 pr-2 text-zinc-300">{f.name}
                  <span className="ml-1 text-[9px] text-zinc-600">({f.source})</span>
                </td>
                <td className="py-1 pr-2 font-mono text-zinc-400">{ago(f.age_seconds)}</td>
                <td className="py-1 pr-2 font-mono text-zinc-600">
                  {f.limit_seconds != null ? `${Math.round(f.limit_seconds / 60)}m` : "—"}
                </td>
                <td className="py-1"><StatusBadge status={f.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function HistoryCard() {
  const { data } = useQuery<any>({
    queryKey: ["system-readiness", "history"],
    queryFn: () => apiJson("/system-readiness/history"),
    refetchInterval: 60_000,
  });
  const entries: any[] = data?.entries ?? [];
  return (
    <Card className="border-zinc-800 bg-zinc-900/60">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <History className="h-4 w-4" /> Check History
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!entries.length ? (
          <div className="text-[11px] text-zinc-600">No readiness checks recorded yet.</div>
        ) : (
          <div className="space-y-1 text-[11px]">
            {entries.map((e: any, i: number) => (
              <div key={i} className="flex flex-wrap items-center gap-2 border-t border-zinc-800/60 py-1 first:border-t-0">
                <StatusBadge status={e.overall} />
                <span className="font-mono text-zinc-500">
                  {e.at ? new Date(e.at).toLocaleString() : "—"}
                </span>
                <span className="text-zinc-600">
                  {e.counts?.READY ?? 0}R / {e.counts?.WARNING ?? 0}W / {e.counts?.BLOCKED ?? 0}B / {e.counts?.UNKNOWN ?? 0}U
                </span>
                {(e.blocking_failures ?? []).length > 0 && (
                  <span className="text-rose-400">
                    blocking: {(e.blocking_failures ?? []).join(", ")}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function SystemReadiness() {
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);
  const { data: d, isLoading, error, refetch } = useQuery<any>({
    queryKey: REPORT_KEY,
    // Aggregate endpoint spawns Python + many collectors — long timeout.
    queryFn: () => apiJson("/system-readiness/report", undefined, 60_000),
    refetchInterval: 60_000,
    retry: 2,
  });

  const runCheck = async () => {
    setRunning(true);
    try {
      const fresh = await apiJson("/system-readiness/report?force=true", undefined, 90_000);
      qc.setQueryData(REPORT_KEY, fresh);
      qc.invalidateQueries({ queryKey: ["system-readiness", "history"] });
    } catch {
      refetch();
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-zinc-100">
            <ShieldCheck className="h-5 w-5 text-teal-400" /> System Readiness
          </h1>
          <p className="text-[11px] text-zinc-500">
            READ-ONLY readiness fold over canonical health sources — PAPER TRADING / RESEARCH ONLY
          </p>
        </div>
      </div>

      {isLoading && <div className="p-8 text-center text-sm text-zinc-500" data-testid="loading">Evaluating readiness…</div>}
      {!!error && (
        <div className="rounded border border-rose-900 bg-rose-950/30 p-3 text-sm text-rose-400" data-testid="error">
          Failed to load readiness report: {String((error as Error).message ?? error)}
        </div>
      )}

      {d?.ok && (
        <>
          <OverallBanner d={d} onRun={runCheck} running={running} />

          {Object.keys(d.source_errors ?? {}).length > 0 && (
            <div className="rounded border border-amber-900 bg-amber-950/30 p-2 text-[11px] text-amber-400"
              data-testid="source-errors">
              <div className="font-semibold">Some canonical sources could not be read (their checks show UNKNOWN):</div>
              {Object.entries(d.source_errors).map(([k, v]) => (
                <div key={k}>{k}: {String(v)}</div>
              ))}
            </div>
          )}

          <div className="grid gap-3 md:grid-cols-2">
            {(d.domains ?? []).map((dom: any) => <DomainCard key={dom.domain} d={dom} />)}
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <FreshnessCard rows={d.freshness} />
            <HistoryCard />
          </div>

          <div className="text-[10px] text-zinc-600">{d.note}</div>
        </>
      )}
    </div>
  );
}
