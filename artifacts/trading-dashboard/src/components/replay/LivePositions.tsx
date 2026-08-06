/**
 * LivePositions — V5.0
 * Progressive position tracker driven by activeStageIdx:
 *   stage 8 (Execution)           → show OPEN / PENDING entries (buys placed)
 *   stage 9 (Portfolio Management) → also reveal WIN / LOSS exits (positions closed)
 *
 * Before stage 8: shows a placeholder encouraging the operator to advance the replay.
 */
import React, { useMemo } from "react";
import { TrendingUp, TrendingDown, Minus, Wallet, DollarSign, Activity } from "lucide-react";

// Stage indices (0-based) — hardcoded to avoid circular import with main page file
const EXECUTION_STAGE_IDX       = 8;  // "execution"
const PORTFOLIO_STAGE_IDX       = 9;  // "portfolio_management"

interface CompItem {
  symbol: string;
  paper_traded: boolean;
  entry_price: number | null;
  current_price: number | null;
  outcome_pct: number | null;
  status: string;
}

interface TradeCard {
  symbol: string;
  entry_price: number;
  exit_price: number | null;
  qty: number;
  capital_used: number;
  stop_loss: number | null;
  target: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  status: "OPEN" | "WIN" | "LOSS" | "PENDING";
  exit_reason: string | null;
  entry_time: string | null;
  exit_time: string | null;
}

interface Props {
  portfolioTrades: TradeCard[];
  activeStageIdx: number;
  comparisonData?: {
    comparisons: CompItem[];
    stats: { wins: number; losses: number; missed_opportunities: number; pending: number };
  };
}

function pnlColor(v: number | null): string {
  if (v === null) return "text-slate-400";
  return v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : "text-slate-400";
}

function statusBadge(status: string): string {
  switch (status) {
    case "WIN":     return "bg-emerald-900/30 border-emerald-600/40 text-emerald-400";
    case "LOSS":    return "bg-red-900/30 border-red-600/40 text-red-400";
    case "OPEN":    return "bg-teal-900/30 border-teal-600/40 text-teal-400";
    case "PENDING": return "bg-amber-900/30 border-amber-600/40 text-amber-400";
    default:        return "bg-slate-800/40 border-slate-700/40 text-slate-400";
  }
}

/** Statuses visible at each replay stage. */
function visibleStatuses(activeStageIdx: number): Set<string> {
  if (activeStageIdx >= PORTFOLIO_STAGE_IDX) {
    // All positions visible: entries AND exits
    return new Set(["OPEN", "PENDING", "WIN", "LOSS"]);
  }
  if (activeStageIdx >= EXECUTION_STAGE_IDX) {
    // Only entries (buys placed, not yet closed)
    return new Set(["OPEN", "PENDING"]);
  }
  return new Set(); // not yet reached Execution
}

