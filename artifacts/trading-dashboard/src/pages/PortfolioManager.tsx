import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetPortfolioManager,
  getGetPortfolioManagerQueryKey,
  getPortfolioManager,
} from "@workspace/api-client-react";
import type {
  PortfolioHolding,
  PortfolioNewBuy,
  PortfolioSkipped,
} from "@workspace/api-client-react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Briefcase,
  RefreshCcw,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Scale,
  Info,
} from "lucide-react";

const ACTION_STYLE: Record<string, string> = {
  BUY:       "text-green-400 bg-green-500/10 border-green-500/30",
  INCREASE:  "text-emerald-300 bg-emerald-500/15 border-emerald-500/40",
  HOLD:      "text-blue-300 bg-blue-500/10 border-blue-500/30",
  REDUCE:    "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  EXIT:      "text-orange-400 bg-orange-500/10 border-orange-500/30",
  HOLD_CASH: "text-slate-300 bg-slate-500/10 border-slate-500/30",
};

const STANCE_STYLE: Record<string, string> = {
  DEPLOY:    "text-green-400 border-green-500/40 bg-green-500/10",
  HOLD:      "text-blue-300 border-blue-500/40 bg-blue-500/10",
  HOLD_CASH: "text-slate-300 border-slate-500/40 bg-slate-500/10",
};

