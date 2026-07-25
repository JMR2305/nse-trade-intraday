import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  BarChart2,
  AlertTriangle,
  CheckCircle2,
  RefreshCcw,
  Activity,
  DollarSign,
  PieChart,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface OpenPosition {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  last_price: number;
  market_value: number;
  unrealised_pnl: number;
  unrealised_pnl_pct: number;
  side: string;
  strategy_id?: string | null;
  sector?: string | null;
  opened_at?: string | null;
}

interface PortfolioSnapshot {
  status: string;
  paper_mode: boolean;
  snapshotted_at: string;
  equity: number;
  cash: number;
  buying_power: number;
  invested_value: number;
  initial_capital: number;
  unrealised_pnl: number;
  realised_pnl_today: number;
  total_pnl: number;
  peak_equity: number;
  drawdown_amount: number;
  drawdown_pct: number;
  open_positions: OpenPosition[];
  open_position_count: number;
  closed_positions_today: number;
}

interface PortfolioHealth {
  status: string;
  initialized: boolean;
  paper_mode: boolean;
  auto_paper_enabled: boolean;
  liveness: boolean;
  readiness: boolean;
  degraded: boolean;
  failure_reason?: string | null;
  unresolved_discrepancies: number;
  state_freshness_s?: number | null;
  checked_at: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL = 15_000; // 15 s

const rupee = (n: number | undefined | null) =>
  `₹${Number(n ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const pct = (n: number | undefined | null, digits = 2) => {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  const v = Number(n);
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
};

const pnlColor = (v: number | undefined | null) => {
  const n = Number(v ?? 0);
  if (n > 0) return "text-green-400";
  if (n < 0) return "text-red-400";
  return "text-muted-foreground";
};

const statusConfig: Record<string, { color: string; icon: typeof CheckCircle2; label: string }> = {
  HEALTHY:   { color: "text-green-400 border-green-500/40 bg-green-500/10",   icon: CheckCircle2,  label: "HEALTHY"   },
  READY:     { color: "text-green-400 border-green-500/40 bg-green-500/10",   icon: CheckCircle2,  label: "READY"     },
  DEGRADED:  { color: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10", icon: AlertTriangle, label: "DEGRADED"  },
  HALTED:    { color: "text-red-400 border-red-500/40 bg-red-500/10",         icon: AlertTriangle, label: "HALTED"    },
  DOWN:      { color: "text-red-400 border-red-500/40 bg-red-500/10",         icon: AlertTriangle, label: "DOWN"      },
  UNKNOWN:   { color: "text-slate-400 border-slate-500/40 bg-slate-500/10",   icon: Activity,      label: "UNKNOWN"   },
  DISABLED:  { color: "text-slate-400 border-slate-500/40 bg-slate-500/10",   icon: Activity,      label: "DISABLED"  },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = statusConfig[status] ?? statusConfig.UNKNOWN;
  const Icon = cfg.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs font-mono font-bold ${cfg.color}`}
      data-testid="badge-portfolio-status"
    >
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

function StatCard({
  label,
  value,
  sub,
  valueClass,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
  icon?: typeof DollarSign;
}) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4 space-y-1">
        <div className="flex items-center gap-1.5 text-xs font-mono uppercase text-muted-foreground tracking-wider">
          {Icon && <Icon className="h-3 w-3" />}
          {label}
        </div>
        <div className={`text-xl font-bold font-mono ${valueClass ?? ""}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function DrawdownBar({ pct: drawdownPct }: { pct: number }) {
  const w = Math.max(0, Math.min(100, drawdownPct));
  const color =
    w < 5 ? "bg-green-500" :
    w < 10 ? "bg-yellow-500" :
    "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-border/60 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${w}%` }} />
      </div>
      <span className={`text-xs font-mono ${w >= 10 ? "text-red-400" : w >= 5 ? "text-yellow-400" : "text-green-400"}`}>
        {w.toFixed(1)}%
      </span>
    </div>
  );
}

