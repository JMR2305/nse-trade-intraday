/**
 * OperatorAnalytics.tsx — Phase 27E: Operator Analytics.
 *
 * "How has the platform been behaving?" — one page over canonical sources:
 *   1. Session summary            (replay sessions)
 *   2. Pipeline funnel + timing   (unified replay counts + pipeline_events)
 *   3. Rejection breakdown        (canonical reason codes, drill-down)
 *   4. Decision distribution      (decision events + canonical snapshot)
 *   5. Risk interventions         (PRECHECK / RISK events)
 *   6. Cross-scan trends          (per-scan event aggregates)
 *   7. Performance & time-of-day  (existing paper-analytics endpoints —
 *                                  never recomputed here)
 *
 * READ-ONLY · ADVISORY-ONLY. No trading state is ever modified.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2, RefreshCw, AlertTriangle, Activity, Filter, GitBranch,
  ShieldCheck, PieChart, TrendingUp, Clock, ListTree, Gauge,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */

const LABEL = "OPERATOR ANALYTICS — READ-ONLY — PAPER TRADING / RESEARCH ONLY";
const SLOW_TIMEOUT_MS = 60_000;

// ---------------------------------------------------------------------------
// UI primitives
// ---------------------------------------------------------------------------

function SectionCard({ title, icon: Icon, source, children, className }: {
  title: string; icon: any; source?: string;
  children: React.ReactNode; className?: string;
}) {
  return (
    <Card className={cn("border-zinc-800 bg-zinc-950", className)}>
      <CardHeader className="py-3">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm text-zinc-200">
          <Icon className="h-4 w-4 text-sky-400" /> {title}
          {source && (
            <span className="ml-auto text-[10px] font-normal normal-case text-zinc-500">
              source: {source}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">{children}</CardContent>
    </Card>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  const fmt = (v: any) => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "number" && (!isFinite(v) || isNaN(v))) return "—";
    return String(v);
  };
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={cn("text-sm font-mono", cls ?? "text-zinc-200")}>{fmt(value)}</div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded border border-dashed border-zinc-800 p-4 text-center text-zinc-500">
      {text}
    </div>
  );
}

function EvidenceBadge({ evidence }: { evidence?: string }) {
  if (!evidence || evidence === "OK") return null;
  const map: Record<string, { text: string; cls: string }> = {
    SOURCE_UNAVAILABLE: { text: "SOURCE UNAVAILABLE", cls: "border-rose-700 text-rose-400" },
    PARTIAL: { text: "PARTIAL — FETCH TRUNCATED", cls: "border-amber-700 text-amber-400" },
    VERIFIED_EMPTY: { text: "VERIFIED EMPTY", cls: "border-zinc-700 text-zinc-500" },
  };
  const m = map[evidence] ?? { text: evidence, cls: "border-zinc-700 text-zinc-400" };
  return <Badge variant="outline" className={cn("text-[10px]", m.cls)}>{m.text}</Badge>;
}

function SourcesBanner({ sources }: { sources?: Record<string, any> }) {
  if (!sources) return null;
  const issues: string[] = [];
  for (const [name, st] of Object.entries(sources)) {
    if (!st?.available) issues.push(`${name}: unavailable${st?.error ? ` (${st.error})` : ""}`);
    else if (st?.truncated) issues.push(`${name}: fetch truncated at ${st.limit} events — counts are partial`);
  }
  if (!issues.length) return null;
  return (
    <div className="flex items-start gap-2 rounded border border-amber-900 bg-amber-950/30 p-2 text-[11px] text-amber-400"
      data-testid="sources-banner">
      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
      <div>
        <div className="font-semibold">Evidence incomplete — some canonical sources are unavailable or truncated:</div>
        {issues.map((t) => <div key={t}>{t}</div>)}
      </div>
    </div>
  );
}

function InsufficientBadge({ note }: { note?: string }) {
  return (
    <Badge variant="outline" className="border-amber-700 text-amber-400 text-[10px]">
      {note ?? "INSUFFICIENT TELEMETRY"}
    </Badge>
  );
}

