/**
 * PortfolioPerformance.tsx — Phase 5D.2 Portfolio Performance Intelligence
 *
 * READ-ONLY analytics dashboard.  Never modifies any trading state.
 * PAPER TRADING / ADVISORY ONLY.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  TrendingUp, TrendingDown, DollarSign, Target, AlertTriangle,
  BarChart3, Layers, RefreshCw, ChevronDown, ChevronUp,
  Trophy, Skull, Clock, Percent,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiJson } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Summary {
  status: string;
  total_portfolio_value: number;
  initial_capital: number;
  cash_available: number;
  invested_capital: number;
  unrealised_pnl: number;
  realised_pnl: number;
  total_net_pnl: number;
  total_return_pct: number;
  today_pnl: number;
  weekly_pnl: number;
  monthly_pnl: number;
  lifetime_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  open_trades: number;
  win_rate: number;
  loss_rate: number;
  avg_winner: number;
  avg_loser: number;
  largest_profit: number;
  largest_loss: number;
  avg_holding_seconds: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  current_drawdown: number;
  current_drawdown_pct: number;
  recovery_pct: number;
  profit_factor: number;
  expectancy: number;
  risk_reward_ratio: number;
  avg_r_multiple: number;
  portfolio_utilisation_pct: number;
  position_concentration_pct: number;
}

interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
  drawdown_pct: number;
}

interface DailyPnl {
  date: string;
  pnl: number;
  pnl_pct: number;
  equity: number;
}

interface MonthlyPnl {
  month: string;
  pnl: number;
  pnl_pct: number;
  equity: number;
}

interface EquityResponse {
  status: string;
  series: EquityPoint[];
  daily_pnl: DailyPnl[];
  monthly_pnl: MonthlyPnl[];
}

interface DrawdownResponse {
  status: string;
  series: EquityPoint[];
  max_drawdown: number;
  max_drawdown_pct: number;
  current_drawdown: number;
  current_drawdown_pct: number;
  recovery_pct: number;
  max_drawdown_start: string | null;
  max_drawdown_end: string | null;
  all_time_peak: number;
  current_equity: number;
}

interface StrategyRow {
  strategy_name: string;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

interface TradeRow {
  trade_id: string;
  symbol: string;
  sector: string;
  entry_ts: string;
  exit_ts: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  holding_seconds: number;
  exit_type: string;
}

interface StatisticsResponse {
  status: string;
  trade_statistics: {
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    win_rate: number;
    avg_winner: number;
    avg_loser: number;
    largest_profit: number;
    largest_loss: number;
    avg_holding_seconds: number;
    avg_holding_human: string;
  };
  strategy_contribution: StrategyRow[];
  top_winners: TradeRow[];
  top_losers: TradeRow[];
}

interface SectorRow { sector: string; value: number; pct: number; }

interface PortfolioResponse {
  status: string;
  total_value: number;
  cash: number;
  invested: number;
  unrealised_pnl: number;
  utilisation_pct: number;
  sector_allocation: SectorRow[];
  open_positions: {
    symbol: string;
    sector: string;
    quantity: number;
    avg_cost: number;
    current_value: number;
    unrealised_pnl: number;
    unrealised_pnl_pct: number;
    weight_pct: number;
  }[];
}

// ── Formatters ────────────────────────────────────────────────────────────────

const fmt = (v: number, dec = 2) =>
  v?.toLocaleString("en-IN", { minimumFractionDigits: dec, maximumFractionDigits: dec }) ?? "—";

const fmtRs = (v: number) =>
  `₹${fmt(v)}`;

const fmtPct = (v: number) =>
  `${v >= 0 ? "+" : ""}${fmt(v, 2)}%`;

const fmtShortTs = (ts: string | null) => {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }); }
  catch { return ts.slice(0, 10); }
};

const fmtHolding = (sec: number) => {
  if (!sec || sec <= 0) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${Math.floor(sec)}s`;
};

// ── Colours ───────────────────────────────────────────────────────────────────

const SECTOR_COLORS = [
  "#0ea5e9", "#10b981", "#f59e0b", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#6366f1",
];

// ── Mini components ───────────────────────────────────────────────────────────

function Pill({ children, green }: { children: React.ReactNode; green?: boolean }) {
  return (
    <span className={cn(
      "inline-block px-2 py-0.5 rounded text-xs font-semibold",
      green ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400",
    )}>
      {children}
    </span>
  );
}

function SummaryCard({
  label, value, sub, icon: Icon, positive, neutral,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ElementType;
  positive?: boolean;
  neutral?: boolean;
}) {
  const color = neutral
    ? "text-muted-foreground"
    : positive === undefined
    ? "text-foreground"
    : positive
    ? "text-emerald-400"
    : "text-red-400";

  return (
    <div className="rounded-xl border border-border bg-card p-4 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-muted-foreground text-xs font-medium uppercase tracking-wide">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className={cn("text-2xl font-bold leading-none", color)}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function DisabledBanner({ flag }: { flag?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-4 text-amber-400">
      <AlertTriangle className="h-5 w-5 shrink-0" />
      <div>
        <p className="font-semibold">Portfolio Performance module is disabled</p>
        <p className="text-sm mt-0.5">
          Set <code className="bg-amber-500/20 px-1 rounded">{flag ?? "PORTFOLIO_PERFORMANCE_ENABLED"}=true</code> in environment variables to enable analytics.
        </p>
      </div>
    </div>
  );
}

function ChartCard({ title, children, className }: {
  title: string; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-5", className)}>
      <h3 className="text-sm font-semibold text-foreground mb-4">{title}</h3>
      {children}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PortfolioPerformance() {
  const [equityPeriod, setEquityPeriod] = useState<"daily" | "weekly" | "monthly">("daily");

  const { data: summary, isLoading: sumLoading, refetch: refetchSum } = useQuery<Summary>({
    queryKey: ["performance-summary"],
    queryFn: () => apiJson("performance/summary"),
    refetchInterval: 60_000,
  });

  const { data: equity, isLoading: eqLoading } = useQuery<EquityResponse>({
    queryKey: ["performance-equity", equityPeriod],
    queryFn: () => apiJson(`performance/equity?period=${equityPeriod}`),
    refetchInterval: 60_000,
  });

  const { data: drawdown, isLoading: ddLoading } = useQuery<DrawdownResponse>({
    queryKey: ["performance-drawdown"],
    queryFn: () => apiJson("performance/drawdown"),
    refetchInterval: 60_000,
  });

  const { data: stats, isLoading: stLoading } = useQuery<StatisticsResponse>({
    queryKey: ["performance-statistics"],
    queryFn: () => apiJson("performance/statistics"),
    refetchInterval: 60_000,
  });

  const { data: portfolio } = useQuery<PortfolioResponse>({
    queryKey: ["performance-portfolio"],
    queryFn: () => apiJson("performance/portfolio"),
    refetchInterval: 60_000,
  });

  const isDisabled = summary?.status === "DISABLED";
  const isLoading  = sumLoading || eqLoading || ddLoading || stLoading;

  // ── Derived ────────────────────────────────────────────────────────────────

  const netPnlPositive = (summary?.total_net_pnl ?? 0) >= 0;

  // Equity series formatted for recharts
  const equitySeries = (equity?.series ?? []).map(p => ({
    date: fmtShortTs(p.timestamp),
    equity: p.equity,
    drawdown: p.drawdown,
  }));

  const dailyPnlBars = (equity?.daily_pnl ?? []).slice(-30).map(p => ({
    date: p.date.slice(5),   // MM-DD
    pnl: p.pnl,
  }));

  const monthlyPnlBars = (equity?.monthly_pnl ?? []).map(p => ({
    month: p.month.slice(5),
    pnl: p.pnl,
  }));

  const ddSeries = (drawdown?.series ?? []).map(p => ({
    date: fmtShortTs(p.timestamp),
    drawdown_pct: -(p.drawdown_pct ?? 0),
  }));

  return (
    <div className="p-6 space-y-6 max-w-[1600px]">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <TrendingUp className="h-6 w-6 text-emerald-500" />
            Portfolio Performance
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Read-only analytics · Paper trading only · Advisory only
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground bg-card border border-border px-3 py-1.5 rounded-lg">
            PAPER / ADVISORY ONLY
          </span>
          <button
            onClick={() => refetchSum()}
            disabled={isLoading}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground border border-border rounded-lg px-3 py-1.5 transition-colors"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* ── Disabled banner ── */}
      {isDisabled && <DisabledBanner flag={(summary as any)?.feature_flag} />}

      {!isDisabled && (
        <>
          {/* ── Summary cards ── */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            <SummaryCard
              label="Portfolio Value"
              value={summary ? fmtRs(summary.total_portfolio_value) : "…"}
              sub={summary ? `Initial: ${fmtRs(summary.initial_capital)}` : undefined}
              icon={DollarSign}
              neutral
            />
            <SummaryCard
              label="Today's P&L"
              value={summary ? fmtRs(summary.today_pnl) : "…"}
              sub={summary ? `Weekly: ${fmtRs(summary.weekly_pnl)}` : undefined}
              icon={summary && summary.today_pnl >= 0 ? TrendingUp : TrendingDown}
              positive={summary ? summary.today_pnl >= 0 : undefined}
            />
            <SummaryCard
              label="Net P&L"
              value={summary ? fmtRs(summary.total_net_pnl) : "…"}
              sub={summary ? fmtPct(summary.total_return_pct) : undefined}
              icon={netPnlPositive ? TrendingUp : TrendingDown}
              positive={netPnlPositive}
            />
            <SummaryCard
              label="Win Rate"
              value={summary ? `${fmt(summary.win_rate, 1)}%` : "…"}
              sub={summary ? `${summary.winning_trades}W / ${summary.losing_trades}L` : undefined}
              icon={Percent}
              positive={summary ? summary.win_rate >= 50 : undefined}
            />
            <SummaryCard
              label="Profit Factor"
              value={summary ? fmt(summary.profit_factor, 2) : "…"}
              sub={summary ? `Expectancy: ${fmtRs(summary.expectancy)}` : undefined}
              icon={BarChart3}
              positive={summary ? summary.profit_factor >= 1.5 : undefined}
            />
            <SummaryCard
              label="Max Drawdown"
              value={summary ? fmtRs(summary.max_drawdown) : "…"}
              sub={summary ? `${fmt(summary.max_drawdown_pct, 2)}% · Recovery ${fmt(summary.recovery_pct, 1)}%` : undefined}
              icon={AlertTriangle}
              positive={summary ? summary.max_drawdown_pct < 5 : undefined}
            />
          </div>

          {/* ── Equity curve + period selector ── */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <ChartCard title="Equity Curve" className="xl:col-span-2">
              <div className="flex gap-2 mb-3">
                {(["daily", "weekly", "monthly"] as const).map(p => (
                  <button
                    key={p}
                    onClick={() => setEquityPeriod(p)}
                    className={cn(
                      "text-xs px-3 py-1 rounded-md border transition-colors capitalize",
                      equityPeriod === p
                        ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-400"
                        : "border-border text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={equitySeries} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#10b981" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                  <YAxis
                    tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                    tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                    width={54}
                  />
                  <Tooltip
                    contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [fmtRs(v), "Equity"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="#10b981"
                    strokeWidth={2}
                    fill="url(#eqGrad)"
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </ChartCard>

            {/* Sector allocation pie */}
            <ChartCard title="Sector Allocation">
              {portfolio?.sector_allocation && portfolio.sector_allocation.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={180}>
                    <PieChart>
                      <Pie
                        data={portfolio.sector_allocation}
                        dataKey="value"
                        nameKey="sector"
                        cx="50%"
                        cy="50%"
                        outerRadius={70}
                        strokeWidth={1}
                        stroke="hsl(var(--background))"
                      >
                        {portfolio.sector_allocation.map((_, i) => (
                          <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                        formatter={(v: number, _: string, props: any) => [
                          `${fmtRs(v)} (${fmt(props.payload.pct, 1)}%)`,
                          props.payload.sector,
                        ]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-1.5 mt-2">
                    {portfolio.sector_allocation.map((s, i) => (
                      <div key={s.sector} className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-1.5">
                          <span
                            className="inline-block w-2 h-2 rounded-full"
                            style={{ background: SECTOR_COLORS[i % SECTOR_COLORS.length] }}
                          />
                          <span className="text-muted-foreground">{s.sector}</span>
                        </div>
                        <span className="font-medium">{fmt(s.pct, 1)}%</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="h-[180px] flex items-center justify-center text-muted-foreground text-sm">
                  No open positions
                </div>
              )}
            </ChartCard>
          </div>

          {/* ── Daily P&L + Monthly P&L + Drawdown ── */}
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <ChartCard title="Daily P&L (Last 30 Days)">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={dailyPnlBars} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                  <YAxis
                    tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                    tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                    width={46}
                  />
                  <Tooltip
                    contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [fmtRs(v), "P&L"]}
                  />
                  <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                    {dailyPnlBars.map((b, i) => (
                      <Cell key={i} fill={b.pnl >= 0 ? "#10b981" : "#f43f5e"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Monthly P&L">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={monthlyPnlBars} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }} />
                  <YAxis
                    tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                    tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`}
                    width={46}
                  />
                  <Tooltip
                    contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [fmtRs(v), "P&L"]}
                  />
                  <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                    {monthlyPnlBars.map((b, i) => (
                      <Cell key={i} fill={b.pnl >= 0 ? "#0ea5e9" : "#f43f5e"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Drawdown Curve">
              <div className="flex gap-4 mb-3 text-xs">
                <span className="text-muted-foreground">
                  Max: <span className="text-red-400 font-semibold">
                    {drawdown ? `${fmt(drawdown.max_drawdown_pct, 2)}%` : "…"}
                  </span>
                </span>
                <span className="text-muted-foreground">
                  Current: <span className="text-amber-400 font-semibold">
                    {drawdown ? `${fmt(drawdown.current_drawdown_pct, 2)}%` : "…"}
                  </span>
                </span>
              </div>
              <ResponsiveContainer width="100%" height={148}>
                <AreaChart data={ddSeries} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#f43f5e" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }} />
                  <YAxis
                    tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))" }}
                    tickFormatter={v => `${v.toFixed(1)}%`}
                    width={42}
                  />
                  <Tooltip
                    contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                    formatter={(v: number) => [`${Math.abs(v).toFixed(2)}%`, "Drawdown"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="drawdown_pct"
                    stroke="#f43f5e"
                    strokeWidth={1.5}
                    fill="url(#ddGrad)"
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          {/* ── Performance summary table + Risk metrics ── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {/* Performance summary */}
            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="text-sm font-semibold mb-4">Performance Summary</h3>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2.5 text-sm">
                {[
                  ["Total Trades",     summary?.total_trades?.toString() ?? "—"],
                  ["Open Trades",      summary?.open_trades?.toString() ?? "—"],
                  ["Winning Trades",   summary?.winning_trades?.toString() ?? "—"],
                  ["Losing Trades",    summary?.losing_trades?.toString() ?? "—"],
                  ["Win Rate",         summary ? `${fmt(summary.win_rate, 2)}%` : "—"],
                  ["Avg Winner",       summary ? fmtRs(summary.avg_winner) : "—"],
                  ["Avg Loser",        summary ? fmtRs(summary.avg_loser) : "—"],
                  ["Largest Profit",   summary ? fmtRs(summary.largest_profit) : "—"],
                  ["Largest Loss",     summary ? fmtRs(summary.largest_loss) : "—"],
                  ["Avg Hold Time",    summary ? fmtHolding(summary.avg_holding_seconds) : "—"],
                  ["Realised P&L",     summary ? fmtRs(summary.realised_pnl) : "—"],
                  ["Unrealised P&L",   summary ? fmtRs(summary.unrealised_pnl) : "—"],
                  ["Lifetime P&L",     summary ? fmtRs(summary.lifetime_pnl) : "—"],
                  ["Total Return",     summary ? fmtPct(summary.total_return_pct) : "—"],
                  ["Portfolio Util.",  summary ? `${fmt(summary.portfolio_utilisation_pct, 1)}%` : "—"],
                  ["Profit Factor",    summary ? fmt(summary.profit_factor, 2) : "—"],
                  ["Expectancy",       summary ? fmtRs(summary.expectancy) : "—"],
                  ["Risk/Reward",      summary ? fmt(summary.risk_reward_ratio, 2) : "—"],
                  ["Avg R Multiple",   summary ? fmt(summary.avg_r_multiple, 2) : "—"],
                  ["Max Drawdown %",   summary ? `${fmt(summary.max_drawdown_pct, 2)}%` : "—"],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between items-center border-b border-border/40 pb-1.5">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-medium tabular-nums">{value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Strategy Contribution */}
            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="text-sm font-semibold mb-4">Strategy Contribution</h3>
              {stats?.strategy_contribution && stats.strategy_contribution.length > 0 ? (
                <div className="overflow-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        <th className="text-left pb-2 pr-3">Strategy</th>
                        <th className="text-right pb-2 pr-3">Trades</th>
                        <th className="text-right pb-2 pr-3">Win %</th>
                        <th className="text-right pb-2">Net P&L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.strategy_contribution.map(s => (
                        <tr key={s.strategy_name} className="border-b border-border/40">
                          <td className="py-2 pr-3 font-medium">{s.strategy_name}</td>
                          <td className="py-2 pr-3 text-right tabular-nums">{s.total_trades}</td>
                          <td className="py-2 pr-3 text-right tabular-nums">
                            <Pill green={s.win_rate >= 50}>{fmt(s.win_rate, 1)}%</Pill>
                          </td>
                          <td className={cn("py-2 text-right tabular-nums font-semibold",
                            s.total_pnl >= 0 ? "text-emerald-400" : "text-red-400",
                          )}>
                            {fmtRs(s.total_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-muted-foreground text-sm text-center py-10">No closed trades yet</div>
              )}
            </div>
          </div>

          {/* ── Top Winners / Top Losers ── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {/* Top Winners */}
            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                <Trophy className="h-4 w-4 text-amber-400" />
                Top Winners
              </h3>
              {stats?.top_winners && stats.top_winners.length > 0 ? (
                <div className="overflow-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        <th className="text-left pb-2 pr-3">Symbol</th>
                        <th className="text-right pb-2 pr-3">P&L</th>
                        <th className="text-right pb-2 pr-3">P&L %</th>
                        <th className="text-right pb-2">Hold</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.top_winners.map((t, i) => (
                        <tr key={t.trade_id + i} className="border-b border-border/40">
                          <td className="py-1.5 pr-3 font-medium">{t.symbol}</td>
                          <td className="py-1.5 pr-3 text-right text-emerald-400 font-semibold tabular-nums">
                            {fmtRs(t.pnl)}
                          </td>
                          <td className="py-1.5 pr-3 text-right text-emerald-400 tabular-nums">
                            +{fmt(t.pnl_pct, 2)}%
                          </td>
                          <td className="py-1.5 text-right text-muted-foreground tabular-nums">
                            {fmtHolding(t.holding_seconds)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-muted-foreground text-sm text-center py-10">No winners yet</div>
              )}
            </div>

            {/* Top Losers */}
            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                <Skull className="h-4 w-4 text-red-400" />
                Top Losers
              </h3>
              {stats?.top_losers && stats.top_losers.length > 0 ? (
                <div className="overflow-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted-foreground border-b border-border">
                        <th className="text-left pb-2 pr-3">Symbol</th>
                        <th className="text-right pb-2 pr-3">P&L</th>
                        <th className="text-right pb-2 pr-3">P&L %</th>
                        <th className="text-right pb-2">Hold</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.top_losers.map((t, i) => (
                        <tr key={t.trade_id + i} className="border-b border-border/40">
                          <td className="py-1.5 pr-3 font-medium">{t.symbol}</td>
                          <td className="py-1.5 pr-3 text-right text-red-400 font-semibold tabular-nums">
                            {fmtRs(t.pnl)}
                          </td>
                          <td className="py-1.5 pr-3 text-right text-red-400 tabular-nums">
                            {fmt(t.pnl_pct, 2)}%
                          </td>
                          <td className="py-1.5 text-right text-muted-foreground tabular-nums">
                            {fmtHolding(t.holding_seconds)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-muted-foreground text-sm text-center py-10">No losers yet</div>
              )}
            </div>
          </div>

          {/* ── Open positions table ── */}
          {portfolio?.open_positions && portfolio.open_positions.length > 0 && (
            <div className="rounded-xl border border-border bg-card p-5">
              <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
                <Layers className="h-4 w-4 text-sky-400" />
                Open Positions
                <span className="ml-auto text-xs text-muted-foreground font-normal">
                  Utilisation: {fmt(portfolio.utilisation_pct, 1)}% · Invested: {fmtRs(portfolio.invested)}
                </span>
              </h3>
              <div className="overflow-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-muted-foreground border-b border-border">
                      <th className="text-left pb-2 pr-3">Symbol</th>
                      <th className="text-left pb-2 pr-3">Sector</th>
                      <th className="text-right pb-2 pr-3">Qty</th>
                      <th className="text-right pb-2 pr-3">Avg Cost</th>
                      <th className="text-right pb-2 pr-3">Cur. Value</th>
                      <th className="text-right pb-2 pr-3">Unreal. P&L</th>
                      <th className="text-right pb-2">Weight</th>
                    </tr>
                  </thead>
                  <tbody>
                    {portfolio.open_positions.map(pos => (
                      <tr key={pos.symbol} className="border-b border-border/40">
                        <td className="py-2 pr-3 font-semibold">{pos.symbol}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{pos.sector}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{pos.quantity}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{fmtRs(pos.avg_cost)}</td>
                        <td className="py-2 pr-3 text-right tabular-nums">{fmtRs(pos.current_value)}</td>
                        <td className={cn("py-2 pr-3 text-right tabular-nums font-medium",
                          pos.unrealised_pnl >= 0 ? "text-emerald-400" : "text-red-400",
                        )}>
                          {fmtRs(pos.unrealised_pnl)}
                          <span className="text-xs ml-1">
                            ({pos.unrealised_pnl >= 0 ? "+" : ""}{fmt(pos.unrealised_pnl_pct, 2)}%)
                          </span>
                        </td>
                        <td className="py-2 text-right tabular-nums text-muted-foreground">
                          {fmt(pos.weight_pct, 1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
