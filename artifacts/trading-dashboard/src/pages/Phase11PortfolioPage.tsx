/**
 * Phase11PortfolioPage — Autonomous Paper Trading Portfolio
 * Displays: Cash, Invested, Buying Power, Current Value, Realised/Unrealised P/L,
 * Portfolio Return, Drawdown, Open Positions table, Closed Positions table,
 * Sector Allocation, Risk Score.
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
  Wallet, TrendingUp, TrendingDown, BarChart2, RefreshCw,
  Target, ShieldAlert, Clock, BookOpen, ChevronDown, ChevronUp,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Portfolio {
  starting_capital: number; cash: number; invested_amount: number;
  buying_power: number; current_value: number;
  realised_pnl: number; unrealised_pnl: number; total_pnl: number;
  portfolio_return: number; daily_pnl: number; daily_return: number;
  drawdown_pct: number; open_positions: number;
  capital_mode: string; capital_mode_label: string;
  paper_only: boolean; advisory_only: boolean; as_of: string;
}

interface OpenPosition {
  stock: string; buy_time: string; buy_price: number; current_price: number;
  quantity: number; current_value: number; current_pnl: number;
  current_pnl_pct: number; ai_confidence: number;
  expected_return_entry: number; expected_return_current: number;
  target: number; stop_loss: number; strategy: string;
  market_regime: string; risk_level: string; holding_label: string;
}

interface ClosedPosition {
  symbol: string; buy_time: string; sell_time: string;
  entry_price: number; exit_price: number; quantity: number;
  pnl: number; pnl_pct: number; holding_label: string;
  exit_reason: string; ai_confidence: number; strategy: string; lesson_learned: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number, d = 0) {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}
function pnlClass(v: number) { return v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400"; }
function istDate(s: string) {
  try { return new Date(s).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }); }
  catch { return s ?? "—"; }
}

function KpiCard({ label, value, sub, icon: Icon, highlight = false }:
  { label: string; value: string; sub?: string; icon: React.ElementType; highlight?: boolean }) {
  return (
    <div className={`rounded-xl p-4 border ${highlight ? "bg-teal-950/30 border-teal-700/40" : "bg-slate-900/60 border-slate-800/40"}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-slate-500 font-medium">{label}</span>
        <Icon className={`w-4 h-4 ${highlight ? "text-teal-400" : "text-slate-600"}`} />
      </div>
      <p className={`text-xl font-bold font-mono ${highlight ? "text-teal-300" : "text-slate-100"}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const cls = level === "LOW" ? "bg-emerald-900/50 text-emerald-300 border-emerald-700/50"
    : level === "HIGH" ? "bg-rose-900/50 text-rose-300 border-rose-700/50"
    : "bg-amber-900/50 text-amber-300 border-amber-700/50";
  return <Badge className={`text-xs ${cls}`}>{level}</Badge>;
}

function RegimeBadge({ regime }: { regime: string }) {
  const cls = regime.includes("TREND") ? "bg-teal-900/50 text-teal-300 border-teal-700/50"
    : regime.includes("RANGE") ? "bg-blue-900/50 text-blue-300 border-blue-700/50"
    : "bg-slate-700/50 text-slate-300 border-slate-600/50";
  return <Badge className={`text-xs ${cls}`}>{regime}</Badge>;
}

// ── Open Positions Table ──────────────────────────────────────────────────────

function OpenPositionsTable({ positions, loading }: { positions: OpenPosition[]; loading: boolean }) {
  if (loading) return <Skeleton className="h-40 rounded-xl" />;
  if (!positions.length) return (
    <div className="text-center py-10 text-slate-500 text-sm">No open positions</div>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-slate-500 border-b border-slate-800">
            {["Stock","Buy Time","Buy Price","Current","Qty","Value","P/L","P/L%","Confidence","Exp.Return","Target","Stop","Strategy","Regime","Risk","Held"].map(h => (
              <th key={h} className="text-left py-2 px-2 whitespace-nowrap font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <tr key={pos.stock} className="border-b border-slate-800/40 hover:bg-slate-800/20 transition-colors">
              <td className="py-2 px-2 font-semibold text-slate-200 whitespace-nowrap">{pos.stock}</td>
              <td className="py-2 px-2 text-slate-400 text-xs whitespace-nowrap">{istDate(pos.buy_time)}</td>
              <td className="py-2 px-2 font-mono">₹{fmt(pos.buy_price)}</td>
              <td className="py-2 px-2 font-mono">₹{fmt(pos.current_price)}</td>
              <td className="py-2 px-2 text-slate-300">{pos.quantity}</td>
              <td className="py-2 px-2 font-mono">₹{fmt(pos.current_value)}</td>
              <td className={`py-2 px-2 font-mono font-bold ${pnlClass(pos.current_pnl)}`}>
                {pos.current_pnl >= 0 ? "+" : ""}₹{fmt(pos.current_pnl)}
              </td>
              <td className={`py-2 px-2 font-mono ${pnlClass(pos.current_pnl_pct)}`}>
                {pos.current_pnl_pct >= 0 ? "+" : ""}{fmt(pos.current_pnl_pct, 2)}%
              </td>
              <td className="py-2 px-2">
                <div className="flex items-center gap-1">
                  <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-teal-500 rounded-full" style={{ width: `${Math.min(100, pos.ai_confidence)}%` }} />
                  </div>
                  <span className="text-xs text-slate-400 tabular-nums">{fmt(pos.ai_confidence, 0)}%</span>
                </div>
              </td>
              <td className={`py-2 px-2 font-mono text-xs ${pnlClass(pos.expected_return_current)}`}>
                {pos.expected_return_current >= 0 ? "+" : ""}{fmt(pos.expected_return_current, 1)}%
              </td>
              <td className="py-2 px-2 font-mono text-emerald-400 text-xs">₹{fmt(pos.target)}</td>
              <td className="py-2 px-2 font-mono text-rose-400 text-xs">₹{fmt(pos.stop_loss)}</td>
              <td className="py-2 px-2 text-slate-400 text-xs whitespace-nowrap">{pos.strategy}</td>
              <td className="py-2 px-2"><RegimeBadge regime={pos.market_regime} /></td>
              <td className="py-2 px-2"><RiskBadge level={pos.risk_level} /></td>
              <td className="py-2 px-2 text-slate-400 text-xs whitespace-nowrap">
                <Clock className="w-3 h-3 inline mr-1 opacity-50" />{pos.holding_label}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Closed Positions Table ────────────────────────────────────────────────────

function ClosedPositionsTable({ positions, loading }: { positions: ClosedPosition[]; loading: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (loading) return <Skeleton className="h-40 rounded-xl" />;
  if (!positions.length) return (
    <div className="text-center py-10 text-slate-500 text-sm">No closed positions yet</div>
  );

  return (
    <div className="space-y-2">
      {positions.map((pos, i) => {
        const isExp = expanded === `${pos.symbol}-${i}`;
        return (
          <div key={i} className={`rounded-lg border transition-colors ${pos.pnl >= 0 ? "border-emerald-800/30 bg-emerald-950/10" : "border-rose-800/30 bg-rose-950/10"}`}>
            <button
              className="w-full flex items-center gap-3 px-4 py-3 text-left"
              onClick={() => setExpanded(isExp ? null : `${pos.symbol}-${i}`)}
            >
              <div className="flex-1 flex items-center gap-3 flex-wrap">
                <span className="font-semibold text-slate-200 w-20">{pos.symbol}</span>
                <span className="text-xs text-slate-500">{pos.strategy}</span>
                <Badge className="text-xs bg-slate-700/50 text-slate-300 border-slate-600/50">{pos.exit_reason?.replace(/_/g, " ")}</Badge>
              </div>
              <div className="flex items-center gap-4">
                <span className={`font-mono font-bold ${pnlClass(pos.pnl)}`}>
                  {pos.pnl >= 0 ? "+" : ""}₹{fmt(pos.pnl)}
                </span>
                <span className={`font-mono text-sm ${pnlClass(pos.pnl_pct)}`}>
                  {pos.pnl_pct >= 0 ? "+" : ""}{fmt(pos.pnl_pct, 2)}%
                </span>
                {isExp ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
              </div>
            </button>
            {isExp && (
              <div className="px-4 pb-3 border-t border-slate-800/40 pt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                <div><p className="text-slate-500">Buy Time</p><p className="text-slate-300">{istDate(pos.buy_time)}</p></div>
                <div><p className="text-slate-500">Sell Time</p><p className="text-slate-300">{istDate(pos.sell_time)}</p></div>
                <div><p className="text-slate-500">Entry Price</p><p className="font-mono text-slate-200">₹{fmt(pos.entry_price)}</p></div>
                <div><p className="text-slate-500">Exit Price</p><p className="font-mono text-slate-200">₹{fmt(pos.exit_price)}</p></div>
                <div><p className="text-slate-500">Quantity</p><p className="text-slate-200">{pos.quantity}</p></div>
                <div><p className="text-slate-500">Held</p><p className="text-slate-200">{pos.holding_label}</p></div>
                <div><p className="text-slate-500">AI Confidence</p><p className="text-slate-200">{fmt(pos.ai_confidence, 0)}%</p></div>
                <div><p className="text-slate-500">Strategy</p><p className="text-slate-200">{pos.strategy}</p></div>
                {pos.lesson_learned && (
                  <div className="col-span-4 bg-slate-800/40 rounded p-2">
                    <p className="text-amber-400 font-semibold mb-0.5 flex items-center gap-1">
                      <BookOpen className="w-3 h-3" /> Lesson
                    </p>
                    <p className="text-slate-300">{pos.lesson_learned}</p>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Phase11PortfolioPage() {
  const [tab, setTab] = useState<"open" | "closed">("open");

  const portQ = useQuery({
    queryKey: ["phase11", "portfolio"],
    queryFn:  () => apiJson<Portfolio>("/phase11/portfolio"),
    refetchInterval: 60_000,
  });

  const openQ = useQuery({
    queryKey: ["phase11", "open-positions"],
    queryFn:  () => apiJson<OpenPosition[]>("/phase11/portfolio/open-positions"),
    refetchInterval: 60_000,
  });

  const closedQ = useQuery({
    queryKey: ["phase11", "closed-positions"],
    queryFn:  () => apiJson<ClosedPosition[]>("/phase11/portfolio/closed-positions"),
    staleTime: 60_000,
  });

  const p = portQ.data;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3">
          <Wallet className="w-6 h-6 text-teal-400 shrink-0" />
          <div>
            <h1 className="text-2xl font-bold">Paper Portfolio</h1>
            <p className="text-slate-500 text-sm">
              {p ? `${p.capital_mode_label} · Starting capital ₹${fmt(p.starting_capital)}` : "Loading…"}
            </p>
          </div>
          <div className="ml-auto flex gap-2">
            <Badge className="bg-teal-900/50 text-teal-300 border-teal-700/50">PAPER ONLY</Badge>
            <Button variant="ghost" size="sm" onClick={() => { portQ.refetch(); openQ.refetch(); closedQ.refetch(); }} className="text-slate-500 hover:text-slate-200">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* KPI bar */}
        {portQ.isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[1,2,3,4,5,6,7,8].map(i => <Skeleton key={i} className="h-20 rounded-xl" />)}
          </div>
        ) : p && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard icon={Wallet} label="Portfolio Value" value={`₹${fmt(p.current_value)}`} highlight
                sub={`${p.portfolio_return >= 0 ? "+" : ""}${fmt(p.portfolio_return, 2)}% return`} />
              <KpiCard icon={BarChart2} label="Cash" value={`₹${fmt(p.cash)}`}
                sub={`Buying power: ₹${fmt(p.buying_power)}`} />
              <KpiCard icon={TrendingUp} label="Today's P/L" value={`${p.daily_pnl >= 0 ? "+" : ""}₹${fmt(p.daily_pnl)}`}
                sub={`${p.daily_return >= 0 ? "+" : ""}${fmt(p.daily_return, 2)}%`} />
              <KpiCard icon={p.drawdown_pct > 5 ? ShieldAlert : TrendingDown} label="Drawdown"
                value={`${fmt(p.drawdown_pct, 2)}%`} sub="from peak" />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard icon={BarChart2} label="Invested" value={`₹${fmt(p.invested_amount)}`}
                sub={`${p.open_positions} open position${p.open_positions !== 1 ? "s" : ""}`} />
              <KpiCard icon={TrendingUp} label="Unrealised P/L" value={`${p.unrealised_pnl >= 0 ? "+" : ""}₹${fmt(p.unrealised_pnl)}`} />
              <KpiCard icon={TrendingUp} label="Realised P/L" value={`${p.realised_pnl >= 0 ? "+" : ""}₹${fmt(p.realised_pnl)}`} />
              <KpiCard icon={TrendingUp} label="Total P/L" value={`${p.total_pnl >= 0 ? "+" : ""}₹${fmt(p.total_pnl)}`}
                highlight={p.total_pnl > 0} />
            </div>
          </>
        )}

        {/* Positions tabs */}
        <Card className="bg-slate-900/60 border-slate-800/40">
          <CardHeader className="pb-0">
            <div className="flex items-center gap-4">
              <button
                className={`text-sm font-semibold pb-2 border-b-2 transition-colors ${tab === "open" ? "border-teal-400 text-teal-300" : "border-transparent text-slate-500 hover:text-slate-300"}`}
                onClick={() => setTab("open")}
              >
                Open Positions ({openQ.data?.length ?? 0})
              </button>
              <button
                className={`text-sm font-semibold pb-2 border-b-2 transition-colors ${tab === "closed" ? "border-teal-400 text-teal-300" : "border-transparent text-slate-500 hover:text-slate-300"}`}
                onClick={() => setTab("closed")}
              >
                Closed Positions ({closedQ.data?.length ?? 0})
              </button>
            </div>
          </CardHeader>
          <CardContent className="pt-4">
            {tab === "open"
              ? <OpenPositionsTable positions={openQ.data ?? []} loading={openQ.isLoading} />
              : <ClosedPositionsTable positions={closedQ.data ?? []} loading={closedQ.isLoading} />
            }
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
