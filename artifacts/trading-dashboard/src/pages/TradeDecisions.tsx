import React, { useState } from "react";
import {
  useGetTradeDecisions,
  getGetTradeDecisionsQueryKey,
} from "@workspace/api-client-react";
import type { TradeDecision } from "@workspace/api-client-react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Target,
  RefreshCcw,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Info,
} from "lucide-react";

const REC_STYLE: Record<string, string> = {
  STRONG_BUY: "text-emerald-300 bg-emerald-500/15 border-emerald-500/40",
  BUY:        "text-green-400 bg-green-500/10 border-green-500/30",
  EXIT:       "text-orange-400 bg-orange-500/10 border-orange-500/30",
  WATCH:      "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  AVOID:      "text-red-400 bg-red-500/10 border-red-500/30",
};

const REC_LABEL: Record<string, string> = {
  STRONG_BUY: "STRONG BUY",
  BUY:        "BUY",
  EXIT:       "EXIT",
  WATCH:      "WATCH",
  AVOID:      "AVOID",
};

const FILTERS = ["All", "STRONG_BUY", "BUY", "EXIT", "WATCH", "AVOID"];

function RecBadge({ rec }: { rec: string }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-[11px] font-mono font-bold whitespace-nowrap ${
        REC_STYLE[rec] ?? REC_STYLE.WATCH
      }`}
      data-testid={`badge-recommendation-${rec.toLowerCase()}`}
    >
      {REC_LABEL[rec] ?? rec}
    </span>
  );
}

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">
          {label}
        </div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

function fmt(n: number | undefined, digits = 2): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits);
}

function rupee(n: number | undefined): string {
  const v = Number(n ?? 0);
  return v > 0 ? `₹${v.toFixed(2)}` : "—";
}

function BreakdownPanel({ d }: { d: TradeDecision }) {
  const rows = d.breakdown ?? [];
  const maxContribution = Math.max(1, ...rows.map((b) => b.contribution));
  return (
    <div>
      <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
        Decision Breakdown
        <span className="ml-1 normal-case tracking-normal text-[9px] text-muted-foreground/70">
          (estimated contribution)
        </span>
      </div>
      <div className="space-y-1.5 font-mono text-xs">
        {rows.map((b) => (
          <div key={b.factor} className="flex items-center gap-2">
            <span className="w-40 flex-shrink-0 text-muted-foreground">{b.factor}</span>
            <div className="flex-1 h-1.5 rounded bg-border/40 overflow-hidden">
              <div
                className="h-full rounded bg-primary/70"
                style={{ width: `${Math.max(0, (b.contribution / maxContribution) * 100)}%` }}
              />
            </div>
            <span className="w-12 text-right font-bold">
              {b.contribution >= 0 ? "+" : ""}
              {b.contribution.toFixed(0)}
            </span>
          </div>
        ))}
        <div className="border-t border-border/50 mt-2 pt-2 flex items-center justify-between">
          <span className="text-muted-foreground">Final Confidence</span>
          <span className="font-bold text-sm">{d.final_confidence.toFixed(0)}%</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Recommendation</span>
          <RecBadge rec={d.recommendation} />
        </div>
      </div>
    </div>
  );
}

function DetailRow({ d }: { d: TradeDecision }) {
  return (
    <tr className="bg-muted/20">
      <td colSpan={11} className="px-6 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 text-sm">
          <BreakdownPanel d={d} />
          <div>
            <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
              Why this recommendation
            </div>
            <p className="text-foreground/90 leading-relaxed">{d.explanation}</p>
            {d.failed_conditions.length > 0 && (
              <div className="mt-3">
                <div className="text-xs font-mono uppercase text-muted-foreground mb-1">
                  What's missing for a stronger rating
                </div>
                <ul className="list-disc list-inside space-y-0.5 text-foreground/80">
                  {d.failed_conditions.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div>
            <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
              Confidence &amp; history
            </div>
            <dl className="space-y-1 font-mono text-xs">
              <div className="flex justify-between"><dt className="text-muted-foreground">Technical confidence</dt><dd>{fmt(d.base_confidence, 0)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Learning adjustment</dt><dd className={d.learning_adjustment >= 0 ? "text-green-400" : "text-red-400"}>{d.learning_adjustment >= 0 ? "+" : ""}{fmt(d.learning_adjustment, 0)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Final confidence</dt><dd className="font-bold">{fmt(d.final_confidence, 0)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Historical matches</dt><dd>{d.historical_trades}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Win rate</dt><dd>{fmt(d.historical_win_rate, 0)}%</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Expectancy</dt><dd className={d.historical_expectancy >= 0 ? "text-green-400" : "text-red-400"}>{d.historical_expectancy >= 0 ? "+" : ""}{fmt(d.historical_expectancy)}%</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Profit factor</dt><dd>{fmt(d.historical_profit_factor)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Best pattern</dt><dd className="text-right ml-2">{d.best_pattern}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Regime match</dt><dd>{d.regime_match ? "Yes" : "No"}</dd></div>
            </dl>
          </div>
          <div>
            <div className="text-xs font-mono uppercase text-muted-foreground mb-2">
              Risk &amp; position
            </div>
            <dl className="space-y-1 font-mono text-xs">
              <div className="flex justify-between"><dt className="text-muted-foreground">Entry</dt><dd>{rupee(d.entry_price)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Stop-loss</dt><dd>{rupee(d.stop_loss)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Target</dt><dd>{rupee(d.target)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Risk : Reward</dt><dd>{d.rr_ratio > 0 ? `${fmt(d.rr_ratio, 1)} : 1` : "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Expected holding</dt><dd>{d.expected_holding_days > 0 ? `${fmt(d.expected_holding_days, 0)} days` : "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Expected drawdown</dt><dd>{d.expected_drawdown !== 0 ? `${fmt(d.expected_drawdown)}%` : "—"}</dd></div>
              {d.position_open && (
                <>
                  <div className="border-t border-border/50 my-2" />
                  <div className="flex justify-between"><dt className="text-muted-foreground">Open position</dt><dd>{d.position_quantity} @ {rupee(d.position_avg_price)}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Unrealized P&amp;L</dt><dd className={d.position_pnl_pct >= 0 ? "text-green-400" : "text-red-400"}>{d.position_pnl_pct >= 0 ? "+" : ""}{fmt(d.position_pnl_pct)}%</dd></div>
                  {d.exit_reason && (
                    <div className="text-orange-400 mt-1">{d.exit_reason}</div>
                  )}
                </>
              )}
            </dl>
          </div>
        </div>
      </td>
    </tr>
  );
}

export default function TradeDecisions() {
  const { data, isLoading, refetch, isFetching } = useGetTradeDecisions(
    undefined,
    { query: { queryKey: getGetTradeDecisionsQueryKey() } },
  );
  const [filter, setFilter] = useState("All");
  const [expanded, setExpanded] = useState<string | null>(null);

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">
            SCANNING MARKET &amp; BUILDING DECISIONS... (~30s)
          </p>
        </div>
      </div>
    );
  }

  const decisions = data?.decisions ?? [];
  const visible =
    filter === "All" ? decisions : decisions.filter((d) => d.recommendation === filter);

  const updatedAt = data?.generated_at
    ? new Date(data.generated_at).toLocaleString()
    : "—";
  const updatedTime = data?.generated_at
    ? new Date(data.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "—";

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full" data-testid="page-trade-decisions">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold font-mono flex items-center gap-2">
            <Target className="h-6 w-6 text-primary" />
            TRADE DECISIONS
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            One clear recommendation per stock — paper trading only, not investment advice.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-mono hover:bg-accent disabled:opacity-50"
          data-testid="button-refresh-decisions"
        >
          <RefreshCcw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          {isFetching ? "SCANNING..." : "REFRESH"}
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <SummaryCard label="Strong Buy" value={data?.strong_buy_count ?? 0} color="text-emerald-300" />
        <SummaryCard label="Buy" value={data?.buy_count ?? 0} color="text-green-400" />
        <SummaryCard label="Exit" value={data?.exit_count ?? 0} color="text-orange-400" />
        <SummaryCard label="Watch" value={data?.watch_count ?? 0} color="text-yellow-400" />
        <SummaryCard label="Avoid" value={data?.avoid_count ?? 0} color="text-red-400" />
        <SummaryCard label="Market Regime" value={data?.market_regime ?? "—"} />
        <SummaryCard label="Last Updated" value={updatedTime} />
      </div>

      {(data?.data_unavailable_count ?? 0) > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-sm text-yellow-400">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          Live NSE data unavailable for {data?.data_unavailable_count} stock(s) — no
          buy recommendations are issued on fallback data.
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-md border px-3 py-1 text-xs font-mono ${
              filter === f
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-accent"
            }`}
            data-testid={`button-filter-${f.toLowerCase()}`}
          >
            {f === "All" ? "ALL" : REC_LABEL[f] ?? f}
          </button>
        ))}
        <span className="ml-auto text-xs font-mono text-muted-foreground flex items-center gap-1">
          <Info className="h-3 w-3" /> Last updated: {updatedAt}
        </span>
      </div>

      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/50 text-xs font-mono uppercase text-muted-foreground">
                <th className="px-4 py-2 text-left w-8"></th>
                <th className="px-2 py-2 text-left">Stock</th>
                <th className="px-2 py-2 text-left">Decision</th>
                <th className="px-2 py-2 text-right">Confidence</th>
                <th className="px-2 py-2 text-right">Price</th>
                <th className="px-2 py-2 text-right">Entry</th>
                <th className="px-2 py-2 text-right">Stop</th>
                <th className="px-2 py-2 text-right">Target</th>
                <th className="px-2 py-2 text-right">R:R</th>
                <th className="px-2 py-2 text-right">Hold (Days)</th>
                <th className="px-4 py-2 text-left">Reason</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((d) => {
                const isOpen = expanded === d.stock;
                return (
                  <React.Fragment key={d.stock}>
                    <tr
                      className="border-b border-border/30 hover:bg-accent/30 cursor-pointer"
                      onClick={() => setExpanded(isOpen ? null : d.stock)}
                      data-testid={`row-decision-${d.stock}`}
                    >
                      <td className="px-4 py-2 text-muted-foreground">
                        {isOpen ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </td>
                      <td className="px-2 py-2 font-mono font-bold">
                        {d.stock}
                        {d.position_open && (
                          <span className="ml-1.5 rounded bg-blue-500/15 border border-blue-500/30 px-1 py-0.5 text-[9px] text-blue-400 font-mono align-middle">
                            HELD
                          </span>
                        )}
                        <div className="text-[10px] font-normal text-muted-foreground">
                          {d.sector}
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex flex-col items-start gap-1">
                          <RecBadge rec={d.recommendation} />
                          {d.low_reliability && (
                            <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1 py-0.5 text-[9px] font-mono text-amber-400 whitespace-nowrap">
                              LOW RELIABILITY
                            </span>
                          )}
                          {d.data_status !== "OK" && (
                            <span className="rounded border border-slate-500/30 bg-slate-500/10 px-1 py-0.5 text-[9px] font-mono text-slate-400 whitespace-nowrap">
                              DATA UNAVAILABLE
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-2 py-2 text-right font-mono">{fmt(d.final_confidence, 0)}</td>
                      <td className="px-2 py-2 text-right font-mono">{rupee(d.price)}</td>
                      <td className="px-2 py-2 text-right font-mono">{rupee(d.entry_price)}</td>
                      <td className="px-2 py-2 text-right font-mono text-red-400/90">{rupee(d.stop_loss)}</td>
                      <td className="px-2 py-2 text-right font-mono text-green-400/90">{rupee(d.target)}</td>
                      <td className="px-2 py-2 text-right font-mono">
                        {d.rr_ratio > 0 ? `${fmt(d.rr_ratio, 1)}:1` : "—"}
                      </td>
                      <td className="px-2 py-2 text-right font-mono">
                        {d.expected_holding_days > 0 ? fmt(d.expected_holding_days, 0) : "—"}
                      </td>
                      <td className="px-4 py-2 text-muted-foreground max-w-md truncate">
                        {d.reason}
                      </td>
                    </tr>
                    {isOpen && <DetailRow d={d} />}
                  </React.Fragment>
                );
              })}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-8 text-center text-muted-foreground font-mono text-sm">
                    No stocks in this category.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground font-mono">
        {data?.warning ?? "Paper trading only — research tool, not investment advice."}
      </p>
    </div>
  );
}
