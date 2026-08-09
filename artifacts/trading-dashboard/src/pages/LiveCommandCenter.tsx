/**
 * LiveCommandCenter.tsx — Phase 23 Part 1: AI Live Trading Command Center.
 *
 * Mission-control view rendered ENTIRELY from the canonical Pipeline Event
 * Store (/api/pipeline/*) plus existing canonical endpoints (portfolio
 * snapshot, scan status). No page-local pipeline calculations, no demo data,
 * no synthetic fallbacks — empty states are shown honestly.
 *
 * PAPER TRADING / RESEARCH ONLY.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { useLiveStream } from "@/hooks/useLiveStream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Link } from "wouter";
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Ban, Bot,
  CheckCircle2, ChevronRight, CircleDollarSign, Clock, Cpu, Pause, Play,
  Radio, RotateCcw, ShieldX, Wallet, Wifi, WifiOff, XCircle, Zap,
} from "lucide-react";

const LABEL = "PAPER TRADING / RESEARCH ONLY";

// ── Types (mirror pipeline_events.py) ────────────────────────────────────────

interface PipelineEvent {
  id: number;
  ts: string;
  mode: string;
  run_id: string | null;
  scan_id: string | null;
  event_type: string;
  stage: string;
  symbol: string | null;
  payload: Record<string, unknown>;
}

interface StageSummary {
  stage: string;
  events: number;
  completed: number;
  rejected: number;
  errors: number;
  last_ts: string | null;
  last_symbol: string | null;
  avg_symbol_ms?: number | null;
}

interface ReplayStage {
  id: string;
  stocks_in?: number; stocks_out?: number; rejected?: number;
  pending?: number; cancelled?: number;
}

interface ReplaySnapshot {
  scan_id?: string | null;
  snapshot_ts?: string | null;
  duration_s?: number | null;
  total_symbols?: number;
  universe_size?: number;
  stages?: ReplayStage[];
  decisions?: Array<{ symbol?: string | null; final_action?: string | null; confidence?: number | null }>;
  pipeline_counts?: Record<string, unknown>;
}

interface CycleLogEntry {
  cycle?: number; scan_id?: string; started_at?: string; duration_s?: number;
  symbols?: number; [k: string]: unknown;
}

interface PipelineSummary {
  scan_id: string | null;
  mode: string;
  total_events: number;
  stages: StageSummary[];
  generated_at: string;
}

interface ScanStatus {
  status?: string;
  scan_id?: string;
  snapshot_ts?: string;
  age_minutes?: number | null;
  progress?: { stage?: string; scan_id?: string; symbols_done?: number; symbols_total?: number } | null;
}

interface PortfolioSnapshot {
  cash?: number;
  equity?: number;
  realised_pnl_today?: number;
  unrealised_pnl?: number;
  initial_capital?: number;
  invested_value?: number;
  sector_exposures?: Array<{
    sector: string; total_value?: number; exposure_pct?: number;
    limit_pct?: number; position_count?: number;
  }>;
  open_positions?: Array<{
    symbol: string; quantity: number; avg_entry_price: number;
    last_price?: number | null; unrealised_pnl?: number | null; sector?: string;
  }>;
}

const STAGE_LABELS: Record<string, string> = {
  SUPERVISOR: "Supervisor",
  SCANNER: "Scanner",
  RESEARCH: "Research",
  MARKET_INTELLIGENCE: "Market Intel",
  MONITORING: "Monitoring",
  STRATEGY: "Strategy",
  PORTFOLIO_PRECHECK: "Portfolio Pre-Check",
  RISK: "Risk",
  AI_DECISION: "AI Decision",
  EXECUTION: "Execution",
  PORTFOLIO: "Portfolio",
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtINR(v: unknown): string {
  const n = typeof v === "number" ? v : null;
  if (n === null || !isFinite(n)) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function timeAgo(ts: string | null): string {
  if (!ts) return "—";
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${(s / 3600).toFixed(1)}h ago`;
}

function eventTone(et: string): "ok" | "warn" | "bad" | "info" {
  if (et.includes("REJECTED") || et.includes("FAILED") || et.includes("CANCELLED")) return "bad";
  if (et.includes("EXECUTED") || et.includes("OPENED") || et.includes("CLOSED") || et === "BUY_GENERATED") return "ok";
  if (et.includes("WATCH")) return "warn";
  return "info";
}

const toneClass = {
  ok: "text-green-500",
  warn: "text-yellow-500",
  bad: "text-red-500",
  info: "text-muted-foreground",
} as const;

function EventIcon({ et }: { et: string }) {
  const tone = eventTone(et);
  const cls = `h-3.5 w-3.5 shrink-0 ${toneClass[tone]}`;
  if (tone === "bad") return <XCircle className={cls} />;
  if (tone === "ok") return <CheckCircle2 className={cls} />;
  if (tone === "warn") return <AlertTriangle className={cls} />;
  return <Activity className={cls} />;
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function LiveCommandCenter() {
  const { connection, market, pipelineEventId } = useLiveStream();
  const [rejectionFilter, setRejectionFilter] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const queryClient = useQueryClient();

  // Streamed pipeline events (SSE bridge) invalidate the REST caches so the
  // page reacts within a second instead of waiting for the next poll.
  useEffect(() => {
    if (!pipelineEventId || paused) return;
    void queryClient.invalidateQueries({ queryKey: ["pipeline-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["pipeline-feed"] });
  }, [pipelineEventId, paused, queryClient]);

  const summaryQ = useQuery<PipelineSummary>({
    queryKey: ["pipeline-summary"],
    queryFn: () => apiJson("/pipeline/summary"),
    refetchInterval: paused ? false : 5_000,
    retry: 3,
  });

  const feedQ = useQuery<{ events: PipelineEvent[] }>({
    queryKey: ["pipeline-feed"],
    queryFn: () => apiJson("/pipeline/events?limit=120&newest_first=true"),
    refetchInterval: paused ? false : 4_000,
    retry: 3,
  });

  const scanId = summaryQ.data?.scan_id ?? null;

  const rejectionsQ = useQuery<{ events: PipelineEvent[] }>({
    queryKey: ["pipeline-rejections", scanId],
    enabled: !!scanId,
    queryFn: () =>
      apiJson(`/pipeline/events?scan_id=${scanId}&limit=500`),
    refetchInterval: paused ? false : 15_000,
    retry: 3,
  });

  const scanQ = useQuery<ScanStatus>({
    queryKey: ["lcc-scan-status"],
    queryFn: () => apiJson("/live-data/scan/status"),
    refetchInterval: paused ? false : 5_000,
    retry: 3,
  });

  const portfolioQ = useQuery<PortfolioSnapshot>({
    queryKey: ["lcc-portfolio"],
    queryFn: () => apiJson("/portfolio/snapshot"),
    refetchInterval: paused ? false : 15_000,
    retry: 3,
  });

  // Canonical replay snapshot of the current cycle: per-stage in/out/
  // pending counts and BUY/WATCH decisions (slow endpoint — long timeout).
  const replayQ = useQuery<ReplaySnapshot>({
    queryKey: ["lcc-replay-latest"],
    queryFn: () => apiJson("/replay/sessions/latest", undefined, 60_000),
    refetchInterval: paused ? false : 30_000,
    retry: 3,
  });

  // Per-cycle log: cycle number + duration from the ops centre store.
  const cycleQ = useQuery<{ entries?: CycleLogEntry[]; cycles?: CycleLogEntry[] }>({
    queryKey: ["lcc-cycle-log"],
    queryFn: () => apiJson("/ops-centre/cycle-log", undefined, 30_000),
    refetchInterval: paused ? false : 30_000,
    retry: 3,
  });

  const events = feedQ.data?.events ?? [];

  const rejections = useMemo(() => {
    const evs = rejectionsQ.data?.events ?? [];
    return evs.filter((e) =>
      ["RISK_REJECTED", "ORDER_REJECTED", "SYMBOL_REJECTED", "STRATEGY_REJECTED", "PRECHECK_REJECTED"].includes(e.event_type) &&
      (!rejectionFilter || e.event_type === rejectionFilter),
    );
  }, [rejectionsQ.data, rejectionFilter]);

  const rejectionCounts = useMemo(() => {
    const evs = rejectionsQ.data?.events ?? [];
    const c: Record<string, number> = {};
    for (const e of evs) {
      if (e.event_type.includes("REJECTED")) c[e.event_type] = (c[e.event_type] || 0) + 1;
    }
    return c;
  }, [rejectionsQ.data]);

  const progress = scanQ.data?.progress ?? null;
  const scanning = !!progress?.stage;

  const positions = portfolioQ.data?.open_positions ?? [];

  // Cycle info: newest entry of the canonical per-cycle log.
  const cycles = (cycleQ.data?.cycles ?? cycleQ.data?.entries ?? []) as CycleLogEntry[];
  const totalCycles = (cycleQ.data as { total_cycles?: number } | undefined)?.total_cycles ?? cycles.length;
  const lastCycle = cycles[0] ?? null;
  const cycleDurationS = useMemo(() => {
    const st = lastCycle?.start_time as string | undefined;
    const en = lastCycle?.end_time as string | undefined;
    if (!st || !en) return null;
    const d = (new Date(en).getTime() - new Date(st).getTime()) / 1000;
    return isFinite(d) && d >= 0 ? d : null;
  }, [lastCycle]);

  // Candidates from the canonical replay snapshot decisions.
  const replay = replayQ.data;
  const decisions = replay?.decisions ?? [];
  // final_action values include "STRONG BUY" / "BUY" / "WATCH" — normalise.
  const buyCandidates = decisions.filter((d) => /BUY/i.test(String(d.final_action ?? "")));
  const watchCandidates = decisions.filter((d) => /WATCH/i.test(String(d.final_action ?? "")));
  const replayStageByName = useMemo(() => {
    const m = new Map<string, ReplayStage>();
    for (const s of replay?.stages ?? []) m.set(String(s.id).toUpperCase(), s);
    // Replay ids and pipeline-summary stage names differ for the scan stage.
    const md = m.get("MARKET_DATA");
    if (md && !m.has("SCANNER")) m.set("SCANNER", md);
    return m;
  }, [replay]);

  // Capital utilisation from canonical portfolio fields (no local math beyond %).
  const investedValue = portfolioQ.data?.invested_value;
  const initialCapital = portfolioQ.data?.initial_capital;
  const capitalUtilPct = typeof investedValue === "number" && typeof initialCapital === "number" && initialCapital > 0
    ? (investedValue / initialCapital) * 100 : null;
  const sectorExposures = portfolioQ.data?.sector_exposures ?? [];

  return (
    <div className="p-4 space-y-4 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Zap className="h-6 w-6 text-primary" />
        <h1 className="text-xl font-semibold">AI Live Trading Command Center</h1>
        <Badge variant="outline">{LABEL}</Badge>
        <div className="ml-auto flex flex-wrap items-center gap-3 text-sm">
          <Button size="sm" variant={paused ? "default" : "outline"}
            onClick={() => setPaused((p) => !p)} data-testid="button-pause-refresh">
            {paused ? <Play className="h-3.5 w-3.5 mr-1" /> : <Pause className="h-3.5 w-3.5 mr-1" />}
            {paused ? "Resume" : "Pause"}
          </Button>
          {scanId && (
            <Link href="/mission-control">
              <Button size="sm" variant="outline" data-testid="button-replay-cycle">
                <RotateCcw className="h-3.5 w-3.5 mr-1" /> Replay cycle
              </Button>
            </Link>
          )}
          <span className="flex items-center gap-1.5">
            {connection === "connected" ? (
              <Wifi className="h-4 w-4 text-green-500" />
            ) : (
              <WifiOff className="h-4 w-4 text-red-500" />
            )}
            <span className="text-muted-foreground">{connection}</span>
          </span>
          {market && (
            <Badge variant={market.is_open ? "default" : "secondary"}>
              Market {market.state}
            </Badge>
          )}
          {scanning ? (
            <Badge className="animate-pulse">
              <Radio className="h-3 w-3 mr-1" />
              SCAN {progress?.stage}
              {progress?.symbols_total
                ? ` ${progress.symbols_done ?? 0}/${progress.symbols_total}`
                : ""}
            </Badge>
          ) : (
            <span className="text-muted-foreground flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              Last scan {scanQ.data?.age_minutes != null ? `${Math.round(scanQ.data.age_minutes)}m ago` : "—"}
            </span>
          )}
        </div>
      </div>

      {/* Pipeline rail */}
      <Card data-testid="card-pipeline-rail">
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Cpu className="h-4 w-4" />
            Live Pipeline
            {scanId && (
              <span className="text-xs font-normal text-muted-foreground">
                scan {scanId} · {summaryQ.data?.total_events ?? 0} events
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {summaryQ.isLoading ? (
            <div className="text-sm text-muted-foreground">Loading pipeline events…</div>
          ) : !summaryQ.data || summaryQ.data.total_events === 0 ? (
            <div className="text-sm text-muted-foreground">
              No pipeline events recorded yet for the latest scan. Events are
              emitted the next time the scanner runs.
            </div>
          ) : (
            <div className="flex items-stretch gap-1 overflow-x-auto pb-1">
              {summaryQ.data.stages.map((s, i) => {
                const active = scanning && s.last_ts != null &&
                  Date.now() - new Date(s.last_ts).getTime() < 60_000;
                const rs = replayStageByName.get(s.stage);
                return (
                  <div key={s.stage} className="flex items-center">
                    <div
                      data-testid={`stage-${s.stage.toLowerCase()}`}
                      className={`min-w-[128px] rounded-md border px-2.5 py-2 text-xs ${
                        active ? "border-primary bg-primary/10 animate-pulse" : "bg-card"
                      }`}
                    >
                      <div className="font-medium mb-1">{STAGE_LABELS[s.stage] ?? s.stage}</div>
                      <div className="flex gap-2">
                        <span className="text-green-500">{s.completed}✓</span>
                        {s.rejected > 0 && <span className="text-red-500">{s.rejected}✗</span>}
                        {(rs?.pending ?? 0) > 0 && <span className="text-amber-500">{rs!.pending}⏳</span>}
                      </div>
                      {rs && (rs.stocks_in ?? 0) > 0 && (
                        <div className="text-muted-foreground mt-0.5">
                          in {rs.stocks_in} · out {rs.stocks_out ?? 0}
                        </div>
                      )}
                      {typeof s.avg_symbol_ms === "number" && (
                        <div className="text-muted-foreground mt-0.5">
                          avg {s.avg_symbol_ms >= 1000
                            ? `${(s.avg_symbol_ms / 1000).toFixed(1)}s`
                            : `${Math.round(s.avg_symbol_ms)}ms`}
                        </div>
                      )}
                      <div className="text-muted-foreground mt-1 truncate">
                        {s.last_symbol ?? (s.events ? timeAgo(s.last_ts) : "idle")}
                      </div>
                    </div>
                    {i < summaryQ.data!.stages.length - 1 && (
                      <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Cycle + candidates */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card data-testid="card-cycle-info">
          <CardHeader className="py-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Radio className="h-4 w-4" /> Scan Cycle
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-1">
            <div className="flex justify-between"><span className="text-muted-foreground">Cycle #</span>
              <span className="font-semibold">{totalCycles || "—"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Duration</span>
              <span className="font-semibold">{cycleDurationS != null ? `${cycleDurationS.toFixed(1)}s` : "—"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Stocks scanned</span>
              <span className="font-semibold">{replay?.total_symbols ?? "—"}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Universe</span>
              <span className="font-semibold">{replay?.universe_size ?? "—"}</span></div>
            {lastCycle?.market_state != null && (
              <div className="flex justify-between"><span className="text-muted-foreground">Market state</span>
                <span className="font-semibold">{String(lastCycle.market_state)}</span></div>
            )}
          </CardContent>
        </Card>
        <Card data-testid="card-buy-candidates">
          <CardHeader className="py-3">
            <CardTitle className="text-sm flex items-center gap-2 text-green-500">
              <ArrowUpRight className="h-4 w-4" /> BUY Candidates ({buyCandidates.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 max-h-[160px] overflow-y-auto text-xs">
            {buyCandidates.length === 0 && <div className="text-muted-foreground">None this cycle.</div>}
            {buyCandidates.map((d, i) => (
              <Link key={i} href={`/explainable-ai?symbol=${d.symbol ?? ""}`}
                className="flex justify-between hover:bg-muted rounded px-1 py-0.5"
                data-testid={`link-buy-${d.symbol}`}>
                <span className="font-semibold">{d.symbol}</span>
                <span className="text-muted-foreground">
                  {typeof d.confidence === "number" ? `${d.confidence}%` : String(d.final_action ?? "")}
                </span>
              </Link>
            ))}
          </CardContent>
        </Card>
        <Card data-testid="card-watch-candidates">
          <CardHeader className="py-3">
            <CardTitle className="text-sm flex items-center gap-2 text-yellow-500">
              <AlertTriangle className="h-4 w-4" /> WATCH Candidates ({watchCandidates.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 max-h-[160px] overflow-y-auto text-xs">
            {watchCandidates.length === 0 && <div className="text-muted-foreground">None this cycle.</div>}
            {watchCandidates.map((d, i) => (
              <Link key={i} href={`/explainable-ai?symbol=${d.symbol ?? ""}`}
                className="flex justify-between hover:bg-muted rounded px-1 py-0.5"
                data-testid={`link-watch-${d.symbol}`}>
                <span className="font-semibold">{d.symbol}</span>
                <span className="text-muted-foreground">
                  {typeof d.confidence === "number" ? `${d.confidence}%` : String(d.final_action ?? "")}
                </span>
              </Link>
            ))}
          </CardContent>
        </Card>
        <Card data-testid="card-capital-utilisation">
          <CardHeader className="py-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <CircleDollarSign className="h-4 w-4" /> Capital & Exposure
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            <div className="flex justify-between"><span className="text-muted-foreground">Deployed</span>
              <span className="font-semibold">{fmtINR(investedValue)}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Utilisation</span>
              <span className="font-semibold">{capitalUtilPct != null ? `${capitalUtilPct.toFixed(1)}%` : "—"}</span></div>
            {capitalUtilPct != null && (
              <div className="h-1.5 rounded bg-muted overflow-hidden">
                <div className="h-full bg-primary" style={{ width: `${Math.min(100, capitalUtilPct)}%` }} />
              </div>
            )}
            <div>
              <div className="text-xs text-muted-foreground mb-1">Sector distribution</div>
              {sectorExposures.length === 0 ? (
                <div className="text-xs text-muted-foreground">No open exposure.</div>
              ) : (
                <div className="space-y-0.5 max-h-[100px] overflow-y-auto text-xs">
                  {sectorExposures.map((se) => (
                    <div key={se.sector} className="flex justify-between gap-2">
                      <span className="truncate">{se.sector}</span>
                      <span className="text-muted-foreground shrink-0">
                        {fmtINR(se.total_value)}{typeof se.exposure_pct === "number" ? ` · ${se.exposure_pct.toFixed(1)}%` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Live event feed */}
        <Card className="lg:col-span-2" data-testid="card-event-feed">
          <CardHeader className="py-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Activity className="h-4 w-4" /> Live Event Feed
            </CardTitle>
          </CardHeader>
          <CardContent>
            {feedQ.isLoading ? (
              <div className="text-sm text-muted-foreground">Loading events…</div>
            ) : events.length === 0 ? (
              <div className="text-sm text-muted-foreground">
                No events yet. The feed populates as the pipeline runs.
              </div>
            ) : (
              <div className="space-y-1 max-h-[420px] overflow-y-auto font-mono text-xs">
                {events.map((e) => (
                  <div key={e.id} className="flex items-center gap-2 py-0.5 border-b border-border/40 last:border-0">
                    <EventIcon et={e.event_type} />
                    <span className="text-muted-foreground w-16 shrink-0">{timeAgo(e.ts)}</span>
                    <span className={`w-44 shrink-0 truncate ${toneClass[eventTone(e.event_type)]}`}>
                      {e.event_type}
                    </span>
                    <span className="w-24 shrink-0 font-semibold truncate">{e.symbol ?? ""}</span>
                    <span className="text-muted-foreground truncate">
                      {String(
                        (e.payload as Record<string, unknown>).reason ??
                        (Array.isArray((e.payload as Record<string, unknown>).reasons)
                          ? ((e.payload as Record<string, unknown>).reasons as unknown[]).join("; ")
                          : undefined) ??
                        (e.payload as Record<string, unknown>).action ??
                        (e.payload as Record<string, unknown>).strategy_name ??
                        (e.payload as Record<string, unknown>).trade_id ??
                        "",
                      )}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Portfolio */}
        <Card data-testid="card-live-portfolio">
          <CardHeader className="py-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Wallet className="h-4 w-4" /> Paper Portfolio
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Equity</div>
                <div className="font-semibold">{fmtINR(portfolioQ.data?.equity)}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Cash</div>
                <div className="font-semibold">{fmtINR(portfolioQ.data?.cash)}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Realized P&L (today)</div>
                <div className={`font-semibold flex items-center gap-1 ${
                  (portfolioQ.data?.realised_pnl_today ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                  {(portfolioQ.data?.realised_pnl_today ?? 0) >= 0
                    ? <ArrowUpRight className="h-3.5 w-3.5" />
                    : <ArrowDownRight className="h-3.5 w-3.5" />}
                  {fmtINR(portfolioQ.data?.realised_pnl_today)}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Unrealized P&L</div>
                <div className={`font-semibold ${
                  (portfolioQ.data?.unrealised_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                  {fmtINR(portfolioQ.data?.unrealised_pnl)}
                </div>
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">
                Open positions ({positions.length})
              </div>
              {positions.length === 0 ? (
                <div className="text-xs text-muted-foreground">No open positions.</div>
              ) : (
                <div className="space-y-1 max-h-[220px] overflow-y-auto">
                  {positions.map((p) => (
                    <div key={p.symbol} className="flex items-center justify-between text-xs border-b border-border/40 pb-1 last:border-0">
                      <span className="font-semibold">{p.symbol}</span>
                      <span className="text-muted-foreground">{p.quantity} @ {fmtINR(p.avg_entry_price)}</span>
                      <span className={(p.unrealised_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}>
                        {fmtINR(p.unrealised_pnl)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Rejection analyzer */}
      <Card data-testid="card-rejection-analyzer">
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <ShieldX className="h-4 w-4" /> Rejection Analyzer
            <span className="text-xs font-normal text-muted-foreground">
              every rejection in scan {scanId ?? "—"} — nothing hidden
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {Object.entries(rejectionCounts).map(([et, n]) => (
              <button
                key={et}
                onClick={() => setRejectionFilter(rejectionFilter === et ? null : et)}
                data-testid={`filter-${et.toLowerCase()}`}
              >
                <Badge variant={rejectionFilter === et ? "default" : "secondary"}>
                  <Ban className="h-3 w-3 mr-1" /> {et} · {n}
                </Badge>
              </button>
            ))}
            {Object.keys(rejectionCounts).length === 0 && (
              <span className="text-xs text-muted-foreground">
                No rejections recorded for this scan.
              </span>
            )}
          </div>
          {rejections.length > 0 && (
            <div className="space-y-1 max-h-[260px] overflow-y-auto text-xs font-mono">
              {rejections.map((e) => {
                const p = e.payload as Record<string, unknown>;
                const failed = p.failed_gates as Record<string, { reason?: string }> | undefined;
                const detail =
                  (p.reason as string) ??
                  (Array.isArray(p.reasons) ? (p.reasons as unknown[]).join("; ") : undefined) ??
                  (failed ? Object.entries(failed).map(([g, v]) => `${g}: ${v?.reason ?? "failed"}`).join("; ") : "") ??
                  (p.error as string) ?? "";
                return (
                  <div key={e.id} className="flex items-start gap-2 border-b border-border/40 py-1 last:border-0">
                    <XCircle className="h-3.5 w-3.5 text-red-500 mt-0.5 shrink-0" />
                    <span className="w-24 shrink-0 font-semibold">{e.symbol ?? "—"}</span>
                    <span className="w-40 shrink-0 text-red-500">{e.event_type}</span>
                    <span className="text-muted-foreground">{detail || "(no detail in payload)"}</span>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="text-xs text-muted-foreground flex items-center gap-2">
        <Bot className="h-3.5 w-3.5" />
        All numbers on this page derive from the canonical Pipeline Event Store
        and canonical portfolio ledger. <CircleDollarSign className="h-3.5 w-3.5" /> {LABEL}
      </div>
    </div>
  );
}
