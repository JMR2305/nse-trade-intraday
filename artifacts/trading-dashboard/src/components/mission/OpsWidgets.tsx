/**
 * OpsWidgets.tsx — Phase 25B Mission Control ops widgets.
 *
 * Replay · Backtest · Mission Timeline · Broker · System Health.
 * PURE DASHBOARD: canonical replay endpoints, existing /backtest API,
 * pipeline event store, kite/broker endpoints, observability summaries.
 * No new business logic or duplicate calculations.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "wouter";
import { useMutation, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Activity, CalendarClock, ExternalLink, FlaskConical, Landmark,
  Pause, Play, Server, SkipBack, SkipForward, Film,
} from "lucide-react";
import { Widget, useWidgetQuery, fmtINR, timeAgo, PnlText } from "./Widget";
import type { ReplayResp } from "./IntelWidgets";

// ── Replay widget — canonical replay endpoints only ─────────────────────────

interface ReplaySummary {
  scan_id?: string; snapshot_ts?: string;
  funnel?: Record<string, number>;
  overall_ai_score?: number; verdict?: string; scan_duration_s?: number;
}

export function ReplayWidget({ replayQ }: { replayQ: UseQueryResult<ReplayResp> }) {
  const summaryQ = useWidgetQuery<ReplaySummary>({
    queryKey: ["mc", "replay-summary"], path: "/replay/sessions/latest/summary",
    refetchInterval: 60_000, timeoutMs: 60_000,
  });
  const stages = useMemo(
    () => [...(replayQ.data?.stages ?? [])].sort((a, b) => a.order - b.order),
    [replayQ.data],
  );
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (playing && stages.length > 0) {
      timer.current = setInterval(() => {
        setCursor((c) => {
          if (c + 1 >= stages.length) { setPlaying(false); return c; }
          return c + 1;
        });
      }, 1_200);
    }
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, stages.length]);

  const cur = stages[Math.min(cursor, Math.max(0, stages.length - 1))];
  const s = summaryQ.data;

  return (
    <Widget
      // Widget state is driven by the SHARED replay snapshot query, so the
      // play/pause/jump controls stay usable even if the summary endpoint fails.
      title="Replay" icon={Film} query={replayQ} refreshMs={60_000}
      testId="mc-replay" skeletonClass="h-40"
      headerExtra={
        <Link href="/replay" className="text-[9px] text-teal-400 hover:underline flex items-center gap-0.5">
          Replay Center <ExternalLink className="w-2.5 h-2.5" />
        </Link>
      }
    >
      <div className="grid grid-cols-3 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Scanned</p><p className="font-semibold">{s?.funnel?.scanned ?? "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">BUY candidates</p><p className="font-semibold text-emerald-400">{s?.funnel?.buy_candidates ?? "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Paper trades</p><p className="font-semibold">{s?.funnel?.paper_trades ?? "—"}</p></div>
      </div>
      {s?.verdict && (
        <p className="text-[10px] text-muted-foreground mb-2">
          AI score <b className="text-foreground">{s.overall_ai_score ?? "—"}</b> · {s.verdict}
          {s.scan_duration_s != null && <> · {s.scan_duration_s.toFixed(1)}s scan</>}
        </p>
      )}
      {summaryQ.isError && (
        <p className="text-[10px] text-amber-400/80 mb-1.5">
          Replay summary unavailable ({(summaryQ.error as Error)?.message}); stage controls remain live.
        </p>
      )}
      {/* Stage replay controls — scoped to this widget */}
      {stages.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No replay stages yet.</p>
      ) : (
        <>
          <div className="flex items-center gap-1.5 mb-1.5">
            <button
              className="rounded-md border border-border p-1 hover:bg-muted/40"
              onClick={() => { setPlaying(false); setCursor((c) => Math.max(0, c - 1)); }}
              data-testid="mc-replay-back" title="Previous stage"
            ><SkipBack className="w-3 h-3" /></button>
            <button
              className="rounded-md border border-border p-1 hover:bg-muted/40"
              onClick={() => setPlaying((p) => !p)}
              data-testid="mc-replay-play" title={playing ? "Pause" : "Play"}
            >{playing ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}</button>
            <button
              className="rounded-md border border-border p-1 hover:bg-muted/40"
              onClick={() => { setPlaying(false); setCursor((c) => Math.min(stages.length - 1, c + 1)); }}
              data-testid="mc-replay-fwd" title="Next stage"
            ><SkipForward className="w-3 h-3" /></button>
            <div className="flex-1 flex gap-0.5 ml-1">
              {stages.map((st, i) => (
                <button
                  key={st.id}
                  title={st.label}
                  onClick={() => { setPlaying(false); setCursor(i); }}
                  className={`h-1.5 flex-1 rounded-full transition-colors ${i <= cursor ? "bg-teal-500" : "bg-muted"}`}
                />
              ))}
            </div>
          </div>
          {cur && (
            <div className="rounded-lg bg-muted/20 border border-border/60 p-2 text-[10px]" data-testid="mc-replay-stage-detail">
              <div className="flex justify-between">
                <span className="font-semibold">{cur.label}</span>
                <span className="text-muted-foreground">stage {cursor + 1}/{stages.length}</span>
              </div>
              <div className="flex gap-3 mt-0.5 text-muted-foreground">
                <span>in <b className="text-foreground">{cur.stocks_in}</b></span>
                <span>out <b className="text-emerald-400">{cur.stocks_out}</b></span>
                <span>rej <b className={cur.rejected > 0 ? "text-red-400" : "text-foreground"}>{cur.rejected}</b></span>
                {cur.duration_ms != null && <span>{(cur.duration_ms / 1000).toFixed(1)}s</span>}
              </div>
            </div>
          )}
        </>
      )}
    </Widget>
  );
}

