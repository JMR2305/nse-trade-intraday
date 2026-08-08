/**
 * MissionControl.tsx — Phase 25A: Mission Control shell & core live panels.
 *
 * Unified operational landing screen for ApexQuant AI. PURE DASHBOARD:
 * every widget reads existing backend endpoints — pipeline event store,
 * canonical portfolio snapshot, unified replay snapshot, phase20 ledger,
 * live scan status. NO business logic is computed here.
 *
 * Layout:
 *   ┌──────────────── Top status bar ─────────────────┐
 *   │ market · IST clock · indices · value · P&L · … │
 *   ├──────────┬──────────────────────┬───────────────┤
 *   │ AI       │  Scanner             │ Portfolio     │
 *   │ Pipeline │  Paper Trading       │ (sidebar)     │
 *   ├──────────┴──────────────────────┴───────────────┤
 *   │ Event stream strip                              │
 *   └─────────────────────────────────────────────────┘
 *
 * Each panel is an independent <Widget> with its own query key, refresh
 * cadence and error state, so one slow endpoint never blanks the page.
 *
 * PAPER TRADING / RESEARCH ONLY.
 */
import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLiveStream, type PipelineStreamEvent } from "@/hooks/useLiveStream";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { Badge } from "@/components/ui/badge";
import {
  Activity, AlertTriangle, CheckCircle2, ChevronRight, Clock, Cpu,
  HeartPulse, PieChart, Radar, Radio, Rocket, Wallet, Wifi, WifiOff, XCircle,
} from "lucide-react";
import { Widget, useWidgetQuery, fmtINR, timeAgo, PnlText } from "@/components/mission/Widget";
import {
  MissionMapWidget, AiHealthWidget, AiLearningWidget, AlertCenterWidget,
} from "@/components/mission/IntelWidgets";
import {
  ReplayWidget, BacktestWidget, MissionTimelineWidget, BrokerWidget, SystemHealthWidget,
} from "@/components/mission/OpsWidgets";

const LABEL = "PAPER TRADING / RESEARCH ONLY";

// ── Refresh cadences (ms) per panel ──────────────────────────────────────────
const R = {
  pipeline: 5_000,     // pipeline/summary — 5 s Node cache behind it
  replay: 30_000,      // unified replay snapshot — heavier Python build
  scan: 5_000,
  portfolio: 15_000,
  ledger: 10_000,
  events: 4_000,
  health: 30_000,
} as const;

// ── Types (mirror backend responses; all fields optional-defensive) ─────────

interface StageSummary {
  stage: string; events: number; completed: number; rejected: number;
  errors: number; last_ts: string | null; last_symbol: string | null;
}
interface PipelineSummary {
  scan_id: string | null; mode: string; total_events: number;
  stages: StageSummary[]; generated_at: string;
}
interface ReplayStage {
  id: string; label: string; order: number;
  stocks_in: number; stocks_out: number;
  rejected: number; pending: number; cancelled: number;
  duration_ms: number | null; status: string;
}
interface ReplayResp { stages?: ReplayStage[]; scan_id?: string; snapshot_ts?: string; error?: string }
interface ScanStatus {
  success?: boolean; status?: string; scan_id?: string; snapshot_ts?: string;
  age_minutes?: number | null;
  latest_scan?: {
    scan_id?: string; snapshot_ts?: string; status?: string;
    symbols_total?: number; symbols_done?: number; duration_s?: number | null;
    universe_size?: number;
  } | null;
  progress?: {
    stage?: string; scan_id?: string; symbol?: string; current_symbol?: string;
    symbols_done?: number; symbols_total?: number; started_at?: string;
  } | null;
}
interface SectorExposure { sector: string; total_value: number; exposure_pct: number; position_count: number }
interface OpenPosition {
  symbol: string; quantity: number; avg_entry_price: number; last_price: number;
  market_value: number; unrealised_pnl: number; unrealised_pnl_pct: number;
  sector?: string | null; exposure_pct?: number;
}
interface PortfolioSnapshot {
  status?: string; equity?: number; cash?: number; invested_value?: number;
  initial_capital?: number; unrealised_pnl?: number; realised_pnl_today?: number;
  total_pnl?: number; drawdown_pct?: number;
  open_positions?: OpenPosition[]; open_position_count?: number;
  closed_positions_today?: number; sector_exposures?: SectorExposure[];
  snapshotted_at?: string;
}
interface LedgerItem {
  trade_id: string; symbol: string; side: string; status: string;
  quantity: number; fill_price: number | null; fill_ts: string | null;
  exit_price: number | null; realized_pnl: number | null; created_at?: string;
  strategy_name?: string | null;
}
interface PipelineEvent {
  id: number; ts: string; event_type: string; stage: string;
  symbol: string | null; payload: Record<string, unknown>;
}

