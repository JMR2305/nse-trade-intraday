/**
 * InvestigationCenter.tsx — Phase 23 Parts 2/3: Historical Backtest Engine +
 * AI Investigation Center (the AI debugger).
 *
 * Everything renders from the canonical stores:
 *   * /api/backtest/*          — runs, isolated backtest portfolio, trades,
 *                                missed opportunities, validation, candles
 *   * /api/pipeline/events     — BACKTEST-mode events (same store as LIVE)
 *
 * Replay is client-side over the run's candle timeline: play/pause,
 * prev/next candle, 1x/5x/20x speeds and jump-to-time. The decision tree,
 * event timeline and chart marker all follow the replay cursor.
 *
 * BACKTEST — SIMULATED, ISOLATED FROM LIVE. No live ledger data on this page.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AlertTriangle, Ban, CheckCircle2, ChevronLeft, ChevronRight, Clock,
  FlaskConical, History, Pause, Play, ShieldCheck, ShieldX, SkipBack,
  SkipForward, Wallet, XCircle,
} from "lucide-react";

const LABEL = "BACKTEST — SIMULATED, ISOLATED FROM LIVE";

// ── Types ────────────────────────────────────────────────────────────────────

interface BacktestRun {
  run_id: string;
  created_at?: string;
  status: string;
  config?: { interval?: string; start?: string; end?: string; capital?: number; symbols?: string[] | null; universe?: string };
  progress?: { phase?: string; done?: number; total?: number; ts?: string; cash?: number };
  metrics?: Record<string, unknown> | null;
  missed?: MissedOpp[] | null;
  validation?: ValidationResult | null;
  error?: string | null;
}

interface Candle { ts: string; open: number; high: number; low: number; close: number; volume: number }

interface PipelineEvent {
  id: number; ts: string; mode: string; run_id: string | null; scan_id: string | null;
  event_type: string; stage: string; symbol: string | null; payload: Record<string, unknown>;
}

interface BacktestTrade {
  trade_id: string; symbol: string; strategy_name?: string; quantity: number;
  fill_ts?: string; fill_price: number; stop_loss?: number; target?: number;
  status: string; exit_ts?: string | null; exit_price?: number | null;
  exit_rule?: string | null; realized_pnl?: number | null; confidence?: number;
}

interface PortfolioSnap {
  starting_capital: number; cash: number; realized_pnl: number; unrealized_pnl: number;
  portfolio_value: number; net_return_pct: number; win_rate: number; wins: number;
  losses: number; max_drawdown_pct: number; open_positions_count: number;
  closed_positions_count: number; total_trades: number;
  equity_curve: Array<{ ts: string; equity: number }>;
  open_positions: Array<Record<string, unknown>>;
}

interface MissedOpp {
  symbol: string; scan_id: string; decision: string; reason: string;
  base_price: number; potential_return_pct: number; return_at_horizon_pct: number;
  would_have_been_profitable: boolean; horizon_bars: number;
  single_rule_relax_hint?: string | null;
}

interface ValidationResult {
  ok: boolean; checked: number; verdict?: string;
  mismatches: Array<{ symbol: string; time: string; expected_decision: string; actual_decision: string; reason: string }>;
}

interface DecisionTree {
  symbol: string;
  stages: Array<{ stage: string; events: PipelineEvent[] }>;
  trades: BacktestTrade[];
  total_events: number;
}

const STAGE_LABELS: Record<string, string> = {
  SUPERVISOR: "Supervisor", SCANNER: "Scanner", RESEARCH: "Research",
  MARKET_INTELLIGENCE: "Market Intel", MONITORING: "Monitoring",
  STRATEGY: "Strategy", RISK: "Risk", AI_DECISION: "AI Decision",
  EXECUTION: "Execution", PORTFOLIO: "Portfolio",
};

function fmtINR(v: unknown): string {
  const n = typeof v === "number" ? v : null;
  if (n === null || !isFinite(n)) return "—";
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function tsShort(ts?: string | null): string {
  if (!ts) return "—";
  return ts.slice(0, 16).replace("T", " ");
}

function rangePreset(days: number): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - days * 86400_000);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

// ── Candle chart (dependency-light SVG) ──────────────────────────────────────

function CandleChart({ candles, cursor, trades }: {
  candles: Candle[]; cursor: number; trades: BacktestTrade[];
}) {
  const W = 860, H = 260, PAD = 8;
  if (!candles.length) {
    return <div className="text-sm text-muted-foreground py-10 text-center">No candles cached for this selection.</div>;
  }
  const lo = Math.min(...candles.map((c) => c.low));
  const hi = Math.max(...candles.map((c) => c.high));
  const y = (v: number) => PAD + (H - 2 * PAD) * (1 - (v - lo) / Math.max(1e-9, hi - lo));
  const bw = Math.max(1.5, (W - 2 * PAD) / candles.length - 1.5);
  const x = (i: number) => PAD + ((W - 2 * PAD) * i) / candles.length;
  const tsToIdx = new Map(candles.map((c, i) => [c.ts, i]));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" data-testid="chart-candles">
      {candles.map((c, i) => {
        const up = c.close >= c.open;
        const seen = i <= cursor;
        const color = !seen ? "hsl(var(--muted-foreground) / 0.25)" : up ? "#22c55e" : "#ef4444";
        return (
          <g key={c.ts}>
            <line x1={x(i) + bw / 2} x2={x(i) + bw / 2} y1={y(c.high)} y2={y(c.low)} stroke={color} strokeWidth={1} />
            <rect x={x(i)} width={bw} y={y(Math.max(c.open, c.close))}
              height={Math.max(1, Math.abs(y(c.open) - y(c.close)))} fill={color} />
          </g>
        );
      })}
      {trades.map((t) => {
        const ei = t.fill_ts ? tsToIdx.get(t.fill_ts) : undefined;
        const xi = t.exit_ts ? tsToIdx.get(t.exit_ts) : undefined;
        return (
          <g key={t.trade_id}>
            {ei !== undefined && ei <= cursor && (
              <polygon points={`${x(ei) + bw / 2},${y(t.fill_price) - 10} ${x(ei) - 2},${y(t.fill_price)} ${x(ei) + bw + 2},${y(t.fill_price)}`}
                fill="#3b82f6" data-testid={`marker-entry-${t.trade_id}`} />
            )}
            {xi !== undefined && xi <= cursor && typeof t.exit_price === "number" && (
              <polygon points={`${x(xi) + bw / 2},${y(t.exit_price) + 10} ${x(xi) - 2},${y(t.exit_price)} ${x(xi) + bw + 2},${y(t.exit_price)}`}
                fill={(t.realized_pnl ?? 0) >= 0 ? "#22c55e" : "#ef4444"} />
            )}
          </g>
        );
      })}
      {cursor >= 0 && cursor < candles.length && (
        <line x1={x(cursor) + bw / 2} x2={x(cursor) + bw / 2} y1={PAD} y2={H - PAD}
          stroke="hsl(var(--primary))" strokeDasharray="4 3" strokeWidth={1.2} />
      )}
    </svg>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function InvestigationCenter() {
  const qc = useQueryClient();

  // run launcher form
  const [interval, setIntervalStr] = useState("1d");
  const [preset, setPreset] = useState<"1w" | "1m" | "3m" | "custom">("1m");
  const [start, setStart] = useState(rangePreset(30).start);
  const [end, setEnd] = useState(rangePreset(30).end);
  const [symbolsText, setSymbolsText] = useState("");
  const [universe, setUniverse] = useState("configured");
  const [capital, setCapital] = useState(100000);

  useEffect(() => {
    if (preset === "custom") return;
    const days = preset === "1w" ? 7 : preset === "1m" ? 30 : 90;
    const r = rangePreset(days);
    setStart(r.start); setEnd(r.end);
  }, [preset]);

  const runsQ = useQuery({
    queryKey: ["bt-runs"],
    queryFn: () => apiJson<{ runs: BacktestRun[] }>("/backtest/runs", undefined, 60_000),
    refetchInterval: 5_000,
  });
  const runs = runsQ.data?.runs ?? [];
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const runId = selectedRunId ?? runs[0]?.run_id ?? null;
  const run = runs.find((r) => r.run_id === runId) ?? null;
  const running = run?.status === "RUNNING" || run?.status === "PENDING";

  const launch = useMutation({
    mutationFn: () => apiJson<{ ok: boolean; run_id?: string; error?: string }>("/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        interval, start, end, capital,
        symbols: symbolsText.trim() ? symbolsText.split(/[\s,]+/).filter(Boolean) : undefined,
        universe,
      }),
    }, 30_000),
    onSuccess: (d) => {
      if (d.run_id) setSelectedRunId(d.run_id);
      void qc.invalidateQueries({ queryKey: ["bt-runs"] });
    },
  });

  const eventsQ = useQuery({
    queryKey: ["bt-events", runId],
    queryFn: () => apiJson<{ events: PipelineEvent[] }>(`/pipeline/events?mode=BACKTEST&run_id=${runId}&limit=3000`, undefined, 60_000),
    enabled: !!runId,
    refetchInterval: running ? 5_000 : false,
  });
  const events = eventsQ.data?.events ?? [];

  const tradesQ = useQuery({
    queryKey: ["bt-trades", runId],
    queryFn: () => apiJson<{ trades: BacktestTrade[] }>(`/backtest/run/${runId}/trades`, undefined, 60_000),
    enabled: !!runId,
    refetchInterval: running ? 5_000 : false,
  });
  const trades = tradesQ.data?.trades ?? [];

  const portfolioQ = useQuery({
    queryKey: ["bt-portfolio", runId],
    queryFn: () => apiJson<PortfolioSnap>(`/backtest/run/${runId}/portfolio`, undefined, 60_000),
    enabled: !!runId,
    refetchInterval: running ? 5_000 : false,
  });
  const pf = portfolioQ.data;

  // replay symbol + candles
  const symbols = useMemo(() => {
    const s = new Set<string>();
    for (const t of trades) s.add(t.symbol);
    for (const e of events) if (e.symbol) s.add(e.symbol);
    return Array.from(s).sort();
  }, [trades, events]);
  const [symbol, setSymbol] = useState<string | null>(null);
  const sym = symbol && symbols.includes(symbol) ? symbol : symbols[0] ?? null;

  const candlesQ = useQuery({
    queryKey: ["bt-candles", runId, sym],
    queryFn: () => apiJson<{ candles: Candle[] }>(`/backtest/candles?symbol=${sym}&interval=${run?.config?.interval ?? "1d"}&start=${run?.config?.start}&end=${run?.config?.end}`, undefined, 60_000),
    enabled: !!runId && !!sym && !!run?.config?.start,
  });
  const candles = candlesQ.data?.candles ?? [];

  // ── Replay engine (Part H) ────────────────────────────────────────────────
  const [cursor, setCursor] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const timerRef = useRef<ReturnType<typeof window.setInterval> | null>(null);
  useEffect(() => { setCursor(candles.length ? candles.length - 1 : -1); setPlaying(false); }, [runId, sym, candles.length]);
  useEffect(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (playing && candles.length) {
      timerRef.current = setInterval(() => {
        setCursor((c) => {
          if (c >= candles.length - 1) { setPlaying(false); return c; }
          return c + 1;
        });
      }, 900 / speed);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [playing, speed, candles.length]);

  const cursorTs = cursor >= 0 && cursor < candles.length ? candles[cursor].ts : null;
  const visibleEvents = useMemo(() => {
    const tickOf = (e: PipelineEvent): number | null => {
      const m = /-T(\d+)$/.exec(e.scan_id ?? "");
      return m ? Number(m[1]) : null;
    };
    const list = events.filter((e) => !sym || !e.symbol || e.symbol === sym);
    if (!cursorTs || cursor >= candles.length - 1) return list.slice().reverse().slice(0, 80);
    // The symbol is only scanned on ticks where it has a candle, so the
    // ordered distinct ticks of ITS events map 1:1 onto its candles —
    // correct even when symbols have gaps in the union timeline.
    const symTicks = Array.from(new Set(
      events.filter((e) => e.symbol === sym).map(tickOf).filter((t): t is number => t !== null),
    )).sort((a, b) => a - b);
    const cursorTick = symTicks.length
      ? symTicks[Math.min(cursor, symTicks.length - 1)]
      : Number.MAX_SAFE_INTEGER;
    return list.filter((e) => {
      const t = tickOf(e);
      return t === null || t <= cursorTick;
    }).slice().reverse().slice(0, 80);
  }, [events, sym, cursorTs, cursor, candles.length]);

  const treeQ = useQuery({
    queryKey: ["bt-tree", runId, sym],
    queryFn: () => apiJson<DecisionTree>(`/backtest/run/${runId}/decision/${sym}`, undefined, 60_000),
    enabled: !!runId && !!sym,
    refetchInterval: running ? 8_000 : false,
  });
  const tree = treeQ.data;

  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const validate = useMutation({
    mutationFn: () => apiJson<ValidationResult>(`/backtest/run/${runId}/validate?sample=25`, undefined, 240_000),
    onSuccess: setValidation,
  });
  const storedValidation = validation ?? run?.validation ?? null;

  const missed: MissedOpp[] = (run?.missed as MissedOpp[]) ?? [];
  const rejections = useMemo(
    () => events.filter((e) => e.event_type.includes("REJECTED")).slice().reverse(),
    [events]);

  const m = run?.metrics as Record<string, number> | undefined;

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="page-investigation-center">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <FlaskConical className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-xl font-semibold">AI Investigation Center</h1>
          <p className="text-xs text-muted-foreground">
            Historical backtests run through the EXACT production pipeline — candle-by-candle, no hidden logic.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Badge variant="outline" className="border-amber-500 text-amber-500">{LABEL}</Badge>
        </div>
      </div>

      {/* Run launcher */}
      <Card data-testid="card-launcher">
        <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><History className="h-4 w-4" />New Backtest</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Interval</span>
            <select className="bg-background border rounded px-2 py-1.5" value={interval}
              onChange={(e) => setIntervalStr(e.target.value)} data-testid="select-interval">
              <option value="1d">Daily</option>
              <option value="15m">15 minute</option>
              <option value="10m">10 minute</option>
              <option value="5m">5 minute</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Range</span>
            <select className="bg-background border rounded px-2 py-1.5" value={preset}
              onChange={(e) => setPreset(e.target.value as typeof preset)} data-testid="select-range">
              <option value="1w">One week</option>
              <option value="1m">One month</option>
              <option value="3m">Three months</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Start</span>
            <input type="date" className="bg-background border rounded px-2 py-1" value={start}
              onChange={(e) => { setPreset("custom"); setStart(e.target.value); }} data-testid="input-start" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">End</span>
            <input type="date" className="bg-background border rounded px-2 py-1" value={end}
              onChange={(e) => { setPreset("custom"); setEnd(e.target.value); }} data-testid="input-end" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Universe</span>
            <select className="bg-background border rounded px-2 py-1.5" value={universe}
              onChange={(e) => setUniverse(e.target.value)} data-testid="select-universe">
              <option value="configured">Configured universe</option>
              <option value="nifty50">Nifty 50</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 min-w-48">
            <span className="text-xs text-muted-foreground">Symbols (optional, overrides universe)</span>
            <input className="bg-background border rounded px-2 py-1.5" placeholder="e.g. RELIANCE, TCS"
              value={symbolsText} onChange={(e) => setSymbolsText(e.target.value)} data-testid="input-symbols" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Capital (₹)</span>
            <input type="number" className="bg-background border rounded px-2 py-1.5 w-28" value={capital}
              onChange={(e) => setCapital(Number(e.target.value) || 100000)} data-testid="input-capital" />
          </label>
          <Button onClick={() => launch.mutate()} disabled={launch.isPending} data-testid="button-run-backtest">
            {launch.isPending ? "Launching…" : "Run Backtest"}
          </Button>
          {launch.data && !launch.data.ok && (
            <span className="text-xs text-red-500">{String(launch.data.error)}</span>
          )}
        </CardContent>
      </Card>

      {/* Runs + status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card data-testid="card-runs">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Backtest Runs</CardTitle></CardHeader>
          <CardContent className="space-y-1 max-h-64 overflow-auto">
            {runs.length === 0 && <div className="text-xs text-muted-foreground">No backtest runs yet. Launch one above.</div>}
            {runs.map((r) => (
              <button key={r.run_id} onClick={() => setSelectedRunId(r.run_id)}
                className={`w-full text-left text-xs rounded px-2 py-1.5 border ${r.run_id === runId ? "border-primary bg-primary/10" : "border-transparent hover:bg-muted"}`}
                data-testid={`row-run-${r.run_id}`}>
                <div className="flex items-center gap-2">
                  <span className="font-mono">{r.run_id}</span>
                  <Badge variant="outline" className={
                    r.status === "COMPLETED" ? "border-green-500 text-green-500"
                      : r.status === "FAILED" ? "border-red-500 text-red-500"
                        : "border-blue-400 text-blue-400"}>{r.status}</Badge>
                </div>
                <div className="text-muted-foreground mt-0.5">
                  {r.config?.interval} · {r.config?.start} → {r.config?.end}
                  {r.progress?.total ? ` · ${r.progress.done}/${r.progress.total} ${r.progress.phase ?? ""}` : ""}
                </div>
                {r.error && <div className="text-red-500 mt-0.5">{r.error}</div>}
              </button>
            ))}
          </CardContent>
        </Card>

        {/* Performance summary */}
        <Card data-testid="card-performance">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Performance Summary</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-2 text-sm">
            {!m && <div className="text-xs text-muted-foreground col-span-2">Completes when the run finishes.</div>}
            {m && (<>
              <div>Net return <div className={`font-semibold ${(m.net_return_pct ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`} data-testid="text-net-return">{m.net_return_pct}%</div></div>
              <div>Win rate <div className="font-semibold">{m.win_rate}% ({m.wins}W/{m.losses}L)</div></div>
              <div>Realized P&L <div className="font-semibold">{fmtINR(m.realized_pnl)}</div></div>
              <div>Max drawdown <div className="font-semibold text-amber-500">{m.max_drawdown_pct}%</div></div>
              <div>Trades <div className="font-semibold">{m.total_trades}</div></div>
              <div>Ticks × symbols <div className="font-semibold">{m.ticks} × {m.symbols}</div></div>
            </>)}
          </CardContent>
        </Card>

        {/* Backtest portfolio */}
        <Card data-testid="card-bt-portfolio">
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Wallet className="h-4 w-4" />Backtest Portfolio</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            {!pf && <div className="text-xs text-muted-foreground">Select a run.</div>}
            {pf && (<>
              <div className="flex justify-between"><span>Starting capital</span><span>{fmtINR(pf.starting_capital)}</span></div>
              <div className="flex justify-between"><span>Cash</span><span data-testid="text-bt-cash">{fmtINR(pf.cash)}</span></div>
              <div className="flex justify-between"><span>Portfolio value</span><span className="font-semibold">{fmtINR(pf.portfolio_value)}</span></div>
              <div className="flex justify-between"><span>Realized / Unrealized</span>
                <span>{fmtINR(pf.realized_pnl)} / {fmtINR(pf.unrealized_pnl)}</span></div>
              <div className="flex justify-between"><span>Open / Closed</span>
                <span>{pf.open_positions_count} / {pf.closed_positions_count}</span></div>
            </>)}
          </CardContent>
        </Card>
      </div>

      {/* Chart + replay controls */}
      <Card data-testid="card-replay">
        <CardHeader className="pb-2 flex flex-row flex-wrap items-center gap-3">
          <CardTitle className="text-sm">Historical Chart & Timeline Replay</CardTitle>
          <select className="bg-background border rounded px-2 py-1 text-xs" value={sym ?? ""}
            onChange={(e) => setSymbol(e.target.value)} data-testid="select-symbol">
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <div className="ml-auto flex items-center gap-1">
            <Button size="icon" variant="ghost" onClick={() => setCursor(0)} data-testid="button-jump-start"><SkipBack className="h-4 w-4" /></Button>
            <Button size="icon" variant="ghost" onClick={() => setCursor((c) => Math.max(0, c - 1))} data-testid="button-prev"><ChevronLeft className="h-4 w-4" /></Button>
            <Button size="icon" variant={playing ? "default" : "outline"} onClick={() => setPlaying((p) => !p)} data-testid="button-play">
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
            <Button size="icon" variant="ghost" onClick={() => setCursor((c) => Math.min(candles.length - 1, c + 1))} data-testid="button-next"><ChevronRight className="h-4 w-4" /></Button>
            <Button size="icon" variant="ghost" onClick={() => setCursor(candles.length - 1)} data-testid="button-jump-end"><SkipForward className="h-4 w-4" /></Button>
            {[1, 5, 20].map((s) => (
              <Button key={s} size="sm" variant={speed === s ? "default" : "ghost"} onClick={() => setSpeed(s)} data-testid={`button-speed-${s}`}>{s}x</Button>
            ))}
            <input type="range" min={0} max={Math.max(0, candles.length - 1)} value={Math.max(0, cursor)}
              onChange={(e) => setCursor(Number(e.target.value))} className="w-40" data-testid="slider-jump" />
          </div>
        </CardHeader>
        <CardContent>
          <CandleChart candles={candles} cursor={cursor} trades={trades.filter((t) => t.symbol === sym)} />
          <div className="text-xs text-muted-foreground mt-1 flex items-center gap-2">
            <Clock className="h-3 w-3" />
            {cursorTs ? `Replay position: ${tsShort(cursorTs)} (candle ${cursor + 1}/${candles.length})` : "No replay data"}
          </div>
        </CardContent>
      </Card>

      {/* Decision tree + event timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card data-testid="card-decision-tree">
          <CardHeader className="pb-2"><CardTitle className="text-sm">AI Decision Tree — {sym ?? "—"}</CardTitle></CardHeader>
          <CardContent className="space-y-2 max-h-96 overflow-auto">
            {!tree && <div className="text-xs text-muted-foreground">Select a run and symbol.</div>}
            {tree?.stages.map((s) => (
              <div key={s.stage} className="border rounded p-2">
                <div className="text-xs font-semibold flex items-center gap-2">
                  {STAGE_LABELS[s.stage] ?? s.stage}
                  <span className="text-muted-foreground font-normal">{s.events.length} events</span>
                </div>
                {s.events.slice(-3).map((e) => (
                  <div key={e.id} className="mt-1 text-xs flex items-start gap-1.5">
                    {e.event_type.includes("REJECTED") ? <ShieldX className="h-3.5 w-3.5 text-red-500 mt-0.5" />
                      : e.event_type.includes("APPROVED") || e.event_type === "BUY_GENERATED" ? <ShieldCheck className="h-3.5 w-3.5 text-green-500 mt-0.5" />
                        : <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground mt-0.5" />}
                    <div className="min-w-0">
                      <span className="font-mono">{e.event_type}</span>
                      <span className="text-muted-foreground"> · {e.scan_id}</span>
                      <div className="text-muted-foreground truncate">{JSON.stringify(e.payload).slice(0, 220)}</div>
                    </div>
                  </div>
                ))}
                {s.events.length === 0 && <div className="text-xs text-muted-foreground mt-1">No events at this stage.</div>}
              </div>
            ))}
          </CardContent>
        </Card>

        <Card data-testid="card-event-timeline">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Event Timeline (follows replay cursor)</CardTitle></CardHeader>
          <CardContent className="space-y-1 max-h-96 overflow-auto">
            {visibleEvents.length === 0 && <div className="text-xs text-muted-foreground">No events for this position.</div>}
            {visibleEvents.map((e) => (
              <div key={e.id} className="text-xs flex items-center gap-2 border-b border-border/40 pb-1" data-testid={`event-${e.id}`}>
                {e.event_type.includes("REJECTED") || e.event_type.includes("FAILED") ? <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                  : e.event_type.includes("EXECUTED") || e.event_type.includes("OPENED") || e.event_type.includes("CLOSED") ? <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                    : <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />}
                <span className="font-mono">{e.event_type}</span>
                <span className="text-muted-foreground">{e.symbol ?? ""}</span>
                <span className="text-muted-foreground ml-auto">{e.scan_id}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Trades + missed + rejections + validation */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card data-testid="card-trade-list">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Trade List</CardTitle></CardHeader>
          <CardContent className="max-h-80 overflow-auto">
            {trades.length === 0 && <div className="text-xs text-muted-foreground">No backtest trades in this run.</div>}
            {trades.length > 0 && (
              <table className="w-full text-xs">
                <thead><tr className="text-muted-foreground text-left">
                  <th className="py-1">Symbol</th><th>Strategy</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Rule</th><th className="text-right">P&L</th>
                </tr></thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={t.trade_id} className="border-t border-border/40" data-testid={`row-trade-${t.trade_id}`}>
                      <td className="py-1 font-medium">{t.symbol}</td>
                      <td>{t.strategy_name ?? "—"}</td>
                      <td>{t.quantity}</td>
                      <td>{fmtINR(t.fill_price)}</td>
                      <td>{t.exit_price != null ? fmtINR(t.exit_price) : <Badge variant="outline">OPEN</Badge>}</td>
                      <td>{t.exit_rule ?? "—"}</td>
                      <td className={`text-right font-semibold ${(t.realized_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
                        {t.realized_pnl != null ? fmtINR(t.realized_pnl) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        <Card data-testid="card-missed">
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-500" />Missed Opportunities (advisory only)</CardTitle></CardHeader>
          <CardContent className="space-y-2 max-h-80 overflow-auto">
            {missed.length === 0 && <div className="text-xs text-muted-foreground">None recorded — appears after a completed run.</div>}
            {missed.slice(0, 25).map((mo, i) => (
              <div key={`${mo.symbol}-${mo.scan_id}-${i}`} className="border rounded p-2 text-xs" data-testid={`row-missed-${i}`}>
                <div className="flex items-center gap-2">
                  <span className="font-medium">{mo.symbol}</span>
                  <Badge variant="outline" className={mo.decision === "RISK_REJECTED" ? "border-red-500 text-red-500" : "border-yellow-500 text-yellow-500"}>{mo.decision}</Badge>
                  <span className={`ml-auto font-semibold ${mo.would_have_been_profitable ? "text-green-500" : "text-red-500"}`}>
                    peak +{mo.potential_return_pct}% · horizon {mo.return_at_horizon_pct}%
                  </span>
                </div>
                <div className="text-muted-foreground mt-1">{mo.reason}</div>
                {mo.single_rule_relax_hint && <div className="text-amber-500 mt-0.5">{mo.single_rule_relax_hint}</div>}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card data-testid="card-rejection-analysis">
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Ban className="h-4 w-4 text-red-500" />Rejection Analysis</CardTitle></CardHeader>
          <CardContent className="space-y-1 max-h-72 overflow-auto">
            {rejections.length === 0 && <div className="text-xs text-muted-foreground">No rejections recorded in this run.</div>}
            {rejections.slice(0, 40).map((e) => (
              <div key={e.id} className="text-xs border-b border-border/40 pb-1">
                <span className="font-medium">{e.symbol}</span>{" "}
                <span className="font-mono text-red-500">{e.event_type}</span>
                <div className="text-muted-foreground truncate">{JSON.stringify(e.payload).slice(0, 200)}</div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card data-testid="card-validation">
          <CardHeader className="pb-2 flex flex-row items-center gap-2">
            <CardTitle className="text-sm flex items-center gap-2"><ShieldCheck className="h-4 w-4" />Historical Validation (replay ≡ pipeline)</CardTitle>
            <Button size="sm" variant="outline" className="ml-auto" disabled={!runId || validate.isPending || running}
              onClick={() => validate.mutate()} data-testid="button-validate">
              {validate.isPending ? "Validating…" : "Run Validation"}
            </Button>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            {!storedValidation && <div className="text-xs text-muted-foreground">
              Re-runs the production pipeline on the exact as-of candles the replay used and compares every sampled decision.
            </div>}
            {storedValidation && (<>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className={storedValidation.mismatches?.length ? "border-red-500 text-red-500" : "border-green-500 text-green-500"} data-testid="badge-validation-verdict">
                  {storedValidation.mismatches?.length ? "MISMATCH" : "MATCH"}
                </Badge>
                <span className="text-xs text-muted-foreground">{storedValidation.checked} decisions re-checked</span>
              </div>
              {(storedValidation.mismatches ?? []).map((mm, i) => (
                <div key={i} className="text-xs border rounded p-2 text-red-500">
                  {mm.symbol} @ {tsShort(mm.time)} — expected {mm.expected_decision}, got {mm.actual_decision}: {mm.reason}
                </div>
              ))}
            </>)}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
