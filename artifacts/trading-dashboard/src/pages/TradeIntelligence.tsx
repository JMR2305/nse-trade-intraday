import { useState } from "react";
import { useGetTradeIntelligence, useImportTradeIntelligence } from "@workspace/api-client-react";
import type {
  TradeIntelligenceRecord,
  TradeIntelligenceBreakdownRow,
  TradeIntelligenceStatistics,
} from "@workspace/api-client-react";
import {
  Database, Loader2, DownloadCloud, AlertCircle, TrendingUp, TrendingDown,
  Clock, Percent, Trophy, ThumbsDown, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import DataFreshnessBar from "@/components/DataFreshnessBar";

const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(d);
const clrPnl = (v: number | null | undefined) =>
  v === null || v === undefined ? "text-muted-foreground"
  : v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-muted-foreground";

const SOURCE_LABELS: Record<string, string> = {
  paper_basket: "Paper Basket Test",
  paper_trade: "Paper Trade",
  historical_replay: "Historical Replay",
};

const REGIME_COLORS: Record<string, string> = {
  "Strong Bullish": "text-emerald-400",
  "Bullish": "text-emerald-300",
  "Neutral": "text-muted-foreground",
  "Bearish": "text-red-300",
  "Strong Bearish": "text-red-400",
  "High Volatility": "text-amber-400",
  "Low Volatility": "text-sky-400",
};

function StatCard({ label, value, sub, icon: Icon, valueClass }: {
  label: string; value: string; sub?: string;
  icon: typeof Database; valueClass?: string;
}) {
  return (
    <div className="rounded border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-muted-foreground text-[10px] font-mono uppercase tracking-wider mb-1">
        <Icon className="w-3.5 h-3.5" />
        {label}
      </div>
      <div className={cn("text-xl font-mono", valueClass ?? "text-foreground")}>{value}</div>
      {sub && <div className="text-[11px] font-mono text-muted-foreground/60 mt-0.5">{sub}</div>}
    </div>
  );
}

function BreakdownTable({ title, rows }: { title: string; rows: TradeIntelligenceBreakdownRow[] }) {
  return (
    <div className="rounded border border-border bg-card overflow-x-auto">
      <div className="px-4 py-2.5 border-b border-border text-xs font-mono uppercase tracking-wider text-muted-foreground">
        {title}
      </div>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-border text-[11px] font-mono uppercase text-muted-foreground">
            <th className="text-left px-4 py-2">Name</th>
            <th className="text-right px-3 py-2">Trades</th>
            <th className="text-right px-3 py-2">Wins</th>
            <th className="text-right px-3 py-2">Losses</th>
            <th className="text-right px-3 py-2">Win Rate</th>
            <th className="text-right px-3 py-2">Avg Return</th>
            <th className="text-right px-4 py-2">P&L ₹</th>
          </tr>
        </thead>
        <tbody className="font-mono text-xs">
          {rows.length === 0 && (
            <tr><td colSpan={7} className="px-4 py-4 text-center text-muted-foreground">No data yet</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.name} className="border-b border-border/50 last:border-0">
              <td className="px-4 py-2 text-foreground">{SOURCE_LABELS[r.name] ?? r.name}</td>
              <td className="px-3 py-2 text-right">{r.trades}</td>
              <td className="px-3 py-2 text-right text-emerald-400">{r.wins}</td>
              <td className="px-3 py-2 text-right text-red-400">{r.losses}</td>
              <td className="px-3 py-2 text-right">{fmt(r.win_rate, 1)}%</td>
              <td className={cn("px-3 py-2 text-right", clrPnl(r.avg_return_pct))}>{fmt(r.avg_return_pct)}%</td>
              <td className={cn("px-4 py-2 text-right", clrPnl(r.total_pnl))}>{fmt(r.total_pnl)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BestWorstCard({ title, best, worst }: {
  title: string;
  best?: TradeIntelligenceStatistics["best_strategy"];
  worst?: TradeIntelligenceStatistics["worst_strategy"];
}) {
  return (
    <div className="rounded border border-border bg-card p-4 space-y-2">
      <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">{title}</div>
      <div className="flex items-center gap-2 text-xs font-mono">
        <Trophy className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
        {best?.name ? (
          <span className="text-foreground">
            {best.name}
            <span className={cn("ml-2", clrPnl(best.avg_return_pct))}>{fmt(best.avg_return_pct)}%</span>
            <span className="text-muted-foreground/60 ml-1">({best.trades})</span>
          </span>
        ) : <span className="text-muted-foreground">—</span>}
      </div>
      <div className="flex items-center gap-2 text-xs font-mono">
        <ThumbsDown className="w-3.5 h-3.5 text-red-400 shrink-0" />
        {worst?.name ? (
          <span className="text-foreground">
            {worst.name}
            <span className={cn("ml-2", clrPnl(worst.avg_return_pct))}>{fmt(worst.avg_return_pct)}%</span>
            <span className="text-muted-foreground/60 ml-1">({worst.trades})</span>
          </span>
        ) : <span className="text-muted-foreground">—</span>}
      </div>
    </div>
  );
}

function DetailRow({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="flex justify-between gap-4 py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("text-foreground text-right", valueClass)}>{value}</span>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground border-b border-border pb-1 mb-2">
        {title}
      </div>
      <div className="text-xs font-mono">{children}</div>
    </div>
  );
}

function TradeDetailPanel({ trade, onClose }: { trade: TradeIntelligenceRecord; onClose: () => void }) {
  const indicators: [string, number | null | undefined][] = [
    ["EMA 9", trade.ema9], ["EMA 20", trade.ema20], ["EMA 50", trade.ema50],
    ["EMA 200", trade.ema200], ["RSI", trade.rsi], ["MACD", trade.macd],
    ["MACD Signal", trade.macd_signal], ["VWAP", trade.vwap], ["ATR", trade.atr],
    ["ADX", trade.adx], ["Supertrend", trade.supertrend], ["Volume Ratio", trade.volume_ratio],
  ];
  const hasIndicators = indicators.some(([, v]) => v !== null && v !== undefined);
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose} data-testid="panel-trade-detail">
      <div
        className="w-full max-w-md h-full bg-card border-l border-border overflow-y-auto p-5 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="text-lg font-semibold font-mono">{trade.symbol}</div>
            <div className="text-[11px] font-mono text-muted-foreground">
              {trade.date} · {SOURCE_LABELS[trade.source] ?? trade.source}
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground" data-testid="button-close-detail">
            <X className="w-4 h-4" />
          </button>
        </div>

        <DetailSection title="Trade Summary">
          <DetailRow label="Entry" value={`₹${fmt(trade.entry_price)}`} />
          <DetailRow label="Exit" value={`₹${fmt(trade.exit_price)}`} />
          <DetailRow label="Quantity" value={String(trade.quantity ?? "—")} />
          <DetailRow label="Profit/Loss" value={`₹${fmt(trade.profit_loss)}`} valueClass={clrPnl(trade.profit_loss)} />
          <DetailRow label="Return %" value={`${fmt(trade.return_percent)}%`} valueClass={clrPnl(trade.return_percent)} />
          <DetailRow label="Holding Days" value={trade.holding_period != null ? String(trade.holding_period) : "—"} />
          <DetailRow
            label="Result"
            value={trade.outcome_classification === 1 ? "Winning (1)" : "Losing (0)"}
            valueClass={trade.outcome_classification === 1 ? "text-emerald-400" : "text-red-400"}
          />
        </DetailSection>

        <DetailSection title="Market Context">
          <DetailRow label="Sector" value={trade.sector || "—"} />
          <DetailRow
            label="Market Regime" value={trade.market_regime || "—"}
            valueClass={REGIME_COLORS[trade.market_regime ?? ""]}
          />
          <DetailRow label="Volatility (NIFTY, ann.)" value={trade.volatility != null ? `${fmt(trade.volatility)}%` : "—"} />
        </DetailSection>

        <DetailSection title="Indicator Snapshot (at entry)">
          {hasIndicators ? (
            <div className="grid grid-cols-2 gap-x-6">
              {indicators.map(([label, v]) => (
                <DetailRow key={label} label={label} value={fmt(v)} />
              ))}
            </div>
          ) : (
            <div className="text-muted-foreground py-1">
              Not captured — this trade was opened before entry snapshots were introduced.
            </div>
          )}
        </DetailSection>

        <DetailSection title="Decision Snapshot">
          <DetailRow label="Entry Strategy" value={trade.entry_strategy || trade.strategy || "—"} />
          <DetailRow label="Opportunity Score" value={fmt(trade.opportunity_score, 1)} />
          <DetailRow label="Confidence" value={fmt(trade.confidence, 1)} />
          <DetailRow label="Trade Quality" value={fmt(trade.trade_quality, 1)} />
          <DetailRow label="Risk / Reward" value={fmt(trade.risk_reward)} />
        </DetailSection>

        <DetailSection title="Exit">
          <DetailRow label="Exit Reason" value={trade.exit_reason || "—"} />
        </DetailSection>
      </div>
    </div>
  );
}

export default function TradeIntelligence() {
  const query = useGetTradeIntelligence({ limit: 200 });
  const importMutation = useImportTradeIntelligence({
    mutation: { onSuccess: () => query.refetch() },
  });
  const [selected, setSelected] = useState<TradeIntelligenceRecord | null>(null);

  const data = query.data;
  const summary = data?.summary;
  const stats = summary?.statistics;
  const trades = data?.trades ?? [];

  return (
    <div className="p-4 md:p-6 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <Database className="w-5 h-5 text-primary" />
            Trade Intelligence
          </h1>
          <p className="text-xs font-mono text-muted-foreground mt-0.5">
            Historical database of every completed paper trade — the foundation future learning modules will use.
            Click any trade to see its full entry snapshot.
          </p>
        </div>
        <button
          onClick={() => importMutation.mutate()}
          disabled={importMutation.isPending}
          className="inline-flex items-center gap-2 text-xs font-mono border border-border rounded px-3 py-1.5 hover:bg-muted/40 disabled:opacity-50"
          data-testid="button-import-trades"
        >
          {importMutation.isPending
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <DownloadCloud className="w-3.5 h-3.5" />}
          Import Existing Trades
        </button>
      </div>

      <DataFreshnessBar variant="scan" />

      {importMutation.data && (
        <div className="text-xs font-mono text-emerald-400 border border-emerald-400/30 bg-emerald-400/5 rounded px-3 py-2">
          Imported {importMutation.data.imported_paper_trades} paper trade(s)
          {importMutation.data.repaired_rows != null && importMutation.data.repaired_rows > 0
            ? `, repaired ${importMutation.data.repaired_rows} older row(s)` : ""}.
          {" "}{importMutation.data.note}
        </div>
      )}

      {query.isLoading && (
        <div className="flex items-center gap-2 text-sm font-mono text-muted-foreground py-10 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading trade intelligence…
        </div>
      )}

      {query.isError && (
        <div className="flex items-center gap-2 text-sm font-mono text-red-400 border border-red-400/30 bg-red-400/5 rounded px-3 py-2">
          <AlertCircle className="w-4 h-4" /> Failed to load trade intelligence data.
        </div>
      )}

      {summary && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <StatCard label="Total Historical Trades" value={String(summary.total_trades)} icon={Database} />
            <StatCard
              label="Winning Trades" value={String(summary.winning_trades)}
              sub={`${fmt(summary.win_rate, 1)}% win rate`} icon={TrendingUp} valueClass="text-emerald-400"
            />
            <StatCard label="Losing Trades" value={String(summary.losing_trades)} icon={TrendingDown} valueClass="text-red-400" />
            <StatCard
              label="Average Return" value={`${fmt(summary.average_return_pct)}%`}
              sub={`Total P&L ₹${fmt(summary.total_pnl)}`} icon={Percent}
              valueClass={clrPnl(summary.average_return_pct)}
            />
            <StatCard label="Avg Holding Days" value={fmt(summary.average_holding_days, 1)} icon={Clock} />
          </div>

          {stats && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
              <BestWorstCard title="Strategy — Best / Worst" best={stats.best_strategy} worst={stats.worst_strategy} />
              <BestWorstCard title="Sector — Best / Worst" best={stats.best_sector} worst={stats.worst_sector} />
              <BestWorstCard title="Regime — Best / Worst" best={stats.best_regime} worst={stats.worst_regime} />
              <div className="rounded border border-border bg-card p-4 space-y-2">
                <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Average Trade</div>
                <div className="text-xs font-mono flex items-center gap-2">
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span className="text-emerald-400">₹{fmt(stats.average_winning_trade)}</span>
                  <span className="text-muted-foreground/60">avg win</span>
                </div>
                <div className="text-xs font-mono flex items-center gap-2">
                  <TrendingDown className="w-3.5 h-3.5 text-red-400 shrink-0" />
                  <span className="text-red-400">₹{fmt(stats.average_losing_trade)}</span>
                  <span className="text-muted-foreground/60">avg loss</span>
                </div>
              </div>
              <div className="rounded border border-border bg-card p-4 space-y-2">
                <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">Largest Trades</div>
                <div className="text-xs font-mono flex items-center gap-2">
                  <Trophy className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  {stats.largest_winner?.symbol ? (
                    <span>
                      {stats.largest_winner.symbol}
                      <span className="text-emerald-400 ml-2">+₹{fmt(stats.largest_winner.profit_loss)}</span>
                    </span>
                  ) : <span className="text-muted-foreground">—</span>}
                </div>
                <div className="text-xs font-mono flex items-center gap-2">
                  <ThumbsDown className="w-3.5 h-3.5 text-red-400 shrink-0" />
                  {stats.largest_loser?.symbol ? (
                    <span>
                      {stats.largest_loser.symbol}
                      <span className="text-red-400 ml-2">₹{fmt(stats.largest_loser.profit_loss)}</span>
                    </span>
                  ) : <span className="text-muted-foreground">—</span>}
                </div>
              </div>
            </div>
          )}

          <div className="grid lg:grid-cols-2 gap-4">
            <BreakdownTable title="Entry Strategy Breakdown" rows={summary.strategy_breakdown} />
            <BreakdownTable title="Exit Reason Breakdown" rows={summary.exit_reason_breakdown} />
          </div>
          <div className="grid lg:grid-cols-2 gap-4">
            <BreakdownTable title="Market Regime Breakdown" rows={summary.regime_breakdown} />
            <BreakdownTable title="Sector Breakdown" rows={summary.sector_breakdown} />
          </div>
          <BreakdownTable title="Source Breakdown" rows={summary.source_breakdown} />

          <div className="rounded border border-border bg-card overflow-x-auto">
            <div className="px-4 py-2.5 border-b border-border text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Recent Trades ({trades.length}) — click a row for details
            </div>
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border text-[11px] font-mono uppercase text-muted-foreground">
                  <th className="text-left px-4 py-2">Date</th>
                  <th className="text-left px-3 py-2">Symbol</th>
                  <th className="text-left px-3 py-2">Source</th>
                  <th className="text-left px-3 py-2">Entry Strategy</th>
                  <th className="text-left px-3 py-2">Exit Reason</th>
                  <th className="text-left px-3 py-2">Regime</th>
                  <th className="text-right px-3 py-2">Entry ₹</th>
                  <th className="text-right px-3 py-2">Exit ₹</th>
                  <th className="text-right px-3 py-2">P&L ₹</th>
                  <th className="text-right px-3 py-2">Return</th>
                  <th className="text-center px-4 py-2">W/L</th>
                </tr>
              </thead>
              <tbody className="font-mono text-xs">
                {trades.length === 0 && (
                  <tr>
                    <td colSpan={11} className="px-4 py-6 text-center text-muted-foreground">
                      No completed trades stored yet. Run a Paper Basket Test, Market Replay,
                      or close a paper trade — completed trades are stored automatically.
                    </td>
                  </tr>
                )}
                {trades.map((t: TradeIntelligenceRecord) => (
                  <tr
                    key={t.trade_id}
                    className="border-b border-border/50 last:border-0 cursor-pointer hover:bg-muted/30"
                    onClick={() => setSelected(t)}
                    data-testid={`row-trade-${t.trade_id}`}
                  >
                    <td className="px-4 py-2 whitespace-nowrap">{t.date}</td>
                    <td className="px-3 py-2 text-foreground">{t.symbol}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{SOURCE_LABELS[t.source] ?? t.source}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{t.entry_strategy || t.strategy || "—"}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{t.exit_reason || "—"}</td>
                    <td className={cn("px-3 py-2 whitespace-nowrap", REGIME_COLORS[t.market_regime ?? ""] ?? "text-muted-foreground")}>
                      {t.market_regime || "—"}
                    </td>
                    <td className="px-3 py-2 text-right">{fmt(t.entry_price)}</td>
                    <td className="px-3 py-2 text-right">{fmt(t.exit_price)}</td>
                    <td className={cn("px-3 py-2 text-right", clrPnl(t.profit_loss))}>{fmt(t.profit_loss)}</td>
                    <td className={cn("px-3 py-2 text-right", clrPnl(t.return_percent))}>{fmt(t.return_percent)}%</td>
                    <td className="px-4 py-2 text-center">
                      <span className={cn(
                        "inline-flex items-center text-[11px] border rounded px-1.5 py-0.5",
                        t.outcome_classification === 1
                          ? "text-emerald-400 border-emerald-400/50 bg-emerald-400/10"
                          : "text-red-400 border-red-400/50 bg-red-400/10",
                      )}>
                        {t.outcome_classification === 1 ? "1 · Win" : "0 · Loss"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {selected && <TradeDetailPanel trade={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
