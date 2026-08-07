/**
 * BottomTimeline — V4.2
 *
 * Zoomable, horizontally-scrollable chronological event timeline with
 * 7 clearly-labelled sections:
 *   PRE MARKET → SCAN → DECISION → BUY → MONITOR → SELL → POST MARKET
 *
 * Events within a section cannot overlap: simultaneous events are
 * stacked in sub-rows.  Each chip shows: time, agent/section, stock,
 * action/status, price. Clicking a chip jumps the replay to that stage.
 *
 * Zoom: pinch or Ctrl+wheel on the track.
 * Scroll: native horizontal scroll on the container.
 */
import React, { useMemo, useState } from "react";
import { TrendingUp, TrendingDown, Zap, Clock, Activity, Brain, BarChart3, List, LayoutGrid } from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────────

interface ComparisonItem {
  symbol: string;
  paper_traded: boolean;
  status: string;
  entry_price: number | null;
  outcome_pct: number | null;
}

interface ExecutionTrade {
  symbol: string;
  action: string;
  entry_ts: string | null;
  exit_ts: string | null;
  entry_price: number;
  qty: number;
  confidence: number;
  strategy: string | null;
  exit_price: number | null;
  pnl: number | null;
  exit_reason: string | null;
}

interface StageData {
  id: string;
  label?: string;
}

