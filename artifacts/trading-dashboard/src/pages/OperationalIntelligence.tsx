/**
 * OperationalIntelligence.tsx — Phase 27.1: Operational Intelligence
 * Refinements. READ-ONLY composition over canonical stores:
 * readiness timeline, history stats, pre-market checklist, session
 * comparison, insights, pipeline health score, investigation shortcuts,
 * executive summary. PAPER TRADING / RESEARCH ONLY.
 */
import { useState } from "react";
import { Link } from "wouter";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, ArrowRight, CheckCircle2, ClipboardList,
  Gauge, History, Lightbulb, RefreshCw, ShieldCheck, TrendingUp,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

const KEY = ["operational-intelligence", "report"];

const STATUS_CLS: Record<string, string> = {
  READY: "border-emerald-800 text-emerald-400",
  PASS: "border-emerald-800 text-emerald-400",
  WARNING: "border-amber-800 text-amber-400",
  BLOCKED: "border-rose-800 text-rose-400",
  FAIL: "border-rose-800 text-rose-400",
  UNKNOWN: "border-zinc-700 text-zinc-400",
};

function SBadge({ s }: { s?: string | null }) {
  return (
    <Badge variant="outline"
      className={cn("text-[10px] font-mono", STATUS_CLS[s ?? "UNKNOWN"] ?? STATUS_CLS.UNKNOWN)}>
      {s ?? "—"}
    </Badge>
  );
}

function Shortcuts({ shortcuts }: { shortcuts: any[] }) {
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="shortcuts">
      {(shortcuts ?? []).map((s: any) => (
        <Link key={s.id} href={s.href}
          className="inline-flex items-center gap-1 rounded border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[10px] text-zinc-400 hover:border-teal-800 hover:text-teal-400">
          {s.label} <ArrowRight className="h-2.5 w-2.5" />
        </Link>
      ))}
    </div>
  );
}