function PositionRow({ pos }: { pos: OpenPosition }) {
  const upnl = pos.unrealised_pnl;
  return (
    <tr
      className="border-b border-border/40 hover:bg-accent/20 transition-colors"
      data-testid={`row-position-${pos.symbol}`}
    >
      <td className="px-3 py-2.5 font-mono font-bold text-sm">{pos.symbol}</td>
      <td className="px-3 py-2.5 text-muted-foreground text-xs">{pos.sector ?? "—"}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{pos.quantity}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{rupee(pos.avg_entry_price)}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{rupee(pos.last_price)}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{rupee(pos.market_value)}</td>
      <td className={`px-3 py-2.5 font-mono text-right text-sm ${pnlColor(upnl)}`}>
        {upnl >= 0 ? "+" : ""}
        {rupee(upnl)}
      </td>
      <td className={`px-3 py-2.5 font-mono text-right text-sm ${pnlColor(upnl)}`}>
        {pct(pos.unrealised_pnl_pct)}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">{pos.strategy_id ?? "—"}</td>
    </tr>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortfolioLive() {
  const snapshotQuery = useQuery<PortfolioSnapshot>({
    queryKey: ["portfolio-snapshot"],
    queryFn: () => apiJson("/portfolio/snapshot"),
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
  });

  const healthQuery = useQuery<PortfolioHealth>({
    queryKey: ["portfolio-health"],
    queryFn: () => apiJson("/portfolio/health"),
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
  });

  // Countdown to next refresh
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const snap = snapshotQuery.data;
  const health = healthQuery.data;
  const isLoading = snapshotQuery.isLoading && !snap;
  const isFetching = snapshotQuery.isFetching || healthQuery.isFetching;
  const error = snapshotQuery.error as Error | null;

  const overallStatus = health?.status ?? snap?.status ?? "UNKNOWN";
  const isAlert = overallStatus === "DEGRADED" || overallStatus === "HALTED" || overallStatus === "DOWN";

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">LOADING PORTFOLIO…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full" data-testid="page-portfolio-live">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold font-mono flex items-center gap-2">
            <PieChart className="h-6 w-6 text-primary" />
            PORTFOLIO
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Live equity, positions, and P&amp;L — paper trading only.
            Refreshes every {REFRESH_INTERVAL / 1000}s.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={overallStatus} />
          <button
            onClick={() => {
              snapshotQuery.refetch();
              healthQuery.refetch();
            }}
            disabled={isFetching}
            className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-mono hover:bg-accent disabled:opacity-50"
            data-testid="button-refresh-portfolio"
          >
            <RefreshCcw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            {isFetching ? "REFRESHING…" : "REFRESH"}
          </button>
        </div>
      </div>

      {/* Snapshot timestamp */}
      {snap?.snapshotted_at && (
        <div className="text-xs font-mono text-muted-foreground" data-testid="text-snapshot-ts">
          Snapshot:{" "}
          {new Date(snap.snapshotted_at).toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
          {snap.paper_mode && (
            <span className="ml-2 rounded border border-blue-500/40 bg-blue-500/10 px-1.5 py-0.5 text-blue-400">
              PAPER
            </span>
          )}
        </div>
      )}

      {/* ── Alert banner for DEGRADED / HALTED ─────────────────────────── */}
      {isAlert && (
        <div
          className="flex items-start gap-3 rounded-md border border-red-500/40 bg-red-500/10 p-4"
          data-testid="banner-portfolio-alert"
        >
          <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-mono font-bold text-red-400 text-sm">
              Portfolio status: {overallStatus}
            </p>
            {health?.failure_reason && (
              <p className="text-sm text-muted-foreground mt-1">{health.failure_reason}</p>
            )}
            {(health?.unresolved_discrepancies ?? 0) > 0 && (
              <p className="text-sm text-muted-foreground mt-1">
                {health!.unresolved_discrepancies} unresolved reconciliation discrepanc
                {health!.unresolved_discrepancies === 1 ? "y" : "ies"} — check Automation Health.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && !snap && (
        <div className="flex items-start gap-3 rounded-md border border-yellow-500/40 bg-yellow-500/10 p-4">
          <AlertTriangle className="h-5 w-5 text-yellow-400 flex-shrink-0" />
          <p className="text-sm text-yellow-400">{error.message}</p>
        </div>
      )}

      {/* ── Summary stat cards ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard
          label="Equity"
          value={rupee(snap?.equity)}
          sub={snap ? `started at ${rupee(snap.initial_capital)}` : undefined}
          icon={DollarSign}
          data-testid="stat-equity"
        />
        <StatCard
          label="Cash / Buying Power"
          value={rupee(snap?.cash)}
          sub={`invested ${rupee(snap?.invested_value)}`}
          icon={Wallet}
          data-testid="stat-cash"
        />
        <StatCard
          label="Unrealised P&L"
          value={snap ? `${snap.unrealised_pnl >= 0 ? "+" : ""}${rupee(snap.unrealised_pnl)}` : "—"}
          valueClass={pnlColor(snap?.unrealised_pnl)}
          sub={snap ? pct(snap.unrealised_pnl / Math.max(snap.invested_value, 1) * 100) + " of invested" : undefined}
          icon={snap && snap.unrealised_pnl >= 0 ? TrendingUp : TrendingDown}
          data-testid="stat-unrealised-pnl"
        />
        <StatCard
          label="Realised P&L Today"
          value={snap ? `${snap.realised_pnl_today >= 0 ? "+" : ""}${rupee(snap.realised_pnl_today)}` : "—"}
          valueClass={pnlColor(snap?.realised_pnl_today)}
          sub={snap ? `${snap.closed_positions_today} position${snap.closed_positions_today !== 1 ? "s" : ""} closed` : undefined}
          icon={BarChart2}
          data-testid="stat-realised-pnl"
        />
        <StatCard
          label="Drawdown"
          value={snap ? `-${rupee(snap.drawdown_amount)}` : "—"}
          sub={snap ? `${snap.drawdown_pct.toFixed(1)}% from peak ${rupee(snap.peak_equity)}` : undefined}
          valueClass={
            (snap?.drawdown_pct ?? 0) >= 10
              ? "text-red-400"
              : (snap?.drawdown_pct ?? 0) >= 5
              ? "text-yellow-400"
              : "text-green-400"
          }
          icon={TrendingDown}
          data-testid="stat-drawdown"
        />
      </div>

      {/* ── Drawdown visual bar ─────────────────────────────────────────── */}
      {snap && (
        <Card className="bg-card/50 border-border/50">
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between text-xs font-mono text-muted-foreground uppercase tracking-wider">
              <span>Drawdown from Peak</span>
              <span>
                {rupee(snap.equity)} / {rupee(snap.peak_equity)} peak
              </span>
            </div>
            <DrawdownBar pct={snap.drawdown_pct} />
          </CardContent>
        </Card>
      )}

      {/* ── Open Positions ──────────────────────────────────────────────── */}
      <Card className="bg-card/50 border-border/50">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-mono uppercase tracking-widest text-muted-foreground flex items-center justify-between">
            <span>Open Positions</span>
            <span className="text-foreground font-bold" data-testid="count-open-positions">
              {snap?.open_position_count ?? 0}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {!snap || snap.open_positions.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground font-mono">
              NO OPEN POSITIONS
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="table-positions">
                <thead>
                  <tr className="border-b border-border/60 text-xs font-mono text-muted-foreground uppercase">
                    <th className="px-3 py-2 text-left">Symbol</th>
                    <th className="px-3 py-2 text-left">Sector</th>
                    <th className="px-3 py-2 text-right">Qty</th>
                    <th className="px-3 py-2 text-right">Avg Price</th>
                    <th className="px-3 py-2 text-right">LTP</th>
                    <th className="px-3 py-2 text-right">Market Value</th>
                    <th className="px-3 py-2 text-right">Unreal. P&L</th>
                    <th className="px-3 py-2 text-right">P&L %</th>
                    <th className="px-3 py-2 text-left">Strategy</th>
                  </tr>
                </thead>
                <tbody>
                  {snap.open_positions.map((pos) => (
                    <PositionRow key={pos.symbol} pos={pos} />
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-border/60 bg-card/30 font-mono text-sm">
                    <td className="px-3 py-2.5 text-muted-foreground font-bold" colSpan={5}>
                      TOTAL
                    </td>
                    <td className="px-3 py-2.5 text-right font-bold">
                      {rupee(snap.invested_value)}
                    </td>
                    <td
                      className={`px-3 py-2.5 text-right font-bold ${pnlColor(snap.unrealised_pnl)}`}
                    >
                      {snap.unrealised_pnl >= 0 ? "+" : ""}
                      {rupee(snap.unrealised_pnl)}
                    </td>
                    <td className="px-3 py-2.5 text-right" />
                    <td className="px-3 py-2.5" />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Health details ──────────────────────────────────────────────── */}
      <Card className="bg-card/50 border-border/50">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-mono uppercase tracking-widest text-muted-foreground">
            Portfolio Health
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {!health ? (
            <p className="text-sm text-muted-foreground font-mono">Loading health…</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              {(
                [
                  ["Initialized",         health.initialized],
                  ["Liveness",            health.liveness],
                  ["Readiness",           health.readiness],
                  ["Auto-Paper Enabled",  health.auto_paper_enabled],
                ] as [string, boolean][]
              ).map(([label, val]) => (
                <div key={label} className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 rounded-full flex-shrink-0 ${val ? "bg-green-500" : "bg-red-500"}`}
                  />
                  <span className="text-xs text-muted-foreground font-mono">{label}</span>
                  <span className={`text-xs font-mono ml-auto ${val ? "text-green-400" : "text-red-400"}`}>
                    {val ? "YES" : "NO"}
                  </span>
                </div>
              ))}
              {health.unresolved_discrepancies > 0 && (
                <div className="flex items-center gap-2 col-span-2 md:col-span-4">
                  <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 flex-shrink-0" />
                  <span className="text-xs text-yellow-400 font-mono">
                    {health.unresolved_discrepancies} unresolved discrepanc
                    {health.unresolved_discrepancies === 1 ? "y" : "ies"}
                  </span>
                </div>
              )}
              {health.state_freshness_s != null && (
                <div className="col-span-2 md:col-span-4 text-xs text-muted-foreground font-mono">
                  State age: {health.state_freshness_s.toFixed(0)}s
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
