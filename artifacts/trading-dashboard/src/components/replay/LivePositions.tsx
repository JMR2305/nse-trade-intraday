/**
 * LivePositions — V4.2
 *
 * Primary data source: `executionTrades` from the backend (real paper trades
 * enriched with stop/target/confidence/strategy).
 * Fallback: `portfolioTrades` derived from comparison data (legacy).
 *
 * Progressive display driven by activeStageIdx:
 *   stage ≥ 8 (Execution)            → show OPEN / PENDING entries
 *   stage ≥ 9 (Portfolio Management) → also reveal WIN / LOSS exits
 */
import React, { useMemo, useState } from "react";
import { TrendingUp, TrendingDown, Minus, Wallet, DollarSign, Activity, ChevronDown, ChevronUp } from "lucide-react";
import { TradeEventCard, type ExecutionTrade } from "./TradeEventCard";

const EXECUTION_STAGE_IDX  = 8;
const PORTFOLIO_STAGE_IDX  = 9;
const STARTING_CAPITAL     = 100_000;

interface LegacyTradeCard {
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

interface CompItem {
  symbol: string;
  paper_traded: boolean;
  entry_price: number | null;
  current_price: number | null;
  outcome_pct: number | null;
  status: string;
}

interface Props {
  /** Real execution trades from backend (preferred data source). */
  executionTrades?: ExecutionTrade[];
  /** Legacy trade cards derived from comparison data (fallback). */
  portfolioTrades: LegacyTradeCard[];
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

/** Compute running portfolio snapshots per trade, sorted by entry_ts.
 *  Branches on trade.action so SELL-side rows never incorrectly debit capital. */
function computePortfolioSnapshots(trades: ExecutionTrade[]): Map<string, { cash: number; invested: number; equity: number }> {
  const sorted = [...trades].sort((a, b) => (a.entry_ts ?? "").localeCompare(b.entry_ts ?? ""));
  let cash = STARTING_CAPITAL;
  let invested = 0;
  const snapshots = new Map<string, { cash: number; invested: number; equity: number }>();

  for (const t of sorted) {
    const capital = t.capital_used;
    const isBuy   = (t.action ?? "BUY").toUpperCase() !== "SELL";

    if (isBuy) {
      // BUY: debit cash, credit invested
      cash     -= capital;
      invested += capital;
      // If this BUY already has an exit recorded on the same row, close it out
      if (t.exit_price != null && t.pnl != null) {
        invested -= capital;
        cash     += capital + t.pnl;
      }
    } else {
      // SELL (exit-only ledger row): return the position's cost basis + realized P&L
      // Clamp so we never go negative from stale/mismatched data
      const costBasis = Math.min(capital, invested);
      invested = Math.max(0, invested - costBasis);
      cash    += costBasis + (t.pnl ?? 0);
    }

    snapshots.set(t.symbol, { cash: Math.max(0, cash), invested: Math.max(0, invested), equity: Math.max(0, cash + invested) });
  }
  return snapshots;
}

export function LivePositions({ executionTrades = [], portfolioTrades, activeStageIdx, comparisonData }: Props) {
  // TradeEventCard manages its own expanded/collapsed state internally.
  // No outer expansion controller needed.

  const isVisible = activeStageIdx >= EXECUTION_STAGE_IDX;
  const showExits = activeStageIdx >= PORTFOLIO_STAGE_IDX;

  // ── Prefer real execution trades ─────────────────────────────────────────
  const useRealTrades = executionTrades.length > 0;

  // Filter real trades to stages reached
  const visibleRealTrades = useMemo(() => {
    if (!useRealTrades || !isVisible) return [];
    return executionTrades.filter(t => {
      const isClosed = t.exit_price != null;
      if (isClosed && !showExits) return false;  // exits only at portfolio stage
      return true;
    });
  }, [executionTrades, isVisible, showExits, useRealTrades]);

  const portfolioSnapshots = useMemo(
    () => computePortfolioSnapshots(executionTrades),
    [executionTrades],
  );

  // ── Fallback: legacy comparison-derived trades ────────────────────────────
  const allowed = useMemo(() => {
    if (activeStageIdx >= PORTFOLIO_STAGE_IDX) return new Set(["OPEN", "PENDING", "WIN", "LOSS"]);
    if (activeStageIdx >= EXECUTION_STAGE_IDX)  return new Set(["OPEN", "PENDING"]);
    return new Set<string>();
  }, [activeStageIdx]);

  const legacyRows = useMemo(() => {
    if (useRealTrades || !isVisible) return [];
    const compMap: Record<string, CompItem> = Object.fromEntries(
      (comparisonData?.comparisons ?? []).map(c => [c.symbol, c]),
    );
    return portfolioTrades
      .filter(t => allowed.has(t.status))
      .map(t => {
        const comp    = compMap[t.symbol];
        const curPx   = comp?.current_price ?? t.exit_price ?? null;
        const unrlPnl = curPx != null ? (curPx - t.entry_price) * t.qty : t.pnl;
        const unrlPct = curPx != null ? ((curPx - t.entry_price) / t.entry_price) * 100 : t.pnl_pct;
        return { ...t, current_price: curPx, unrealised_pnl: unrlPnl, unrealised_pct: unrlPct };
      });
  }, [portfolioTrades, comparisonData, isVisible, allowed, useRealTrades]);

  // ── Running totals (real trades) ─────────────────────────────────────────
  const realTotals = useMemo(() => {
    if (!useRealTrades) return null;
    let capitalUsed = 0, netPnl = 0, openCount = 0, closedCount = 0;
    for (const t of visibleRealTrades) {
      capitalUsed += t.capital_used;
      netPnl      += t.pnl ?? 0;
      if (t.exit_price != null) closedCount++; else openCount++;
    }
    return { capitalUsed, netPnl, openCount, closedCount };
  }, [visibleRealTrades, useRealTrades]);

  // ── Legacy totals ────────────────────────────────────────────────────────
  const legacyTotals = useMemo(() => {
    const capitalUsed      = legacyRows.reduce((s, r) => s + r.capital_used, 0);
    const netUnrealisedPnl = legacyRows.reduce((s, r) => s + (r.unrealised_pnl ?? 0), 0);
    const openCount        = legacyRows.filter(r => r.status === "OPEN" || r.status === "PENDING").length;
    const closedCount      = legacyRows.filter(r => r.status === "WIN" || r.status === "LOSS").length;
    return { capitalUsed, netUnrealisedPnl, openCount, closedCount };
  }, [legacyRows]);

  // ── Pre-Execution placeholder ────────────────────────────────────────────
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

  // ── Real execution trades view ───────────────────────────────────────────
  if (useRealTrades) {
    if (visibleRealTrades.length === 0) {
      return (
        <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-6 text-center">
          <Activity size={24} className="mx-auto text-slate-700 mb-2" />
          <p className="text-slate-500 text-sm">
            {showExits ? "No paper positions found for this session" : "No entries placed yet — waiting for execution orders"}
          </p>
        </div>
      );
    }

    const t = realTotals!;
    return (
      <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden">
        {/* Header */}
        <div className="px-4 py-3 border-b border-slate-800/60 flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <TrendingUp size={14} className="text-teal-400" />
            <span className="text-sm font-semibold text-slate-200">Live Positions</span>
            <span className="px-2 py-0.5 bg-teal-900/30 border border-teal-700/40 rounded text-xs text-teal-400 font-semibold">
              {t.openCount} open · {t.closedCount} closed
            </span>
            {!showExits && (
              <span className="px-2 py-0.5 bg-amber-900/20 border border-amber-700/30 rounded text-xs text-amber-500">
                Exits visible at Portfolio stage
              </span>
            )}
          </div>
          <div className="ml-auto flex gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <DollarSign size={11} className="text-slate-500" />
              <span className="text-slate-500">Capital</span>
              <span className="font-mono font-semibold text-slate-300">
                ₹{t.capitalUsed.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              {t.netPnl >= 0
                ? <TrendingUp size={11} className="text-emerald-400" />
                : <TrendingDown size={11} className="text-red-400" />}
              <span className="text-slate-500">Net P&L</span>
              <span className={`font-mono font-semibold ${pnlColor(t.netPnl)}`}>
                {t.netPnl >= 0 ? "+" : ""}₹{Math.abs(t.netPnl).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
              </span>
            </div>
          </div>
        </div>

        {/* Trade Event Cards */}
        <div className="p-3 space-y-2 max-h-[480px] overflow-y-auto">
          {visibleRealTrades.map(trade => (
            <TradeEventCard
              key={trade.symbol}
              trade={trade}
              portfolioAfter={portfolioSnapshots.get(trade.symbol)}
              defaultExpanded={false}
            />
          ))}
        </div>
      </div>
    );
  }

  // ── Legacy fallback: table view ──────────────────────────────────────────
  if (legacyRows.length === 0) {
    return (
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-6 text-center">
        <Activity size={24} className="mx-auto text-slate-700 mb-2" />
        <p className="text-slate-500 text-sm">
          {showExits ? "No paper positions found for this session" : "No entries placed yet"}
        </p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-800/60 flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <TrendingUp size={14} className="text-teal-400" />
          <span className="text-sm font-semibold text-slate-200">Live Positions</span>
          <span className="px-2 py-0.5 bg-teal-900/30 border border-teal-700/40 rounded text-xs text-teal-400 font-semibold">
            {legacyTotals.openCount} open · {legacyTotals.closedCount} closed
          </span>
          {!showExits && (
            <span className="px-2 py-0.5 bg-amber-900/20 border border-amber-700/30 rounded text-xs text-amber-500">
              Exits visible at Portfolio stage
            </span>
          )}
        </div>
        <div className="ml-auto flex gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <DollarSign size={11} className="text-slate-500" />
            <span className="text-slate-500">Capital Used</span>
            <span className="font-mono font-semibold text-slate-300">
              ₹{legacyTotals.capitalUsed.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {legacyTotals.netUnrealisedPnl >= 0
              ? <TrendingUp size={11} className="text-emerald-400" />
              : <TrendingDown size={11} className="text-red-400" />}
            <span className="text-slate-500">Net P&L</span>
            <span className={`font-mono font-semibold ${pnlColor(legacyTotals.netUnrealisedPnl)}`}>
              {legacyTotals.netUnrealisedPnl >= 0 ? "+" : ""}
              ₹{Math.abs(legacyTotals.netUnrealisedPnl).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
            </span>
          </div>
        </div>
      </div>

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
              <th className="text-left px-3 py-2 font-semibold">Exit</th>
            </tr>
          </thead>
          <tbody>
            {legacyRows.map((row, i) => (
              <tr key={row.symbol} className={`border-b border-slate-800/40 hover:bg-slate-800/20 transition-colors ${i % 2 === 0 ? "" : "bg-slate-800/10"}`}>
                <td className="px-4 py-2.5">
                  <span className="font-mono font-semibold text-slate-200">{row.symbol}</span>
                  {row.entry_time && <div className="text-slate-600 text-xs">{row.entry_time}</div>}
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-slate-300">{row.qty}</td>
                <td className="px-3 py-2.5 text-right font-mono text-slate-300">{row.entry_price.toFixed(2)}</td>
                <td className="px-3 py-2.5 text-right font-mono">
                  {row.current_price != null ? (
                    <span className={pnlColor(row.current_price - row.entry_price)}>{row.current_price.toFixed(2)}</span>
                  ) : <span className="text-slate-600">—</span>}
                </td>
                <td className="px-3 py-2.5 text-right font-mono">
                  <span className={pnlColor(row.unrealised_pnl ?? null)}>
                    {row.unrealised_pnl != null ? `${row.unrealised_pnl >= 0 ? "+" : ""}${row.unrealised_pnl.toFixed(0)}` : "—"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right font-mono">
                  <span className={pnlColor(row.unrealised_pct ?? null)}>
                    {row.unrealised_pct != null ? `${row.unrealised_pct >= 0 ? "+" : ""}${row.unrealised_pct.toFixed(2)}%` : "—"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right font-mono text-slate-400">
                  ₹{row.capital_used.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <span className={`px-2 py-0.5 rounded border text-xs font-bold ${statusBadge(row.status)}`}>{row.status}</span>
                </td>
                <td className="px-3 py-2.5 text-left text-slate-500">
                  {row.exit_reason ?? <span className="flex items-center gap-1 text-teal-600"><Minus size={10} /> Open</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
