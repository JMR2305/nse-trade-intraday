/**
 * IntelWidgets.tsx — Phase 25B Mission Control intelligence widgets.
 *
 * Mission Map · AI Health · AI Learning · Alert Center.
 * PURE DASHBOARD: every widget reads existing endpoints (unified replay
 * snapshot, agent framework, autonomous ops, learning layer, phase24,
 * observability/operations alerts, notification deliveries). No business
 * logic or duplicate calculations here. ADVISORY-ONLY labelling preserved.
 */
import { useMemo, useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle, Bell, Bot, BrainCircuit, GitBranch,
} from "lucide-react";
import { Widget, useWidgetQuery, timeAgo } from "./Widget";

// ── Shared types ─────────────────────────────────────────────────────────────

export interface ReplayStage {
  id: string; label: string; order: number;
  stocks_in: number; stocks_out: number;
  rejected: number; pending: number; cancelled: number;
  duration_ms: number | null; status: string;
}
export interface ReplayResp { stages?: ReplayStage[]; scan_id?: string; snapshot_ts?: string; error?: string }

// ── Mission Map — Universe → Portfolio visual flow ───────────────────────────
// Shares the SAME replay query as the pipeline panel (no separate count fetch).
//
// Layout: outer wrapper is overflow-x-auto; inner flex uses min-w-max so every
// stage box keeps its natural width and scrolls cleanly on tablet / mobile
// instead of overlapping. Stage wrappers are shrink-0 so the arrow connectors
// never cause boxes to collapse below their content width.

