import { useGetTradeIntelligence, useImportTradeIntelligence } from "@workspace/api-client-react";
import type {
  TradeIntelligenceRecord,
  TradeIntelligenceBreakdownRow,
} from "@workspace/api-client-react";
import { Database, Loader2, DownloadCloud, AlertCircle, TrendingUp, TrendingDown, Clock, Percent } from "lucide-react";
import { cn } from "@/lib/utils";

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

export default function TradeIntelligence() {
  const query = useGetTradeIntelligence({ limit: 200 });
  const importMutation = useImportTradeIntelligence({
    mutation: { onSuccess: () => query.refetch() },
  });

  const data = query.data;
  const summary = data?.summary;
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
            New Paper Basket Tests, Paper Trades and Historical Replays are stored automatically.
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

      {importMutation.data && (
        <div className="text-xs font-mono text-emerald-400 border border-emerald-400/30 bg-emerald-400/5 rounded px-3 py-2">
          Imported {importMutation.data.imported_paper_trades} paper trade(s). {importMutation.data.note}
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

          <div className="grid lg:grid-cols-2 gap-4">
            <BreakdownTable title="Market Regime Breakdown" rows={summary.regime_breakdown} />
            <BreakdownTable title="Strategy Breakdown" rows={summary.strategy_breakdown} />
          </div>
          <BreakdownTable title="Source Breakdown" rows={summary.source_breakdown} />

          <div className="rounded border border-border bg-card overflow-x-auto">
            <div className="px-4 py-2.5 border-b border-border text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Recent Trades ({trades.length})
            </div>
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border text-[11px] font-mono uppercase text-muted-foreground">
                  <th className="text-left px-4 py-2">Date</th>
                  <th className="text-left px-3 py-2">Symbol</th>
                  <th className="text-left px-3 py-2">Source</th>
                  <th className="text-left px-3 py-2">Strategy</th>
                  <th className="text-left px-3 py-2">Regime</th>
                  <th className="text-right px-3 py-2">Entry ₹</th>
                  <th className="text-right px-3 py-2">Exit ₹</th>
                  <th className="text-right px-3 py-2">Qty</th>
                  <th className="text-right px-3 py-2">P&L ₹</th>
                  <th className="text-right px-3 py-2">Return</th>
                  <th className="text-right px-3 py-2">RSI</th>
                  <th className="text-right px-3 py-2">Score</th>
                  <th className="text-center px-4 py-2">W/L</th>
                </tr>
              </thead>
              <tbody className="font-mono text-xs">
                {trades.length === 0 && (
                  <tr>
                    <td colSpan={13} className="px-4 py-6 text-center text-muted-foreground">
                      No completed trades stored yet. Run a Paper Basket Test, Market Replay,
                      or close a paper trade — completed trades are stored automatically.
                    </td>
                  </tr>
                )}
                {trades.map((t: TradeIntelligenceRecord) => (
                  <tr key={t.trade_id} className="border-b border-border/50 last:border-0" data-testid={`row-trade-${t.trade_id}`}>
                    <td className="px-4 py-2 whitespace-nowrap">{t.date}</td>
                    <td className="px-3 py-2 text-foreground">{t.symbol}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{SOURCE_LABELS[t.source] ?? t.source}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{t.strategy || "—"}</td>
                    <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{t.market_regime || "—"}</td>
                    <td className="px-3 py-2 text-right">{fmt(t.entry_price)}</td>
                    <td className="px-3 py-2 text-right">{fmt(t.exit_price)}</td>
                    <td className="px-3 py-2 text-right">{t.quantity ?? "—"}</td>
                    <td className={cn("px-3 py-2 text-right", clrPnl(t.profit_loss))}>{fmt(t.profit_loss)}</td>
                    <td className={cn("px-3 py-2 text-right", clrPnl(t.return_percent))}>{fmt(t.return_percent)}%</td>
                    <td className="px-3 py-2 text-right">{fmt(t.rsi, 1)}</td>
                    <td className="px-3 py-2 text-right">{fmt(t.opportunity_score, 1)}</td>
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
    </div>
  );
}
