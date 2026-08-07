/**
 * TradeEventCard — V4.2
 * Detailed expandable card for a BUY or SELL event in the replay.
 *
 * BUY card: stock, buy time, buy price, qty, capital, stop, target,
 *           confidence, strategy, risk score, portfolio state after BUY.
 * SELL card: sell time, sell price, exit reason, holding time, P&L ₹, P&L %,
 *            portfolio state after SELL.
 */
import React, { useState } from "react";
import {
  TrendingUp, TrendingDown, ChevronDown, ChevronUp,
  Target, Shield, Brain, Clock, DollarSign,
} from "lucide-react";

export interface ExecutionTrade {
  symbol: string;
  action: string;
  entry_price: number;
  qty: number;
  capital_used: number;
  stop_loss: number | null;
  target: number | null;
  confidence: number;
  strategy: string | null;
  risk_score: number;
  entry_ts: string | null;
  exit_price: number | null;
  exit_ts: string | null;
  exit_reason: string | null;
  pnl: number | null;
  pnl_pct: number | null;
}

interface PortfolioSnapshot {
  cash: number;
  invested: number;
  equity: number;
}

interface Props {
  trade: ExecutionTrade;
  portfolioAfter?: PortfolioSnapshot;
  defaultExpanded?: boolean;
}

function fmtRs(v: number) {
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function fmtTs(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return ts; }
}

function holdingTime(entry: string | null, exit: string | null): string {
  if (!entry || !exit) return "—";
  try {
    const diff = new Date(exit).getTime() - new Date(entry).getTime();
    if (diff < 0) return "—";
    const h = Math.floor(diff / 3_600_000);
    const m = Math.floor((diff % 3_600_000) / 60_000);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  } catch { return "—"; }
}

const exitReasonColor: Record<string, string> = {
  "Target Hit":    "bg-emerald-900/30 text-emerald-400 border-emerald-700/40",
  "Stop Loss":     "bg-red-900/30 text-red-400 border-red-700/40",
  "Trailing Stop": "bg-amber-900/30 text-amber-400 border-amber-700/40",
  "AI Exit":       "bg-blue-900/30 text-blue-400 border-blue-700/40",
  "End of Day":    "bg-slate-800 text-slate-400 border-slate-600",
};