// ── Backtest widget — existing /backtest API only ────────────────────────────

interface BtRun {
  run_id: string; created_at?: string; status?: string;
  config?: { start?: string; end?: string; interval?: string };
  progress?: { done?: number; total?: number; phase?: string };
  metrics?: {
    win_rate?: number; realized_pnl?: number; net_return_pct?: number;
    max_drawdown_pct?: number; sharpe_ratio?: number; total_trades?: number;
    portfolio_value?: number;
  };
}
interface P24Ranking { items?: { strategy?: string; name?: string; win_rate?: number; trades?: number }[] }

function istDate(daysAgo: number): string {
  const d = new Date(Date.now() - daysAgo * 86_400_000);
  return d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export function BacktestWidget() {
  const queryClient = useQueryClient();
  const runsQ = useWidgetQuery<{ runs?: BtRun[] }>({
    queryKey: ["mc", "bt-runs"], path: "/backtest/runs",
    refetchInterval: 10_000, timeoutMs: 60_000,
  });
  const rankingQ = useWidgetQuery<P24Ranking>({
    queryKey: ["mc", "p24-strategy-ranking"], path: "/phase24/strategy-ranking",
    refetchInterval: 300_000, timeoutMs: 90_000,
  });
  const [custom, setCustom] = useState(false);
  const [start, setStart] = useState(istDate(30));
  const [end, setEnd] = useState(istDate(0));

  const launch = useMutation({
    mutationFn: (range: { start: string; end: string }) =>
      apiJson("/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interval: "1d", start: range.start, end: range.end }),
      }, 60_000),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["mc", "bt-runs"] }),
  });

  const runs = runsQ.data?.runs ?? [];
  const latest = runs[0];
  const running = latest?.status === "RUNNING" || latest?.status === "PENDING";
  const m = latest?.metrics;
  const ranking = (rankingQ.data?.items ?? []).slice(0, 3);

  const preset = (days: number) => launch.mutate({ start: istDate(days), end: istDate(0) });

  return (
    <Widget
      title="Backtest" icon={FlaskConical} query={runsQ} refreshMs={10_000}
      testId="mc-backtest" skeletonClass="h-40"
      headerExtra={
        <>
          {running && <Badge className="animate-pulse text-[9px] px-1.5 py-0">RUNNING {latest?.progress?.done ?? 0}/{latest?.progress?.total ?? "?"}</Badge>}
          <Link href="/backtest" className="text-[9px] text-teal-400 hover:underline flex items-center gap-0.5">
            Full page <ExternalLink className="w-2.5 h-2.5" />
          </Link>
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-1.5 mb-2">
        {[["1 Day", 1], ["1 Week", 7], ["1 Month", 30]].map(([label, days]) => (
          <button
            key={String(label)}
            disabled={launch.isPending || running}
            onClick={() => preset(days as number)}
            className="text-[10px] rounded-md border border-border px-2 py-0.5 hover:bg-muted/40 disabled:opacity-50"
            data-testid={`mc-bt-${String(label).replace(/\s/g, "").toLowerCase()}`}
          >{label}</button>
        ))}
        <button
          className={`text-[10px] rounded-md border px-2 py-0.5 hover:bg-muted/40 ${custom ? "border-teal-500 text-teal-400" : "border-border"}`}
          onClick={() => setCustom((c) => !c)}
        >Custom</button>
        {launch.isError && <span className="text-[9px] text-red-400">{(launch.error as Error)?.message}</span>}
      </div>
      {custom && (
        <div className="flex items-center gap-1.5 mb-2 text-[10px]">
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="bg-muted/30 border border-border rounded px-1 py-0.5" />
          <span className="text-muted-foreground">→</span>
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="bg-muted/30 border border-border rounded px-1 py-0.5" />
          <button
            disabled={launch.isPending || running}
            onClick={() => launch.mutate({ start, end })}
            className="rounded-md border border-teal-600 text-teal-400 px-2 py-0.5 hover:bg-teal-500/10 disabled:opacity-50"
          >Run</button>
        </div>
      )}
      {latest ? (
        <>
          <p className="text-[10px] text-muted-foreground mb-1">
            Latest: <span className="font-mono">{latest.run_id}</span> · {latest.status}
            {latest.config?.start && <> · {latest.config.start} → {latest.config.end}</>}
          </p>
          <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 text-[11px]">
            <div><p className="text-muted-foreground text-[10px]">P&L</p><PnlText value={m?.realized_pnl} className="font-semibold" /></div>
            <div><p className="text-muted-foreground text-[10px]">Return</p><p className="font-semibold">{m?.net_return_pct != null ? `${m.net_return_pct}%` : "—"}</p></div>
            <div><p className="text-muted-foreground text-[10px]">Win rate</p><p className="font-semibold">{m?.win_rate != null ? `${m.win_rate}%` : "—"}</p></div>
            <div><p className="text-muted-foreground text-[10px]">Max DD</p><p className="font-semibold">{m?.max_drawdown_pct != null ? `${m.max_drawdown_pct}%` : "—"}</p></div>
            <div><p className="text-muted-foreground text-[10px]">Sharpe</p><p className="font-semibold">{m?.sharpe_ratio != null ? m.sharpe_ratio.toFixed(2) : "—"}</p></div>
          </div>
        </>
      ) : (
        <p className="text-[11px] text-muted-foreground">No backtest runs yet — launch one above.</p>
      )}
      {ranking.length > 0 && (
        <>
          <p className="text-[10px] text-muted-foreground mt-2 mb-0.5">Strategy ranking (advisory)</p>
          {ranking.map((r, i) => (
            <p key={i} className="text-[10px] flex justify-between">
              <span className="truncate">{i + 1}. {r.strategy ?? r.name}</span>
              <span className="text-muted-foreground">{r.win_rate != null ? `${r.win_rate}% win` : ""}{r.trades != null ? ` · ${r.trades}t` : ""}</span>
            </p>
          ))}
        </>
      )}
    </Widget>
  );
}

