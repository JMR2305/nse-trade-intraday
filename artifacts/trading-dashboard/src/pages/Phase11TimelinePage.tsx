/**
 * Phase11TimelinePage — Paper Trading Session Timeline
 * Chronological log of all trading events for a session:
 * MARKET_OPEN, SCAN, BUY, SELL, PARTIAL_EXIT, LEARNING, etc.
 * PAPER ONLY — advisory display only.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Clock, RefreshCw, TrendingUp, TrendingDown, Activity,
  Search, Zap, BookOpen, Bell, Monitor,
} from "lucide-react";

interface TimelineEvent {
  ts: string; type: string; label: string; detail?: string;
  symbol?: string; price?: number; pnl?: number;
  strategy?: string; category: string;
}

interface TimelineData {
  session_date: string;
  events: TimelineEvent[];
  event_count: number;
  advisory_only: boolean;
  paper_only: boolean;
}

function fmt(n: number, d = 0) {
  if (n == null || isNaN(n)) return "";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}

function istTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString("en-IN", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false, timeZone: "Asia/Kolkata",
    });
  } catch { return ts?.slice(11, 19) ?? ""; }
}

function eventIcon(type: string, category: string) {
  if (category === "MARKET")       return <Monitor className="w-4 h-4" />;
  if (category === "SCAN")         return <Search className="w-4 h-4" />;
  if (category === "LEARNING")     return <BookOpen className="w-4 h-4" />;
  if (category === "NOTIFICATION") return <Bell className="w-4 h-4" />;
  if (type === "BUY" || type === "ADD") return <TrendingUp className="w-4 h-4" />;
  if (type === "SELL" || type === "EXIT" || type === "CLOSE") return <TrendingDown className="w-4 h-4" />;
  if (type === "PARTIAL_EXIT")     return <Zap className="w-4 h-4" />;
  return <Activity className="w-4 h-4" />;
}

function eventColor(type: string, category: string) {
  if (type === "BUY" || type === "ADD")                   return "text-emerald-400 bg-emerald-950/30 border-emerald-800/40";
  if (type === "SELL" || type === "EXIT" || type === "CLOSE") return "text-rose-400 bg-rose-950/30 border-rose-800/40";
  if (type === "PARTIAL_EXIT")                            return "text-amber-400 bg-amber-950/30 border-amber-800/40";
  if (category === "MARKET")                              return "text-blue-400 bg-blue-950/30 border-blue-800/40";
  if (category === "SCAN")                                return "text-teal-400 bg-teal-950/30 border-teal-800/40";
  if (category === "LEARNING")                            return "text-purple-400 bg-purple-950/30 border-purple-800/40";
  return "text-slate-400 bg-slate-800/30 border-slate-700/40";
}

function connectorColor(type: string, category: string) {
  if (type === "BUY" || type === "ADD")                   return "bg-emerald-700/30";
  if (type === "SELL" || type === "EXIT" || type === "CLOSE") return "bg-rose-700/30";
  if (category === "MARKET")                              return "bg-blue-700/30";
  if (category === "SCAN")                                return "bg-teal-700/30";
  if (category === "LEARNING")                            return "bg-purple-700/30";
  return "bg-slate-700/30";
}

const CATEGORIES = ["ALL", "TRADE", "MARKET", "SCAN", "LEARNING", "NOTIFICATION"];

export default function Phase11TimelinePage() {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate]   = useState(today);
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");

  const q = useQuery({
    queryKey: ["phase11", "timeline", date],
    queryFn:  () => apiJson<TimelineData>(`/phase11/timeline?date=${date}`),
    staleTime: 60_000,
    refetchInterval: date === today ? 120_000 : false,
  });

  const events = (q.data?.events ?? []).filter(e => {
    const cat = filter === "ALL" || e.category === filter;
    const srch = !search || e.label?.toLowerCase().includes(search.toLowerCase()) ||
      e.symbol?.toLowerCase().includes(search.toLowerCase());
    return cat && srch;
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3">
          <Clock className="w-6 h-6 text-teal-400 shrink-0" />
          <div>
            <h1 className="text-2xl font-bold">Trading Timeline</h1>
            <p className="text-slate-500 text-sm">Chronological session log</p>
          </div>
          <div className="ml-auto flex gap-2 items-center">
            <Badge className="bg-teal-900/50 text-teal-300 border-teal-700/50">PAPER ONLY</Badge>
            <Button variant="ghost" size="sm" onClick={() => q.refetch()} className="text-slate-500 hover:text-slate-200">
              <RefreshCw className={`w-4 h-4 ${q.isFetching ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        {/* Controls */}
        <div className="bg-slate-900/60 rounded-xl border border-slate-800/40 p-4 flex flex-wrap gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <Clock className="w-4 h-4" />
            <input type="date" value={date} max={today}
              onChange={e => setDate(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200 text-sm" />
          </label>
          <input
            placeholder="Search symbol or event…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-200 placeholder:text-slate-600 flex-1 min-w-40"
          />
          <div className="flex gap-1 flex-wrap">
            {CATEGORIES.map(c => (
              <button key={c}
                onClick={() => setFilter(c)}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  filter === c ? "bg-teal-900/60 text-teal-300 ring-1 ring-teal-700/50" : "bg-slate-800/60 text-slate-500 hover:text-slate-300"
                }`}
              >{c}</button>
            ))}
          </div>
        </div>

        {/* Stats */}
        {q.data && (
          <div className="flex gap-4 text-sm text-slate-500 px-1">
            <span>{q.data.event_count} total events</span>
            <span>·</span>
            <span>{events.length} shown</span>
            <span>·</span>
            <span>{q.data.session_date}</span>
          </div>
        )}

        {/* Timeline */}
        {q.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
          </div>
        ) : events.length === 0 ? (
          <div className="text-center py-16 text-slate-500">
            <Activity className="w-12 h-12 mx-auto mb-3 opacity-20" />
            <p className="text-lg font-semibold">No events found</p>
            <p className="text-sm mt-1">
              {q.data?.event_count === 0
                ? "No trading activity recorded for this date."
                : "Try adjusting the filter or search."}
            </p>
          </div>
        ) : (
          <div className="relative">
            {/* Vertical line */}
            <div className="absolute left-[23px] top-6 bottom-6 w-px bg-slate-800" />

            <div className="space-y-3">
              {events.map((ev, i) => {
                const colorClass   = eventColor(ev.type, ev.category);
                const [textCl, bgCl, borderCl] = colorClass.split(" ");
                const isLast = i === events.length - 1;

                return (
                  <div key={i} className="flex gap-3 items-start">
                    {/* Icon */}
                    <div className={`relative z-10 w-12 h-12 shrink-0 rounded-full border flex items-center justify-center ${bgCl} ${borderCl} ${textCl}`}>
                      {eventIcon(ev.type, ev.category)}
                    </div>

                    {/* Content */}
                    <div className={`flex-1 rounded-xl border p-3 pb-3 ${bgCl} ${borderCl}`}>
                      <div className="flex items-start justify-between gap-2 flex-wrap">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`font-mono text-xs font-semibold ${textCl}`}>{istTime(ev.ts)}</span>
                          <Badge className={`text-xs ${bgCl} ${textCl} ${borderCl}`}>{ev.type}</Badge>
                          {ev.symbol && <span className="font-bold text-slate-200 text-sm">{ev.symbol}</span>}
                        </div>
                        {ev.price != null && ev.price > 0 && (
                          <span className="font-mono text-xs text-slate-400">₹{fmt(ev.price)}</span>
                        )}
                      </div>

                      <p className="text-sm text-slate-300 mt-1">{ev.label}</p>

                      {ev.pnl != null && ev.pnl !== 0 && (
                        <p className={`text-sm font-bold font-mono mt-0.5 ${ev.pnl > 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {ev.pnl > 0 ? "+" : ""}₹{fmt(ev.pnl)} P/L
                        </p>
                      )}
                      {ev.strategy && (
                        <p className="text-xs text-slate-500 mt-0.5">{ev.strategy}</p>
                      )}
                      {ev.detail && (
                        <p className="text-xs text-slate-500 mt-1 italic">{ev.detail}</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