const STAGE_LABELS: Record<string, string> = {
  SUPERVISOR: "Supervisor", SCANNER: "Scanner", RESEARCH: "Research",
  MARKET_INTELLIGENCE: "Market Intel", MONITORING: "Monitoring",
  STRATEGY: "Strategy", RISK: "Risk", AI_DECISION: "AI Decision",
  EXECUTION: "Execution", PORTFOLIO: "Portfolio",
};

function eventTone(et: string): "ok" | "warn" | "bad" | "info" {
  if (et.includes("REJECTED") || et.includes("FAILED") || et.includes("CANCELLED")) return "bad";
  if (et.includes("EXECUTED") || et.includes("OPENED") || et.includes("CLOSED") || et === "BUY_GENERATED") return "ok";
  if (et.includes("WATCH")) return "warn";
  return "info";
}
const toneClass = { ok: "text-emerald-400", warn: "text-amber-400", bad: "text-red-400", info: "text-muted-foreground" } as const;

// ── IST clock ─────────────────────────────────────────────────────────────────

function IstClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(id);
  }, []);
  const ist = now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
  return <span className="font-mono text-xs">{ist} IST</span>;
}

// ── Top status bar ───────────────────────────────────────────────────────────

function StatusBar({
  portfolio, portfolioErr, stream,
}: {
  portfolio: PortfolioSnapshot | undefined; portfolioErr: boolean;
  stream: ReturnType<typeof useLiveStream>;
}) {
  const { connection, market, quotes } = stream;
  const healthQ = useWidgetQuery<{ status?: string; uptime_s?: number }>({
    queryKey: ["mc", "health"], path: "/health/live", refetchInterval: R.health, timeoutMs: 10_000,
  });

  const idx = (key: string, label: string) => {
    const q = quotes[key];
    return (
      <div className="flex items-baseline gap-1.5" key={key}>
        <span className="text-[10px] text-muted-foreground">{label}</span>
        <span className="text-xs font-semibold">
          {q?.ltp != null ? q.ltp.toLocaleString("en-IN", { maximumFractionDigits: key === "INDIAVIX" ? 2 : 0 }) : "—"}
        </span>
        {q?.change_pct != null && (
          <span className={`text-[10px] ${q.change_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {q.change_pct >= 0 ? "▲" : "▼"}{Math.abs(q.change_pct).toFixed(2)}%
          </span>
        )}
      </div>
    );
  };

  const healthy = healthQ.data?.status === "ok";
  const todayPnl = portfolio != null
    ? (portfolio.realised_pnl_today ?? 0) + (portfolio.unrealised_pnl ?? 0)
    : null;

  return (
    <div className="bg-card border border-border rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-2" data-testid="mc-status-bar">
      {/* Market status */}
      <div className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${market?.is_open ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`} />
        <span className="text-xs font-semibold">NSE {market?.state ?? "—"}</span>
        {market?.next_transition && (
          <span className="text-[10px] text-muted-foreground hidden xl:inline">
            {market.next_transition.event} {market.next_transition.at_ist?.slice(11, 16)}
          </span>
        )}
      </div>
      <IstClock />
      {/* Indices */}
      {idx("NIFTY", "NIFTY")}
      {idx("BANKNIFTY", "BANK NIFTY")}
      {idx("INDIAVIX", "VIX")}
      <span className="hidden md:inline-block w-px h-4 bg-border" />
      {/* Portfolio strip */}
      <div className="flex items-baseline gap-1.5">
        <span className="text-[10px] text-muted-foreground">Value</span>
        <span className="text-xs font-semibold">{portfolioErr ? "—" : fmtINR(portfolio?.equity)}</span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[10px] text-muted-foreground">Today P&L</span>
        <PnlText value={todayPnl} className="text-xs font-semibold" />
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[10px] text-muted-foreground">Open</span>
        <span className="text-xs font-semibold">{portfolioErr ? "—" : (portfolio?.open_position_count ?? "—")}</span>
      </div>
      <span className="ml-auto flex items-center gap-3">
        {/* System health */}
        <span className="flex items-center gap-1" title={`API server ${healthy ? "healthy" : "unreachable"}`}>
          <HeartPulse className={`w-3.5 h-3.5 ${healthy ? "text-emerald-400" : "text-red-400"}`} />
          <span className={`text-[10px] ${healthy ? "text-emerald-400" : "text-red-400"}`}>
            {healthQ.isLoading ? "…" : healthy ? "HEALTHY" : "DOWN"}
          </span>
        </span>
        {/* Stream connection */}
        <span className="flex items-center gap-1" title={`Live stream: ${connection}`}>
          {connection === "connected"
            ? <Wifi className="w-3.5 h-3.5 text-emerald-400" />
            : <WifiOff className="w-3.5 h-3.5 text-amber-400" />}
        </span>
        <Badge variant="outline" className="text-[9px] border-amber-500/40 text-amber-300">PAPER</Badge>
      </span>
    </div>
  );
}

// ── Panel 1 — Live AI Pipeline ───────────────────────────────────────────────

function PipelinePanel({ scanning, replayQ }: {
  scanning: boolean;
  /** Shared unified replay snapshot query — the ONLY source of in/out/rejected/pending/cancelled (also drives Mission Map & Replay widget). */
  replayQ: ReturnType<typeof useWidgetQuery<ReplayResp>>;
}) {
  const summaryQ = useWidgetQuery<PipelineSummary>({
    queryKey: ["mc", "pipeline-summary"], path: "/pipeline/summary", refetchInterval: R.pipeline,
  });

  const replayByLabel = useMemo(() => {
    const m = new Map<string, ReplayStage>();
    for (const s of replayQ.data?.stages ?? []) {
      m.set(s.label.toUpperCase().replace(/[\s&]+/g, "_"), s);
      m.set(s.id.toUpperCase(), s);
    }
    return m;
  }, [replayQ.data]);

  const stages = summaryQ.data?.stages ?? [];

  return (
    <Widget
      title="Live AI Pipeline" icon={Cpu} query={summaryQ} refreshMs={R.pipeline}
      testId="mc-pipeline" skeletonClass="h-64"
      headerExtra={
        <>
          {summaryQ.data?.scan_id && (
            <span className="text-[9px] text-muted-foreground font-mono truncate max-w-[120px]">{summaryQ.data.scan_id}</span>
          )}
          {scanning && <Badge className="animate-pulse text-[9px] px-1.5 py-0"><Radio className="h-2.5 w-2.5 mr-1" />SCANNING</Badge>}
        </>
      }
    >
      {stages.length === 0 ? (
        <p className="text-xs text-muted-foreground">No pipeline events recorded yet — the flow populates on the next scan.</p>
      ) : (
        <div className="space-y-1.5">
          {stages.map((s) => {
            const active = scanning && s.last_ts != null && Date.now() - new Date(s.last_ts).getTime() < 60_000;
            const r = replayByLabel.get(s.stage) ?? replayByLabel.get(STAGE_LABELS[s.stage]?.toUpperCase().replace(/[\s]+/g, "_") ?? "");
            return (
              <div
                key={s.stage}
                data-testid={`mc-stage-${s.stage.toLowerCase()}`}
                className={`rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors ${
                  active ? "border-primary bg-primary/10 animate-pulse" : "border-border/60 bg-muted/20"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{STAGE_LABELS[s.stage] ?? s.stage}</span>
                  {s.errors > 0 && (
                    <span className="text-red-400 flex items-center gap-0.5" title={`${s.errors} errors`}>
                      <AlertTriangle className="w-3 h-3" />{s.errors}
                    </span>
                  )}
                  <span className="ml-auto text-[9px] text-muted-foreground">
                    {r?.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s · ` : ""}{timeAgo(s.last_ts)}
                  </span>
                </div>
                <div className="flex flex-wrap gap-x-2.5 mt-0.5 text-[10px] text-muted-foreground">
                  {r ? (
                    <>
                      <span>in <b className="text-foreground">{r.stocks_in}</b></span>
                      <span>out <b className="text-emerald-400">{r.stocks_out}</b></span>
                      <span>rej <b className={r.rejected > 0 ? "text-red-400" : "text-foreground"}>{r.rejected}</b></span>
                      <span>pend <b className={r.pending > 0 ? "text-amber-400" : "text-foreground"}>{r.pending}</b></span>
                      <span>canc <b className="text-foreground">{r.cancelled}</b></span>
                    </>
                  ) : (
                    <>
                      <span className="text-emerald-400">{s.completed}✓</span>
                      {s.rejected > 0 && <span className="text-red-400">{s.rejected}✗</span>}
                      <span>{s.events} events</span>
                    </>
                  )}
                  {s.last_symbol && <span className="truncate font-mono">{s.last_symbol}</span>}
                </div>
              </div>
            );
          })}
          {replayQ.isError && (
            <p className="text-[10px] text-amber-400/80 pt-1">
              Replay counts unavailable ({(replayQ.error as Error)?.message}); showing event counts only.
            </p>
          )}
        </div>
      )}
    </Widget>
  );
}

// ── Panel 2 — Live Scanner ───────────────────────────────────────────────────

function ScannerPanel({ scanQ }: { scanQ: ReturnType<typeof useWidgetQuery<ScanStatus>> }) {
  const d = scanQ.data;
  const meta = d?.latest_scan ?? d ?? {};
  const progress = d?.progress ?? null;
  const scanning = !!progress?.stage;
  const done = progress?.symbols_done ?? 0;
  const total = progress?.symbols_total ?? (meta as { symbols_total?: number }).symbols_total ?? 0;
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  const currentSymbol = progress?.current_symbol ?? progress?.symbol ?? null;
  const ageMin = d?.age_minutes;

  return (
    <Widget
      title="Live Scanner" icon={Radar} query={scanQ} refreshMs={R.scan} testId="mc-scanner"
      headerExtra={scanning
        ? <Badge className="animate-pulse text-[9px] px-1.5 py-0">RUNNING · {progress?.stage}</Badge>
        : <Badge variant="secondary" className="text-[9px] px-1.5 py-0">IDLE</Badge>}
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Universe</p><p className="font-semibold">{total || "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Scanned</p><p className="font-semibold">{scanning ? done : (total || "—")}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Remaining</p><p className="font-semibold">{scanning && total ? total - done : 0}</p></div>
        <div>
          <p className="text-muted-foreground text-[10px]">Freshness</p>
          <p className={`font-semibold ${ageMin != null && ageMin > 30 ? "text-amber-400" : ""}`}>
            {ageMin != null ? `${Math.round(ageMin)}m` : "—"}
          </p>
        </div>
      </div>
      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-muted mb-1.5">
        <div
          className={`h-1.5 rounded-full transition-all ${scanning ? "bg-primary" : "bg-emerald-500"}`}
          style={{ width: `${scanning ? pct : 100}%` }}
        />
      </div>
      <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
        {scanning ? (
          <>
            <span>{done}/{total} · {pct.toFixed(0)}%</span>
            {currentSymbol && <span className="font-mono text-foreground">{currentSymbol}</span>}
          </>
        ) : (
          <>
            <Clock className="w-3 h-3" />
            <span>Last scan {d?.snapshot_ts ? timeAgo(d.snapshot_ts) : "—"}</span>
            {(meta as { scan_id?: string }).scan_id && (
              <span className="font-mono truncate">{(meta as { scan_id?: string }).scan_id}</span>
            )}
          </>
        )}
      </div>
    </Widget>
  );
}

// ── Panel 3 — Live Paper Trading ─────────────────────────────────────────────

function PaperTradingPanel({ portfolio }: { portfolio: PortfolioSnapshot | undefined }) {
  const ledgerQ = useWidgetQuery<{ success?: boolean; ledger?: LedgerItem[] }>({
    queryKey: ["mc", "ledger"], path: "/phase20/ledger?limit=200", refetchInterval: R.ledger, timeoutMs: 30_000,
  });

  const ledger = ledgerQ.data?.ledger ?? [];
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const t of ledger) {
      const st = (t.status || "UNKNOWN").toUpperCase();
      c[st] = (c[st] || 0) + 1;
    }
    return c;
  }, [ledger]);

  const open = counts["OPEN"] ?? 0;
  const closed = counts["CLOSED"] ?? 0;
  const pending = (counts["PENDING"] ?? 0) + (counts["EXIT_PENDING"] ?? 0);
  const rejected = counts["REJECTED"] ?? 0;
  const cancelled = counts["CANCELLED"] ?? 0;
  const filled = ledger.filter((t) => t.fill_ts != null).length;

  const equity = portfolio?.equity ?? 0;
  const invested = portfolio?.invested_value ?? 0;
  const utilisation = equity > 0 ? (invested / equity) * 100 : 0;
  const recent = ledger.slice(0, 6);

  return (
    <Widget
      title="Live Paper Trading" icon={Rocket} query={ledgerQ} refreshMs={R.ledger} testId="mc-paper-trading"
      headerExtra={pending > 0 && <Badge variant="outline" className="text-[9px] px-1.5 py-0 border-amber-500/40 text-amber-300">{pending} pending</Badge>}
    >
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Filled</p><p className="font-semibold text-emerald-400">{filled}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Pending</p><p className={`font-semibold ${pending > 0 ? "text-amber-400" : ""}`}>{pending}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Rejected</p><p className={`font-semibold ${rejected > 0 ? "text-red-400" : ""}`}>{rejected}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Cancelled</p><p className="font-semibold">{cancelled}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Open / Closed</p><p className="font-semibold">{open} / {closed}</p></div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] mb-2">
        <div><p className="text-muted-foreground text-[10px]">Portfolio Value</p><p className="font-semibold">{fmtINR(portfolio?.equity)}</p></div>
        <div>
          <p className="text-muted-foreground text-[10px]">Today P&L</p>
          <PnlText
            value={portfolio != null ? (portfolio.realised_pnl_today ?? 0) + (portfolio.unrealised_pnl ?? 0) : null}
            className="font-semibold"
          />
        </div>
        <div><p className="text-muted-foreground text-[10px]">Cash</p><p className="font-semibold">{fmtINR(portfolio?.cash)}</p></div>
        <div>
          <p className="text-muted-foreground text-[10px]">Utilisation</p>
          <p className="font-semibold">{portfolio != null ? `${utilisation.toFixed(1)}%` : "—"}</p>
        </div>
      </div>
      {/* Recent fills */}
      <p className="text-[10px] text-muted-foreground mb-1">Recent trades</p>
      {recent.length === 0 ? (
        <p className="text-[11px] text-muted-foreground">No paper trades recorded yet.</p>
      ) : (
        <div className="space-y-0.5 max-h-[130px] overflow-y-auto">
          {recent.map((t) => (
            <div key={t.trade_id} className="flex items-center gap-2 text-[10px] border-b border-border/40 py-0.5 last:border-0">
              <span className={`w-8 shrink-0 font-semibold ${t.side === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{t.side}</span>
              <span className="w-20 shrink-0 font-mono truncate">{t.symbol}</span>
              <span className="text-muted-foreground">{t.quantity} @ {fmtINR(t.fill_price, 2)}</span>
              <span className="ml-auto flex items-center gap-1.5">
                {t.realized_pnl != null && <PnlText value={t.realized_pnl} />}
                <span className="text-muted-foreground">{t.status}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </Widget>
  );
}

// ── Panel 5 — Live Portfolio (right sidebar) ─────────────────────────────────

function PortfolioSidebar({ q }: { q: ReturnType<typeof useWidgetQuery<PortfolioSnapshot>> }) {
  const p = q.data;
  const equity = p?.equity ?? 0;
  const initial = p?.initial_capital ?? 0;
  const netReturnPct = initial > 0 ? ((equity - initial) / initial) * 100 : null;
  const exposurePct = equity > 0 ? ((p?.invested_value ?? 0) / equity) * 100 : 0;
  const positions = p?.open_positions ?? [];
  const largest = positions.length
    ? [...positions].sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))[0]
    : null;
  const sectors = (p?.sector_exposures ?? []).slice(0, 5);
  const realisedToday = p?.realised_pnl_today ?? 0;

  return (
    <Widget title="Live Portfolio" icon={Wallet} query={q} refreshMs={R.portfolio} testId="mc-portfolio" skeletonClass="h-72">
      <div className="grid grid-cols-2 gap-2 text-[11px] mb-3">
        <div><p className="text-muted-foreground text-[10px]">Value</p><p className="font-semibold text-sm">{fmtINR(p?.equity)}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Cash</p><p className="font-semibold text-sm">{fmtINR(p?.cash)}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Invested</p><p className="font-semibold">{fmtINR(p?.invested_value)}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Exposure</p><p className="font-semibold">{p != null ? `${exposurePct.toFixed(1)}%` : "—"}</p></div>
        <div><p className="text-muted-foreground text-[10px]">Realized (today)</p><PnlText value={realisedToday} className="font-semibold" /></div>
        <div><p className="text-muted-foreground text-[10px]">Unrealized</p><PnlText value={p?.unrealised_pnl} className="font-semibold" /></div>
        <div className="col-span-2">
          <p className="text-muted-foreground text-[10px]">Net Return</p>
          <p className={`font-semibold ${netReturnPct == null ? "" : netReturnPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {netReturnPct == null ? "—" : `${netReturnPct >= 0 ? "+" : ""}${netReturnPct.toFixed(2)}%`}
          </p>
        </div>
      </div>

      {/* Sector allocation */}
      <p className="text-[10px] text-muted-foreground mb-1 flex items-center gap-1"><PieChart className="w-3 h-3" /> Sector allocation</p>
      {sectors.length === 0 ? (
        <p className="text-[11px] text-muted-foreground mb-3">No open exposure.</p>
      ) : (
        <div className="space-y-1 mb-3">
          {sectors.map((s) => (
            <div key={s.sector} className="text-[10px]">
              <div className="flex justify-between">
                <span className="truncate">{s.sector}</span>
                <span className="text-muted-foreground">{s.exposure_pct.toFixed(1)}%</span>
              </div>
              <div className="h-1 rounded-full bg-muted mt-0.5">
                <div className="h-1 rounded-full bg-teal-500" style={{ width: `${Math.min(100, s.exposure_pct)}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Largest position */}
      <p className="text-[10px] text-muted-foreground mb-1">Largest position</p>
      {largest ? (
        <div className="rounded-lg bg-muted/20 border border-border/60 p-2 text-[11px]">
          <div className="flex justify-between">
            <span className="font-semibold font-mono">{largest.symbol}</span>
            <PnlText value={largest.unrealised_pnl} />
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground mt-0.5">
            <span>{largest.quantity} @ {fmtINR(largest.avg_entry_price, 2)}</span>
            <span>{fmtINR(largest.market_value)}</span>
          </div>
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">No open positions.</p>
      )}
    </Widget>
  );
}

// ── Panel 4 — Live Event Stream (bottom strip) ───────────────────────────────

function EventStreamPanel({ streamEvents }: { streamEvents: PipelineStreamEvent[] }) {
  const feedQ = useWidgetQuery<{ events?: PipelineEvent[] }>({
    queryKey: ["mc", "event-feed"], path: "/pipeline/events?limit=80&newest_first=true", refetchInterval: R.events,
  });
  // Merge SSE-streamed events (rendered immediately) ahead of the REST feed,
  // deduped by event id, newest first.
  const events = useMemo(() => {
    const rest = feedQ.data?.events ?? [];
    const seen = new Set(rest.map((e) => e.id));
    const fresh = streamEvents.filter((e) => !seen.has(e.id));
    return [...fresh, ...rest].sort((a, b) => b.id - a.id).slice(0, 100);
  }, [feedQ.data, streamEvents]);
  return (
    <Widget title="Live Event Stream" icon={Activity} query={feedQ} refreshMs={R.events} testId="mc-event-stream" skeletonClass="h-24"
      headerExtra={<span className="text-[9px] text-muted-foreground">SSE + polling · pipeline event store</span>}
    >
      {events.length === 0 ? (
        <p className="text-xs text-muted-foreground">No events yet — the feed populates as the pipeline runs.</p>
      ) : (
        <div className="max-h-[180px] overflow-y-auto font-mono text-[10px] space-y-0.5">
          {events.map((e) => {
            const tone = eventTone(e.event_type);
            const Icon = tone === "bad" ? XCircle : tone === "ok" ? CheckCircle2 : tone === "warn" ? AlertTriangle : ChevronRight;
            return (
              <div key={e.id} className="flex items-center gap-2 border-b border-border/30 py-0.5 last:border-0">
                <Icon className={`h-3 w-3 shrink-0 ${toneClass[tone]}`} />
                <span className="text-muted-foreground w-14 shrink-0">{timeAgo(e.ts)}</span>
                <span className="w-28 shrink-0 truncate text-muted-foreground/70">{e.stage}</span>
                <span className={`w-44 shrink-0 truncate ${toneClass[tone]}`}>{e.event_type}</span>
                <span className="w-24 shrink-0 font-semibold truncate">{e.symbol ?? ""}</span>
                <span className="text-muted-foreground truncate">
                  {String(e.payload?.reason ?? e.payload?.action ?? e.payload?.strategy_name ?? e.payload?.trade_id ?? "")}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Widget>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function MissionControl() {
  const stream = useLiveStream(); // single SSE connection shared with the status bar
  const { pipelineEventId, scanEvent } = stream;
  const queryClient = useQueryClient();

  // SSE tail: new pipeline events invalidate every affected canonical query so
  // the page reacts within a second instead of waiting for the next poll.
  useEffect(() => {
    if (!pipelineEventId) return;
    void queryClient.invalidateQueries({ queryKey: ["mc", "event-feed"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "pipeline-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "ledger"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "portfolio"] });
  }, [pipelineEventId, queryClient]);

  // Scan lifecycle events (scan.started / scan.completed) refresh the scanner,
  // replay counts and portfolio immediately.
  useEffect(() => {
    if (!scanEvent) return;
    void queryClient.invalidateQueries({ queryKey: ["mc", "scan-status"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "replay-latest"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "pipeline-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "portfolio"] });
  }, [scanEvent, queryClient]);

  // Shared queries used by multiple regions (fetched ONCE each).
  const portfolioQ = useWidgetQuery<PortfolioSnapshot>({
    queryKey: ["mc", "portfolio"], path: "/portfolio/snapshot", refetchInterval: R.portfolio, timeoutMs: 30_000,
  });
  const scanQ = useWidgetQuery<ScanStatus>({
    queryKey: ["mc", "scan-status"], path: "/live-data/scan/status", refetchInterval: R.scan,
  });
  const scanning = !!scanQ.data?.progress?.stage;
  // Unified replay snapshot — fetched ONCE and shared by the pipeline panel,
  // Mission Map and Replay widget (no separate fetch of stage counts).
  const replayQ = useWidgetQuery<ReplayResp>({
    queryKey: ["mc", "replay-latest"], path: "/replay/sessions/latest",
    refetchInterval: R.replay, timeoutMs: 45_000,
  });

  return (
    <div className="p-4 space-y-3 max-w-[1700px] mx-auto" data-testid="page-mission-control">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Radio className="h-5 w-5 text-primary" />
        <h1 className="text-lg font-semibold">Mission Control</h1>
        <Badge variant="outline" className="text-[10px]">{LABEL}</Badge>
        <span className="text-[10px] text-muted-foreground ml-auto">
          All data from the canonical pipeline event store, replay snapshot & phase20 ledger — no page-local calculations.
        </span>
      </div>

      {/* Canonical data freshness indicator (scan snapshot + staleness) */}
      <DataFreshnessBar variant="scan" />

      {/* Top status bar */}
      <StatusBar portfolio={portfolioQ.data} portfolioErr={portfolioQ.isError} stream={stream} />

      {/* Mission Map — Universe → Portfolio stage flow (shared replay query) */}
      <MissionMapWidget replayQ={replayQ} scanning={scanning} />

      {/* Main grid: left pipeline · center trading · right portfolio */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 items-start">
        <PipelinePanel scanning={scanning} replayQ={replayQ} />
        <div className="lg:col-span-2 space-y-3 min-w-0">
          <ScannerPanel scanQ={scanQ} />
          <PaperTradingPanel portfolio={portfolioQ.data} />
        </div>
        <PortfolioSidebar q={portfolioQ} />
      </div>

      {/* Intelligence row: AI health · AI learning · alert center */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-start">
        <AiHealthWidget />
        <AiLearningWidget />
        <AlertCenterWidget />
      </div>

      {/* Ops row: replay · backtest · broker · system health */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 items-start">
        <ReplayWidget replayQ={replayQ} />
        <BacktestWidget />
        <BrokerWidget />
        <SystemHealthWidget />
      </div>

      {/* Mission Timeline — the trading day from open to close */}
      <MissionTimelineWidget />

      {/* Bottom event feed strip */}
      <EventStreamPanel streamEvents={stream.pipelineEvents} />
    </div>
  );
}