function ExecutiveSummary({ ex, shortcuts }: { ex: any; shortcuts: any[] }) {
  const kpis = [
    ["Readiness", ex?.readiness],
    ["AI Health", ex?.ai_health],
    ["Trading Health", ex?.trading_health],
    ["Portfolio Health", ex?.portfolio_health],
    ["System Health", ex?.system_health],
  ];
  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="executive-summary">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <ShieldCheck className="h-4 w-4 text-teal-400" /> Executive Summary
          {ex?.pipeline_health_score != null && (
            <span className="ml-auto font-mono text-lg text-teal-400">
              {ex.pipeline_health_score}
              <span className="text-[10px] text-zinc-500"> /100</span>
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {kpis.map(([label, s]) => (
            <div key={label as string} className="rounded border border-zinc-800 bg-zinc-950/60 p-2">
              <div className="text-[10px] text-zinc-500">{label}</div>
              <SBadge s={s as string} />
            </div>
          ))}
        </div>
        {(ex?.operator_alerts ?? []).length > 0 && (
          <div className="space-y-1">
            {(ex.operator_alerts ?? []).map((a: any, i: number) => (
              <div key={i} className={cn("flex items-start gap-1.5 text-[11px]",
                a.severity === "CRITICAL" ? "text-rose-400" : "text-amber-400")}>
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" /> {a.text}
              </div>
            ))}
          </div>
        )}
        {(ex?.outstanding_issues ?? []).length > 0 && (
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase text-zinc-500">Outstanding issues</div>
            <div className="space-y-1">
              {(ex.outstanding_issues ?? []).map((o: any, i: number) => (
                <div key={i} className="flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-400">
                  <SBadge s={o.status} />
                  <span className="text-zinc-300">{o.check}</span>
                  <span className="text-zinc-600">({o.domain}{o.blocking ? " · blocking" : ""})</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <Shortcuts shortcuts={shortcuts} />
      </CardContent>
    </Card>
  );
}

function Timeline({ t, shortcuts }: { t: any; shortcuts: any[] }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const events: any[] = t?.events ?? [];
  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="timeline">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <Activity className="h-4 w-4" /> Session Readiness Timeline
          <span className="ml-auto"><SBadge s={t?.current_status} /></span>
        </CardTitle>
        <div className="text-[10px] text-zinc-600">
          {t?.session_events?.length ?? 0} changes this session · {t?.evaluations_recorded ?? 0} evaluations recorded
        </div>
      </CardHeader>
      <CardContent>
        {!events.length ? (
          <div className="text-[11px] text-zinc-600">No readiness evaluations recorded yet.</div>
        ) : (
          <div className="space-y-1">
            {events.slice(0, 20).map((e: any, i: number) => (
              <div key={i} className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-[11px]">
                <button className="flex w-full flex-wrap items-center gap-2 text-left"
                  onClick={() => setOpenIdx(openIdx === i ? null : i)}
                  data-testid={`timeline-event-${i}`}>
                  <span className="font-mono text-zinc-500">
                    {e.at ? new Date(e.at).toLocaleString() : "—"}
                  </span>
                  {e.from && <><SBadge s={e.from} /><ArrowRight className="h-3 w-3 text-zinc-600" /></>}
                  <SBadge s={e.to} />
                  {e.recovery_minutes != null && (
                    <span className="text-zinc-600">recovered in {e.recovery_minutes}m</span>
                  )}
                </button>
                <div className="mt-0.5 pl-1 text-zinc-500">{e.reason}</div>
                {openIdx === i && (
                  <div className="mt-1 space-y-1 pl-1">
                    {(e.components ?? []).length > 0 && (
                      <div className="text-zinc-500">Components: {(e.components ?? []).join(", ")}</div>
                    )}
                    {(e.issues ?? []).map((iss: any, j: number) => (
                      <div key={j} className="flex flex-wrap items-center gap-1.5 text-zinc-400">
                        <SBadge s={iss.status} />
                        <span className="font-mono text-zinc-500">{iss.id}</span>
                        <span>{iss.actual}</span>
                      </div>
                    ))}
                    {e.operator_action && (
                      <div className="text-amber-500/90">Action: {e.operator_action}</div>
                    )}
                    <Shortcuts shortcuts={shortcuts} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HistoryStats({ h }: { h: any }) {
  const [win, setWin] = useState("7d");
  const w = h?.[win] ?? {};
  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="history-stats">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <History className="h-4 w-4" /> Readiness History
          <span className="ml-auto flex gap-1">
            {["7d", "30d", "90d"].map((k) => (
              <button key={k} onClick={() => setWin(k)}
                className={cn("rounded border px-2 py-0.5 text-[10px]",
                  win === k ? "border-teal-800 text-teal-400" : "border-zinc-800 text-zinc-500")}>
                {k}
              </button>
            ))}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
          {[["READY", w.ready], ["WARNING", w.warning], ["BLOCKED", w.blocked], ["UNKNOWN", w.unknown]].map(([k, v]) => (
            <div key={k as string} className="rounded border border-zinc-800 bg-zinc-950/60 p-2">
              <SBadge s={k as string} />
              <div className="mt-1 font-mono text-lg text-zinc-200">{v ?? 0}</div>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
          <div><span className="text-zinc-600">Avg score</span><div className="font-mono text-zinc-300">{w.avg_readiness_score ?? "—"}</div></div>
          <div><span className="text-zinc-600">Longest READY streak</span><div className="font-mono text-zinc-300">{w.longest_ready_streak ?? "—"}</div></div>
          <div><span className="text-zinc-600">Most common failure</span><div className="font-mono text-zinc-300">{w.most_common_failure ?? "none"}</div></div>
          <div><span className="text-zinc-600">Avg recovery</span><div className="font-mono text-zinc-300">{w.avg_recovery_minutes != null ? `${w.avg_recovery_minutes}m` : "—"}</div></div>
        </div>
        {w.insufficient_data && (
          <div className="text-[10px] text-zinc-600">Limited history in this window — statistics may not be representative yet.</div>
        )}
        {(w.trend ?? []).length > 1 && (
          <div className="h-24">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={w.trend}>
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#71717a" }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: "#71717a" }} width={28} />
                <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }} />
                <Line type="monotone" dataKey="avg_score" stroke="#2dd4bf" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Checklist({ c }: { c: any }) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="checklist">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <ClipboardList className="h-4 w-4" /> Pre-Market Checklist
          <span className="ml-auto"><SBadge s={c?.overall} /></span>
        </CardTitle>
        <div className="text-[10px] text-zinc-600">
          {c?.counts?.PASS ?? 0} pass · {c?.counts?.WARNING ?? 0} warnings · {c?.counts?.FAIL ?? 0} fail
        </div>
      </CardHeader>
      <CardContent className="grid gap-1.5 sm:grid-cols-2">
        {(c?.items ?? []).map((it: any) => (
          <div key={it.item} className="rounded border border-zinc-800 bg-zinc-950/60 p-2 text-[11px]"
            data-testid={`checklist-${it.item.replace(/\s+/g, "-").toLowerCase()}`}>
            <div className="flex items-center gap-2">
              {it.status === "PASS"
                ? <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                : <AlertTriangle className={cn("h-3 w-3", it.status === "FAIL" ? "text-rose-500" : "text-amber-500")} />}
              <span className="font-medium text-zinc-200">{it.item}</span>
              <span className="ml-auto"><SBadge s={it.status} /></span>
            </div>
            {(it.detail ?? []).map((d: string, i: number) => (
              <div key={i} className="mt-0.5 pl-5 text-zinc-500">{d}</div>
            ))}
            {it.remediation && (
              <div className="mt-0.5 pl-5 text-amber-500/90">Fix: {it.remediation}</div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Comparison({ c }: { c: any }) {
  const days: any[] = c?.days ?? [];
  const rows: [string, (d: any) => any][] = [
    ["Stocks scanned", (d) => d.stocks_scanned],
    ["Signals", (d) => d.signals],
    ["Trades", (d) => d.trades],
    ["Win rate", (d) => (d.win_rate_pct != null ? `${d.win_rate_pct}%` : null)],
    ["PnL", (d) => (d.pnl != null ? d.pnl.toFixed(0) : null)],
    ["Risk rejections", (d) => d.risk_rejections],
    ["Execution success", (d) => (d.execution_success_pct != null ? `${d.execution_success_pct}%` : null)],
    ["Paper orders", (d) => d.paper_orders],
    ["Scan duration", (d) => (d.scan_duration_s != null ? `${d.scan_duration_s}s` : null)],
    ["Pipeline latency", (d) => (d.pipeline_latency_ms != null ? `${d.pipeline_latency_ms}ms` : null)],
  ];
  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="session-comparison">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <TrendingUp className="h-4 w-4" /> Session Comparison
        </CardTitle>
        <div className="text-[10px] text-zinc-600">{c?.note}</div>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {!days.length ? (
          <div className="text-[11px] text-zinc-600">No sessions recorded yet.</div>
        ) : (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-zinc-600">
                <th className="pb-1 pr-2 font-normal">Metric</th>
                {days.map((d) => (
                  <th key={d.date} className="pb-1 pr-2 font-normal">
                    <div className="text-zinc-400">{d.label.replace(/_/g, " ")}</div>
                    <div className="font-mono text-[9px]">{d.date}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, get]) => (
                <tr key={label} className="border-t border-zinc-800/60">
                  <td className="py-1 pr-2 text-zinc-500">{label}</td>
                  {days.map((d) => (
                    <td key={d.date} className="py-1 pr-2 font-mono text-zinc-300">
                      {get(d) ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function Insights({ list }: { list: any[] }) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="insights">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <Lightbulb className="h-4 w-4" /> Operator Insights
          <Badge variant="outline" className="ml-auto border-zinc-700 text-[9px] text-zinc-500">ADVISORY ONLY</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {(list ?? []).map((i: any, idx: number) => (
          <div key={idx} className={cn("flex items-start gap-1.5 text-[11px]",
            i.severity === "CRITICAL" ? "text-rose-400" :
            i.severity === "WARNING" ? "text-amber-400" : "text-zinc-400")}>
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
            {i.text}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function HealthScore({ h }: { h: any }) {
  return (
    <Card className="border-zinc-800 bg-zinc-900/60" data-testid="health-score">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-zinc-200">
          <Gauge className="h-4 w-4" /> Pipeline Health Score
          <span className="ml-auto font-mono text-lg text-teal-400">
            {h?.overall_score ?? "—"}<span className="text-[10px] text-zinc-500"> /100</span>
          </span>
          {h?.trend && <Badge variant="outline" className="border-zinc-700 text-[9px] text-zinc-400">{h.trend}</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {(h?.components ?? []).map((c: any, i: number) => (
            <div key={`${c.component}-${c.kind}-${i}`} className="flex items-center gap-1.5 rounded border border-zinc-800 bg-zinc-950/60 p-1.5 text-[10px]">
              <span className="truncate text-zinc-400">{c.component}</span>
              <span className="ml-auto font-mono text-zinc-300">{c.score}</span>
              <SBadge s={c.status} />
            </div>
          ))}
        </div>
        {(h?.history ?? []).length > 1 && (
          <div className="h-20">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={h.history}>
                <XAxis dataKey="at" hide />
                <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: "#71717a" }} width={28} />
                <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }}
                  labelFormatter={(v) => new Date(String(v)).toLocaleString()} />
                <Line type="monotone" dataKey="score" stroke="#818cf8" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function OperationalIntelligence() {
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);
  const { data: d, isLoading, error } = useQuery<any>({
    queryKey: KEY,
    queryFn: () => apiJson("/operational-intelligence/report", undefined, 90_000),
    refetchInterval: 60_000,
    retry: 2,
  });

  const refresh = async () => {
    setRunning(true);
    try {
      const fresh = await apiJson("/operational-intelligence/report?force=true", undefined, 120_000);
      qc.setQueryData(KEY, fresh);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-zinc-100">
            <Activity className="h-5 w-5 text-teal-400" /> Operational Intelligence
          </h1>
          <p className="text-[11px] text-zinc-500">
            Phase 27.1 · read-only composition of canonical stores · PAPER TRADING / RESEARCH ONLY
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={refresh} disabled={running} data-testid="button-refresh">
          <RefreshCw className={cn("mr-1 h-3 w-3", running && "animate-spin")} /> Refresh
        </Button>
      </div>

      {isLoading && <div className="p-8 text-center text-sm text-zinc-500" data-testid="loading">Composing operational intelligence…</div>}
      {!!error && (
        <div className="rounded border border-rose-900 bg-rose-950/30 p-3 text-sm text-rose-400" data-testid="error">
          Failed to load report: {String((error as Error).message ?? error)}
        </div>
      )}

      {d?.ok && (
        <>
          {Object.entries(d.sources ?? {}).some(([, v]: any) => !v.available) && (
            <div className="rounded border border-amber-900 bg-amber-950/30 p-2 text-[11px] text-amber-400" data-testid="source-warnings">
              Unavailable sources:{" "}
              {Object.entries(d.sources).filter(([, v]: any) => !v.available)
                .map(([k, v]: any) => `${k} (${v.error ?? "unavailable"})`).join("; ")}
            </div>
          )}
          <ExecutiveSummary ex={d.executive_summary} shortcuts={d.shortcuts} />
          <div className="grid gap-3 lg:grid-cols-2">
            <Timeline t={d.timeline} shortcuts={d.shortcuts} />
            <HistoryStats h={d.history_stats} />
          </div>
          <Checklist c={d.checklist} />
          <div className="grid gap-3 lg:grid-cols-2">
            <Comparison c={d.session_comparison} />
            <Insights list={d.insights} />
          </div>
          <HealthScore h={d.health_score} />
          <div className="text-[10px] text-zinc-600">{d.note}</div>
        </>
      )}
    </div>
  );
}
