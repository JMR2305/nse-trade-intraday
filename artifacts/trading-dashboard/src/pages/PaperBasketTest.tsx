import { useState } from "react";
import { useRunPaperBasket } from "@workspace/api-client-react";
import type {
  PaperBasketResult, PaperBasketItem,
  PaperBasketRequestHoldingPeriod, PaperBasketRequestMethod,
} from "@workspace/api-client-react";
import {
  Layers, Download, AlertTriangle, AlertCircle, Loader2, Play,
} from "lucide-react";
import { cn } from "@/lib/utils";

const METHODS = [
  { value: "opportunity_score", label: "Opportunity Score" },
  { value: "gainers",           label: "Prev-Day Gainers" },
  { value: "volume_spike",      label: "Prev-Day Volume Spike" },
  { value: "sector_strength",   label: "Sector Strength" },
];

const HOLDING_PERIODS = [1, 3, 5, 10];

function today() { return new Date().toISOString().split("T")[0]; }
function daysAgo(n: number) {
  const dt = new Date(); dt.setDate(dt.getDate() - n);
  return dt.toISOString().split("T")[0];
}

const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? "—" : v.toFixed(d);
const clrPnl = (v: number | null | undefined) =>
  v === null || v === undefined ? "text-muted-foreground"
  : v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-muted-foreground";

const OUTCOME_CFG: Record<string, string> = {
  "Excellent":    "text-emerald-400 border-emerald-400/50 bg-emerald-400/10",
  "Good":         "text-sky-400     border-sky-400/50     bg-sky-400/10",
  "Weak Profit":  "text-yellow-400  border-yellow-400/50  bg-yellow-400/10",
  "Small Loss":   "text-orange-400  border-orange-400/50  bg-orange-400/10",
  "Failed":       "text-red-400     border-red-400/50     bg-red-400/10",
};

function OutcomeBadge({ outcome }: { outcome: string }) {
  const cls = OUTCOME_CFG[outcome] ?? "text-muted-foreground border-border bg-muted/10";
  return (
    <span className={cn("inline-flex items-center text-[11px] font-mono border rounded px-1.5 py-0.5", cls)}>
      {outcome}
    </span>
  );
}