// ── Mission Timeline — the trading day from the pipeline event store ────────

interface PipelineEvent {
  id: number; ts: string; event_type: string; stage: string;
  symbol: string | null; payload: Record<string, unknown>;
  run_id?: string | null;
}

/**
 * Phase 25.1 Part 5 — build an Investigation Center deep-link for a pipeline
 * event. InvestigationCenter parses ?run=&symbol=&trade=&ts=.
 */
function investigateHref(e: {
  symbol?: string | null; ts?: string; run_id?: string | null;
  payload?: Record<string, unknown>;
}): string {
  const p = new URLSearchParams();
  if (e.symbol) p.set("symbol", e.symbol);
  if (e.ts) p.set("ts", e.ts);
  const run = e.run_id ?? (e.payload?.run_id as string | undefined);
  if (run) p.set("run", String(run));
  const trade = e.payload?.trade_id as string | undefined;
  if (trade) p.set("trade", String(trade));
  return `/investigation-center?${p.toString()}`;
}

const TL_CATEGORIES: { match: (e: PipelineEvent) => boolean; label: string; color: string }[] = [
  { match: (e) => e.event_type.startsWith("SCAN_"), label: "Scan", color: "bg-sky-400" },
  { match: (e) => e.stage === "RESEARCH" || e.stage === "MARKET_INTELLIGENCE", label: "Research", color: "bg-violet-400" },
  { match: (e) => e.event_type === "BUY_GENERATED", label: "BUY", color: "bg-emerald-400" },
  { match: (e) => e.stage === "EXECUTION" || e.event_type.includes("EXECUTED") || e.event_type.includes("OPENED"), label: "Execution", color: "bg-teal-400" },
  { match: (e) => e.event_type.includes("CLOSED") || e.event_type.includes("SELL") || e.event_type.includes("EXIT"), label: "SELL/Exit", color: "bg-red-400" },
];

