/**
 * Phase11ReportsPage — Paper Trading Reports
 * Daily, Weekly, Monthly reports with P/L, win rate, strategy breakdown,
 * capital history, reset history, and top-up log.
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
  FileText, RefreshCw, TrendingUp, TrendingDown, BarChart2,
  Calendar, DollarSign, Trophy, AlertCircle,
} from "lucide-react";

type ReportType = "daily" | "weekly" | "monthly";

interface DailyReport {
  report_type: "DAILY"; date: string;
  capital_mode: string; starting_capital: number;
  trades: number; closed_trades: number; pnl: number; win_rate: number;
  avg_confidence: number; best_trade: { symbol: string; pnl: number } | null;
  worst_trade: { symbol: string; pnl: number } | null;
  closed_detail: unknown[]; top_up_events: unknown[];
  generated_at: string; advisory_only: boolean; paper_only: boolean;
}

interface WeeklyReport {
  report_type: "WEEKLY"; week_start: string; week_end: string;
  total_trades: number; closed_trades: number; opened_trades: number;
  total_pnl: number; wins: number; losses: number; win_rate: number;
  best_strategy: string | null; worst_strategy: string | null;
  strategy_pnl: Record<string, number>;
  daily_breakdown: Record<string, { pnl: number; trades: number }>;
  top_up_events: unknown[]; generated_at: string;
}

interface MonthlyReport {
  report_type: "MONTHLY"; year: number; month: number; month_label: string;
  starting_capital: number; capital_mode: string;
  total_trades: number; closed_trades: number; total_pnl: number;
  wins: number; losses: number; win_rate: number; avg_confidence: number;
  profit_factor: number; top_up_count: number; total_topup: number;
  capital_end: number; generated_at: string;
}

function fmt(n: number, d = 0) {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}
function pnlClass(v: number) { return v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400"; }

function MetricRow({ label, value, highlight }: { label: string; value: string | React.ReactNode; highlight?: boolean }) {
  return (
    <div className={`flex justify-between items-center py-2 border-b border-slate-800/40 ${highlight ? "text-teal-300" : ""}`}>
      <span className="text-sm text-slate-400">{label}</span>
      <span className={`text-sm font-semibold ${highlight ? "text-teal-300" : "text-slate-100"}`}>{value}</span>
    </div>
  );
}

function DailyReportView({ report }: { report: DailyReport }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {[
          { label: "Date", value: report.date },
          { label: "Capital Mode", value: `Mode ${report.capital_mode}` },
          { label: "Starting Capital", value: `₹${fmt(report.starting_capital)}` },
          { label: "Total Trades", value: String(report.trades) },
          { label: "Closed Trades", value: String(report.closed_trades) },
          { label: "Win Rate", value: `${fmt(report.win_rate, 1)}%` },
          { label: "Session P/L", value: `${report.pnl >= 0 ? "+" : ""}₹${fmt(report.pnl)}`,  },
          { label: "Avg Confidence", value: `${fmt(report.avg_confidence, 0)}%` },
        ].map(m => (
          <div key={m.label} className="bg-slate-800/40 rounded-lg p-3">
            <p className="text-xs text-slate-500 mb-0.5">{m.label}</p>
            <p className={`font-bold font-mono ${m.label === "Session P/L" ? pnlClass(report.pnl) : "text-slate-100"}`}>{m.value}</p>
          </div>
        ))}
      </div>
      {report.best_trade && (
        <div className="bg-emerald-950/20 border border-emerald-800/30 rounded-xl p-3">
          <p className="text-xs text-emerald-500 font-semibold mb-1 flex items-center gap-1"><Trophy className="w-3 h-3" /> Best Trade</p>
          <div className="flex justify-between">
            <span className="font-semibold text-slate-200">{report.best_trade.symbol}</span>
            <span className="text-emerald-400 font-mono font-bold">+₹{fmt(report.best_trade.pnl)}</span>
          </div>
        </div>
      )}
      {report.worst_trade && (
        <div className="bg-rose-950/20 border border-rose-800/30 rounded-xl p-3">
          <p className="text-xs text-rose-500 font-semibold mb-1 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> Worst Trade</p>
          <div className="flex justify-between">
            <span className="font-semibold text-slate-200">{report.worst_trade.symbol}</span>
            <span className="text-rose-400 font-mono font-bold">₹{fmt(report.worst_trade.pnl)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function WeeklyReportView({ report }: { report: WeeklyReport }) {
  const days = Object.entries(report.daily_breakdown ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const stratEntries = Object.entries(report.strategy_pnl ?? {}).sort(([, a], [, b]) => b - a);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { l: "Week", v: `${report.week_start} → ${report.week_end}` },
          { l: "Total P/L", v: `${report.total_pnl >= 0 ? "+" : ""}₹${fmt(report.total_pnl)}` },
          { l: "Win Rate", v: `${fmt(report.win_rate, 1)}%` },
          { l: "Trades", v: `${report.closed_trades} closed` },
          { l: "Best Strategy", v: report.best_strategy ?? "—" },
          { l: "Worst Strategy", v: report.worst_strategy ?? "—" },
          { l: "Wins", v: String(report.wins) },
          { l: "Losses", v: String(report.losses) },
        ].map(m => (
          <div key={m.l} className="bg-slate-800/40 rounded-lg p-3">
            <p className="text-xs text-slate-500 mb-0.5">{m.l}</p>
            <p className={`font-bold text-sm ${m.l === "Total P/L" ? pnlClass(report.total_pnl) : "text-slate-100"}`}>{m.v}</p>
          </div>
        ))}
      </div>

      {days.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-3 space-y-2">
          <p className="text-xs text-slate-500 font-semibold mb-2 flex items-center gap-1"><Calendar className="w-3 h-3" /> Daily Breakdown</p>
          {days.map(([date, d]) => (
            <div key={date} className="flex justify-between items-center text-sm">
              <span className="text-slate-400">{date}</span>
              <span className="text-slate-400">{d.trades} trades</span>
              <span className={`font-mono font-bold ${pnlClass(d.pnl)}`}>{d.pnl >= 0 ? "+" : ""}₹{fmt(d.pnl)}</span>
            </div>
          ))}
        </div>
      )}

      {stratEntries.length > 0 && (
        <div className="bg-slate-800/30 rounded-xl p-3 space-y-2">
          <p className="text-xs text-slate-500 font-semibold mb-2 flex items-center gap-1"><BarChart2 className="w-3 h-3" /> Strategy P/L</p>
          {stratEntries.map(([strat, pnl]) => (
            <div key={strat} className="flex justify-between items-center text-sm">
              <span className="text-slate-300">{strat}</span>
              <span className={`font-mono font-bold ${pnlClass(pnl)}`}>{pnl >= 0 ? "+" : ""}₹{fmt(pnl)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MonthlyReportView({ report }: { report: MonthlyReport }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { l: "Period", v: report.month_label },
          { l: "Capital Mode", v: `Mode ${report.capital_mode}` },
          { l: "Starting Capital", v: `₹${fmt(report.starting_capital)}` },
          { l: "Approx. End Capital", v: `₹${fmt(report.capital_end)}` },
          { l: "Total P/L", v: `${report.total_pnl >= 0 ? "+" : ""}₹${fmt(report.total_pnl)}` },
          { l: "Win Rate", v: `${fmt(report.win_rate, 1)}%` },
          { l: "Profit Factor", v: report.profit_factor > 0 ? fmt(report.profit_factor, 2) : "—" },
          { l: "Avg Confidence", v: `${fmt(report.avg_confidence, 0)}%` },
          { l: "Total Trades", v: `${report.total_trades}` },
          { l: "Closed Trades", v: `${report.closed_trades}` },
          { l: "Wins / Losses", v: `${report.wins} / ${report.losses}` },
          { l: "Top-ups (Mode B)", v: `${report.top_up_count} × ₹${fmt(report.total_topup)}` },
        ].map(m => (
          <div key={m.l} className="bg-slate-800/40 rounded-lg p-3">
            <p className="text-xs text-slate-500 mb-0.5">{m.l}</p>
            <p className={`font-bold text-sm ${m.l === "Total P/L" ? pnlClass(report.total_pnl) : "text-slate-100"}`}>{m.v}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Phase11ReportsPage() {
  const [type, setType] = useState<ReportType>("daily");
  const today = new Date();
  const [dailyDate, setDailyDate] = useState(today.toISOString().slice(0, 10));
  const [weekStart, setWeekStart] = useState(() => {
    const d = new Date(today);
    d.setDate(d.getDate() - d.getDay() + 1);
    return d.toISOString().slice(0, 10);
  });
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [year,  setYear]  = useState(today.getFullYear());

  const dailyQ = useQuery({
    queryKey: ["phase11", "reports", "daily", dailyDate],
    queryFn:  () => apiJson<DailyReport>(`/phase11/reports/daily?date=${dailyDate}`),
    staleTime: 300_000, enabled: type === "daily",
  });
  const weeklyQ = useQuery({
    queryKey: ["phase11", "reports", "weekly", weekStart],
    queryFn:  () => apiJson<WeeklyReport>(`/phase11/reports/weekly?week_start=${weekStart}`),
    staleTime: 300_000, enabled: type === "weekly",
  });
  const monthlyQ = useQuery({
    queryKey: ["phase11", "reports", "monthly", year, month],
    queryFn:  () => apiJson<MonthlyReport>(`/phase11/reports/monthly?year=${year}&month=${month}`),
    staleTime: 300_000, enabled: type === "monthly",
  });

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  const isLoading = type === "daily" ? dailyQ.isLoading : type === "weekly" ? weeklyQ.isLoading : monthlyQ.isLoading;
  const refetch   = type === "daily" ? dailyQ.refetch  : type === "weekly" ? weeklyQ.refetch  : monthlyQ.refetch;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3">
          <FileText className="w-6 h-6 text-teal-400 shrink-0" />
          <div>
            <h1 className="text-2xl font-bold">Paper Trading Reports</h1>
            <p className="text-slate-500 text-sm">Daily · Weekly · Monthly performance summaries</p>
          </div>
          <div className="ml-auto flex gap-2 items-center">
            <Badge className="bg-teal-900/50 text-teal-300 border-teal-700/50">PAPER ONLY</Badge>
            <Button variant="ghost" size="sm" onClick={() => refetch()} className="text-slate-500 hover:text-slate-200">
              <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 bg-slate-900/60 rounded-xl p-1 border border-slate-800/40">
          {(["daily","weekly","monthly"] as ReportType[]).map(t => (
            <button key={t}
              onClick={() => setType(t)}
              className={`flex-1 py-2 px-4 rounded-lg text-sm font-semibold transition-all capitalize ${
                type === t ? "bg-teal-900/50 text-teal-300" : "text-slate-500 hover:text-slate-300"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Date selector */}
        <div className="bg-slate-900/60 rounded-xl border border-slate-800/40 p-4">
          {type === "daily" && (
            <label className="flex items-center gap-3 text-sm text-slate-400">
              <Calendar className="w-4 h-4" /> Date:
              <input type="date" value={dailyDate} max={today.toISOString().slice(0,10)}
                onChange={e => setDailyDate(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200" />
            </label>
          )}
          {type === "weekly" && (
            <label className="flex items-center gap-3 text-sm text-slate-400">
              <Calendar className="w-4 h-4" /> Week starting (Monday):
              <input type="date" value={weekStart}
                onChange={e => setWeekStart(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200" />
            </label>
          )}
          {type === "monthly" && (
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <Calendar className="w-4 h-4" />
              <select value={month} onChange={e => setMonth(Number(e.target.value))}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200">
                {MONTHS.map((m, i) => <option key={i} value={i+1}>{m}</option>)}
              </select>
              <select value={year} onChange={e => setYear(Number(e.target.value))}
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-200">
                {[2024,2025,2026].map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
          )}
        </div>

        {/* Report content */}
        <Card className="bg-slate-900/60 border-slate-800/40">
          <CardHeader>
            <CardTitle className="text-sm font-semibold text-slate-400 capitalize flex items-center gap-2">
              <FileText className="w-4 h-4 text-teal-400" />
              {type} Report
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-3">{[1,2,3].map(i => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
            ) : type === "daily" && dailyQ.data ? (
              <DailyReportView report={dailyQ.data} />
            ) : type === "weekly" && weeklyQ.data ? (
              <WeeklyReportView report={weeklyQ.data} />
            ) : type === "monthly" && monthlyQ.data ? (
              <MonthlyReportView report={monthlyQ.data} />
            ) : (
              <div className="text-center py-10 text-slate-500 text-sm">
                No data for the selected period
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