export function TradeEventCard({ trade, portfolioAfter, defaultExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const isClosed = trade.exit_price != null;
  const isWin    = (trade.pnl ?? 0) > 0;
  const pnlColor = trade.pnl == null ? "text-slate-400" : isWin ? "text-emerald-400" : "text-red-400";

  return (
    <div className={`bg-slate-900/70 border rounded-xl overflow-hidden transition-all ${
      isClosed
        ? isWin ? "border-emerald-700/40" : "border-red-700/40"
        : "border-teal-700/40"
    }`}>
      {/* ── Compact header (always visible) ── */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/30 transition-colors text-left"
      >
        {/* Direction icon */}
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
          isClosed ? (isWin ? "bg-emerald-900/40" : "bg-red-900/40") : "bg-teal-900/40"
        }`}>
          {isClosed
            ? (isWin ? <TrendingUp size={14} className="text-emerald-400" /> : <TrendingDown size={14} className="text-red-400" />)
            : <TrendingUp size={14} className="text-teal-400" />
          }
        </div>

        {/* Symbol + status */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold text-sm text-slate-100">{trade.symbol}</span>
            <span className={`text-xs px-2 py-0.5 rounded border font-semibold ${
              isClosed
                ? (isWin ? exitReasonColor["Target Hit"] : exitReasonColor["Stop Loss"])
                : "bg-teal-900/30 border-teal-600/40 text-teal-400"
            }`}>
              {isClosed ? (trade.exit_reason ?? "CLOSED") : "OPEN"}
            </span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            {trade.strategy ?? "—"} · Entry {fmtRs(trade.entry_price)} · {trade.qty} shares
          </div>
        </div>

        {/* P&L */}
        <div className={`text-right flex-shrink-0 font-mono font-bold text-sm ${pnlColor}`}>
          {trade.pnl != null
            ? `${trade.pnl >= 0 ? "+" : ""}${fmtRs(trade.pnl)}`
            : "Open"}
          {trade.pnl_pct != null && (
            <div className="text-xs font-normal">
              {trade.pnl_pct >= 0 ? "+" : ""}{trade.pnl_pct.toFixed(2)}%
            </div>
          )}
        </div>

        {expanded ? <ChevronUp size={14} className="text-slate-500 flex-shrink-0" /> : <ChevronDown size={14} className="text-slate-500 flex-shrink-0" />}
      </button>

      {/* ── Expanded detail ── */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-800/60 pt-3">
          {/* BUY details grid */}
          <div>
            <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
              <TrendingUp size={10} className="text-emerald-400" /> BUY Details
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                { icon: Clock,      label: "Buy Time",    value: fmtTs(trade.entry_ts) },
                { icon: DollarSign, label: "Buy Price",   value: `₹${trade.entry_price.toFixed(2)}` },
                { icon: DollarSign, label: "Qty",         value: String(trade.qty) },
                { icon: DollarSign, label: "Capital",     value: fmtRs(trade.capital_used) },
                { icon: Shield,     label: "Stop Loss",   value: trade.stop_loss != null ? `₹${trade.stop_loss.toFixed(2)}` : "—" },
                { icon: Target,     label: "Target",      value: trade.target    != null ? `₹${trade.target.toFixed(2)}`    : "—" },
                { icon: Brain,      label: "Confidence",  value: `${trade.confidence}%` },
                { icon: Brain,      label: "Risk Score",  value: String(trade.risk_score) },
              ].map(({ icon: Icon, label, value }) => (
                <div key={label} className="bg-slate-800/60 rounded-lg p-2">
                  <div className="flex items-center gap-1 text-xs text-slate-500 mb-0.5">
                    <Icon size={9} /> {label}
                  </div>
                  <div className="text-xs font-mono font-semibold text-slate-200">{value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* SELL details — only if closed */}
          {isClosed && (
            <div>
              <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1">
                <TrendingDown size={10} className={isWin ? "text-emerald-400" : "text-red-400"} /> SELL Details
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  { label: "Sell Time",     value: fmtTs(trade.exit_ts) },
                  { label: "Sell Price",    value: trade.exit_price != null ? `₹${trade.exit_price.toFixed(2)}` : "—" },
                  { label: "Exit Reason",   value: trade.exit_reason ?? "—" },
                  { label: "Holding Time",  value: holdingTime(trade.entry_ts, trade.exit_ts) },
                  { label: "P&L ₹",        value: trade.pnl != null ? `${trade.pnl >= 0 ? "+" : ""}₹${trade.pnl.toFixed(2)}` : "—" },
                  { label: "P&L %",        value: trade.pnl_pct != null ? `${trade.pnl_pct >= 0 ? "+" : ""}${trade.pnl_pct.toFixed(2)}%` : "—" },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-slate-800/60 rounded-lg p-2">
                    <div className="text-xs text-slate-500 mb-0.5">{label}</div>
                    <div className={`text-xs font-mono font-semibold ${
                      label.startsWith("P&L") ? pnlColor : "text-slate-200"
                    }`}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Portfolio snapshot after this trade */}
          {portfolioAfter && (
            <div className="bg-slate-800/40 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-2 font-semibold uppercase tracking-wider">
                Portfolio After {isClosed ? "SELL" : "BUY"}
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div className="text-center">
                  <div className="text-slate-600">Cash</div>
                  <div className="font-mono font-semibold text-slate-300">{fmtRs(portfolioAfter.cash)}</div>
                </div>
                <div className="text-center">
                  <div className="text-slate-600">Invested</div>
                  <div className="font-mono font-semibold text-slate-300">{fmtRs(portfolioAfter.invested)}</div>
                </div>
                <div className="text-center">
                  <div className="text-slate-600">Total</div>
                  <div className={`font-mono font-semibold ${portfolioAfter.equity >= 100_000 ? "text-emerald-400" : "text-red-400"}`}>
                    {fmtRs(portfolioAfter.equity)}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