function fmtMs(v: any): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms`;
}

function fmtTs(ts: any): string {
  if (!ts) return "—";
  try {
    return new Date(String(ts)).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
      hour: "2-digit", minute: "2-digit",
    }) + " IST";
  } catch { return String(ts); }
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

function SessionSummary({ sessions, currentScanId }: { sessions: any[]; currentScanId?: string }) {
  if (!sessions?.length) return <Empty text="No real replay sessions recorded yet (demo sessions excluded)." />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-zinc-800 text-[10px] uppercase text-zinc-500">
            <th className="py-1 pr-2">Scan</th><th className="py-1 pr-2">Time</th>
            <th className="py-1 pr-2">Status</th><th className="py-1 pr-2">Universe</th>
            <th className="py-1 pr-2">Processed</th><th className="py-1 pr-2">Recs</th>
            <th className="py-1 pr-2">BUYs</th><th className="py-1 pr-2">Paper orders</th>
            <th className="py-1">Duration</th>
          </tr>
        </thead>
        <tbody>
          {sessions.slice(0, 10).map((s: any) => (
            <tr key={s.scan_id}
              className={cn("border-b border-zinc-900",
                s.scan_id === currentScanId && "bg-sky-950/30")}>
              <td className="py-1 pr-2 font-mono text-[10px]">{String(s.scan_id).slice(0, 14)}
                {s.scan_id === currentScanId && (
                  <Badge className="ml-1 bg-sky-900 text-sky-300 text-[9px]">current</Badge>)}
              </td>
              <td className="py-1 pr-2 text-zinc-400">{fmtTs(s.snapshot_ts)}</td>
              <td className="py-1 pr-2">{s.status ?? "—"}</td>
              <td className="py-1 pr-2 font-mono">{s.universe_size ?? "—"}</td>
              <td className="py-1 pr-2 font-mono">{s.symbols_processed ?? "—"}</td>
              <td className="py-1 pr-2 font-mono">{s.total_recommendations ?? "—"}</td>
              <td className="py-1 pr-2 font-mono text-emerald-400">{s.buy_signals ?? "—"}</td>
              <td className="py-1 pr-2 font-mono">{s.paper_orders ?? "—"}</td>
              <td className="py-1 font-mono">{s.duration_s != null ? `${s.duration_s}s` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Funnel({ funnel }: { funnel: any }) {
  const stages: any[] = funnel?.stages ?? [];
  if (!stages.length) return <Empty text="No replay stages for this scan." />;
  const maxIn = Math.max(1, ...stages.map((s) => Number(s.stocks_in) || 0));
  return (
    <div className="space-y-1">
      {stages.map((s: any) => {
        const t = s.timing ?? {};
        return (
          <div key={s.id} data-testid={`funnel-stage-${s.id}`}
            className="grid grid-cols-12 items-center gap-2 rounded border border-zinc-900 bg-zinc-900/30 px-2 py-1">
            <div className="col-span-3 truncate text-zinc-300">{s.label ?? s.id}</div>
            <div className="col-span-3">
              <div className="h-2 rounded bg-zinc-800">
                <div className="h-2 rounded bg-sky-600"
                  style={{ width: `${((Number(s.stocks_out) || 0) / maxIn) * 100}%` }} />
              </div>
            </div>
            <div className="col-span-3 font-mono text-[10px] text-zinc-400">
              {s.stocks_in}→{s.stocks_out}
              {Number(s.rejected) > 0 && <span className="text-rose-400"> · rej {s.rejected}</span>}
              {Number(s.pending) > 0 && <span className="text-amber-400"> · pend {s.pending}</span>}
              {Number(s.cancelled) > 0 && <span className="text-zinc-500"> · canc {s.cancelled}</span>}
              <span className="text-zinc-500"> · {s.conversion_pct != null ? `${s.conversion_pct}%` : "—"}</span>
            </div>
            <div className="col-span-3 text-right text-[10px]">
              {t.insufficient_telemetry
                ? <InsufficientBadge />
                : <span className="font-mono text-zinc-400">
                    avg {fmtMs(t.avg_ms)} · med {fmtMs(t.median_ms)} · p95 {fmtMs(t.p95_ms)}
                    <span className="text-zinc-600"> ({t.samples})</span>
                  </span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Rejections({ rejections }: { rejections: any }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows: any[] = rejections?.reasons ?? [];
  if (!rows.length) {
    if (rejections?.evidence === "SOURCE_UNAVAILABLE")
      return <EvidenceBadge evidence="SOURCE_UNAVAILABLE" />;
    return <Empty text="No rejections recorded for this scan (event store verified empty)." />;
  }
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-zinc-400">
        <span>Rejected events: <span className="font-mono text-zinc-200">{rejections.rejected_events}</span></span>
        <span>· Reason occurrences: <span className="font-mono text-zinc-200">{rejections.reason_occurrences}</span></span>
        <EvidenceBadge evidence={rejections.evidence} />
      </div>
      <div className="text-[10px] text-zinc-600">% = share of reason occurrences (one event can fail several gates)</div>
      {rows.map((r: any) => {
        const key = `${r.event_type}|${r.reason_code}`;
        return (
          <div key={key} className="rounded border border-zinc-900 bg-zinc-900/30">
            <button className="flex w-full items-center gap-2 px-2 py-1 text-left"
              onClick={() => setOpen(open === key ? null : key)}
              data-testid={`rejection-${r.event_type}`}>
              <Badge variant="outline" className="border-zinc-700 text-[9px] text-zinc-400">{r.group}</Badge>
              <span className="flex-1 truncate font-mono text-[11px] text-zinc-300">{r.reason_code}</span>
              <span className="font-mono text-rose-400">{r.count}</span>
              <span className="w-12 text-right font-mono text-zinc-500">{r.pct_of_occurrences}%</span>
            </button>
            {open === key && (
              <div className="border-t border-zinc-900 px-2 py-1 text-[10px] text-zinc-400">
                <div>event type: <span className="font-mono">{r.event_type}</span></div>
                <div>symbols: {r.symbols?.length ? r.symbols.join(", ") : "—"}</div>
                <div>event ids: {r.event_ids?.length ? r.event_ids.join(", ") : "—"}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Decisions({ decisions }: { decisions: any }) {
  const ev = decisions?.event_decisions ?? {};
  const snap = decisions?.snapshot_distribution ?? {};
  const colors: Record<string, string> = {
    "STRONG BUY": "text-emerald-300", BUY: "text-emerald-400",
    WATCH: "text-amber-400", HOLD: "text-sky-400",
    IGNORE: "text-zinc-500", SELL: "text-rose-400", REJECT: "text-rose-400",
  };
  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1 text-[10px] uppercase text-zinc-500">Decision events (this scan)</div>
        {ev.total ? (
          <div className="flex flex-wrap gap-2">
            {Object.entries(ev.counts ?? {}).map(([k, v]: any) => (
              <Stat key={k} label={k} value={`${v} (${ev.pct?.[k] ?? 0}%)`} cls={colors[k]} />
            ))}
          </div>
        ) : ev.evidence === "SOURCE_UNAVAILABLE"
          ? <EvidenceBadge evidence="SOURCE_UNAVAILABLE" />
          : <Empty text="No decision events for this scan (event store verified empty)." />}
      </div>
      <div>
        <div className="mb-1 text-[10px] uppercase text-zinc-500">Canonical snapshot distribution</div>
        {snap.available ? (
          <>
            <div className="flex flex-wrap gap-2">
              {(snap.actions ?? []).map((a: any) => (
                <Stat key={a.action} label={a.action} value={`${a.count} (${a.pct}%)`} cls={colors[a.action]} />
              ))}
              {snap.regime && <Stat label="Regime" value={snap.regime} />}
            </div>
            {(snap.by_sector ?? []).length > 0 && (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-[10px]">
                  <thead><tr className="border-b border-zinc-800 uppercase text-zinc-500">
                    <th className="py-1 pr-2">Sector</th><th className="py-1">Actions</th></tr></thead>
                  <tbody>
                    {snap.by_sector.map((s: any) => (
                      <tr key={s.sector} className="border-b border-zinc-900">
                        <td className="py-1 pr-2 text-zinc-300">{s.sector}</td>
                        <td className="py-1 font-mono text-zinc-400">
                          {Object.entries(s.actions).map(([a, c]: any) => `${a}:${c}`).join("  ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : <InsufficientBadge note={snap.note ?? "SNAPSHOT UNAVAILABLE"} />}
      </div>
    </div>
  );
}

function RiskInterventions({ risk }: { risk: any }) {
  const blocks = [
    { key: "risk", title: "Risk gates" },
    { key: "portfolio_precheck", title: "Portfolio pre-check" },
  ];
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {blocks.map(({ key, title }) => {
        const b = risk?.[key];
        if (!b) return <Empty key={key} text={`No ${title} data.`} />;
        return (
          <div key={key} className="rounded border border-zinc-900 bg-zinc-900/30 p-2" data-testid={`risk-${key}`}>
            <div className="mb-2 text-zinc-300">{title}</div>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Candidates" value={b.candidates} />
              <Stat label="Approved" value={b.approved} cls="text-emerald-400" />
              <Stat label="Blocked" value={b.blocked} cls={b.blocked ? "text-rose-400" : undefined} />
            </div>
            <div className="mt-1 text-[10px] text-zinc-500">
              block rate: {b.block_rate_pct != null ? `${b.block_rate_pct}%` : "—"}
              <span className="ml-2"><EvidenceBadge evidence={b.evidence} /></span>
            </div>
            {(b.reasons ?? []).length > 0 && (
              <div className="mt-2 space-y-1">
                {b.reasons.map((r: any) => (
                  <div key={r.reason_code} className="flex items-center gap-2 text-[10px]">
                    <span className="flex-1 truncate font-mono text-zinc-300">{r.reason_code}</span>
                    <span className="font-mono text-rose-400">{r.count}</span>
                    <span className="text-zinc-500">{r.symbols?.join(", ")}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Trends({ trends }: { trends: any }) {
  const points: any[] = trends?.points ?? [];
  if (!points.length) return <Empty text="No prior scans available for trends." />;
  return (
    <div className="space-y-2">
      {trends.note && <InsufficientBadge note={trends.note} />}
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead><tr className="border-b border-zinc-800 text-[10px] uppercase text-zinc-500">
            <th className="py-1 pr-2">Scan</th><th className="py-1 pr-2">Time</th>
            <th className="py-1 pr-2">Rejections</th><th className="py-1 pr-2">Decisions</th>
            <th className="py-1">Top rejection reasons</th></tr></thead>
          <tbody>
            {points.map((p: any) => (
              <tr key={p.scan_id} className={cn("border-b border-zinc-900", p.is_current && "bg-sky-950/30")}>
                <td className="py-1 pr-2 font-mono text-[10px]">{String(p.scan_id).slice(0, 14)}</td>
                <td className="py-1 pr-2 text-zinc-400">{fmtTs(p.snapshot_ts)}</td>
                <td className="py-1 pr-2 font-mono text-rose-400">
                  {p.rejected_events}
                  {p.evidence === "SOURCE_UNAVAILABLE" && <span className="ml-1 text-[9px] text-rose-500">src down</span>}
                  {p.evidence === "PARTIAL" && <span className="ml-1 text-[9px] text-amber-500">partial</span>}
                </td>
                <td className="py-1 pr-2 font-mono text-zinc-300">
                  {Object.entries(p.decisions ?? {}).map(([k, v]: any) => `${k}:${v}`).join("  ") || "—"}
                </td>
                <td className="py-1 text-[10px] text-zinc-500">
                  {Object.entries(p.rejections_by_reason ?? {})
                    .sort((a: any, b: any) => b[1] - a[1]).slice(0, 3)
                    .map(([k, v]: any) => `${k} (${v})`).join("; ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Performance() {
  const summary = useQuery({
    queryKey: ["/paper-analytics/summary"],
    queryFn: () => apiJson("/paper-analytics/summary", undefined, SLOW_TIMEOUT_MS),
    staleTime: 30_000, retry: 2,
  });
  const snapshot = useQuery({
    queryKey: ["/paper-analytics/snapshot"],
    queryFn: () => apiJson("/paper-analytics/snapshot", undefined, SLOW_TIMEOUT_MS),
    staleTime: 30_000, retry: 2,
  });
  const s: any = summary.data ?? {};
  const time: any = (snapshot.data as any)?.time_analytics ?? {};
  if (summary.isLoading) return <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />;
  if (!s.available) return <Empty text="Paper analytics unavailable or disabled." />;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
        <Stat label="Trades" value={s.total_trades} />
        <Stat label="Win rate" value={s.win_rate != null ? `${s.win_rate}%` : null} />
        <Stat label="Profit factor" value={s.profit_factor} />
        <Stat label="Expectancy" value={s.expectancy} />
        <Stat label="Total P&L" value={s.total_pnl}
          cls={Number(s.total_pnl) >= 0 ? "text-emerald-400" : "text-rose-400"} />
        <Stat label="Max DD" value={s.max_drawdown_pct != null ? `${s.max_drawdown_pct}%` : null} cls="text-rose-400" />
      </div>
      <div>
        <div className="mb-1 text-[10px] uppercase text-zinc-500">Time of day (IST sessions)</div>
        {time.available && (time.sessions ?? []).length ? (
          <div className="flex flex-wrap gap-2">
            {time.sessions.map((row: any, i: number) => (
              <Stat key={i} label={row.session ?? row.label ?? `#${i}`}
                value={`${row.trades ?? "—"} trades · ${row.win_rate ?? "—"}% win`} />
            ))}
            <Stat label="Best session" value={time.best_session} cls="text-emerald-400" />
            <Stat label="Worst session" value={time.worst_session} cls="text-rose-400" />
          </div>
        ) : <Empty text="No closed paper trades yet — time-of-day analytics will populate after trading sessions." />}
      </div>
      <div className="text-[10px] text-zinc-600">
        source: paper-analytics endpoints (paper trades only — never recomputed here)
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function OperatorAnalytics() {
  const report = useQuery({
    queryKey: ["/operator-analytics/report"],
    queryFn: () => apiJson("/operator-analytics/report", undefined, SLOW_TIMEOUT_MS),
    staleTime: 30_000, retry: 2, refetchInterval: 60_000,
  });
  const d: any = report.data ?? {};

  return (
    <div className="space-y-4 p-4" data-testid="operator-analytics-page">
      <div className="flex flex-wrap items-center gap-3">
        <Gauge className="h-6 w-6 text-sky-400" />
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Operator Analytics</h1>
          <div className="text-[10px] text-zinc-500">{LABEL}</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {d.scan_id && (
            <Badge variant="outline" className="border-zinc-700 font-mono text-[10px] text-zinc-400">
              scan {String(d.scan_id).slice(0, 14)}
            </Badge>
          )}
          {d.snapshot_ts && (
            <span className="text-[10px] text-zinc-500">{fmtTs(d.snapshot_ts)}</span>
          )}
          <Button size="sm" variant="outline" className="h-7 border-zinc-700 text-xs"
            onClick={() => report.refetch()} disabled={report.isFetching}>
            {report.isFetching
              ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              : <RefreshCw className="mr-1 h-3 w-3" />}
            Refresh
          </Button>
        </div>
      </div>

      {report.isLoading && (
        <div className="flex items-center gap-2 text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Aggregating canonical stores…
        </div>
      )}
      {report.isError && (
        <div className="flex items-center gap-2 rounded border border-rose-900 bg-rose-950/30 p-3 text-rose-400">
          <AlertTriangle className="h-4 w-4" />
          Failed to load operator analytics: {String((report.error as any)?.message ?? report.error)}
          <Button size="sm" variant="outline" className="ml-auto h-7 border-rose-800 text-xs"
            onClick={() => report.refetch()}>Retry</Button>
        </div>
      )}

      {d.ok && (
        <>
          {d.generated_at && (Date.now() - new Date(d.generated_at).getTime()) > 5 * 60 * 1000 && (
            <div
              className="flex items-center gap-2 rounded border border-amber-700 bg-amber-950/40 px-3 py-2 text-xs text-amber-300"
              data-testid="stale-data-warning"
            >
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
              <span>
                Data may be stale — report was generated {fmtTs(d.generated_at)}.
                Hit <strong>Refresh</strong> to fetch a fresh report.
              </span>
            </div>
          )}

          <SourcesBanner sources={d.sources} />

          <SectionCard title="Pipeline Funnel & Stage Timing" icon={GitBranch}
            source={d.funnel?.source}>
            <Funnel funnel={d.funnel} />
          </SectionCard>

          <div className="grid gap-4 lg:grid-cols-2">
            <SectionCard title="Rejection Breakdown" icon={Filter} source={d.rejections?.source}>
              <Rejections rejections={d.rejections} />
            </SectionCard>
            <SectionCard title="Decision Distribution" icon={PieChart} source={d.decisions?.source}>
              <Decisions decisions={d.decisions} />
            </SectionCard>
          </div>

          <SectionCard title="Risk Interventions" icon={ShieldCheck} source={d.risk_interventions?.source}>
            <RiskInterventions risk={d.risk_interventions} />
          </SectionCard>

          <SectionCard title="Cross-Scan Trends" icon={TrendingUp} source={d.trends?.source}>
            <Trends trends={d.trends} />
          </SectionCard>

          <SectionCard title="Session Summary" icon={ListTree}
            source={d.session_summary?.source}>
            <SessionSummary sessions={d.session_summary?.sessions ?? []} currentScanId={d.scan_id} />
          </SectionCard>

          <SectionCard title="Performance & Time of Day" icon={Clock}
            source="paper-analytics endpoints">
            <Performance />
          </SectionCard>

          <div className="flex items-center gap-2 text-[10px] text-zinc-600">
            <Activity className="h-3 w-3" />
            {d.note} · generated {fmtTs(d.generated_at)} · {d.event_count} events for this scan
          </div>
        </>
      )}
    </div>
  );
}