export function LivePositions({ portfolioTrades, activeStageIdx, comparisonData }: Props) {
  const isVisible = activeStageIdx >= EXECUTION_STAGE_IDX;
  const showExits = activeStageIdx >= PORTFOLIO_STAGE_IDX;
  const allowed   = visibleStatuses(activeStageIdx);

  // Build enriched rows, filtered to stages currently reached
  const positionRows = useMemo(() => {
    if (!isVisible) return [];
    const compMap: Record<string, CompItem> = Object.fromEntries(
      (comparisonData?.comparisons ?? []).map(c => [c.symbol, c]),
    );
    return portfolioTrades
      .filter(trade => allowed.has(trade.status))
      .map(trade => {
        const comp    = compMap[trade.symbol];
        const curPx   = comp?.current_price ?? trade.exit_price ?? null;
        const unrlPnl = curPx != null
          ? (curPx - trade.entry_price) * trade.qty
          : trade.pnl;
        const unrlPct = curPx != null
          ? ((curPx - trade.entry_price) / trade.entry_price) * 100
          : trade.pnl_pct;
        return { ...trade, current_price: curPx, unrealised_pnl: unrlPnl, unrealised_pct: unrlPct };
      });
  }, [portfolioTrades, comparisonData, isVisible, showExits, activeStageIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  // Running totals
  const totals = useMemo(() => {
    const capitalUsed      = positionRows.reduce((s, r) => s + r.capital_used, 0);
    const netUnrealisedPnl = positionRows.reduce((s, r) => s + (r.unrealised_pnl ?? 0), 0);
    const openCount        = positionRows.filter(r => r.status === "OPEN" || r.status === "PENDING").length;
    const closedCount      = positionRows.filter(r => r.status === "WIN" || r.status === "LOSS").length;
    return { capitalUsed, netUnrealisedPnl, openCount, closedCount };
  }, [positionRows]);

  // ── Pre-Execution placeholder ──
  if (!isVisible) {
    return (
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-6 text-center">
        <Wallet size={28} className="mx-auto text-slate-700 mb-2" />
        <p className="text-slate-500 text-sm">
          Live positions appear when replay reaches the <span className="text-teal-500 font-semibold">Execution</span> stage
        </p>
        <p className="text-slate-600 text-xs mt-1">
          {activeStageIdx < 0
            ? "Press Play to start the replay"
            : `Waiting for stage ${EXECUTION_STAGE_IDX + 1} — currently at stage ${activeStageIdx + 1}`}
        </p>
      </div>
    );
  }

  // ── At Execution but no rows yet (no paper trades) ──
  if (positionRows.length === 0) {
    return (
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-6 text-center">
        <Activity size={24} className="mx-auto text-slate-700 mb-2" />
        <p className="text-slate-500 text-sm">
          {showExits
            ? "No paper positions found for this session"
            : "No entries placed yet — waiting for execution orders"}
        </p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800/60 flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-teal-400" />
          <span className="text-sm font-semibold text-slate-200">Live Positions</span>
          <span className="px-2 py-0.5 bg-teal-900/30 border border-teal-700/40 rounded text-xs text-teal-400 font-semibold">
            {totals.openCount} open · {totals.closedCount} closed
          </span>
          {!showExits && (
            <span className="px-2 py-0.5 bg-amber-900/20 border border-amber-700/30 rounded text-xs text-amber-500">
              Exits visible at Portfolio stage
            </span>
          )}
        </div>

        {/* Running totals */}
        <div className="ml-auto flex gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <DollarSign size={11} className="text-slate-500" />
            <span className="text-slate-500">Capital Used</span>
            <span className="font-mono font-semibold text-slate-300">
              ₹{totals.capitalUsed.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {totals.netUnrealisedPnl >= 0 ? (
              <TrendingUp size={11} className="text-emerald-400" />
            ) : (
              <TrendingDown size={11} className="text-red-400" />
            )}
            <span className="text-slate-500">Net P&L</span>
            <span className={`font-mono font-semibold ${pnlColor(totals.netUnrealisedPnl)}`}>
              {totals.netUnrealisedPnl >= 0 ? "+" : ""}
              ₹{Math.abs(totals.netUnrealisedPnl).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </span>
          </div>
        </div>
      </div>

      {/* Positions table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-800/60 text-slate-500 uppercase tracking-wider">
              <th className="text-left px-4 py-2 font-semibold">Symbol</th>
              <th className="text-right px-3 py-2 font-semibold">Qty</th>
              <th className="text-right px-3 py-2 font-semibold">Entry ₹</th>
              <th className="text-right px-3 py-2 font-semibold">Current ₹</th>
              <th className="text-right px-3 py-2 font-semibold">P&amp;L ₹</th>
              <th className="text-right px-3 py-2 font-semibold">P&amp;L %</th>
              <th className="text-right px-3 py-2 font-semibold">Capital</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
              <th className="text-left px-3 py-2 font-semibold">Exit Reason</th>
            </tr>
          </thead>
          <tbody>
            {positionRows.map((row, i) => (
              <tr
                key={row.symbol}
                className={`border-b border-slate-800/40 hover:bg-slate-800/20 transition-colors ${
                  i % 2 === 0 ? "bg-transparent" : "bg-slate-800/10"
                }`}
              >
                <td className="px-4 py-2.5">
                  <span className="font-mono font-semibold text-slate-200">{row.symbol}</span>
                  {row.entry_time && (
                    <div className="text-slate-600 text-xs">{row.entry_time}</div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-slate-300">{row.qty}</td>
                <td className="px-3 py-2.5 text-right font-mono text-slate-300">
                  {row.entry_price.toFixed(2)}
                </td>
                <td className="px-3 py-2.5 text-right font-mono">
                  {row.current_price != null ? (
                    <span className={pnlColor(row.current_price - row.entry_price)}>
                      {row.current_price.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right font-mono">
                  <span className={pnlColor(row.unrealised_pnl ?? null)}>
                    {row.unrealised_pnl != null
                      ? `${row.unrealised_pnl >= 0 ? "+" : ""}${row.unrealised_pnl.toFixed(0)}`
                      : "—"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right font-mono">
                  <span className={pnlColor(row.unrealised_pct ?? null)}>
                    {row.unrealised_pct != null
                      ? `${row.unrealised_pct >= 0 ? "+" : ""}${row.unrealised_pct.toFixed(2)}%`
                      : "—"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-slate-400">
                  ₹{row.capital_used.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <span className={`px-2 py-0.5 rounded border text-xs font-bold ${statusBadge(row.status)}`}>
                    {row.status}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-left text-slate-500">
                  {row.exit_reason ?? (
                    <span className="flex items-center gap-1 text-teal-600">
                      <Minus size={10} /> Open
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
