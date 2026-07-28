/**
 * ExecutionQualityPage.tsx — Phase 5D.1
 * Read-only execution quality analytics for paper trading.
 * PAPER TRADING / ADVISORY ONLY.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { AlertCircle, Gauge, TrendingDown, Clock, Award, XCircle } from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface EQSummary {
  status: string;
  total_trades: number;
  completed_trades: number;
  avg_execution_score: number | null;
  avg_entry_slippage_rs: number | null;
  avg_entry_slippage_pct: number | null;
  avg_exit_slippage_rs: number | null;
  avg_exit_slippage_pct: number | null;
  avg_fill_delay_seconds: number | null;
  best_trade:  { trade_id: string; symbol: string; score: number; grade: string } | null;
  worst_trade: { trade_id: string; symbol: string; score: number; grade: string } | null;
  most_efficient_strategy: string | null;
  highest_slippage_symbol: string | null;
}

interface EQTrade {
  trade_id: string;
  symbol: string;
  strategy_name: string;
  entry_ts: string | null;
  actual_entry_price: number;
  actual_exit_price: number;
  entry_slippage_rs: number;
  entry_slippage_pct: number;
  fill_delay_seconds: number;
  exit_type: string;
  pnl: number;
  quality_score: number;
  quality_grade: string;
  is_complete: boolean;
}

interface SlippageDim { label: string; avg: number | null; median: number | null; count: number }

interface EQSlippage {
  status: string;
  entry_rs: { avg: number | null; median: number | null; worst: number | null; best: number | null };
  by_symbol:   SlippageDim[];
  by_strategy: SlippageDim[];
  by_regime:   SlippageDim[];
}

interface EQFills {
  status: string;
  avg_delay_seconds: number | null;
  median_delay_seconds: number | null;
  max_delay_seconds: number | null;
  instant_fills: number;
  delayed_fills: number;
  total_fills: number;
  instant_pct: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const gradeColor = (grade: string) => {
  if (grade === "Excellent") return "text-emerald-400";
  if (grade === "Good")      return "text-teal-400";
  if (grade === "Fair")      return "text-amber-400";
  return "text-red-400";
};

const scoreBadge = (score: number, grade: string) => (
  <span className={`font-bold tabular-nums ${gradeColor(grade)}`}>
    {score}<span className="text-muted-foreground font-normal text-xs">/100</span>
    <span className="ml-1 text-xs">{grade}</span>
  </span>
);

const pct  = (v: number | null) => v == null ? "—" : `${v.toFixed(3)}%`;
const rs   = (v: number | null) => v == null ? "—" : `₹${v.toFixed(2)}`;
const secs = (v: number | null) => v == null ? "—" : `${v.toFixed(1)}s`;
const fmt  = (v: string | null) => v ? new Date(v).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : "—";

function DisabledBanner() {
  return (
    <div className="flex flex-col items-center justify-center h-[40vh] gap-4 text-muted-foreground">
      <AlertCircle className="w-10 h-10 text-amber-400" />
      <p className="text-lg font-semibold">Execution Quality Analytics is disabled</p>
      <p className="text-sm">Set <code className="bg-muted px-1 rounded">EXECUTION_QUALITY_ENABLED=true</code> to activate Phase 5D.1.</p>
    </div>
  );
}

// ── Summary cards ─────────────────────────────────────────────────────────────

function SummaryCards({ s }: { s: EQSummary }) {
  const cards = [
    { label: "Avg Execution Score", icon: Gauge,
      value: s.avg_execution_score != null
        ? <span className={gradeColor(s.avg_execution_score >= 90 ? "Excellent" : s.avg_execution_score >= 75 ? "Good" : s.avg_execution_score >= 60 ? "Fair" : "Poor")}>
            {s.avg_execution_score.toFixed(1)}
          </span>
        : "—",
      sub: `${s.completed_trades} completed / ${s.total_trades} total` },
    { label: "Avg Entry Slippage", icon: TrendingDown,
      value: rs(s.avg_entry_slippage_rs),
      sub: pct(s.avg_entry_slippage_pct) },
    { label: "Avg Exit Slippage", icon: TrendingDown,
      value: rs(s.avg_exit_slippage_rs),
      sub: pct(s.avg_exit_slippage_pct) },
    { label: "Avg Fill Delay", icon: Clock,
      value: secs(s.avg_fill_delay_seconds),
      sub: "seconds to fill" },
    { label: "Best Trade", icon: Award,
      value: s.best_trade
        ? <span className="text-emerald-400 font-bold">{s.best_trade.symbol} {s.best_trade.score}/100</span>
        : "—",
      sub: s.best_trade?.grade ?? "" },
    { label: "Worst Trade", icon: XCircle,
      value: s.worst_trade
        ? <span className="text-red-400 font-bold">{s.worst_trade.symbol} {s.worst_trade.score}/100</span>
        : "—",
      sub: s.worst_trade?.grade ?? "" },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      {cards.map(c => (
        <Card key={c.label} className="border-border/50">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-1">
              <c.icon className="w-4 h-4 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">{c.label}</span>
            </div>
            <div className="text-xl font-bold tabular-nums">{c.value}</div>
            <div className="text-xs text-muted-foreground mt-0.5">{c.sub}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Charts ────────────────────────────────────────────────────────────────────

function ScoreTrendChart({ trades }: { trades: EQTrade[] }) {
  const data = trades
    .filter(t => t.entry_ts)
    .slice(-40)
    .map((t, i) => ({ i: i + 1, score: t.quality_score, symbol: t.symbol }));

  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2"><CardTitle className="text-sm">Execution Score Trend</CardTitle></CardHeader>
      <CardContent>
        {data.length === 0
          ? <p className="text-xs text-muted-foreground text-center py-6">No data yet</p>
          : <ResponsiveContainer width="100%" height={180}>
              <LineChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                <XAxis dataKey="i" tick={{ fontSize: 10 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: "#1a1a2e", border: "1px solid #ffffff20", fontSize: 12 }}
                  formatter={(v: number) => [`${v}/100`, "Score"]}
                  labelFormatter={(i) => data[Number(i) - 1]?.symbol ?? ""}
                />
                <Line type="monotone" dataKey="score" stroke="#14b8a6" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
        }
      </CardContent>
    </Card>
  );
}

function SlippageTrendChart({ trades }: { trades: EQTrade[] }) {
  const data = trades.slice(-40).map((t, i) => ({
    i: i + 1, slip: t.entry_slippage_rs, symbol: t.symbol,
  }));
  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2"><CardTitle className="text-sm">Entry Slippage Trend (₹)</CardTitle></CardHeader>
      <CardContent>
        {data.length === 0
          ? <p className="text-xs text-muted-foreground text-center py-6">No data yet</p>
          : <ResponsiveContainer width="100%" height={180}>
              <BarChart data={data}>
                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                <XAxis dataKey="i" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: "#1a1a2e", border: "1px solid #ffffff20", fontSize: 12 }}
                  formatter={(v: number) => [`₹${v.toFixed(2)}`, "Slippage"]}
                />
                <Bar dataKey="slip" fill="#f59e0b" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
        }
      </CardContent>
    </Card>
  );
}

function StrategyComparisonChart({ slippage }: { slippage: EQSlippage }) {
  const data = (slippage.by_strategy ?? [])
    .filter(d => d.avg != null)
    .map(d => ({ name: d.label, slip: d.avg ?? 0, count: d.count }));
  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2"><CardTitle className="text-sm">Slippage by Strategy (₹ avg)</CardTitle></CardHeader>
      <CardContent>
        {data.length === 0
          ? <p className="text-xs text-muted-foreground text-center py-6">No data yet</p>
          : <ResponsiveContainer width="100%" height={180}>
              <BarChart data={data} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10 }} width={90} />
                <Tooltip
                  contentStyle={{ background: "#1a1a2e", border: "1px solid #ffffff20", fontSize: 12 }}
                  formatter={(v: number) => [`₹${v.toFixed(2)}`, "Avg Slippage"]}
                />
                <Bar dataKey="slip" fill="#6366f1" radius={[0, 2, 2, 0]} />
              </BarChart>
            </ResponsiveContainer>
        }
      </CardContent>
    </Card>
  );
}

function FillDelayChart({ fills }: { fills: EQFills }) {
  const data = [
    { label: "Instant (<5s)",  value: fills.instant_fills },
    { label: "Delayed (≥60s)", value: fills.delayed_fills },
    { label: "Other",          value: Math.max(0, fills.total_fills - fills.instant_fills - fills.delayed_fills) },
  ].filter(d => d.value > 0);
  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2"><CardTitle className="text-sm">Fill Speed Distribution</CardTitle></CardHeader>
      <CardContent>
        {fills.total_fills === 0
          ? <p className="text-xs text-muted-foreground text-center py-6">No data yet</p>
          : <>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid #ffffff20", fontSize: 12 }} />
                  <Bar dataKey="value" fill="#22d3ee" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="flex gap-4 mt-2 text-xs text-muted-foreground justify-center">
                <span>Avg: {secs(fills.avg_delay_seconds)}</span>
                <span>Max: {secs(fills.max_delay_seconds)}</span>
                {fills.instant_pct != null && <span>Instant: {fills.instant_pct}%</span>}
              </div>
            </>
        }
      </CardContent>
    </Card>
  );
}

// ── Trade table ───────────────────────────────────────────────────────────────

function TradesTable({ trades }: { trades: EQTrade[] }) {
  return (
    <Card className="border-border/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Trade Execution Detail ({trades.length})</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-border/40">
                <TableHead>Symbol</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Signal Time</TableHead>
                <TableHead className="text-right">Entry ₹</TableHead>
                <TableHead className="text-right">Exit ₹</TableHead>
                <TableHead className="text-right">Slippage</TableHead>
                <TableHead className="text-right">Delay</TableHead>
                <TableHead>Exit</TableHead>
                <TableHead className="text-right">Score</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-muted-foreground py-8">
                    No trades recorded yet
                  </TableCell>
                </TableRow>
              )}
              {trades.map(t => (
                <TableRow key={t.trade_id} className="border-border/20 hover:bg-white/5">
                  <TableCell className="font-medium">{t.symbol}</TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-[110px] truncate">
                    {t.strategy_name}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">{fmt(t.entry_ts)}</TableCell>
                  <TableCell className="text-right tabular-nums text-xs">
                    {t.actual_entry_price > 0 ? `₹${t.actual_entry_price.toFixed(2)}` : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-xs">
                    {t.is_complete && t.actual_exit_price > 0 ? `₹${t.actual_exit_price.toFixed(2)}` : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-xs text-amber-400">
                    {rs(t.entry_slippage_rs)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-xs">
                    {secs(t.fill_delay_seconds)}
                  </TableCell>
                  <TableCell>
                    {t.is_complete
                      ? <Badge variant="outline" className="text-xs">{t.exit_type || "—"}</Badge>
                      : <Badge variant="secondary" className="text-xs text-slate-400">Open</Badge>
                    }
                  </TableCell>
                  <TableCell className="text-right">
                    {scoreBadge(t.quality_score, t.quality_grade)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ExecutionQualityPage() {
  const { data: summary, isLoading: sLoading } =
    useQuery<EQSummary>({ queryKey: ["execution-quality/summary"],
      queryFn: () => apiJson("execution-quality/summary"), refetchInterval: 60_000 });

  const { data: tradesData, isLoading: tLoading } =
    useQuery<{ trades: EQTrade[] }>({ queryKey: ["execution-quality/trades"],
      queryFn: () => apiJson("execution-quality/trades?limit=200"), refetchInterval: 60_000 });

  const { data: slippage, isLoading: slLoading } =
    useQuery<EQSlippage>({ queryKey: ["execution-quality/slippage"],
      queryFn: () => apiJson("execution-quality/slippage"), refetchInterval: 60_000 });

  const { data: fills, isLoading: fLoading } =
    useQuery<EQFills>({ queryKey: ["execution-quality/fills"],
      queryFn: () => apiJson("execution-quality/fills"), refetchInterval: 60_000 });

  const loading = sLoading || tLoading || slLoading || fLoading;

  if (loading) {
    return (
      <div className="p-6 space-y-4 animate-pulse">
        <div className="h-6 bg-white/10 rounded w-48" />
        <div className="grid grid-cols-6 gap-3">
          {[...Array(6)].map((_, i) => <div key={i} className="h-20 bg-white/5 rounded" />)}
        </div>
      </div>
    );
  }

  if (summary?.status === "DISABLED") return <DisabledBanner />;

  const trades = tradesData?.trades ?? [];

  return (
    <div className="p-4 md:p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Execution Quality</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Phase 5D.1 · Paper Trading · Advisory Only
          </p>
        </div>
        {summary && (
          <div className="text-right text-xs text-muted-foreground">
            <div>Most efficient: <span className="text-foreground">{summary.most_efficient_strategy ?? "—"}</span></div>
            <div>Highest slippage: <span className="text-amber-400">{summary.highest_slippage_symbol ?? "—"}</span></div>
          </div>
        )}
      </div>

      {/* Summary cards */}
      {summary && <SummaryCards s={summary} />}

      {/* Charts 2×2 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ScoreTrendChart    trades={trades} />
        <SlippageTrendChart trades={trades} />
        {slippage  && <StrategyComparisonChart slippage={slippage} />}
        {fills     && <FillDelayChart fills={fills} />}
      </div>

      {/* Trade table */}
      <TradesTable trades={trades} />
    </div>
  );
}
