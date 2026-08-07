/**
 * LivePositions — V4.2
 *
 * Primary data source: `executionTrades` from the backend (real paper trades
 * enriched with stop/target/confidence/strategy).
 * Positions render exclusively from the real execution ledger; when no
 * records exist an explicit empty state is shown (nothing is synthesized).
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
/** Fallback only — the canonical value comes from the replay API
 *  (`starting_capital`, sourced from portfolio_store.INITIAL_CAPITAL). */
const DEFAULT_STARTING_CAPITAL = 50_000;

interface Props {
  /** Real execution trades from backend (preferred data source). */
  executionTrades?: ExecutionTrade[];
  activeStageIdx: number;
  /** Configured paper-trading starting capital (from the replay API). */
  startingCapital?: number;
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
function computePortfolioSnapshots(trades: ExecutionTrade[], startingCapital: number): Map<ExecutionTrade, { cash: number; invested: number; equity: number }> {
  const sorted = [...trades].sort((a, b) => (a.entry_ts ?? "").localeCompare(b.entry_ts ?? ""));
  let cash = startingCapital;
  let invested = 0;
  // Keyed by trade object reference — repeated trades in the same symbol
  // must each keep their own running balance, never overwrite each other.
  const snapshots = new Map<ExecutionTrade, { cash: number; invested: number; equity: number }>();

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

    snapshots.set(t, { cash: Math.max(0, cash), invested: Math.max(0, invested), equity: Math.max(0, cash + invested) });
  }
  return snapshots;
}

export function LivePositions({ executionTrades = [], activeStageIdx, startingCapital = DEFAULT_STARTING_CAPITAL }: Props) {
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
    () => computePortfolioSnapshots(executionTrades, startingCapital),
    [executionTrades, startingCapital],
  );

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
          {visibleRealTrades.map((trade, i) => (
            <TradeEventCard
              key={`${trade.symbol}|${trade.entry_ts ?? ""}|${i}`}
              trade={trade}
              portfolioAfter={portfolioSnapshots.get(trade)}
              defaultExpanded={false}
              startingCapital={startingCapital}
            />
          ))}
        </div>
      </div>
    );
  }

  // ── No ledger records: report honestly, never synthesize legacy rows ─────
  return (
    <div className="bg-slate-900/40 border border-amber-800/40 rounded-xl p-6 text-center">
      <Activity size={24} className="mx-auto text-amber-600 mb-2" />
      <p className="text-slate-400 text-sm font-semibold">No executed trade records found for this session</p>
      <p className="text-slate-600 text-xs mt-1">
        The paper-trade ledger has no entries for this scan. Positions are only
        displayed from real execution records — nothing is reconstructed.
      </p>
    </div>
  );
}