export function MissionMapWidget({ replayQ, scanning }: {
  replayQ: UseQueryResult<ReplayResp>; scanning: boolean;
}) {
  const stages = useMemo(
    () => [...(replayQ.data?.stages ?? [])].sort((a, b) => a.order - b.order),
    [replayQ.data],
  );

  const totalIn   = stages[0]?.stocks_in ?? 0;
  const totalOut  = stages[stages.length - 1]?.stocks_out ?? 0;
  const totalRej  = stages.reduce((s, r) => s + (r.rejected ?? 0), 0);

  return (
    <Widget
      title="Mission Map" icon={GitBranch} query={replayQ} refreshMs={30_000}
      testId="mc-mission-map" skeletonClass="h-28"
      headerExtra={
        <div className="flex items-center gap-2 flex-wrap">
          {replayQ.data?.scan_id && (
            <span
              className="text-[9px] text-muted-foreground font-mono max-w-[130px] truncate"
              title={replayQ.data.scan_id}
            >
              {replayQ.data.scan_id.slice(0, 12)}…
            </span>
          )}
          {totalIn > 0 && (
            <span className="text-[9px] text-muted-foreground hidden sm:inline">
              {totalIn} in · <span className="text-emerald-400">{totalOut} out</span>
              {totalRej > 0 && <> · <span className="text-red-400">{totalRej} rej</span></>}
            </span>
          )}
          {scanning && <Badge className="animate-pulse text-[9px] px-1.5 py-0">PROCESSING</Badge>}
        </div>
      }
    >
      {stages.length === 0 ? (
        <p className="text-xs text-muted-foreground">No replay snapshot yet — the map lights up after the next scan.</p>
      ) : (
        /* ── Horizontal-scroll container ────────────────────────────────
           overflow-x-auto on the outer div + min-w-max on the inner flex
           means the row scrolls rather than compressing / overlapping.
           Each stage wrapper is shrink-0 so no box can ever be squashed. */
        <div className="overflow-x-auto pb-2 -mx-0.5 px-0.5" data-testid="mc-mission-map-flow">
          <div className="flex items-stretch gap-1.5 min-w-max">
            {stages.map((s, i) => {
              const active = scanning && (s.status === "RUNNING" || s.status === "ACTIVE");
              const done   = s.stocks_out > 0 || s.status === "COMPLETED" || s.status === "DONE";
              const pctOut = s.stocks_in > 0 ? Math.round((s.stocks_out / s.stocks_in) * 100) : null;
              return (
                <div key={s.id} className="flex items-center gap-1.5 shrink-0">
                  <div
                    data-testid={`mc-map-stage-${s.id.toLowerCase()}`}
                    className={[
                      "rounded-lg border px-2.5 py-2 text-center w-[82px] transition-colors",
                      active ? "border-primary bg-primary/15 animate-pulse"
                        : done ? "border-emerald-700/40 bg-emerald-950/30"
                          : "border-border/60 bg-muted/20",
                    ].join(" ")}
                    title={`${s.label}: in ${s.stocks_in} · out ${s.stocks_out} · rej ${s.rejected}${s.duration_ms ? ` · ${(s.duration_ms / 1000).toFixed(1)}s` : ""}`}
                  >
                    {/* Stage name — no truncate; box is fixed-width so label is always readable */}
                    <p className="text-[9px] font-semibold uppercase tracking-wide leading-tight whitespace-nowrap overflow-hidden text-ellipsis">
                      {s.label}
                    </p>
                    {/* in → out */}
                    <p className="text-[11px] font-mono mt-0.5">
                      <span className="text-muted-foreground">{s.stocks_in}→</span>
                      <b className={done ? "text-emerald-400" : "text-foreground"}>{s.stocks_out}</b>
                    </p>
                    {/* Rejected */}
                    {s.rejected > 0 && (
                      <p className="text-[9px] text-red-400 leading-tight">−{s.rejected} rej</p>
                    )}
                    {/* Pass-rate pill */}
                    {pctOut !== null && s.stocks_in > 0 && (
                      <p className="text-[8px] text-muted-foreground/70 leading-tight">{pctOut}%✓</p>
                    )}
                    {/* Duration */}
                    {s.duration_ms != null && (
                      <p className="text-[8px] text-muted-foreground/60 leading-tight">{(s.duration_ms / 1000).toFixed(1)}s</p>
                    )}
                  </div>
                  {i < stages.length - 1 && (
                    <span className="text-muted-foreground/40 text-[10px] shrink-0 select-none">→</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </Widget>
  );
}

// ── AI Health — per-agent status from the agent framework ───────────────────

interface AgentRow {
  agent_id: string; name: string; state?: string; health_score?: number;
  heartbeat_status?: string; current_activity?: string; last_error?: string | null;
  queue_depth?: number; processing_time_ms?: number;
}
interface AgentsResp { available?: boolean; agents?: AgentRow[] }
interface AutoOpsResp {
  registered_agents?: number; healthy_agents?: number; failed_agents?: number;
  warning_agents?: number; queue_depth?: number; avg_decision_latency_ms?: number;
  overall_health?: string; overall_health_score?: number; heartbeat_status?: string;
}

function stateTone(state?: string): string {
  const s = (state ?? "").toUpperCase();
  if (s === "RUNNING" || s === "ACTIVE") return "text-emerald-400";
  if (s === "WAITING" || s === "STARTING") return "text-amber-400";
  if (s === "FAILED" || s === "ERROR") return "text-red-400";
  return "text-muted-foreground";
}

export function AiHealthWidget() {
  const agentsQ = useWidgetQuery<AgentsResp>({
    queryKey: ["mc", "ai-agents"], path: "/agent-framework/agents",
    refetchInterval: 30_000, timeoutMs: 45_000,
  });
  const opsQ = useWidgetQuery<AutoOpsResp>({
    queryKey: ["mc", "auto-ops"], path: "/autonomous-ops/snapshot",
    refetchInterval: 60_000, timeoutMs: 90_000,
  });
  const agents = agentsQ.data?.agents ?? [];
  const o = opsQ.data;
  return (
    <Widget
      title="AI Health" icon={Bot} query={agentsQ} refreshMs={30_000}
      testId="mc-ai-health" skeletonClass="h-56"
      headerExtra={o?.overall_health && (
        <Badge
          variant="outline"
          className={`text-[9px] px-1.5 py-0 ${
            o.overall_health === "HEALTHY" ? "border-emerald-500/40 text-emerald-300"
              : o.overall_health === "CRITICAL" ? "border-red-500/40 text-red-300"
                : "border-amber-500/40 text-amber-300"
          }`}
        >
          {o.overall_health}{o.overall_health_score != null ? ` · ${Math.round(o.overall_health_score)}` : ""}
        </Badge>
      )}
    >
      {o && (
        <div className="grid grid-cols-4 gap-2 text-[11px] mb-2">
          <div><p className="text-muted-foreground text-[10px]">Healthy</p><p className="font-semibold text-emerald-400">{o.healthy_agents ?? "—"}/{o.registered_agents ?? "—"}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Failed</p><p className={`font-semibold ${(o.failed_agents ?? 0) > 0 ? "text-red-400" : ""}`}>{o.failed_agents ?? 0}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Queue</p><p className="font-semibold">{o.queue_depth ?? "—"}</p></div>
          <div><p className="text-muted-foreground text-[10px]">Latency</p><p className="font-semibold">{o.avg_decision_latency_ms != null ? `${o.avg_decision_latency_ms.toFixed(0)}ms` : "—"}</p></div>
        </div>
      )}
      {agents.length === 0 ? (
        <p className="text-xs text-muted-foreground">No agent snapshots yet.</p>
      ) : (
        <div className="space-y-0.5 max-h-[210px] overflow-y-auto">
          {agents.map((a) => (
            <div key={a.agent_id} className="flex items-center gap-2 text-[10px] border-b border-border/40 py-1 last:border-0" data-testid={`mc-agent-${a.agent_id}`}>
              <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                (a.state ?? "").toUpperCase() === "RUNNING" ? "bg-emerald-400"
                  : (a.state ?? "").toUpperCase() === "FAILED" ? "bg-red-400" : "bg-slate-500"
              }`} />
              <span className="w-28 shrink-0 font-medium truncate">{a.name}</span>
              <span className={`w-16 shrink-0 ${stateTone(a.state)}`}>{a.state ?? "—"}</span>
              <span className="w-10 shrink-0 text-muted-foreground">{a.health_score != null ? `${a.health_score}%` : "—"}</span>
              <span className="truncate text-muted-foreground flex-1">
                {a.last_error ? <span className="text-red-400">{a.last_error}</span> : a.current_activity ?? ""}
              </span>
              {(a.queue_depth ?? 0) > 0 && <span className="text-amber-400 shrink-0">q{a.queue_depth}</span>}
            </div>
          ))}
        </div>
      )}
      {opsQ.isError && (
        <p className="text-[10px] text-amber-400/80 pt-1">Autonomous-ops summary unavailable ({(opsQ.error as Error)?.message}).</p>
      )}
    </Widget>
  );
}

// ── AI Learning — learning-layer + phase24 (advisory-only) ──────────────────

interface P24Overview {
  daily_lessons?: { trades?: number; mistakes?: { description?: string; mistake?: string; count?: number }[]; improvements?: string[] };
  best_worst?: { best?: { strategy?: string; name?: string }[]; worst?: { strategy?: string; name?: string }[] };
  calibration?: { overall_calibration_error?: number; total_trades?: number };
  scorecard?: { overall?: number; strengths?: string[]; weaknesses?: string[] };
}
interface LLSummary {
  best_strategy?: string; worst_strategy?: string; top_lessons?: string[];
  confidence_calibration?: number; learning_health?: string; trades_learned_today?: number;
}
interface P24Recs { items?: { title?: string; recommendation?: string; description?: string; status?: string }[] }

export function AiLearningWidget() {
  const overviewQ = useWidgetQuery<P24Overview>({
    queryKey: ["mc", "p24-overview"], path: "/phase24/overview",
    refetchInterval: 120_000, timeoutMs: 150_000,
  });
  const llQ = useWidgetQuery<LLSummary>({
    queryKey: ["mc", "ll-summary"], path: "/learning-layer/summary",
    refetchInterval: 300_000, timeoutMs: 200_000,
  });
  const recsQ = useWidgetQuery<P24Recs>({
    queryKey: ["mc", "p24-recs"], path: "/phase24/recommendations?status=PROPOSED",
    refetchInterval: 120_000, timeoutMs: 60_000,
  });

  const ov = overviewQ.data;
  const ll = llQ.data;
  const best = ll?.best_strategy && ll.best_strategy !== "N/A"
    ? ll.best_strategy
    : ov?.best_worst?.best?.[0]?.strategy ?? ov?.best_worst?.best?.[0]?.name ?? null;
  const worst = ll?.worst_strategy && ll.worst_strategy !== "N/A"
    ? ll.worst_strategy
    : ov?.best_worst?.worst?.[0]?.strategy ?? ov?.best_worst?.worst?.[0]?.name ?? null;
  const topMistake = ov?.daily_lessons?.mistakes?.[0];
  const rec = recsQ.data?.items?.[0];
  const lessons = (ll?.top_lessons ?? []).slice(0, 3);
  const calib = ov?.calibration?.overall_calibration_error ?? null;

  return (
    <Widget
      title="AI Learning" icon={BrainCircuit} query={overviewQ} refreshMs={120_000}
      testId="mc-ai-learning" skeletonClass="h-56"
      headerExtra={<Badge variant="outline" className="text-[9px] px-1.5 py-0 border-amber-500/40 text-amber-300">ADVISORY ONLY</Badge>}
    >
      <div className="grid grid-cols-3 gap-2 text-[11px] mb-2">
        <div>
          <p className="text-muted-foreground text-[10px]">Daily AI score</p>
          <p className="font-semibold text-sm">{ov?.scorecard?.overall != null ? `${ov.scorecard.overall}/10` : "—"}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Calibration err</p>
          <p className={`font-semibold ${calib != null && calib > 0.2 ? "text-amber-400" : ""}`}>
            {calib != null ? calib.toFixed(3) : "—"}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Learned today</p>
          <p className="font-semibold">{ll?.trades_learned_today ?? ov?.daily_lessons?.trades ?? "—"}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-[10px] mb-2">
        <div className="rounded-lg bg-muted/20 border border-border/60 p-1.5">
          <p className="text-muted-foreground">Best strategy</p>
          <p className="font-semibold text-emerald-400 truncate">{best ?? "—"}</p>
        </div>
        <div className="rounded-lg bg-muted/20 border border-border/60 p-1.5">
          <p className="text-muted-foreground">Worst strategy</p>
          <p className="font-semibold text-red-400 truncate">{worst ?? "—"}</p>
        </div>
      </div>
      {topMistake && (
        <p className="text-[10px] mb-1">
          <span className="text-muted-foreground">Top mistake: </span>
          <span className="text-amber-300">{topMistake.description ?? topMistake.mistake ?? "—"}</span>
        </p>
      )}
      {rec && (
        <p className="text-[10px] mb-1">
          <span className="text-muted-foreground">Top recommendation: </span>
          {rec.title ?? rec.recommendation ?? rec.description}
        </p>
      )}
      <p className="text-[10px] text-muted-foreground mb-0.5">Today's lessons</p>
      {llQ.isLoading ? (
        <p className="text-[10px] text-muted-foreground animate-pulse">Loading learning summary (slow endpoint)…</p>
      ) : llQ.isError ? (
        <p className="text-[10px] text-amber-400/80">Learning summary unavailable ({(llQ.error as Error)?.message}).</p>
      ) : lessons.length === 0 ? (
        <p className="text-[10px] text-muted-foreground">No lessons yet — populates as trades close.</p>
      ) : (
        <ul className="space-y-0.5">
          {lessons.map((l, i) => (
            <li key={i} className="text-[10px] text-muted-foreground flex gap-1"><span className="text-teal-400">•</span><span>{l}</span></li>
          ))}
        </ul>
      )}
    </Widget>
  );
}

// ── Alert Center — consolidated alerts, deduped in display ──────────────────

interface ObsAlert {
  alert_id?: string; severity?: string; category?: string; title?: string;
  detail?: string; generated_at?: string;
}
interface ObsAlertsResp { critical_alerts?: ObsAlert[]; warnings?: ObsAlert[]; info?: ObsAlert[]; status?: string }
interface OpsAlertsResp { status?: string; alerts?: ObsAlert[]; items?: ObsAlert[] }
interface Delivery { id: number; kind?: string; severity?: string; title?: string; status?: string; createdAt?: string }

const sevTone: Record<string, string> = {
  CRITICAL: "text-red-400 border-red-500/40",
  ERROR: "text-red-400 border-red-500/40",
  WARNING: "text-amber-400 border-amber-500/40",
  INFO: "text-sky-400 border-sky-500/40",
};

// Ack/dismiss state is display-level only (Phase 25.1 Part 10) — persisted in
// localStorage keyed by severity|title; no backend mutation exists for alerts.
const ALERT_STATE_KEY = "mc-alert-state-v1";
type AlertState = Record<string, "acked" | "dismissed">;
function loadAlertState(): AlertState {
  try {
    const raw = JSON.parse(localStorage.getItem(ALERT_STATE_KEY) ?? "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch { return {}; }
}

export function AlertCenterWidget() {
  const obsQ = useWidgetQuery<ObsAlertsResp>({
    queryKey: ["mc", "obs-alerts"], path: "/observability/alerts",
    refetchInterval: 30_000, timeoutMs: 60_000,
  });
  const opsQ = useWidgetQuery<OpsAlertsResp>({
    queryKey: ["mc", "ops-alerts"], path: "/operations/alerts",
    refetchInterval: 60_000, timeoutMs: 90_000,
  });
  const notifQ = useWidgetQuery<{ deliveries?: Delivery[] }>({
    queryKey: ["mc", "notif-deliveries"], path: "/notifications/deliveries?limit=20",
    refetchInterval: 60_000, timeoutMs: 30_000,
  });

  const alerts = useMemo(() => {
    const rows: { key: string; severity: string; source: string; title: string; detail?: string; ts?: string }[] = [];
    const push = (a: ObsAlert, source: string) => {
      if (!a?.title) return;
      rows.push({
        key: `${(a.severity ?? "INFO").toUpperCase()}|${a.title}`,
        severity: (a.severity ?? "INFO").toUpperCase(),
        source: a.category ?? source, title: a.title, detail: a.detail, ts: a.generated_at,
      });
    };
    for (const a of obsQ.data?.critical_alerts ?? []) push(a, "SYSTEM");
    for (const a of obsQ.data?.warnings ?? []) push(a, "SYSTEM");
    for (const a of obsQ.data?.info ?? []) push(a, "SYSTEM");
    for (const a of opsQ.data?.alerts ?? opsQ.data?.items ?? []) push(a, "OPS");
    for (const d of notifQ.data?.deliveries ?? []) {
      if (!d.title) continue;
      rows.push({
        key: `${(d.severity ?? "INFO").toUpperCase()}|${d.title}`,
        severity: (d.severity ?? "INFO").toUpperCase(),
        source: (d.kind ?? "notification").toUpperCase(), title: d.title, ts: d.createdAt,
      });
    }
    // Display-level dedup by severity+title, keep first (newest sources first).
    const seen = new Set<string>();
    const out = rows.filter((r) => (seen.has(r.key) ? false : (seen.add(r.key), true)));
    const rank: Record<string, number> = { CRITICAL: 0, ERROR: 1, WARNING: 2, INFO: 3 };
    return out.sort((a, b) => (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9)).slice(0, 20);
  }, [obsQ.data, opsQ.data, notifQ.data]);

  const [alertState, setAlertState] = useState<AlertState>(loadAlertState);
  const setState = (key: string, v: "acked" | "dismissed" | null) => {
    setAlertState((prev) => {
      const next = { ...prev };
      if (v === null) delete next[key]; else next[key] = v;
      try { localStorage.setItem(ALERT_STATE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  };
  const visible = alerts.filter((a) => alertState[a.key] !== "dismissed");
  const dismissedCount = alerts.length - visible.length;
  const critCount = visible.filter(
    (a) => (a.severity === "CRITICAL" || a.severity === "ERROR") && alertState[a.key] !== "acked").length;

  return (
    <Widget
      title="Alert Center" icon={Bell} query={obsQ} refreshMs={30_000}
      testId="mc-alert-center" skeletonClass="h-40"
      headerExtra={critCount > 0 && (
        <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-red-500/40 text-red-300">
          {critCount} critical
        </Badge>
      )}
    >
      {visible.length === 0 ? (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> No active alerts.
        </p>
      ) : (
        <div className="space-y-1 max-h-[190px] overflow-y-auto">
          {visible.map((a) => {
            const acked = alertState[a.key] === "acked";
            return (
              <div key={a.key}
                className={`flex items-start gap-2 text-[10px] rounded-lg border border-border/50 bg-muted/10 px-2 py-1 ${acked ? "opacity-50" : ""}`}
                data-testid={`mc-alert-${acked ? "acked" : "active"}`}>
                <AlertTriangle className={`w-3 h-3 mt-0.5 shrink-0 ${(sevTone[a.severity] ?? "").split(" ")[0]}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className={`font-semibold ${(sevTone[a.severity] ?? "").split(" ")[0]}`}>{a.severity}</span>
                    <span className="text-muted-foreground uppercase text-[9px]">{a.source}</span>
                    {acked && <span className="text-[9px] text-emerald-400/80 uppercase">ack</span>}
                    <span className="ml-auto text-muted-foreground text-[9px]">{a.ts ? timeAgo(a.ts) : ""}</span>
                  </div>
                  <p className="truncate font-medium">{a.title}</p>
                  {a.detail && <p className="truncate text-muted-foreground">{a.detail}</p>}
                </div>
                <div className="flex flex-col gap-0.5 shrink-0">
                  {!acked && (
                    <button className="text-[9px] px-1 rounded border border-border/60 text-muted-foreground hover:text-emerald-300 hover:border-emerald-500/40"
                      onClick={() => setState(a.key, "acked")} data-testid="mc-alert-ack">Ack</button>
                  )}
                  <button className="text-[9px] px-1 rounded border border-border/60 text-muted-foreground hover:text-red-300 hover:border-red-500/40"
                    onClick={() => setState(a.key, "dismissed")} data-testid="mc-alert-dismiss">✕</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {dismissedCount > 0 && (
        <button className="text-[9px] text-muted-foreground underline pt-1"
          onClick={() => { alerts.forEach((a) => alertState[a.key] === "dismissed" && setState(a.key, null)); }}
          data-testid="mc-alert-restore">
          {dismissedCount} dismissed — restore
        </button>
      )}
      {(opsQ.data?.status === "DISABLED") && (
        <p className="text-[9px] text-muted-foreground pt-1">Operations Centre alerts disabled (OPERATIONS_CENTER_ENABLED=false).</p>
      )}
    </Widget>
  );
}