function ActionBadge({ action }: { action: string }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-[11px] font-mono font-bold whitespace-nowrap ${
        ACTION_STYLE[action] ?? ACTION_STYLE.HOLD
      }`}
      data-testid={`badge-action-${action.toLowerCase()}`}
    >
      {action.replace("_", " ")}
    </span>
  );
}

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">
          {label}
        </div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
      </CardContent>
    </Card>
  );
}

const rupee = (n: number | undefined) =>
  `₹${Number(n ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

const pct = (n: number | undefined, digits = 1) =>
  n === undefined || n === null || Number.isNaN(n) ? "—" : `${Number(n).toFixed(digits)}%`;

function GaugeBar({ value, max = 100, color }: { value: number; max?: number; color: string }) {
  const w = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-2 w-full rounded-full bg-border/60 overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${w}%` }} />
    </div>
  );
}

function NewBuyRow({ b }: { b: PortfolioNewBuy }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        className="border-b border-border/40 hover:bg-accent/30 cursor-pointer"
        onClick={() => setOpen(!open)}
        data-testid={`row-newbuy-${b.symbol}`}
      >
        <td className="px-3 py-2 font-mono font-bold">
          <span className="flex items-center gap-1">
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {b.symbol}
          </span>
        </td>
        <td className="px-3 py-2 text-muted-foreground">{b.sector}</td>
        <td className="px-3 py-2 font-mono text-right">{rupee(b.price)}</td>
        <td className="px-3 py-2 font-mono text-right">{b.shares}</td>
        <td className="px-3 py-2 font-mono text-right">{rupee(b.allocation)}</td>
        <td className="px-3 py-2 font-mono text-right">{pct(b.weight_pct)}</td>
        <td className="px-3 py-2 font-mono text-right text-primary">{b.score.toFixed(0)}</td>
        <td className="px-3 py-2 font-mono text-right">{b.confidence.toFixed(0)}</td>
        <td className="px-3 py-2 font-mono text-right">
          {b.expectancy !== undefined ? `${b.expectancy > 0 ? "+" : ""}${b.expectancy.toFixed(2)}%` : "—"}
        </td>
        <td className="px-3 py-2 font-mono text-right text-muted-foreground">
          {b.stop_loss ? rupee(b.stop_loss) : "—"} / {b.target ? rupee(b.target) : "—"}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border/40 bg-accent/10">
          <td colSpan={10} className="px-4 py-3 text-sm text-muted-foreground">
            <div className="flex gap-2 items-start">
              <Info className="h-4 w-4 mt-0.5 flex-shrink-0 text-primary" />
              <p className="leading-relaxed">{b.rationale}</p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function SkippedRow({ s }: { s: PortfolioSkipped }) {
  return (
    <tr className="border-b border-border/30" data-testid={`row-skipped-${s.symbol}`}>
      <td className="px-3 py-2 font-mono font-bold text-muted-foreground">{s.symbol}</td>
      <td className="px-3 py-2 text-muted-foreground">{s.sector}</td>
      <td className="px-3 py-2 font-mono text-right">{s.score.toFixed(0)}</td>
      <td className="px-3 py-2 text-muted-foreground text-sm">{s.reason}</td>
    </tr>
  );
}

function HoldingRow({ h }: { h: PortfolioHolding }) {
  return (
    <tr className="border-b border-border/40" data-testid={`row-holding-${h.symbol}`}>
      <td className="px-3 py-2 font-mono font-bold">{h.symbol}</td>
      <td className="px-3 py-2 text-muted-foreground">{h.sector}</td>
      <td className="px-3 py-2 font-mono text-right">{h.quantity}</td>
      <td className="px-3 py-2 font-mono text-right">{rupee(h.avg_price)}</td>
      <td className="px-3 py-2 font-mono text-right">{rupee(h.current_price)}</td>
      <td className="px-3 py-2 font-mono text-right">{rupee(h.value)}</td>
      <td className="px-3 py-2 font-mono text-right">{pct(h.weight_pct)}</td>
      <td
        className={`px-3 py-2 font-mono text-right ${
          h.pnl_pct >= 0 ? "text-green-400" : "text-red-400"
        }`}
      >
        {h.pnl_pct >= 0 ? "+" : ""}
        {h.pnl_pct.toFixed(2)}%
      </td>
      <td className="px-3 py-2 text-center">
        <ActionBadge action={h.action} />
      </td>
      <td className="px-3 py-2 text-sm text-muted-foreground max-w-md">{h.action_reason}</td>
    </tr>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-sm font-mono font-bold uppercase tracking-widest text-muted-foreground">
      {children}
    </h2>
  );
}

export default function PortfolioManager() {
  const queryClient = useQueryClient();
  const { data, isLoading, isFetching } = useGetPortfolioManager(
    undefined,
    { query: { queryKey: getGetPortfolioManagerQueryKey() } },
  );
  const [showComparisons, setShowComparisons] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const busy = isFetching || refreshing;

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const fresh = await getPortfolioManager({ refresh: "true" });
      queryClient.setQueryData(getGetPortfolioManagerQueryKey(), fresh);
    } catch {
      // keep showing the last good data on failure
    } finally {
      setRefreshing(false);
    }
  };

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">
            BUILDING PORTFOLIO DECISION... (~30s)
          </p>
        </div>
      </div>
    );
  }

  const m = data?.metrics;
  const perf = data?.allocation_performance;
  const stance = data?.stance ?? "HOLD_CASH";

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full" data-testid="page-portfolio-manager">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold font-mono flex items-center gap-2">
            <Briefcase className="h-6 w-6 text-primary" />
            PORTFOLIO MANAGER
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            One portfolio-level decision per refresh — paper trading only, nothing executes
            automatically.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={busy}
          className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-mono hover:bg-accent disabled:opacity-50"
          data-testid="button-refresh-portfolio"
        >
          <RefreshCcw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
          {busy ? "DECIDING..." : "REFRESH"}
        </button>
      </div>

      {/* Decision summary */}
      <Card className={`border ${STANCE_STYLE[stance] ?? STANCE_STYLE.HOLD_CASH}`}>
        <CardContent className="p-4 flex items-start gap-3">
          <span
            className={`rounded border px-2.5 py-1 text-sm font-mono font-bold whitespace-nowrap ${
              STANCE_STYLE[stance] ?? ""
            }`}
            data-testid="badge-stance"
          >
            {stance.replace("_", " ")}
          </span>
          <p className="text-sm leading-relaxed" data-testid="text-summary">
            {data?.summary}
          </p>
        </CardContent>
      </Card>

      {/* Capital cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCard label="Total Capital" value={rupee(data?.total_capital)} />
        <StatCard
          label="Invested (Planned)"
          value={rupee(data?.planned_invested_value)}
          sub={`currently ${rupee(data?.invested_value)}`}
          color="text-primary"
        />
        <StatCard
          label="Cash After Plan"
          value={rupee(data?.cash_after)}
          sub={pct(data?.cash_pct)}
        />
        <StatCard label="Market Regime" value={data?.market_regime ?? "—"} />
        <StatCard
          label="New Positions"
          value={`${m?.new_positions_count ?? 0} / ${m?.max_new_positions ?? 5}`}
        />
        <StatCard label="Model Version" value={`v${data?.model_version ?? 0}`} />
      </div>

      {/* Portfolio metrics */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <Card className="bg-card/50 border-border/50">
          <CardContent className="p-4 space-y-2">
            <div className="text-xs font-mono uppercase text-muted-foreground">Portfolio Confidence</div>
            <div className="text-xl font-bold font-mono">{(m?.portfolio_confidence ?? 0).toFixed(0)}</div>
            <GaugeBar value={m?.portfolio_confidence ?? 0} color="bg-primary" />
          </CardContent>
        </Card>
        <Card className="bg-card/50 border-border/50">
          <CardContent className="p-4 space-y-2">
            <div className="text-xs font-mono uppercase text-muted-foreground">Expected Monthly Return</div>
            <div
              className={`text-xl font-bold font-mono ${
                (m?.expected_monthly_return_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"
              }`}
            >
              {(m?.expected_monthly_return_pct ?? 0) >= 0 ? "+" : ""}
              {pct(m?.expected_monthly_return_pct, 2)}
            </div>
            <div className="text-[11px] text-muted-foreground">based on historical expectancy</div>
          </CardContent>
        </Card>
        <Card className="bg-card/50 border-border/50">
          <CardContent className="p-4 space-y-2">
            <div className="text-xs font-mono uppercase text-muted-foreground">Expected Max Drawdown</div>
            <div className="text-xl font-bold font-mono text-orange-400">
              -{pct(m?.expected_max_drawdown_pct, 2)}
            </div>
            <div className="text-[11px] text-muted-foreground">weighted historical drawdown</div>
          </CardContent>
        </Card>
        <Card className="bg-card/50 border-border/50">
          <CardContent className="p-4 space-y-2">
            <div className="text-xs font-mono uppercase text-muted-foreground">Diversification</div>
            <div className="text-xl font-bold font-mono">{(m?.diversification_score ?? 0).toFixed(0)}</div>
            <GaugeBar value={m?.diversification_score ?? 0} color="bg-blue-400" />
          </CardContent>
        </Card>
        <Card className="bg-card/50 border-border/50">
          <CardContent className="p-4 space-y-2">
            <div className="text-xs font-mono uppercase text-muted-foreground">Risk Score</div>
            <div className="text-xl font-bold font-mono">{(m?.risk_score ?? 0).toFixed(0)}</div>
            <GaugeBar
              value={m?.risk_score ?? 0}
              color={
                (m?.risk_score ?? 0) > 66
                  ? "bg-red-400"
                  : (m?.risk_score ?? 0) > 33
                  ? "bg-yellow-400"
                  : "bg-green-400"
              }
            />
          </CardContent>
        </Card>
      </div>

      {/* Allocation vs equal weight (portfolio-level learning) */}
      <Card className="bg-card/50 border-border/50">
        <CardContent className="p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Scale className="h-4 w-4 text-primary" />
            <SectionTitle>AI Allocation vs Equal Weight</SectionTitle>
          </div>
          <p className="text-sm text-muted-foreground" data-testid="text-benchmark-verdict">
            {perf?.verdict}
          </p>
          {(perf?.evaluated_count ?? 0) > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="Decisions Judged" value={perf?.evaluated_count ?? 0} />
              <StatCard
                label="Avg AI Return"
                value={pct(perf?.avg_ai_return_pct, 2)}
                color={(perf?.avg_ai_return_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"}
              />
              <StatCard label="Avg Equal-Weight" value={pct(perf?.avg_equal_weight_return_pct, 2)} />
              <StatCard
                label="Avg Alpha"
                value={`${(perf?.avg_alpha_pct ?? 0) >= 0 ? "+" : ""}${pct(perf?.avg_alpha_pct, 2)}`}
                color={(perf?.avg_alpha_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"}
                sub={`${pct(perf?.outperform_rate_pct, 0)} of decisions outperformed`}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Exit alerts */}
      {(data?.exits?.length ?? 0) > 0 && (
        <div
          className="flex items-start gap-2 rounded-md border border-orange-500/30 bg-orange-500/10 px-3 py-2 text-sm text-orange-400"
          data-testid="alert-exits"
        >
          <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
          <div>
            <span className="font-bold">Exit recommended: </span>
            {data?.exits?.map((e) => `${e.symbol} (${e.reason})`).join("; ")}
          </div>
        </div>
      )}

      {/* Holdings */}
      <div className="space-y-2">
        <SectionTitle>Current Holdings — Actions</SectionTitle>
        {(data?.holdings?.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground">
            No open positions — the whole portfolio is in cash.
          </p>
        ) : (
          <div className="rounded-md border border-border/50 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left text-xs font-mono uppercase text-muted-foreground">
                  <th className="px-3 py-2">Stock</th>
                  <th className="px-3 py-2">Sector</th>
                  <th className="px-3 py-2 text-right">Qty</th>
                  <th className="px-3 py-2 text-right">Avg</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Value</th>
                  <th className="px-3 py-2 text-right">Weight</th>
                  <th className="px-3 py-2 text-right">P&L</th>
                  <th className="px-3 py-2 text-center">Action</th>
                  <th className="px-3 py-2">Why</th>
                </tr>
              </thead>
              <tbody>
                {data?.holdings?.map((h) => <HoldingRow key={h.symbol} h={h} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* New buys */}
      <div className="space-y-2">
        <SectionTitle>Recommended New Buys ({data?.new_buys?.length ?? 0})</SectionTitle>
        {(data?.new_buys?.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="text-no-buys">
            No new positions recommended this refresh — cash is held deliberately when no
            opportunity beats the quality bar.
          </p>
        ) : (
          <div className="rounded-md border border-border/50 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left text-xs font-mono uppercase text-muted-foreground">
                  <th className="px-3 py-2">Stock</th>
                  <th className="px-3 py-2">Sector</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Shares</th>
                  <th className="px-3 py-2 text-right">Allocation</th>
                  <th className="px-3 py-2 text-right">Weight</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2 text-right">Conf</th>
                  <th className="px-3 py-2 text-right">Expectancy</th>
                  <th className="px-3 py-2 text-right">Stop / Target</th>
                </tr>
              </thead>
              <tbody>
                {data?.new_buys?.map((b) => <NewBuyRow key={b.symbol} b={b} />)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Sector exposure */}
      <div className="space-y-2">
        <SectionTitle>Sector Exposure (cap {pct(m?.max_sector_pct ?? 30, 0)})</SectionTitle>
        {(data?.sector_exposure?.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground">No sector exposure — 100% cash.</p>
        ) : (
          <div className="space-y-2">
            {data?.sector_exposure?.map((se) => (
              <div key={se.sector} className="flex items-center gap-3" data-testid={`row-sector-${se.sector}`}>
                <div className="w-40 text-sm font-mono truncate">{se.sector}</div>
                <div className="flex-1">
                  <GaugeBar
                    value={se.pct}
                    max={se.cap_pct || 30}
                    color={se.pct > (se.cap_pct || 30) * 0.9 ? "bg-yellow-400" : "bg-primary"}
                  />
                </div>
                <div className="w-28 text-right text-sm font-mono text-muted-foreground">
                  {rupee(se.value)} · {pct(se.pct)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Skipped + comparisons */}
      {(data?.skipped?.length ?? 0) > 0 && (
        <div className="space-y-2">
          <SectionTitle>
            Considered But Skipped
            {(data?.skipped_total ?? 0) > (data?.skipped?.length ?? 0)
              ? ` (showing ${data?.skipped?.length} of ${data?.skipped_total})`
              : ""}
          </SectionTitle>
          <div className="rounded-md border border-border/50 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left text-xs font-mono uppercase text-muted-foreground">
                  <th className="px-3 py-2">Stock</th>
                  <th className="px-3 py-2">Sector</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2">Why It Was Skipped</th>
                </tr>
              </thead>
              <tbody>
                {data?.skipped?.map((s) => <SkippedRow key={s.symbol} s={s} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(data?.comparisons?.length ?? 0) > 0 && (
        <div className="space-y-2">
          <button
            onClick={() => setShowComparisons(!showComparisons)}
            className="flex items-center gap-1 text-sm font-mono font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground"
            data-testid="button-toggle-comparisons"
          >
            {showComparisons ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            Why X Over Y — Allocation Comparisons
          </button>
          {showComparisons && (
            <div className="space-y-2">
              {data?.comparisons?.map((c, i) => (
                <div
                  key={i}
                  className="rounded-md border border-border/50 bg-card/40 px-3 py-2 text-sm text-muted-foreground leading-relaxed"
                >
                  {c}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Recent decisions */}
      {(data?.recent_decisions?.length ?? 0) > 0 && (
        <div className="space-y-2">
          <SectionTitle>Recent Portfolio Decisions</SectionTitle>
          <div className="rounded-md border border-border/50 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left text-xs font-mono uppercase text-muted-foreground">
                  <th className="px-3 py-2">When</th>
                  <th className="px-3 py-2">Regime</th>
                  <th className="px-3 py-2">Stance</th>
                  <th className="px-3 py-2 text-right">New Buys</th>
                  <th className="px-3 py-2 text-right">Invested</th>
                  <th className="px-3 py-2 text-right">AI vs Equal Weight</th>
                </tr>
              </thead>
              <tbody>
                {data?.recent_decisions?.map((r) => (
                  <tr key={r.id} className="border-b border-border/30" data-testid={`row-decision-${r.id}`}>
                    <td className="px-3 py-2 font-mono text-muted-foreground">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2">{r.regime}</td>
                    <td className="px-3 py-2">
                      <ActionBadge action={r.stance === "DEPLOY" ? "BUY" : r.stance} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{r.new_buys_count}</td>
                    <td className="px-3 py-2 text-right font-mono">{pct(r.invested_pct)}</td>
                    <td className="px-3 py-2 text-right font-mono">
                      {r.evaluation && r.evaluation.alpha_pct !== undefined ? (
                        <span
                          className={
                            (r.evaluation.alpha_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                          }
                        >
                          {(r.evaluation.alpha_pct ?? 0) >= 0 ? "+" : ""}
                          {pct(r.evaluation.alpha_pct, 2)} alpha
                        </span>
                      ) : (
                        <span className="text-muted-foreground">pending</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground border-t border-border/40 pt-3">
        {data?.warning}
      </p>
    </div>
  );
}
