/**
 * SessionWidgets.tsx — Phase 25.1 Mission Control live-operations widgets.
 *
 * Parts 1–4 of the Phase 25.1 spec, all PURE DASHBOARD:
 *   1. MarketSessionWidget    — NSE session progress (IST clock, phase strip)
 *   2. ThroughputWidget       — today's cumulative AI funnel + order/trade counts
 *   3. LivePerformanceWidget  — today's return, PnL, win-rate, best strategy/sector
 *   4. MarketBreadthWidget    — advance/decline, sectors, VIX, indices, regime
 *
 * NO new backend logic. Every widget reads existing canonical endpoints:
 *   - unified replay snapshot   (prop `replay`, shared page query — never refetched here)
 *   - canonical portfolio       (prop `portfolio`, shared page query — never refetched here)
 *   - /phase20/ledger           (own query, or shared via `ledger` prop + useLedgerToday())
 *   - /market-overview + /market-intelligence/breadth (breadth widget's own queries)
 *
 * Presentation-level aggregation of canonical rows (counting today-IST events,
 * averaging today's closed trades) is allowed; business metrics that an endpoint
 * already provides (equity, PnL, sector exposure) are read straight from the field.
 *
 * IST time is ALWAYS derived via Intl.DateTimeFormat parts (Asia/Kolkata) — never
 * local-timezone math — mirroring the lib/homeRoute.ts pattern.
 */
import { useEffect, useMemo, useState } from "react";
import {
  Clock, Gauge, TrendingUp, Waves, Info,
} from "lucide-react";
import { Widget, useWidgetQuery, PnlText } from "./Widget";

// ── Shared IST helpers (Intl parts only — no local TZ math) ─────────────────

interface IstParts { weekday: string; hour: number; minute: number; second: number; date: string }

/** Break a Date into Asia/Kolkata parts using Intl (never getHours() etc.). */
function istPartsOf(now: Date): IstParts {
  const p = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", hour12: false,
    weekday: "short", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(now);
  const get = (t: string) => p.find((x) => x.type === t)?.value ?? "";
  return {
    weekday: get("weekday"),
    hour: parseInt(get("hour"), 10) || 0,
    minute: parseInt(get("minute"), 10) || 0,
    second: parseInt(get("second"), 10) || 0,
    date: `${get("year")}-${get("month")}-${get("day")}`,
  };
}

/** IST calendar date (YYYY-MM-DD) of an arbitrary timestamp — via Intl. */
function istDateOf(ts: string | null | undefined): string | null {
  if (!ts) return null;
  const d = new Date(ts);
  if (isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

/** A 1-second ticking clock that yields Asia/Kolkata parts. */
function useIstClock(): IstParts {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(id);
  }, []);
  return istPartsOf(now);
}

