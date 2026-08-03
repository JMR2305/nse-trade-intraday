/**
 * Phase11SummaryPage — Autonomous Paper Trading Main Dashboard
 * Calendar view + day-drill-down: portfolio snapshot, trades,
 * timeline, and learnings for any selected date.
 * PAPER ONLY — advisory display only.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CalendarDays, ChevronLeft, ChevronRight, TrendingUp, TrendingDown,
  BarChart2, Clock, Activity, RefreshCw, Trophy, AlertCircle,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface CalendarDay {
  date: string; weekday: number; has_trades: boolean;
  trade_count: number; pnl: number; wins: number; losses: number;
  outcome: "WIN" | "LOSS" | "NEUTRAL" | null;
}

interface DailySummary {
  date: string;
  summary: {
    total_trades: number; opened: number; closed: number; total_pnl: number;
    wins: number; losses: number; win_rate: number; avg_confidence: number;
  };
  market_summary: Record<string, unknown>;
  closed_trades: { symbol: string; pnl: number; strategy: string; exit_reason: string }[];
  best_trade: { symbol: string; pnl: number; strategy: string } | null;
  worst_trade: { symbol: string; pnl: number; strategy: string } | null;
  timeline: { ts: string; type: string; label: string; category: string }[];
  learning: Record<string, unknown>;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MONTH_NAMES = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];
const DAY_LABELS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number, d = 0) {
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: d, maximumFractionDigits: d,
  }).format(n);
}
function pnlClass(v: number) {
  return v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400";
}
function istTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString("en-IN", {
      hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata",
    });
  } catch { return ""; }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function CalCell({
  day, selected, onClick,
}: { day: CalendarDay; selected: boolean; onClick: () => void }) {
  const isWeekend = day.weekday >= 5;
  let ringClass = "";
  if (day.has_trades) {
    if (day.outcome === "WIN")     ringClass = "ring-1 ring-emerald-500/50 bg-emerald-950/30";
    else if (day.outcome === "LOSS") ringClass = "ring-1 ring-rose-500/50 bg-rose-950/30";
    else                           ringClass = "ring-1 ring-amber-500/50 bg-amber-950/20";
  }

  return (
    <button
      onClick={onClick}
      className={[
        "relative rounded-lg p-2 text-left transition-all min-h-[72px] w-full",
        isWeekend ? "opacity-40 pointer-events-none" : "cursor-pointer",
        selected
          ? "ring-2 ring-teal-400 bg-teal-950/40"
          : "hover:bg-slate-800/60",
        ringClass,
      ].join(" ")}
    >
      <span className={`text-sm font-semibold ${selected ? "text-teal-300" : "text-slate-300"}`}>
        {day.date.slice(8)}
      </span>
      {day.has_trades && (
        <div className="mt-1 space-y-0.5">
          <div className={`text-xs font-mono font-bold ${pnlClass(day.pnl)}`}>
            {day.pnl >= 0 ? "+" : ""}₹{fmt(day.pnl)}
          </div>
          <div className="text-xs text-slate-500">{day.trade_count} trade{day.trade_count !== 1 ? "s" : ""}</div>
        </div>
      )}
    </button>
  );
}

function StatBox({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-slate-800/50 rounded-lg p-3">
      <p className="text-xs text-slate-500 mb-0.5">{label}</p>
      <p className="text-lg font-bold font-mono text-slate-100">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function DayDetail({ data, loading }: { data?: DailySummary; loading: boolean }) {
  if (loading) return <div className="space-y-3">{[1,2,3].map(i => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>;
  if (!data) return (
    <div className="flex flex-col items-center justify-center h-64 text-slate-500 gap-3">
      <CalendarDays className="w-10 h-10 opacity-30" />
      <p className="text-sm text-center">Select a trading day<br />to see the full session</p>
    </div>
  );

  const s = data.summary;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        <StatBox label="Total P/L" value={`${s.total_pnl>=0?"+":""}₹${fmt(s.total_pnl)}`} />
        <StatBox label="Win Rate" value={`${fmt(s.win_rate,0)}%`} sub={`${s.wins}W / ${s.losses}L`} />
        <StatBox label="Trades" value={`${s.total_trades}`} sub={`${s.opened} opened, ${s.closed} closed`} />
        <StatBox label="Avg Confidence" value={`${fmt(s.avg_confidence,0)}%`} />
      </div>

      {data.best_trade && (
        <div className="bg-emerald-950/30 border border-emerald-800/30 rounded-lg p-3">
          <p className="text-xs text-emerald-500 font-semibold mb-1 flex items-center gap-1">
            <Trophy className="w-3 h-3" /> Best Trade
          </p>
          <div className="flex justify-between items-center">
            <span className="font-semibold text-slate-200">{data.best_trade.symbol}</span>
            <span className="text-emerald-400 font-mono text-sm font-bold">+₹{fmt(data.best_trade.pnl)}</span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">{data.best_trade.strategy}</p>
        </div>
      )}

      {data.worst_trade && (
        <div className="bg-rose-950/30 border border-rose-800/30 rounded-lg p-3">
          <p className="text-xs text-rose-500 font-semibold mb-1 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" /> Worst Trade
          </p>
          <div className="flex justify-between items-center">
            <span className="font-semibold text-slate-200">{data.worst_trade.symbol}</span>
            <span className="text-rose-400 font-mono text-sm font-bold">₹{fmt(data.worst_trade.pnl)}</span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">{data.worst_trade.strategy}</p>
        </div>
      )}

      {data.timeline.length > 0 && (
        <div className="bg-slate-800/30 rounded-lg p-3">
          <p className="text-xs text-slate-500 font-semibold mb-2 flex items-center gap-1">
            <Clock className="w-3 h-3" /> Session Timeline
          </p>
          <div className="space-y-1.5">
            {data.timeline.slice(0, 8).map((ev, i) => (
              <div key={i} className="flex gap-2 text-xs">
                <span className="text-slate-500 shrink-0 w-12 font-mono tabular-nums">{ev.ts ? istTime(ev.ts) : ""}</span>
                <span className={`font-semibold shrink-0 w-14 text-right ${ev.category === "TRADE" ? "text-teal-400" : "text-slate-500"}`}>{ev.type}</span>
                <span className="text-slate-300 truncate">{ev.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.closed_trades.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-slate-500 font-semibold flex items-center gap-1">
            <BarChart2 className="w-3 h-3" /> Closed Positions
          </p>
          {data.closed_trades.slice(0, 5).map((t, i) => (
            <div key={i} className="bg-slate-800/40 rounded-lg px-3 py-2 flex justify-between items-center">
              <div>
                <span className="text-slate-200 font-semibold text-sm">{t.symbol}</span>
                <span className="text-slate-500 text-xs ml-2">{t.strategy}</span>
              </div>
              <span className={`font-mono text-sm font-bold ${pnlClass(t.pnl || 0)}`}>
                {(t.pnl||0) >= 0 ? "+" : ""}₹{fmt(t.pnl || 0)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Phase11SummaryPage() {
  const now = new Date();
  const [year,  setYear]  = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [sel,   setSel]   = useState<string | null>(null);

  const calQ = useQuery({
    queryKey: ["phase11", "calendar", year, month],
    queryFn:  () => apiJson<{ days: CalendarDay[]; trading_days: number; total_pnl: number; total_trades: number }>(
      `/phase11/calendar?year=${year}&month=${month}`
    ),
    staleTime: 60_000,
  });

  const dayQ = useQuery({
    queryKey: ["phase11", "daily-summary", sel],
    queryFn:  () => apiJson<DailySummary>(`/phase11/daily-summary?date=${sel}`),
    enabled:  !!sel,
    staleTime: 120_000,
  });

  const prevMonth = () => {
    if (month === 1) { setYear(y => y - 1); setMonth(12); }
    else setMonth(m => m - 1);
    setSel(null);
  };
  const nextMonth = () => {
    if (month === 12) { setYear(y => y + 1); setMonth(1); }
    else setMonth(m => m + 1);
    setSel(null);
  };

  const days = calQ.data?.days ?? [];
  const totalPnl = calQ.data?.total_pnl ?? 0;
  const tradingDays = calQ.data?.trading_days ?? 0;

  // Pad start of month with empty cells
  const firstWeekday = days.length > 0 ? days[0].weekday : 0;
  const gridItems: (CalendarDay | null)[] = [
    ...Array(firstWeekday).fill(null),
    ...days,
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <CalendarDays className="w-6 h-6 text-teal-400 shrink-0" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Paper Trading Summary</h1>
            <p className="text-slate-500 text-sm">Click any date to explore that session</p>
          </div>
          <Badge className="ml-auto bg-teal-900/50 text-teal-300 border-teal-700/50">PAPER ONLY</Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6">
          {/* Calendar */}
          <div className="space-y-4">
            {/* Month nav */}
            <div className="flex items-center justify-between bg-slate-900/60 rounded-xl p-4 border border-slate-800/40">
              <Button variant="ghost" size="sm" onClick={prevMonth} className="text-slate-400 hover:text-slate-200">
                <ChevronLeft className="w-5 h-5" />
              </Button>
              <div className="text-center">
                <h2 className="text-lg font-bold">{MONTH_NAMES[month - 1]} {year}</h2>
                <p className="text-xs text-slate-500">
                  {tradingDays} trading day{tradingDays !== 1 ? "s" : ""} ·{" "}
                  <span className={pnlClass(totalPnl)}>
                    {totalPnl >= 0 ? "+" : ""}₹{fmt(totalPnl)} total
                  </span>
                </p>
              </div>
              <Button variant="ghost" size="sm" onClick={nextMonth} className="text-slate-400 hover:text-slate-200">
                <ChevronRight className="w-5 h-5" />
              </Button>
            </div>

            {/* Day headers */}
            <div className="grid grid-cols-7 gap-1">
              {DAY_LABELS.map(d => (
                <div key={d} className="text-center text-xs font-semibold text-slate-600 py-1">{d}</div>
              ))}
            </div>

            {/* Grid */}
            {calQ.isLoading ? (
              <div className="grid grid-cols-7 gap-1">
                {Array.from({ length: 35 }).map((_, i) => (
                  <Skeleton key={i} className="h-[72px] rounded-lg" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-7 gap-1">
                {gridItems.map((day, i) =>
                  day === null ? <div key={i} /> : (
                    <CalCell
                      key={day.date}
                      day={day}
                      selected={sel === day.date}
                      onClick={() => setSel(sel === day.date ? null : day.date)}
                    />
                  )
                )}
              </div>
            )}

            {/* Legend */}
            <div className="flex flex-wrap gap-4 text-xs text-slate-600 pt-1">
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-sm bg-emerald-950 ring-1 ring-emerald-500/50 inline-block" />
                Profitable day
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-sm bg-rose-950 ring-1 ring-rose-500/50 inline-block" />
                Loss day
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-sm bg-teal-950 ring-2 ring-teal-400 inline-block" />
                Selected
              </span>
            </div>
          </div>

          {/* Day detail */}
          <div className="bg-slate-900/60 rounded-xl border border-slate-800/40 p-4 overflow-y-auto max-h-[700px]">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-slate-200 flex items-center gap-2">
                <Activity className="w-4 h-4 text-teal-400" />
                {sel ?? "Session Detail"}
              </h3>
              {sel && (
                <Button variant="ghost" size="sm" onClick={() => dayQ.refetch()} className="text-slate-500 hover:text-slate-200 h-7 w-7 p-0">
                  <RefreshCw className="w-3 h-3" />
                </Button>
              )}
            </div>
            <DayDetail data={dayQ.data} loading={dayQ.isLoading && !!sel} />
          </div>
        </div>
      </div>
    </div>
  );
}