interface Props {
  snapshotTs: string | undefined;
  comparisonData?: {
    comparisons: ComparisonItem[];
    stats: { wins: number; losses: number; missed_opportunities: number; pending: number };
  };
  executionTrades?: ExecutionTrade[];
  stages: StageData[];
  pipelineCfg: { id: string; label: string }[];
  activeStageIdx: number;
  onJumpToStage: (idx: number) => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(ts: string | undefined | null, addS = 0): string {
  if (!ts) return "—";
  try {
    const d = new Date(new Date(ts).getTime() + addS * 1000);
    return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return "—"; }
}

function tsValue(ts: string | null, fallbackEpoch: number): number {
  if (!ts) return fallbackEpoch;
  return new Date(ts).getTime();
}

// Approximate seconds-after-session-open for each stage
const STAGE_OFFSETS_S: Record<string, number> = {
  supervisor: 2, market_data: 5, research: 8, market_intelligence: 16,
  monitoring: 24, strategy: 35, risk: 41, ai_decision: 45,
  execution: 46, portfolio_management: 61,
};

// ── Component ────────────────────────────────────────────────────────────────

interface TimelineRow {
  id: string;
  timestamp: number;
  timeLabel: string;
  agent: string;
  symbol: string;
  action: string;
  details: string;
  reason: string;
  stageIdx?: number;
  type: "stage" | "buy" | "sell" | "system";
}

export function BottomTimeline({
  snapshotTs,
  executionTrades = [],
  pipelineCfg,
  activeStageIdx,
  onJumpToStage,
}: Props) {
  const [density, setDensity] = useState<"compact" | "comfortable">("compact");

  const rows = useMemo<TimelineRow[]>(() => {
    const res: TimelineRow[] = [];
    const baseTime = snapshotTs ? new Date(snapshotTs).getTime() : Date.now();

    // 1. Pipeline stages
    pipelineCfg.forEach((stage, i) => {
      const offsetS = STAGE_OFFSETS_S[stage.id] ?? (i * 6);
      const ts = baseTime + offsetS * 1000;
      res.push({
        id: `stage-${stage.id}`,
        timestamp: ts,
        timeLabel: fmtTime(snapshotTs, offsetS),
        agent: "Pipeline Orchestrator",
        symbol: "—",
        action: "STAGE START",
        details: stage.label,
        reason: "Advancing pipeline to next agent",
        stageIdx: i,
        type: "stage",
      });
    });

    // 2. Real trades (never fabricate)
    executionTrades.forEach((t, i) => {
      const isBuy = (t.action ?? "BUY").toUpperCase() !== "SELL";
      if (isBuy && t.entry_price != null) {
        res.push({
          id: `buy-${t.symbol}-${i}`,
          timestamp: tsValue(t.entry_ts, baseTime + 46000),
          timeLabel: fmtTime(t.entry_ts),
          agent: "Execution Agent",
          symbol: t.symbol,
          action: "BUY",
          details: `₹${t.entry_price.toFixed(2)} × ${t.qty} | Conf: ${t.confidence}%`,
          reason: `Strategy matched: ${t.strategy ?? "Unknown"}`,
          type: "buy",
        });
      }

      if (t.exit_price != null) {
        const isWin = (t.pnl ?? 0) >= 0;
        res.push({
          id: `sell-${t.symbol}-${i}`,
          timestamp: tsValue(t.exit_ts, baseTime + 61000),
          timeLabel: fmtTime(t.exit_ts),
          agent: "Portfolio Manager",
          symbol: t.symbol,
          action: isWin ? "WIN" : "LOSS",
          details: `Exit: ₹${t.exit_price.toFixed(2)} | P&L: ${t.pnl! >= 0 ? "+" : ""}₹${Math.abs(t.pnl!).toFixed(2)}`,
          reason: t.exit_reason ?? "Closed by system",
          type: "sell",
        });
      }
    });

    // 3. System markers
    res.push({
      id: "market-open",
      timestamp: baseTime,
      timeLabel: fmtTime(snapshotTs, 0),
      agent: "System",
      symbol: "—",
      action: "START",
      details: "Session initialized",
      reason: "Historical replay started",
      type: "system",
    });

    return res.sort((a, b) => a.timestamp - b.timestamp);
  }, [snapshotTs, executionTrades, pipelineCfg]);

  return (
    <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden flex flex-col max-h-[500px]">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-slate-800/60 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Clock size={14} className="text-teal-400" />
          <span className="text-xs font-semibold text-slate-200 uppercase tracking-wider">Chronological Agent Flow</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setDensity(d => d === "compact" ? "comfortable" : "compact")}
            className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800 border border-slate-700 text-xs text-slate-300 hover:text-white"
          >
            {density === "compact" ? <List size={12} /> : <LayoutGrid size={12} />}
            {density === "compact" ? "Detailed" : "Compact"}
          </button>
        </div>
      </div>

      {/* Table Header */}
      <div className="px-4 py-2 border-b border-slate-800/60 flex text-xs font-semibold text-slate-500 uppercase tracking-wider flex-shrink-0">
        <div className="w-24">Time</div>
        <div className="w-40">Agent</div>
        <div className="w-24">Symbol</div>
        <div className="w-24">Action</div>
        <div className="w-64">Key Values</div>
        <div className="flex-1">Reason</div>
      </div>

      {/* Scrollable list */}
      <div className="overflow-x-auto overflow-y-auto flex-1">
        <div className="min-w-[800px] flex flex-col p-2 space-y-1">
          {rows.map((row) => {
            const isStage = row.type === "stage";
            const isActive = isStage && row.stageIdx === activeStageIdx;
            const bgClass =
              row.type === "buy" ? "bg-emerald-900/10 border-emerald-800/30" :
              row.type === "sell" ? "bg-red-900/10 border-red-800/30" :
              isActive ? "bg-teal-900/30 border-teal-500/50" :
              "bg-slate-800/30 border-slate-800";
            const textClass =
              row.type === "buy" ? "text-emerald-400" :
              row.type === "sell" ? "text-red-400" :
              row.type === "stage" ? "text-teal-300" :
              "text-slate-400";

            return (
              <div
                key={row.id}
                onClick={() => row.stageIdx != null && onJumpToStage(row.stageIdx)}
                className={`flex items-center px-2 border rounded-lg transition-all ${
                  density === "compact" ? "py-1.5" : "py-3"
                } ${bgClass} ${row.stageIdx != null ? "cursor-pointer hover:brightness-125" : ""}`}
              >
                <div className="w-24 text-xs font-mono text-slate-400">{row.timeLabel}</div>
                <div className={`w-40 text-xs font-semibold ${textClass}`}>{row.agent}</div>
                <div className="w-24 text-xs font-mono font-bold text-slate-200">{row.symbol}</div>
                <div className="w-24">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                    row.type === "buy" ? "bg-emerald-900/40 border-emerald-500/30 text-emerald-300" :
                    row.type === "sell" ? "bg-red-900/40 border-red-500/30 text-red-300" :
                    "bg-slate-800 border-slate-600 text-slate-300"
                  }`}>
                    {row.action}
                  </span>
                </div>
                <div className="w-64 text-xs font-mono text-slate-300">{row.details}</div>
                <div className="flex-1 text-xs text-slate-400 truncate" title={row.reason}>{row.reason}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