function istMinutes(ts: string): number | null {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(new Date(ts));
    const h = Number(parts.find((p) => p.type === "hour")?.value);
    const m = Number(parts.find((p) => p.type === "minute")?.value);
    if (!isFinite(h) || !isFinite(m)) return null;
    return h * 60 + m;
  } catch { return null; }
}

const OPEN_MIN = 9 * 60;        // 09:00 IST (pre-open included)
const CLOSE_MIN = 15 * 60 + 30; // 15:30 IST

export function MissionTimelineWidget() {
  const eventsQ = useWidgetQuery<{ events?: PipelineEvent[] }>({
    queryKey: ["mc", "timeline-events"], path: "/pipeline/events?limit=400&newest_first=true",
    refetchInterval: 30_000, timeoutMs: 30_000,
  });
  const [selected, setSelected] = useState<PipelineEvent | null>(null);

  const todayIst = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  const points = useMemo(() => {
    const out: { e: PipelineEvent; cat: (typeof TL_CATEGORIES)[number]; pct: number }[] = [];
    for (const e of eventsQ.data?.events ?? []) {
      const dateIst = new Date(e.ts).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
      if (dateIst !== todayIst) continue;
      const cat = TL_CATEGORIES.find((c) => c.match(e));
      if (!cat) continue;
      const min = istMinutes(e.ts);
      if (min == null) continue;
      const pct = Math.max(0, Math.min(100, ((min - OPEN_MIN) / (CLOSE_MIN - OPEN_MIN)) * 100));
      out.push({ e, cat, pct });
    }
    return out;
  }, [eventsQ.data, todayIst]);

  const laneIndex = (cat: string) => TL_CATEGORIES.findIndex((c) => c.label === cat);

  return (
    <Widget
      title="Mission Timeline" icon={CalendarClock} query={eventsQ} refreshMs={30_000}
      testId="mc-mission-timeline" skeletonClass="h-32"
      headerExtra={
        <span className="text-[9px] text-muted-foreground">09:00 → 15:30 IST · {points.length} events today</span>
      }
    >
      {points.length === 0 ? (
        <p className="text-xs text-muted-foreground">No trading-day events yet — the timeline fills as scans and trades happen.</p>
      ) : (
        <>
          <div className="relative h-[90px] mb-1" data-testid="mc-timeline-lanes">
            {/* Lane labels + tracks */}
            {TL_CATEGORIES.map((c, li) => (
              <div key={c.label} className="absolute left-0 right-0 flex items-center" style={{ top: `${li * 18}px` }}>
                <span className="w-16 shrink-0 text-[9px] text-muted-foreground">{c.label}</span>
                <div className="relative flex-1 h-px bg-border/60">
                  {points.filter((p) => p.cat.label === c.label).map((p) => (
                    <button
                      key={p.e.id}
                      title={`${p.e.event_type} ${p.e.symbol ?? ""} · ${timeAgo(p.e.ts)}`}
                      onClick={() => setSelected(p.e)}
                      className={`absolute -top-[3px] h-[7px] w-[7px] rounded-full ${p.cat.color} hover:scale-150 transition-transform ${selected?.id === p.e.id ? "ring-2 ring-white/70" : ""}`}
                      style={{ left: `${p.pct}%` }}
                      data-testid={`mc-timeline-pt-${p.e.id}`}
                    />
                  ))}
                </div>
              </div>
            ))}
            {/* Hour marks */}
            <div className="absolute left-16 right-0 bottom-0 flex justify-between text-[8px] text-muted-foreground">
              {["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:30"].map((t) => <span key={t}>{t}</span>)}
            </div>
          </div>
          {selected && (
            <div className="rounded-lg bg-muted/20 border border-border/60 p-2 text-[10px]" data-testid="mc-timeline-detail">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`h-1.5 w-1.5 rounded-full ${TL_CATEGORIES[Math.max(0, laneIndex(TL_CATEGORIES.find((c) => c.match(selected))?.label ?? ""))]?.color ?? "bg-slate-400"}`} />
                <span className="font-semibold">{selected.event_type}</span>
                {selected.symbol && <span className="font-mono">{selected.symbol}</span>}
                <span className="text-muted-foreground">{selected.stage} · {timeAgo(selected.ts)}</span>
                <Link
                  href={investigateHref(selected)}
                  className="ml-auto text-teal-400 hover:underline flex items-center gap-0.5"
                  data-testid={`mc-timeline-investigate-${selected.id}`}
                >Investigate <ExternalLink className="w-2.5 h-2.5" /></Link>
              </div>
              <p className="text-muted-foreground truncate mt-0.5">
                {String(selected.payload?.reason ?? selected.payload?.action ?? selected.payload?.strategy_name ?? JSON.stringify(selected.payload ?? {}).slice(0, 160))}
              </p>
            </div>
          )}
        </>
      )}
    </Widget>
  );
}