function exportCsv(result: PaperBasketResult) {
  const headers = [
    "Stock", "Sector", "Selection Reason", "Buy Date", "Buy Price",
    "Sell Date", "Sell Price", "Quantity", "Investment ₹", "P&L ₹", "P&L %", "Outcome",
  ];
  const rows = result.items.map((r: PaperBasketItem) => [
    r.stock, r.sector, `"${r.selection_reason}"`, r.buy_date, fmt(r.buy_price),
    r.sell_date, fmt(r.sell_price), r.quantity, fmt(r.investment),
    fmt(r.pnl_rupees), fmt(r.pnl_pct), r.outcome,
  ]);
  const csv = [headers, ...rows].map(row => row.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `paper_basket_${result.selection_date}_${result.method}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function PaperBasketTest() {
  const [selectionDate, setSelectionDate] = useState(daysAgo(7));
  const [holdingPeriod, setHoldingPeriod] = useState<PaperBasketRequestHoldingPeriod>(5);
  const [numStocks, setNumStocks] = useState(10);
  const [quantity, setQuantity] = useState(10);
  const [method, setMethod] = useState<PaperBasketRequestMethod>("opportunity_score");
  const [result, setResult] = useState<PaperBasketResult | null>(null);

  const runBasket = useRunPaperBasket();

  function handleRun() {
    setResult(null);
    runBasket.mutate(
      {
        data: {
          selection_date: selectionDate,
          holding_period: holdingPeriod,
          num_stocks: numStocks,
          quantity,
          method,
        },
      },
      { onSuccess: data => setResult(data) },
    );
  }

  const isLoading = runBasket.isPending;
  const hasError = runBasket.isError;
  const summary = result?.summary;

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1500px]">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Layers className="mt-0.5 h-6 w-6 text-primary shrink-0" />
        <div>
          <h1 className="text-2xl font-bold font-mono tracking-tight">Paper Basket Test</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Simulate buying a basket of stocks selected from a previous trading day's data — paper trading only, no lookahead bias.
          </p>
        </div>
      </div>

      {/* Warning banner (always visible) */}
      <div className="flex items-center gap-2 rounded border border-yellow-500/30 bg-yellow-500/10 p-3 text-sm text-yellow-400 font-mono">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        This is historical paper testing only. No real orders are placed.
      </div>

      {/* Controls */}
      <div className="rounded border border-border bg-card p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Selection Date</label>
            <input
              type="date"
              value={selectionDate}
              max={today()}
              onChange={e => setSelectionDate(e.target.value)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Holding Period</label>
            <select value={holdingPeriod} onChange={e => setHoldingPeriod(Number(e.target.value) as PaperBasketRequestHoldingPeriod)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary">
              {HOLDING_PERIODS.map(p => <option key={p} value={p}>{p} day{p > 1 ? "s" : ""}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider"># Stocks</label>
            <input
              type="number" min={1} max={30} value={numStocks}
              onChange={e => setNumStocks(Math.max(1, Number(e.target.value)))}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono w-20 focus:outline-none focus:border-primary"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Qty / Stock</label>
            <input
              type="number" min={1} value={quantity}
              onChange={e => setQuantity(Math.max(1, Number(e.target.value)))}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono w-20 focus:outline-none focus:border-primary"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Selection Method</label>
            <select value={method} onChange={e => setMethod(e.target.value as PaperBasketRequestMethod)}
              className="bg-background border border-border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:border-primary min-w-[180px]">
              {METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <button onClick={handleRun} disabled={isLoading}
            className="flex items-center gap-2 bg-primary text-primary-foreground font-mono text-sm px-5 py-1.5 rounded hover:bg-primary/90 disabled:opacity-60 disabled:cursor-not-allowed transition-colors ml-auto">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {isLoading ? "Running…" : "Run Basket Test"}
          </button>
          {result && (
            <button onClick={() => exportCsv(result)}
              className="flex items-center gap-2 border border-border text-sm font-mono px-4 py-1.5 rounded hover:bg-accent transition-colors">
              <Download className="h-4 w-4" />
              Export CSV
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {hasError && (
        <div className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to run paper basket test. Check the API server is running and the date has valid trading data.
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="rounded border border-border bg-card p-10 flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <div className="text-sm font-mono text-muted-foreground text-center">
            Selecting basket and fetching historical prices…
          </div>
        </div>
      )}

      {/* Results */}
      {!isLoading && result && (
        <>
          {/* Summary */}
          {summary && (
            <div className="rounded border border-border bg-card p-4">
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <span className="font-mono text-sm text-foreground font-semibold">
                  {result.method_label}
                </span>
                <span className="text-xs font-mono text-muted-foreground">
                  Selected {result.selection_date} · Buy {result.buy_date} · Hold {result.holding_period}d · {result.num_stocks} stocks × {result.quantity} qty
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 text-xs font-mono">
                <div>
                  <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-0.5">Investment</div>
                  <div className="text-foreground text-sm">₹{fmt(summary.total_investment)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-0.5">Final Value</div>
                  <div className="text-foreground text-sm">₹{fmt(summary.final_value)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-0.5">Net P&L</div>
                  <div className={cn("text-sm", clrPnl(summary.net_pnl))}>
                    {summary.net_pnl >= 0 ? "+" : ""}₹{fmt(summary.net_pnl)}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-0.5">Net Return</div>
                  <div className={cn("text-sm", clrPnl(summary.net_return_pct))}>
                    {summary.net_return_pct >= 0 ? "+" : ""}{fmt(summary.net_return_pct)}%
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-0.5">Win Rate</div>
                  <div className="text-foreground text-sm">{fmt(summary.win_rate, 1)}%</div>
                  <div className="text-muted-foreground/60 text-[10px]">{summary.winning_stocks}W / {summary.losing_stocks}L</div>
                </div>
                <div>
                  <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-0.5">Best Stock</div>
                  <div className="text-emerald-400 text-sm">{summary.best_stock ?? "—"}</div>
                  <div className="text-muted-foreground/60 text-[10px]">{fmt(summary.best_stock_return)}%</div>
                </div>
                <div>
                  <div className="text-muted-foreground uppercase tracking-wider text-[10px] mb-0.5">Worst Stock</div>
                  <div className="text-red-400 text-sm">{summary.worst_stock ?? "—"}</div>
                  <div className="text-muted-foreground/60 text-[10px]">{fmt(summary.worst_stock_return)}%</div>
                </div>
              </div>
            </div>
          )}

          {/* Table */}
          <div className="rounded border border-border bg-card overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left   px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Stock</th>
                  <th className="text-left   px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider min-w-[200px]">Selection Reason</th>
                  <th className="text-left   px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Buy Date</th>
                  <th className="text-right  px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Buy Price</th>
                  <th className="text-left   px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Sell Date</th>
                  <th className="text-right  px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Sell Price</th>
                  <th className="text-right  px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Qty</th>
                  <th className="text-right  px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Investment ₹</th>
                  <th className="text-right  px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">P&L ₹</th>
                  <th className="text-right  px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">P&L %</th>
                  <th className="text-left   px-3 py-3 font-mono text-xs text-muted-foreground uppercase tracking-wider">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((item, i) => (
                  <tr key={i} className="border-b border-border/30 hover:bg-accent/10">
                    <td className="px-3 py-2 font-mono text-xs text-foreground font-semibold">
                      {item.stock}
                      <div className="text-muted-foreground/60 text-[10px] font-normal">{item.sector}</div>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{item.selection_reason}</td>
                    <td className="px-3 py-2 font-mono text-xs">{item.buy_date}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{item.buy_price !== null ? `₹${fmt(item.buy_price)}` : "—"}</td>
                    <td className="px-3 py-2 font-mono text-xs">{item.sell_date}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{item.sell_price !== null ? `₹${fmt(item.sell_price)}` : "—"}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{item.quantity}</td>
                    <td className="px-3 py-2 text-right font-mono text-xs">{item.investment !== null ? `₹${fmt(item.investment)}` : "—"}</td>
                    <td className={cn("px-3 py-2 text-right font-mono text-xs", clrPnl(item.pnl_rupees))}>
                      {item.pnl_rupees !== null ? `${item.pnl_rupees >= 0 ? "+" : ""}₹${fmt(item.pnl_rupees)}` : "—"}
                    </td>
                    <td className={cn("px-3 py-2 text-right font-mono text-xs", clrPnl(item.pnl_pct))}>
                      {item.pnl_pct !== null ? `${item.pnl_pct >= 0 ? "+" : ""}${fmt(item.pnl_pct)}%` : "—"}
                    </td>
                    <td className="px-3 py-2">
                      {item.error ? (
                        <span className="text-[11px] font-mono text-muted-foreground/60">{item.error}</span>
                      ) : (
                        <OutcomeBadge outcome={item.outcome} />
                      )}
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