function fmtMinsAsTime(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function fmtRemaining(mins: number): string {
  if (mins <= 0) return "0m";
  const h = Math.floor(mins / 60);
  const m = Math.round(mins % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// ═════════════════════════════════════════════════════════════════════════════
// PART 1 — MarketSessionWidget
// ═════════════════════════════════════════════════════════════════════════════

interface Phase {
  id: string; label: string; startMin: number; endMin: number;
}
// NSE cash-market session (IST). Pre-open + auction + continuous + closing.
const SESSION_PHASES: Phase[] = [
  { id: "preopen",    label: "Pre-Open",         startMin: 9 * 60,       endMin: 9 * 60 + 8 },
  { id: "auction",    label: "Opening Auction",  startMin: 9 * 60 + 8,   endMin: 9 * 60 + 15 },
  { id: "continuous", label: "Continuous",       startMin: 9 * 60 + 15,  endMin: 15 * 60 + 30 },
  { id: "closing",    label: "Closing",          startMin: 15 * 60 + 30, endMin: 16 * 60 },
];
const SESSION_OPEN_MIN = SESSION_PHASES[0].startMin;    // 09:00
const SESSION_CLOSE_MIN = SESSION_PHASES[SESSION_PHASES.length - 1].endMin; // 16:00

interface MarketProp {
  is_open?: boolean;
  state?: string;
  next_transition?: { event?: string; at_ist?: string; seconds_until?: number } | null;
}

export function MarketSessionWidget({ market }: { market?: MarketProp }) {
  const ist = useIstClock();
  // This widget derives entirely from the local IST clock; use a resolved query
  // shim so the shared <Widget> chrome renders (no fetch — session math is pure).
  const clockQ = useWidgetQuery<{ ok: boolean }>({
    queryKey: ["mc", "market-session-clock"], path: "/health/live",
    refetchInterval: 60_000, timeoutMs: 10_000, retry: 0,
  });

  const isWeekend = ist.weekday === "Sat" || ist.weekday === "Sun";
  const nowMin = ist.hour * 60 + ist.minute;

  // Authoritative live-stream state wins when present: on an NSE holiday (or
  // any closed state the backend reports) never show a computed in-session
  // phase/progress from clock-only logic. Clock math is the fallback only.
  const authClosed = market?.is_open === false;
  const authOpen = market?.is_open;

  const activePhase = isWeekend || authClosed
    ? null
    : SESSION_PHASES.find((p) => nowMin >= p.startMin && nowMin < p.endMin) ?? null;

  const beforeOpen = !isWeekend && nowMin < SESSION_OPEN_MIN;
  const afterClose = !isWeekend && nowMin >= SESSION_CLOSE_MIN;
  const closed = isWeekend || beforeOpen || afterClose || authClosed;

  // Session progress across the whole 09:00–16:00 IST window.
  const spanMin = SESSION_CLOSE_MIN - SESSION_OPEN_MIN;
  const elapsed = Math.max(0, Math.min(spanMin, nowMin - SESSION_OPEN_MIN));
  const progressPct = closed ? (afterClose ? 100 : 0) : (elapsed / spanMin) * 100;
  const remainingMin = SESSION_CLOSE_MIN - nowMin;

  const clockStr = `${String(ist.hour).padStart(2, "0")}:${String(ist.minute).padStart(2, "0")}:${String(ist.second).padStart(2, "0")}`;

  // Authoritative live-stream state (prop) overrides the computed label when present.
  const authState = market?.state;

  return (
    <Widget
      title="Market Session" icon={Clock} query={clockQ} refreshMs={60_000}
      testId="mc-market-session" skeletonClass="h-40"
      headerExtra={
        <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-medium border ${
          (authOpen ?? !closed)
            ? "bg-emerald-950/60 border-emerald-700/40 text-emerald-300"
            : "bg-amber-950/60 border-amber-700/40 text-amber-300"
        }`}>
          <span className={`w-1 h-1 rounded-full inline-block ${(authOpen ?? !closed) ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
          NSE {authState ?? (closed ? (isWeekend ? "WEEKEND" : afterClose ? "CLOSED" : "PRE") : activePhase?.label.toUpperCase() ?? "OPEN")}
        </span>
      }
    >
      {isWeekend ? (
        <div className="rounded-lg border border-amber-700/40 bg-amber-950/30 p-3 text-center" data-testid="mc-session-weekend">
          <p className="text-[11px] font-semibold text-amber-300">Market closed — weekend</p>
          <p className="text-[10px] text-amber-400/70 mt-0.5">NSE cash market trades Mon–Fri · 09:15–15:30 IST</p>
          <p className="font-mono text-lg mt-2 text-foreground">{clockStr} <span className="text-[10px] text-muted-foreground">IST</span></p>
        </div>
      ) : (
        <>
          {/* Times row */}
          <div className="grid grid-cols-4 gap-2 text-[11px] mb-2.5">
            <div>
              <p className="text-muted-foreground text-[10px]">Open</p>
              <p className="font-semibold font-mono">09:00</p>
            </div>
            <div>
              <p className="text-muted-foreground text-[10px]">Now (IST)</p>
              <p className="font-semibold font-mono text-teal-300">{clockStr}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-[10px]">Close</p>
              <p className="font-semibold font-mono">16:00</p>
            </div>
            <div>
              <p className="text-muted-foreground text-[10px]">Remaining</p>
              <p className={`font-semibold ${remainingMin <= 0 ? "text-muted-foreground" : ""}`}>
                {remainingMin > 0 && !beforeOpen ? fmtRemaining(remainingMin) : afterClose ? "—" : `opens ${fmtRemaining(SESSION_OPEN_MIN - nowMin)}`}
              </p>
            </div>
          </div>

          {/* Progress bar */}
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] text-muted-foreground">Session progress</span>
            <span className="ml-auto text-[10px] font-semibold">{progressPct.toFixed(1)}%</span>
          </div>
          <div className="h-1.5 rounded-full bg-muted mb-3">
            <div
              className={`h-1.5 rounded-full transition-all ${afterClose ? "bg-slate-500" : "bg-teal-500"}`}
              style={{ width: `${Math.max(0, Math.min(100, progressPct))}%` }}
              data-testid="mc-session-progress"
            />
          </div>

          {/* Phase strip — active phase highlighted */}
          <div className="flex gap-1" data-testid="mc-session-phases">
            {SESSION_PHASES.map((p) => {
              const active = activePhase?.id === p.id;
              const done = !closed && nowMin >= p.endMin;
              return (
                <div
                  key={p.id}
                  className={`flex-1 rounded-md border px-1.5 py-1 transition-colors ${
                    active
                      ? "border-teal-500 bg-teal-500/15"
                      : done
                        ? "border-border/60 bg-muted/30"
                        : "border-border/40 bg-muted/10"
                  }`}
                  data-testid={`mc-session-phase-${p.id}`}
                >
                  <p className={`text-[9px] font-semibold truncate ${active ? "text-teal-300" : done ? "text-muted-foreground" : "text-muted-foreground/70"}`}>
                    {p.label}
                  </p>
                  <p className="text-[8px] text-muted-foreground font-mono">
                    {fmtMinsAsTime(p.startMin)}–{fmtMinsAsTime(p.endMin)}
                  </p>
                </div>
              );
            })}
          </div>

          {beforeOpen && (
            <p className="text-[10px] text-amber-400/80 mt-2">Pre-market — session opens at 09:00 IST.</p>
          )}
          {afterClose && (
            <p className="text-[10px] text-amber-400/80 mt-2" data-testid="mc-session-closed">Market closed for the day — resumes 09:00 IST next trading day.</p>
          )}
          {market?.next_transition?.event && market.next_transition.at_ist && (
            <p className="text-[9px] text-muted-foreground mt-2">
              Next: {market.next_transition.event} · {market.next_transition.at_ist.slice(11, 16)} IST
            </p>
          )}
        </>
      )}
    </Widget>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Shared ledger types + today-IST hook (page calls once, passes to widgets 2 & 3)
// ═════════════════════════════════════════════════════════════════════════════

export interface LedgerRow {
  trade_id: string;
  symbol: string;
  sector?: string | null;
  strategy_id?: string | null;
  strategy_name?: string | null;
  side: string;                 // BUY / SELL
  status: string;               // OPEN / CLOSED / EXIT_PENDING / PENDING / REJECTED / CANCELLED
  quantity?: number | null;
  fill_price?: number | null;
  fill_ts?: string | null;
  exit_price?: number | null;
  exit_ts?: string | null;
  realized_pnl?: number | null;
  created_at?: string | null;
}
interface LedgerResp { success?: boolean; ledger?: LedgerRow[] }

/**
 * useLedgerToday — one shared /phase20/ledger query the Mission Control page
 * calls ONCE and passes down to ThroughputWidget + LivePerformanceWidget as a
 * prop, so the ledger is never fetched twice. 30 s cadence per spec.
 */
export function useLedgerToday() {
  const q = useWidgetQuery<LedgerResp>({
    queryKey: ["mc", "phase20-ledger-today"], path: "/phase20/ledger?limit=500",
    refetchInterval: 30_000, timeoutMs: 30_000,
  });
  return q;
}

/** Rows whose fill happened today (IST); falls back to created_at for un-filled rows. */
function ledgerRowsToday(rows: LedgerRow[], todayIst: string): LedgerRow[] {
  return rows.filter((r) => {
    const d = istDateOf(r.fill_ts) ?? istDateOf(r.created_at);
    return d === todayIst;
  });
}

// ═════════════════════════════════════════════════════════════════════════════
// PART 2 — ThroughputWidget
// ═════════════════════════════════════════════════════════════════════════════

interface ReplayStageLite {
  id: string; label: string;
  stocks_in?: number; stocks_out?: number;
  rejected?: number; pending?: number; cancelled?: number;
}
interface ReplayDecision { symbol: string; final_action?: string | null }
interface ReplaySnapshot {
  stages?: ReplayStageLite[];
  decisions?: ReplayDecision[];
  error?: string;
}

// Map replay stage ids (canonical) → spec funnel labels.
const FUNNEL_STAGES: { id: string; label: string; field: "stocks_out" | "stocks_in" }[] = [
  { id: "supervisor",          label: "Universe Loaded",       field: "stocks_out" },
  { id: "market_data",         label: "Scanned",               field: "stocks_out" },
  { id: "research",            label: "Analysed",              field: "stocks_out" },
  { id: "market_intelligence", label: "Market Intelligence",   field: "stocks_out" },
  { id: "monitoring",          label: "Monitoring",            field: "stocks_out" },
  { id: "strategy",            label: "Strategy Evaluated",    field: "stocks_out" },
  { id: "risk",                label: "Risk Approved",         field: "stocks_out" },
];

export function ThroughputWidget({
  replay, ledger,
}: {
  replay?: ReplaySnapshot;
  /** Shared ledger query result from useLedgerToday() (page passes it down). */
  ledger: ReturnType<typeof useLedgerToday>;
}) {
  const todayIst = istPartsOf(new Date()).date;
  const stageById = useMemo(() => {
    const m = new Map<string, ReplayStageLite>();
    for (const s of replay?.stages ?? []) m.set(s.id, s);
    return m;
  }, [replay]);

  // Risk rejected = the risk stage's rejected count (canonical field).
  const riskStage = stageById.get("risk");
  const riskRejected = Math.max(0, riskStage?.rejected ?? 0);

  // BUY / SELL / WATCH from the replay decision stage (final_action).
  const signals = useMemo(() => {
    const c = { BUY: 0, SELL: 0, WATCH: 0 };
    for (const d of replay?.decisions ?? []) {
      const a = (d.final_action ?? "").toUpperCase();
      if (a === "BUY") c.BUY++;
      else if (a === "SELL") c.SELL++;
      else if (a === "WATCH") c.WATCH++;
    }
    return c;
  }, [replay]);

  // Order / position / trade counts from today's ledger rows (canonical events).
  const rowsToday = useMemo(
    () => ledgerRowsToday(ledger.data?.ledger ?? [], todayIst),
    [ledger.data, todayIst],
  );
  const orderCounts = useMemo(() => {
    let submitted = 0, filled = 0, cancelled = 0, open = 0, closed = 0, completed = 0;
    for (const r of rowsToday) {
      submitted++;
      if (r.fill_ts != null) filled++;
      const st = (r.status || "").toUpperCase();
      if (st === "CANCELLED" || st === "REJECTED") cancelled++;
      if (st === "OPEN") open++;
      if (st === "CLOSED") { closed++; completed++; }
    }
    return { submitted, filled, cancelled, open, closed, completed };
  }, [rowsToday]);

  const replayMissing = !replay || !!replay.error || (replay.stages ?? []).length === 0;

  const Cell = ({ label, value, tone = "" }: { label: string; value: number | string; tone?: string }) => (
    <div>
      <p className="text-muted-foreground text-[9px] leading-tight">{label}</p>
      <p className={`font-semibold text-[13px] ${tone}`}>{value}</p>
    </div>
  );

  return (
    <Widget
      title="AI Throughput (Today)" icon={Gauge} query={ledger} refreshMs={30_000}
      testId="mc-throughput" skeletonClass="h-52"
      headerExtra={<span className="text-[9px] text-muted-foreground">replay funnel · phase20 ledger</span>}
    >
      {/* Pipeline funnel from the unified replay snapshot */}
      <p className="text-[10px] text-muted-foreground mb-1">Pipeline funnel</p>
      {replayMissing ? (
        <p className="text-[11px] text-amber-400/80 mb-2 rounded-md border border-amber-700/30 bg-amber-950/20 px-2 py-1.5" data-testid="mc-throughput-noreplay">
          No replay snapshot yet — funnel populates on the next scan.
        </p>
      ) : (
        <div className="grid grid-cols-4 gap-x-2 gap-y-2 mb-3" data-testid="mc-throughput-funnel">
          {FUNNEL_STAGES.map((f) => {
            const s = stageById.get(f.id);
            return <Cell key={f.id} label={f.label} value={s?.[f.field] ?? "—"} />;
          })}
          <Cell label="Risk Rejected" value={replayMissing ? "—" : riskRejected} tone={riskRejected > 0 ? "text-red-400" : ""} />
        </div>
      )}

      {/* Signal counts from the decision stage */}
      <p className="text-[10px] text-muted-foreground mb-1">Signals</p>
      <div className="grid grid-cols-3 gap-2 mb-3" data-testid="mc-throughput-signals">
        <Cell label="BUY" value={replayMissing ? "—" : signals.BUY} tone="text-emerald-400" />
        <Cell label="SELL" value={replayMissing ? "—" : signals.SELL} tone="text-red-400" />
        <Cell label="WATCH" value={replayMissing ? "—" : signals.WATCH} tone="text-amber-400" />
      </div>

      {/* Orders / positions / trades from today's ledger */}
      <p className="text-[10px] text-muted-foreground mb-1">Orders &amp; trades</p>
      <div className="grid grid-cols-4 gap-x-2 gap-y-2" data-testid="mc-throughput-orders">
        <Cell label="Submitted" value={orderCounts.submitted} />
        <Cell label="Filled" value={orderCounts.filled} tone="text-emerald-400" />
        <Cell label="Cancelled" value={orderCounts.cancelled} tone={orderCounts.cancelled > 0 ? "text-red-400" : ""} />
        <Cell label="Open Pos" value={orderCounts.open} />
        <Cell label="Closed Pos" value={orderCounts.closed} />
        <Cell label="Trades Done" value={orderCounts.completed} />
      </div>
    </Widget>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// PART 3 — LivePerformanceWidget
// ═════════════════════════════════════════════════════════════════════════════

interface SectorExposureLite { sector: string; exposure_pct?: number }
interface PortfolioProp {
  equity?: number; cash?: number; invested_value?: number; initial_capital?: number;
  unrealised_pnl?: number; realised_pnl_today?: number; total_pnl?: number;
  open_position_count?: number;
  sector_exposures?: SectorExposureLite[];
}

function pct(n: number): string { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`; }

export function LivePerformanceWidget({
  portfolio, ledger,
}: {
  portfolio?: PortfolioProp;
  /** Shared ledger query result from useLedgerToday(). */
  ledger: ReturnType<typeof useLedgerToday>;
}) {
  const todayIst = istPartsOf(new Date()).date;
  const p = portfolio;

  // Canonical PnL fields — read straight from the snapshot (never recomputed).
  const realized = p?.realised_pnl_today ?? null;
  const unrealized = p?.unrealised_pnl ?? null;
  const net = p != null ? (realized ?? 0) + (unrealized ?? 0) : null;
  const equity = p?.equity ?? 0;
  const invested = p?.invested_value ?? 0;
  const initial = p?.initial_capital ?? 0;
  const todayReturnPct = initial > 0 && net != null ? (net / initial) * 100 : null;
  const exposurePct = equity > 0 ? (invested / equity) * 100 : null;
  const utilisationPct = equity > 0 ? (invested / equity) * 100 : null;

  // Today's CLOSED trades — presentation aggregation over canonical ledger rows.
  const closedToday = useMemo(() => {
    const rows = ledger.data?.ledger ?? [];
    return rows.filter((r) => {
      if ((r.status || "").toUpperCase() !== "CLOSED") return false;
      if (typeof r.realized_pnl !== "number") return false;
      const d = istDateOf(r.exit_ts) ?? istDateOf(r.fill_ts) ?? istDateOf(r.created_at);
      return d === todayIst;
    });
  }, [ledger.data, todayIst]);

  const perf = useMemo(() => {
    const wins = closedToday.filter((r) => (r.realized_pnl ?? 0) > 0);
    const losses = closedToday.filter((r) => (r.realized_pnl ?? 0) < 0);
    const winRate = closedToday.length > 0 ? (wins.length / closedToday.length) * 100 : null;
    const avg = (arr: LedgerRow[]) =>
      arr.length ? arr.reduce((s, r) => s + (r.realized_pnl ?? 0), 0) / arr.length : null;
    const largest = (arr: LedgerRow[], dir: 1 | -1) =>
      arr.length ? arr.reduce((best, r) => {
        const v = r.realized_pnl ?? 0;
        return dir === 1 ? (v > (best.realized_pnl ?? 0) ? r : best)
                         : (v < (best.realized_pnl ?? 0) ? r : best);
      }) : null;

    // Best strategy / sector today by summed PnL of today's closed trades (min 1 trade).
    const groupBest = (key: (r: LedgerRow) => string | null | undefined) => {
      const agg = new Map<string, { pnl: number; trades: number }>();
      for (const r of closedToday) {
        const k = (key(r) ?? "").trim();
        if (!k) continue;
        const cur = agg.get(k) ?? { pnl: 0, trades: 0 };
        cur.pnl += r.realized_pnl ?? 0;
        cur.trades += 1;
        agg.set(k, cur);
      }
      let best: { name: string; pnl: number; trades: number } | null = null;
      for (const [name, v] of agg) {
        if (v.trades < 1) continue;
        if (!best || v.pnl > best.pnl) best = { name, pnl: v.pnl, trades: v.trades };
      }
      return best;
    };

    return {
      winRate,
      avgWinner: avg(wins),
      avgLoser: avg(losses),
      largestWinner: largest(wins, 1),
      largestLoser: largest(losses, -1),
      bestStrategy: groupBest((r) => r.strategy_name ?? r.strategy_id),
      bestSector: groupBest((r) => r.sector),
      count: closedToday.length,
    };
  }, [closedToday]);

  const hasPortfolio = p != null;

  return (
    <Widget
      title="Live Performance (Today)" icon={TrendingUp} query={ledger} refreshMs={30_000}
      testId="mc-live-performance" skeletonClass="h-56"
      headerExtra={<span className="text-[9px] text-muted-foreground">{perf.count} closed today · portfolio snapshot</span>}
    >
      {/* Headline PnL row */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        <div>
          <p className="text-muted-foreground text-[10px]">Today's Return</p>
          <p className={`font-semibold text-sm ${todayReturnPct == null ? "text-muted-foreground" : todayReturnPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            {todayReturnPct == null ? "—" : pct(todayReturnPct)}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Net PnL</p>
          <PnlText value={net} className="font-semibold text-sm" />
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Realized</p>
          <PnlText value={realized} className="font-semibold text-sm" />
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Unrealized</p>
          <PnlText value={unrealized} className="font-semibold text-sm" />
        </div>
      </div>

      {/* Win/loss stats from today's closed trades */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        <div>
          <p className="text-muted-foreground text-[10px]">Win Rate</p>
          <p className="font-semibold">{perf.winRate == null ? "—" : `${perf.winRate.toFixed(0)}%`}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Avg Winner</p>
          <PnlText value={perf.avgWinner} className="font-semibold" />
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Avg Loser</p>
          <PnlText value={perf.avgLoser} className="font-semibold" />
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Exposure</p>
          <p className="font-semibold">{exposurePct == null || !hasPortfolio ? "—" : `${exposurePct.toFixed(1)}%`}</p>
        </div>
      </div>

      {/* Largest winner/loser + utilization */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div>
          <p className="text-muted-foreground text-[10px]">Largest Winner</p>
          {perf.largestWinner ? (
            <p className="font-semibold text-[11px]">
              <span className="font-mono">{perf.largestWinner.symbol}</span> <PnlText value={perf.largestWinner.realized_pnl} />
            </p>
          ) : <p className="text-muted-foreground">—</p>}
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Largest Loser</p>
          {perf.largestLoser ? (
            <p className="font-semibold text-[11px]">
              <span className="font-mono">{perf.largestLoser.symbol}</span> <PnlText value={perf.largestLoser.realized_pnl} />
            </p>
          ) : <p className="text-muted-foreground">—</p>}
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Capital Util.</p>
          <p className="font-semibold">{utilisationPct == null || !hasPortfolio ? "—" : `${utilisationPct.toFixed(1)}%`}</p>
        </div>
      </div>

      {/* Best strategy / sector today */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg bg-muted/20 border border-border/60 p-2">
          <p className="text-muted-foreground text-[9px]">Best Strategy Today</p>
          {perf.bestStrategy ? (
            <p className="font-semibold text-[11px] truncate">
              {perf.bestStrategy.name} · <PnlText value={perf.bestStrategy.pnl} /> <span className="text-muted-foreground">({perf.bestStrategy.trades}t)</span>
            </p>
          ) : <p className="text-muted-foreground text-[11px]">—</p>}
        </div>
        <div className="rounded-lg bg-muted/20 border border-border/60 p-2">
          <p className="text-muted-foreground text-[9px]">Best Sector Today</p>
          {perf.bestSector ? (
            <p className="font-semibold text-[11px] truncate">
              {perf.bestSector.name} · <PnlText value={perf.bestSector.pnl} /> <span className="text-muted-foreground">({perf.bestSector.trades}t)</span>
            </p>
          ) : <p className="text-muted-foreground text-[11px]">—</p>}
        </div>
      </div>

      {!hasPortfolio && (
        <p className="text-[10px] text-amber-400/80 mt-2">Portfolio snapshot unavailable — exposure &amp; utilization hidden.</p>
      )}
    </Widget>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// PART 4 — MarketBreadthWidget
// ═════════════════════════════════════════════════════════════════════════════

interface MoStock { symbol: string; price?: number; change_pct?: number; signal?: string; confidence?: number }
interface MarketOverviewResp {
  nifty_price?: number; nifty_change_pct?: number; nifty_trend?: string;
  banknifty_price?: number; banknifty_change_pct?: number; banknifty_trend?: string;
  regime?: string; regime_description?: string;
  vix_value?: number; vix_status?: string;
  market_score?: number;
  top_strong?: MoStock[]; top_weak?: MoStock[];
  scanned_at?: string;
  error?: string;
}
interface BreadthResp {
  status?: string;
  advancers?: number; decliners?: number; neutral?: number; total?: number;
  advance_decline_ratio?: number;
  breadth_strength?: number; breadth_momentum?: string; breadth_label?: string;
  sector_participation?: { sector: string; advancing: number; total: number; participation_rate: number; participating: boolean }[];
  participating_sectors?: number; total_sectors_scanned?: number;
  regime?: string;
  error?: string;
}

/** "no canonical source" placeholder — intentional, never computed from raw quotes. */
function NoSource() {
  return (
    <span className="text-muted-foreground cursor-help" title="no canonical source">—</span>
  );
}

function TrendPill({ trend }: { trend?: string }) {
  const t = (trend ?? "").toUpperCase();
  if (!t) return <NoSource />;
  const up = t === "UP" || t.includes("BULL");
  const down = t === "DOWN" || t.includes("BEAR");
  return (
    <span className={`font-semibold ${up ? "text-emerald-400" : down ? "text-red-400" : "text-amber-400"}`}>
      {up ? "▲ " : down ? "▼ " : "▬ "}{t}
    </span>
  );
}

export function MarketBreadthWidget() {
  // Richest single endpoint for regime / VIX / indices / gainers-losers.
  // MI endpoints spawn a fresh Python process per request (no server cache) →
  // long cold-start; use generous timeouts and a 60 s cadence per spec.
  const overviewQ = useWidgetQuery<MarketOverviewResp>({
    queryKey: ["mc", "market-overview"], path: "/market-overview",
    refetchInterval: 60_000, timeoutMs: 90_000,
  });
  // Advance/decline + volume/breadth participation + sector participation.
  const breadthQ = useWidgetQuery<BreadthResp>({
    queryKey: ["mc", "mi-breadth"], path: "/market-intelligence/breadth",
    refetchInterval: 60_000, timeoutMs: 60_000,
  });

  const o = overviewQ.data;
  const b = breadthQ.data;
  const biEnabled = b?.status === "ENABLED" || (b?.total ?? 0) > 0;

  const gainers = (o?.top_strong ?? []).slice(0, 4);
  const losers = (o?.top_weak ?? []).slice(0, 4);

  // Sector leaders/laggards from breadth participation (advisory, canonical).
  const sortedPart = useMemo(
    () => [...(b?.sector_participation ?? [])].sort((x, y) => y.participation_rate - x.participation_rate),
    [b],
  );
  const leaders = sortedPart.slice(0, 3);
  const laggards = [...sortedPart].reverse().slice(0, 3);

  const StockList = ({ rows, tone }: { rows: MoStock[]; tone: string }) =>
    rows.length === 0 ? <p className="text-[10px] text-muted-foreground">—</p> : (
      <div className="space-y-0.5">
        {rows.map((s) => (
          <div key={s.symbol} className="flex items-center justify-between text-[10px]">
            <span className="font-mono truncate">{s.symbol}</span>
            <span className={tone}>
              {s.change_pct != null ? `${s.change_pct >= 0 ? "+" : ""}${s.change_pct.toFixed(2)}%` : (s.signal ?? "—")}
            </span>
          </div>
        ))}
      </div>
    );

  const adv = b?.advancers ?? null;
  const dec = b?.decliners ?? null;

  return (
    <Widget
      title="Market Breadth" icon={Waves} query={overviewQ} refreshMs={60_000}
      testId="mc-market-breadth" skeletonClass="h-56"
      headerExtra={
        <span className="text-[9px] text-muted-foreground flex items-center gap-1">
          <Info className="w-2.5 h-2.5" /> advisory
        </span>
      }
    >
      {/* Regime / indices row */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        <div>
          <p className="text-muted-foreground text-[10px]">Regime</p>
          <p className="font-semibold text-[11px]">{o?.regime ?? <NoSource />}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">India VIX</p>
          <p className="font-semibold">
            {o?.vix_value != null ? o.vix_value.toFixed(2) : <NoSource />}
            {o?.vix_status && <span className="text-[9px] text-muted-foreground ml-1">{o.vix_status}</span>}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Nifty Trend</p>
          <p className="text-[11px]"><TrendPill trend={o?.nifty_trend} /></p>
          {o?.nifty_change_pct != null && (
            <p className={`text-[9px] ${o.nifty_change_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {o.nifty_change_pct >= 0 ? "+" : ""}{o.nifty_change_pct.toFixed(2)}%
            </p>
          )}
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Bank Nifty Trend</p>
          <p className="text-[11px]"><TrendPill trend={o?.banknifty_trend} /></p>
          {o?.banknifty_change_pct != null && (
            <p className={`text-[9px] ${o.banknifty_change_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {o.banknifty_change_pct >= 0 ? "+" : ""}{o.banknifty_change_pct.toFixed(2)}%
            </p>
          )}
        </div>
      </div>

      {/* Advance/decline + volume breadth from MI breadth */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        <div>
          <p className="text-muted-foreground text-[10px]">Advance / Decline</p>
          <p className="font-semibold text-[11px]">
            {adv != null && dec != null
              ? <><span className="text-emerald-400">{adv}</span> / <span className="text-red-400">{dec}</span></>
              : <NoSource />}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">A/D Ratio</p>
          <p className="font-semibold">{b?.advance_decline_ratio != null && biEnabled ? b.advance_decline_ratio.toFixed(2) : <NoSource />}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Volume Breadth</p>
          <p className="font-semibold">
            {b?.breadth_strength != null && biEnabled ? `${b.breadth_strength.toFixed(0)}%` : <NoSource />}
            {b?.breadth_label && biEnabled && <span className="text-[9px] text-muted-foreground ml-1">{b.breadth_label}</span>}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-[10px]">Gap %</p>
          {/* No canonical gap% source across a market-wide feed. */}
          <p className="font-semibold"><NoSource /></p>
        </div>
      </div>

      {/* Sector leaders / laggards */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <p className="text-muted-foreground text-[10px] mb-1">Sector Leaders</p>
          {leaders.length === 0 ? <p className="text-[10px] text-muted-foreground">—</p> : (
            <div className="space-y-0.5">
              {leaders.map((s) => (
                <div key={s.sector} className="flex justify-between text-[10px]">
                  <span className="truncate">{s.sector}</span>
                  <span className="text-emerald-400">{(s.participation_rate * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <p className="text-muted-foreground text-[10px] mb-1">Sector Laggards</p>
          {laggards.length === 0 ? <p className="text-[10px] text-muted-foreground">—</p> : (
            <div className="space-y-0.5">
              {laggards.map((s) => (
                <div key={s.sector} className="flex justify-between text-[10px]">
                  <span className="truncate">{s.sector}</span>
                  <span className="text-red-400">{(s.participation_rate * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Top gainers / losers (by AI signal strength, canonical /market-overview) */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-muted-foreground text-[10px] mb-1">Top Gainers</p>
          <StockList rows={gainers} tone="text-emerald-400" />
        </div>
        <div>
          <p className="text-muted-foreground text-[10px] mb-1">Top Losers</p>
          <StockList rows={losers} tone="text-red-400" />
        </div>
      </div>

      {breadthQ.isError && (
        <p className="text-[10px] text-amber-400/80 mt-2">Breadth detail unavailable ({(breadthQ.error as Error)?.message}); regime &amp; indices still shown.</p>
      )}
    </Widget>
  );
}