// ── Broker widget — kite + broker endpoints ──────────────────────────────────

interface BrokerStatus {
  success?: boolean; execution_mode?: string; data_quality?: string;
  daily_orders_today?: number;
  broker?: { connected?: boolean; broker?: string; token_status?: string; is_mock?: boolean; latency_ms?: number; error?: string | null };
  safety_controls?: { kill_switch?: boolean };
}
interface PaperSummary {
  open_orders?: number; filled_orders?: number; filled_today?: number;
  open_positions?: number; closed_trades?: number; paper_cash?: number;
  capital_deployed?: number; execution_queue?: unknown[];
  realized_pnl?: number; todays_pnl?: number;
}
interface KiteStatus {
  connected?: boolean; connection_state?: string; token_status?: string;
  token_expiry_note?: string; is_mock?: boolean; latency_ms?: number | null;
}

export function BrokerWidget() {
  const statusQ = useWidgetQuery<BrokerStatus>({
    queryKey: ["mc", "broker-status"], path: "/broker/status",
    refetchInterval: 30_000, timeoutMs: 45_000,
  });
  const paperQ = useWidgetQuery<PaperSummary>({
    queryKey: ["mc", "broker-paper"], path: "/broker/paper-summary",
    refetchInterval: 30_000, timeoutMs: 45_000,
  });
  const kiteQ = useWidgetQuery<KiteStatus>({
    queryKey: ["mc", "kite-status"], path: "/kite/status",
    refetchInterval: 60_000, timeoutMs: 30_000,
  });

  const b = statusQ.data;
  const p = paperQ.data;
  const k = kiteQ.data;
  const connected = b?.broker?.connected ?? false;
  const queueLen = p?.execution_queue?.length ?? 0;

  return (
    <Widget
      title="Broker" icon={Landmark} query={statusQ} refreshMs={30_000}
      testId="mc-broker" skeletonClass="h-44"
      headerExtra={
        <>
          <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-amber-500/40 text-amber-300">
            {b?.execution_mode ?? "PAPER"}
          </Badge>
          {b?.safety_controls?.kill_switch && (
            <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-red-500/40 text-red-300">KILL SWITCH</Badge>
          )}
        </>
      }
    >
      <div className="flex items-center gap-2 text-[11px] mb-2">
        <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`} />
        <span className="font-medium">{b?.broker?.broker ?? "Broker"}</span>
        <span className="text-muted-foreground text-[10px]">
          token {b?.broker?.token_status ?? "—"}{b?.broker?.is_mock ? " · MOCK" : ""}
          {b?.broker?.latency_ms != null && ` · ${b.broker.latency_ms}ms`}
        </span>
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Queue</p><p className={`font-semibold ${queueLen > 0 ? "text-amber-400" : ""}`}>{queueLen}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Pending</p><p className="font-semibold">{p?.open_orders ?? "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Filled</p><p className="font-semibold text-emerald-400">{p?.filled_orders ?? "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Open pos</p><p className="font-semibold">{p?.open_positions ?? "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Closed</p><p className="font-semibold">{p?.closed_trades ?? "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Orders today</p><p className="font-semibold">{b?.daily_orders_today ?? "—"}</p></div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Paper cash</p><p className="font-semibold">{fmtINR(p?.paper_cash)}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Deployed</p><p className="font-semibold">{fmtINR(p?.capital_deployed)}</p></div>
      </div>
      {/* Portfolio sync / Zerodha session state */}
      <div className="rounded-lg bg-muted/20 border border-border/60 p-2 text-[10px]">
        <div className="flex items-center gap-1.5">
          <span className={`h-1.5 w-1.5 rounded-full ${k?.connected ? "bg-emerald-400" : "bg-amber-400"}`} />
          <span className="font-medium">
            Zerodha session: {k?.connection_state ?? (kiteQ.isError ? "UNKNOWN" : kiteQ.isLoading ? "…" : k?.token_status ?? "UNKNOWN")}
          </span>
          <span className="ml-auto text-muted-foreground">data {b?.data_quality ?? "—"}</span>
        </div>
        {k?.token_expiry_note && <p className="text-muted-foreground mt-0.5 truncate">{k.token_expiry_note}</p>}
      </div>
    </Widget>
  );
}

// ── System Health widget — observability/operations summaries ───────────────

interface ObsSystem {
  overall_status?: string; health_score?: number; uptime_hours?: number;
  memory?: { used_mb?: number; total_mb?: number; usage_pct?: number; status?: string };
  cpu?: { load_1m?: number; load_5m?: number; status?: string };
  database?: { status?: string; connection?: { connected?: boolean; latency_ms?: number } };
  jobs?: { scheduler_status?: string; last_scan?: { age_min?: number; fresh?: boolean }; running_count?: number; failed_count?: number };
}
interface ObsSummary {
  observability_score?: number; grade?: string; system_status?: string;
  db_status?: string; api_status?: string; scheduler_status?: string;
  error_count_session?: number; availability_pct?: number;
}
interface PipeSummary { total_events?: number; generated_at?: string }

const stTone = (s?: string) =>
  s === "HEALTHY" ? "text-emerald-400" : s === "DEGRADED" ? "text-amber-400" : s ? "text-red-400" : "text-muted-foreground";

export function SystemHealthWidget() {
  const sysQ = useWidgetQuery<ObsSystem>({
    queryKey: ["mc", "obs-system"], path: "/observability/system",
    refetchInterval: 30_000, timeoutMs: 60_000,
  });
  const sumQ = useWidgetQuery<ObsSummary>({
    queryKey: ["mc", "obs-summary"], path: "/observability/summary",
    refetchInterval: 60_000, timeoutMs: 90_000,
  });
  const pipeQ = useWidgetQuery<PipeSummary>({
    queryKey: ["mc", "pipeline-summary"], path: "/pipeline/summary",
    refetchInterval: 30_000,
  });

  const s = sysQ.data;
  const m = sumQ.data;

  return (
    <Widget
      title="System Health" icon={Server} query={sysQ} refreshMs={30_000}
      testId="mc-system-health" skeletonClass="h-44"
      headerExtra={m?.grade && (
        <Badge variant="outline" className="text-[9px] px-1.5 py-0">
          {m.grade} · {m.observability_score ?? "—"}
        </Badge>
      )}
    >
      <div className="grid grid-cols-3 gap-2 text-[11px] mb-2">
        <div>
          <p className="text-muted-foreground text-[10px]">CPU load</p>
          <p className={`font-semibold ${stTone(s?.cpu?.status)}`}>{s?.cpu?.load_1m != null ? s.cpu.load_1m.toFixed(2) : "—"}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">RAM</p>
          <p className={`font-semibold ${stTone(s?.memory?.status)}`}>
            {s?.memory?.usage_pct != null ? `${s.memory.usage_pct.toFixed(0)}%` : "—"}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Database</p>
          <p className={`font-semibold ${stTone(s?.database?.status ?? m?.db_status)}`}>
            {s?.database?.connection?.latency_ms != null ? `${s.database.connection.latency_ms.toFixed(0)}ms` : (s?.database?.status ?? m?.db_status ?? "—")}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">API</p>
          <p className={`font-semibold ${stTone(m?.api_status)}`}>{m?.api_status ?? "—"}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Scheduler</p>
          <p className={`font-semibold ${stTone(s?.jobs?.scheduler_status ?? m?.scheduler_status)}`}>
            {s?.jobs?.scheduler_status ?? m?.scheduler_status ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Errors (session)</p>
          <p className={`font-semibold ${(m?.error_count_session ?? 0) > 0 ? "text-amber-400" : ""}`}>{m?.error_count_session ?? "—"}</p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 text-[11px] mb-2">
        <div>
          <p className="text-muted-foreground text-[10px]">Jobs running</p>
          <p className="font-semibold">{s?.jobs?.running_count ?? "—"}{s?.jobs?.failed_count ? <span className="text-red-400"> · {s.jobs.failed_count} failed</span> : null}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Scan freshness</p>
          <p className={`font-semibold ${s?.jobs?.last_scan?.fresh === false ? "text-amber-400" : ""}`}>
            {s?.jobs?.last_scan?.age_min != null ? `${Math.round(s.jobs.last_scan.age_min)}m` : "—"}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Event throughput</p>
          <p className="font-semibold flex items-center gap-1">
            <Activity className="w-3 h-3 text-teal-400" />
            {pipeQ.data?.total_events ?? "—"}
          </p>
        </div>
      </div>
      <p className="text-[9px] text-muted-foreground">
        Uptime {s?.uptime_hours != null ? `${s.uptime_hours.toFixed(1)}h` : "—"} · availability {m?.availability_pct != null ? `${m.availability_pct}%` : "—"} ·
        overall <span className={stTone(s?.overall_status)}>{s?.overall_status ?? "—"}</span>
      </p>
    </Widget>
  );
}
