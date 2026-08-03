/**
 * Phase11ReplayPage — Paper Trading Session Replay
 * Replay an entire trading session for any historical date.
 * Shows AI decisions, trades, portfolio state at each step, P/L progression.
 * PAPER ONLY — no real money, no live orders.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  PlayCircle, ChevronLeft, ChevronRight, SkipForward,
  SkipBack, BarChart2, Clock, TrendingUp, TrendingDown, RefreshCw,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface TradeSnapshot {
  ts: string; action: string; symbol: string;
  quantity: number; price: number; pnl: number;
  cash: number; invested: number; portfolio_value: number;
  open_positions: number; cumulative_pnl: number;
}

interface ReplayData {
  date: string;
  events: { ts: string; type: string; label: string; category: string }[];
  trade_snapshots: TradeSnapshot[];
  final_pnl: number;
  trade_count: number;
  ai_decisions: { symbol: string; decision: string; confidence: number; ts: string }[];
  advisory_only: boolean;
  paper_only: boolean;
}

function fmt(n: number, d = 0) {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}
function pnlClass(v: number) { return v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400"; }
function istTime(ts: string) {
  try { return new Date(ts).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" }); }
  catch { return ts?.slice(11, 16) ?? ""; }
}

function ActionBadge({ action }: { action: string }) {
  const cls = action === "BUY" || action === "ADD"
    ? "bg-emerald-900/50 text-emerald-300 border-emerald-700/50"
    : action === "SELL" || action === "EXIT" || action === "CLOSE"
    ? "bg-rose-900/50 text-rose-300 border-rose-700/50"
    : "bg-amber-900/50 text-amber-300 border-amber-700/50";
  return <Badge className={`text-xs ${cls}`}>{action}</Badge>;
}

export default function Phase11ReplayPage() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate]   = useState(today);
  const [step, setStep]   = useState(0);
  const [playing, setPlaying] = useState(false);

  const q = useQuery({
    queryKey: ["phase11", "replay", date],
    queryFn:  () => apiJson<ReplayData>(`/phase11/replay?date=${date}`),
    staleTime: 300_000,
    enabled:  !!date,
  });

  const data = q.data;
  const snapshots = data?.trade_snapshots ?? [];
  const cur = snapshots[step] ?? null;

  // Chart data up to current step
  const chartData = snapshots.slice(0, step + 1).map((s) => ({
    time:  istTime(s.ts),
    value: s.portfolio_value,
    pnl:   s.cumulative_pnl,
  }));

  const handlePlay = () => {
    if (step >= snapshots.length - 1) { setStep(0); return; }
    setPlaying(true);
    const interval = setInterval(() => {
      setStep(prev => {
        if (prev >= snapshots.length - 1) { clearInterval(interval); setPlaying(false); return prev; }
        return prev + 1;
      });
    }, 800);
    return () => { clearInterval(interval); setPlaying(false); };
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3">
          <PlayCircle className="w-6 h-6 text-teal-400 shrink-0" />
          <div>
            <h1 className="text-2xl font-bold">Session Replay</h1>
            <p className="text-slate-500 text-sm">Replay any paper trading session step-by-step</p>
          </div>
          <Badge className="ml-auto bg-teal-900/50 text-teal-300 border-teal-700/50">PAPER ONLY</Badge>
        </div>

        {/* Date picker + controls */}
        <div className="bg-slate-900/60 rounded-xl border border-slate-800/40 p-4 flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-500" />
            <label className="text-sm text-slate-400">Date:</label>
            <input
              type="date"
              value={date}
              max={today}
              onChange={e => { setDate(e.target.value); setStep(0); setPlaying(false); }}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 text-sm"
            />
          </div>
          {q.isFetching && <RefreshCw className="w-4 h-4 text-slate-500 animate-spin" />}
          {data && snapshots.length > 0 && (
            <div className="flex items-center gap-2 ml-auto">
              <Button variant="ghost" size="sm" onClick={() => setStep(0)} disabled={step === 0}
                className="text-slate-400 hover:text-slate-200">
                <SkipBack className="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setStep(s => Math.max(0, s - 1))} disabled={step === 0}
                className="text-slate-400 hover:text-slate-200">
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <Button variant="outline" size="sm" onClick={handlePlay} disabled={playing}
                className="border-teal-700/50 text-teal-300 hover:bg-teal-900/30">
                <PlayCircle className="w-4 h-4 mr-1" /> {playing ? "Playing…" : "Play"}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setStep(s => Math.min(snapshots.length - 1, s + 1))}
                disabled={step >= snapshots.length - 1} className="text-slate-400 hover:text-slate-200">
                <ChevronRight className="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setStep(snapshots.length - 1)}
                disabled={step >= snapshots.length - 1} className="text-slate-400 hover:text-slate-200">
                <SkipForward className="w-4 h-4" />
              </Button>
              <span className="text-xs text-slate-500 ml-2">
                {step + 1} / {snapshots.length}
              </span>
            </div>
          )}
        </div>

        {q.isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[1,2,3].map(i => <Skeleton key={i} className="h-40 rounded-xl" />)}
            <Skeleton className="col-span-3 h-52 rounded-xl" />
          </div>
        ) : !data || snapshots.length === 0 ? (
          <div className="text-center py-16 text-slate-500">
            <PlayCircle className="w-12 h-12 mx-auto mb-3 opacity-20" />
            <p className="text-lg font-semibold">No trades on {date}</p>
            <p className="text-sm mt-1">Select a date when paper trades were executed.</p>
          </div>
        ) : (
          <>
            {/* Current step KPIs */}
            {cur && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: "Action", value: <ActionBadge action={cur.action} /> },
                  { label: "Symbol", value: <span className="font-bold text-slate-100">{cur.symbol || "—"}</span> },
                  { label: "Price", value: <span className="font-mono font-bold text-slate-100">₹{fmt(cur.price)}</span> },
                  { label: "Qty", value: <span className="font-bold text-slate-200">{cur.quantity || "—"}</span> },
                  { label: "Portfolio Value", value: <span className="font-mono font-bold text-teal-300">₹{fmt(cur.portfolio_value)}</span> },
                  { label: "Cash", value: <span className="font-mono text-slate-200">₹{fmt(cur.cash)}</span> },
                  { label: "Open Positions", value: <span className="text-slate-200">{cur.open_positions}</span> },
                  { label: "Cumulative P/L", value: <span className={`font-mono font-bold ${pnlClass(cur.cumulative_pnl)}`}>{cur.cumulative_pnl >= 0 ? "+" : ""}₹{fmt(cur.cumulative_pnl)}</span> },
                ].map((m, i) => (
                  <div key={i} className="bg-slate-900/60 rounded-xl border border-slate-800/40 p-3">
                    <p className="text-xs text-slate-500 mb-1">{m.label}</p>
                    <div className="text-base">{m.value}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Step slider */}
            <div className="bg-slate-900/60 rounded-xl border border-slate-800/40 p-4">
              <input
                type="range" min={0} max={snapshots.length - 1} value={step}
                onChange={e => setStep(Number(e.target.value))}
                className="w-full accent-teal-400"
              />
              <div className="flex justify-between text-xs text-slate-500 mt-1">
                <span>{istTime(snapshots[0]?.ts ?? "")}</span>
                <span>{istTime(snapshots[snapshots.length - 1]?.ts ?? "")}</span>
              </div>
            </div>

            {/* Portfolio value chart */}
            {chartData.length >= 2 && (
              <Card className="bg-slate-900/60 border-slate-800/40">
                <CardHeader><CardTitle className="text-sm font-semibold text-slate-400 flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-teal-400" /> Portfolio Value Progression
                </CardTitle></CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={180}>
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                      <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false}
                        tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
                      <Tooltip
                        contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
                        labelStyle={{ color: "#94a3b8" }}
                        formatter={(v: number) => [`₹${fmt(v)}`, "Portfolio Value"]}
                      />
                      <ReferenceLine y={chartData[0]?.value} stroke="#475569" strokeDasharray="4 4" />
                      <Line type="monotone" dataKey="value" stroke="#14b8a6" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}

            {/* Trade log */}
            <Card className="bg-slate-900/60 border-slate-800/40">
              <CardHeader><CardTitle className="text-sm font-semibold text-slate-400 flex items-center gap-2">
                <BarChart2 className="w-4 h-4 text-teal-400" /> Trade Log
              </CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {snapshots.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => setStep(i)}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors text-sm ${
                        i === step ? "bg-teal-950/40 ring-1 ring-teal-700/50" : i < step ? "bg-slate-800/30" : "opacity-40"
                      }`}
                    >
                      <span className="text-slate-500 w-10 shrink-0 font-mono text-xs">{istTime(s.ts)}</span>
                      <ActionBadge action={s.action} />
                      <span className="font-semibold text-slate-200 w-16">{s.symbol}</span>
                      <span className="font-mono text-slate-400 text-xs">₹{fmt(s.price)} × {s.quantity}</span>
                      {s.pnl !== 0 && (
                        <span className={`ml-auto font-mono font-bold text-xs ${pnlClass(s.pnl)}`}>
                          {s.pnl >= 0 ? "+" : ""}₹{fmt(s.pnl)}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Final stats */}
            <div className="bg-slate-900/60 rounded-xl border border-slate-800/40 p-4 flex flex-wrap gap-6">
              <div>
                <p className="text-xs text-slate-500">Session Date</p>
                <p className="font-semibold text-slate-200">{data.date}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Total Trades</p>
                <p className="font-semibold text-slate-200">{data.trade_count}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Session P/L</p>
                <p className={`font-bold font-mono ${pnlClass(data.final_pnl)}`}>
                  {data.final_pnl >= 0 ? "+" : ""}₹{fmt(data.final_pnl)}
                </p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
