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
import React, { useMemo, useRef, useCallback } from "react";
import { TrendingUp, TrendingDown, Zap, Clock, Activity, Brain, BarChart3 } from "lucide-react";

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
  action: string;       // "BUY" | "SELL" — determines which section the chip appears in
  entry_ts: string | null;
  exit_ts: string | null;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  exit_reason: string | null;
}

interface StageData {
  id: string;
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

// ── Section definitions ───────────────────────────────────────────────────────

const SECTIONS = [
  { id: "pre_market", label: "PRE MARKET", icon: Clock,      color: "text-slate-400",   bg: "bg-slate-800/30",   border: "border-slate-700/40",   dot: "bg-slate-500" },
  { id: "scan",       label: "SCAN",       icon: Activity,    color: "text-teal-400",    bg: "bg-teal-900/10",    border: "border-teal-700/30",    dot: "bg-teal-500"  },
  { id: "decision",   label: "DECISION",   icon: Brain,       color: "text-blue-400",    bg: "bg-blue-900/10",    border: "border-blue-700/30",    dot: "bg-blue-500"  },
  { id: "buy",        label: "BUY",        icon: TrendingUp,  color: "text-emerald-400", bg: "bg-emerald-900/10", border: "border-emerald-700/30", dot: "bg-emerald-500" },
  { id: "monitor",    label: "MONITOR",    icon: BarChart3,   color: "text-amber-400",   bg: "bg-amber-900/10",   border: "border-amber-700/30",   dot: "bg-amber-500" },
  { id: "sell",       label: "SELL",       icon: TrendingDown,color: "text-red-400",     bg: "bg-red-900/10",     border: "border-red-700/30",     dot: "bg-red-500"   },
  { id: "post_market",label: "POST MARKET",icon: Zap,         color: "text-purple-400",  bg: "bg-purple-900/10",  border: "border-purple-700/30",  dot: "bg-purple-500"},
] as const;

// Stage ID → section
const STAGE_SECTION: Record<string, typeof SECTIONS[number]["id"]> = {
  supervisor:          "scan",
  market_data:         "scan",
  research:            "scan",
  market_intelligence: "scan",
  monitoring:          "scan",
  strategy:            "scan",
  risk:                "scan",
  ai_decision:         "decision",
  execution:           "decision",
  portfolio_management:"monitor",
};

// Approximate seconds-after-session-open for each stage (mirrors main file)
const STAGE_OFFSETS_S: Record<string, number> = {
  supervisor: 2, market_data: 5, research: 8, market_intelligence: 16,
  monitoring: 24, strategy: 35, risk: 41, ai_decision: 45,
  execution: 46, portfolio_management: 61,
};

// NSE market hours in seconds after 09:15
const MARKET_OPEN_S  = 0;         // 09:15
const MARKET_CLOSE_S = 22_500;    // 15:30 (6h 15m)

// ── Event model ──────────────────────────────────────────────────────────────

interface TimelineEvent {
  id: string;
  sectionId: typeof SECTIONS[number]["id"];
  label: string;
  sublabel: string;
  secondsFromOpen: number;   // 0 = market open (09:15)
  stageIdx?: number;
  kind: "open" | "close" | "stage" | "buy" | "sell" | "monitor";
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(ts: string | undefined | null, addS = 0): string {
  if (!ts) return "—";
  try {
    const d = new Date(new Date(ts).getTime() + addS * 1000);
    return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" });
  } catch { return "—"; }
}

function tsToSecondsFromOpen(ts: string | null, snapshotTs: string | undefined): number | null {
  if (!ts || !snapshotTs) return null;
  try {
    const snap = new Date(snapshotTs);
    const baseOpen = new Date(snap);
    baseOpen.setHours(9, 15, 0, 0);
    const diff = (new Date(ts).getTime() - baseOpen.getTime()) / 1000;
    return Math.max(0, diff);
  } catch { return null; }
}

// ── Component ────────────────────────────────────────────────────────────────

export function BottomTimeline({
  snapshotTs,
  comparisonData,
  executionTrades = [],
  pipelineCfg,
  activeStageIdx,
  onJumpToStage,
}: Props) {
  const scrollRef  = useRef<HTMLDivElement>(null);
  const scaleRef   = useRef(1);

  // ── Build event list ───────────────────────────────────────────────────────
  const events = useMemo<TimelineEvent[]>(() => {
    const result: TimelineEvent[] = [];

    // Pre-market marker
    result.push({
      id: "pre-open", sectionId: "pre_market",
      label: "Market Open", sublabel: "09:15 IST",
      secondsFromOpen: 0, kind: "open",
    });

    // Scan / Decision pipeline stages
    pipelineCfg.forEach((stage, i) => {
      const offsetS = STAGE_OFFSETS_S[stage.id] ?? (i * 6);
      const sectionId = STAGE_SECTION[stage.id] ?? "scan";
      result.push({
        id: `stage-${stage.id}`,
        sectionId,
        label: stage.label,
        sublabel: fmtTime(snapshotTs, offsetS),
        secondsFromOpen: offsetS,
        stageIdx: i,
        kind: "stage",
      });
    });

    // BUY events from real execution trades first, then comparison fallback.
    // Filter by action so SELL-side ledger rows don't appear as BUY chips.
    const isBuyRow = (t: ExecutionTrade) => (t.action ?? "BUY").toUpperCase() !== "SELL";
    const executionBuys = executionTrades.filter(t => isBuyRow(t) && t.entry_price != null);
    if (executionBuys.length > 0) {
      const execIdx = pipelineCfg.findIndex(s => s.id === "execution");
      executionBuys.forEach((t, i) => {
        const sFromOpen = tsToSecondsFromOpen(t.entry_ts, snapshotTs) ?? (900 + i * 300);
        result.push({
          id: `buy-${t.symbol}-${i}`,
          sectionId: "buy",
          label: `BUY ${t.symbol}`,
          sublabel: `₹${t.entry_price.toFixed(1)}`,
          secondsFromOpen: sFromOpen,
          stageIdx: execIdx >= 0 ? execIdx : undefined,
          kind: "buy",
        });
      });

      // SELL events: BUY rows that already have an exit price recorded,
      // plus any explicit SELL-side ledger rows.
      const portIdx = pipelineCfg.findIndex(s => s.id === "portfolio_management");
      const sellCandidates = [
        ...executionTrades.filter(t => isBuyRow(t) && t.exit_price != null),  // closed BUY rows
        ...executionTrades.filter(t => !isBuyRow(t)),                          // SELL-side rows
      ];
      sellCandidates.forEach((t, i) => {
        const ts = !isBuyRow(t) ? t.entry_ts : t.exit_ts;
        const sFromOpen = tsToSecondsFromOpen(ts, snapshotTs) ?? (3600 + i * 600);
        const isWin = (t.pnl ?? 0) >= 0;
        result.push({
          id: `sell-${t.symbol}-${i}`,
          sectionId: "sell",
          label: `${isWin ? "WIN" : "LOSS"} ${t.symbol}`,
          sublabel: t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}₹${Math.abs(t.pnl).toFixed(0)}` : "",
          secondsFromOpen: sFromOpen,
          stageIdx: portIdx >= 0 ? portIdx : undefined,
          kind: "sell",
        });
      });
    } else {
      // Fallback to comparison data (staggered synthetic timestamps)
      const paperItems = (comparisonData?.comparisons ?? []).filter(c => c.paper_traded && c.entry_price != null);
      const execIdx = pipelineCfg.findIndex(s => s.id === "execution");
      paperItems.forEach((item, i) => {
        result.push({
          id: `buy-${item.symbol}`,
          sectionId: "buy",
          label: `BUY ${item.symbol}`,
          sublabel: item.entry_price != null ? `₹${item.entry_price.toFixed(1)}` : "",
          secondsFromOpen: 900 + i * 300,
          stageIdx: execIdx >= 0 ? execIdx : undefined,
          kind: "buy",
        });
      });

      const closedItems = (comparisonData?.comparisons ?? []).filter(c => c.paper_traded && (c.status === "WIN" || c.status === "LOSS"));
      const portIdx = pipelineCfg.findIndex(s => s.id === "portfolio_management");
      closedItems.forEach((item, i) => {
        result.push({
          id: `sell-${item.symbol}`,
          sectionId: "sell",
          label: `${item.status} ${item.symbol}`,
          sublabel: item.outcome_pct != null ? `${item.outcome_pct >= 0 ? "+" : ""}${item.outcome_pct.toFixed(1)}%` : "",
          secondsFromOpen: 3600 + i * 600,
          stageIdx: portIdx >= 0 ? portIdx : undefined,
          kind: "sell",
        });
      });
    }

    // Monitor / post-market
    result.push({
      id: "market-close", sectionId: "post_market",
      label: "Market Close", sublabel: "15:30 IST",
      secondsFromOpen: MARKET_CLOSE_S, kind: "close",
    });

    return result.sort((a, b) => a.secondsFromOpen - b.secondsFromOpen);
  }, [snapshotTs, comparisonData, executionTrades, pipelineCfg]);

  // ── Group events by section ───────────────────────────────────────────────
  const eventsBySection = useMemo(() => {
    const map = new Map<string, TimelineEvent[]>();
    for (const sec of SECTIONS) map.set(sec.id, []);
    for (const ev of events) {
      const arr = map.get(ev.sectionId);
      if (arr) arr.push(ev);
    }
    return map;
  }, [events]);

  // ── Zoom via Ctrl+wheel ───────────────────────────────────────────────────
  const handleWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.85 : 1.18;
    scaleRef.current = Math.min(4, Math.max(0.5, scaleRef.current * delta));
    if (scrollRef.current) {
      scrollRef.current.style.minWidth = `${Math.round(1200 * scaleRef.current)}px`;
    }
  }, []);

  // ── Horizontal position for an event within its section row ──────────────
  function xPct(secondsFromOpen: number): number {
    return Math.min(99, Math.max(1, (secondsFromOpen / MARKET_CLOSE_S) * 100));
  }

  // ── De-overlap: assign sub-row index so chips don't stack on same pixel ──
  function deOverlap(evs: TimelineEvent[]): { ev: TimelineEvent; row: number }[] {
    // Bucket by integer-percent position; each bucket picks next available row
    const rowByBucket: Record<number, number> = {};
    return evs.map(ev => {
      const bucket = Math.round(xPct(ev.secondsFromOpen));
      const row = rowByBucket[bucket] ?? 0;
      rowByBucket[bucket] = row + 1;
      return { ev, row };
    });
  }

  return (
    <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-slate-800/60 flex items-center gap-3 flex-wrap">
        <Clock size={13} className="text-teal-400" />
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Event Timeline</span>
        <span className="text-xs text-slate-600 ml-2">Ctrl+scroll to zoom · scroll to pan</span>
        <div className="ml-auto flex gap-4 text-xs text-slate-600">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-teal-500 inline-block" />Scan</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />Decision</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />BUY</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" />SELL</span>
        </div>
      </div>

      {/* Scrollable track */}
      <div
        ref={scrollRef}
        className="overflow-x-auto"
        onWheel={handleWheel}
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        <div style={{ minWidth: "1200px" }} className="px-2 py-2 space-y-0.5">
          {SECTIONS.map(sec => {
            const secEvents = eventsBySection.get(sec.id) ?? [];
            const deOverlapped = deOverlap(secEvents);
            const maxRow = Math.max(0, ...deOverlapped.map(d => d.row));
            const rowH = 26; // px per sub-row
            const sectionH = Math.max(rowH, (maxRow + 1) * rowH);
            const Icon = sec.icon;

            return (
              <div key={sec.id} className={`flex border ${sec.border} rounded-lg overflow-hidden`}>
                {/* Section label */}
                <div className={`${sec.bg} flex-shrink-0 flex items-center justify-center w-24 border-r ${sec.border}`}>
                  <div className="flex flex-col items-center gap-0.5 px-1">
                    <Icon size={10} className={sec.color} />
                    <span className={`text-xs font-bold tracking-wider ${sec.color}`} style={{ fontSize: "9px" }}>
                      {sec.label}
                    </span>
                  </div>
                </div>

                {/* Event track */}
                <div className={`flex-1 relative ${sec.bg}`} style={{ height: `${sectionH}px` }}>
                  {/* Track line */}
                  <div className="absolute left-0 right-0 h-px bg-slate-700/30" style={{ top: "50%" }} />

                  {/* Events */}
                  {deOverlapped.map(({ ev, row }) => {
                    const isActive = ev.stageIdx != null && ev.stageIdx === activeStageIdx;
                    const topPx = row * rowH + 4;

                    const chipStyle = ev.kind === "buy"
                      ? "bg-emerald-900/60 border-emerald-600/60 text-emerald-300 hover:bg-emerald-800/60"
                      : ev.kind === "sell"
                      ? "bg-red-900/60 border-red-600/60 text-red-300 hover:bg-red-800/60"
                      : ev.kind === "stage" || ev.kind === "open" || ev.kind === "close"
                      ? `${sec.bg} border-current ${sec.color} hover:brightness-125`
                      : "bg-slate-800/60 border-slate-600 text-slate-400";

                    return (
                      <button
                        key={ev.id}
                        onClick={() => ev.stageIdx != null && onJumpToStage(ev.stageIdx)}
                        disabled={ev.stageIdx == null}
                        title={`${ev.label}${ev.sublabel ? " — " + ev.sublabel : ""}${ev.stageIdx != null ? " (click to jump)" : ""}`}
                        className={`absolute flex items-center gap-1 px-1.5 py-0.5 rounded border text-xs font-mono font-medium
                          transition-all cursor-pointer disabled:cursor-default select-none whitespace-nowrap
                          -translate-x-1/2 ${chipStyle}
                          ${isActive ? "ring-2 ring-offset-1 ring-offset-slate-900 ring-teal-400 z-20" : "z-10"}
                          hover:z-30 hover:scale-105`}
                        style={{
                          left: `${xPct(ev.secondsFromOpen)}%`,
                          top:  `${topPx}px`,
                          fontSize: "10px",
                          maxWidth: "120px",
                        }}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${sec.dot}`} />
                        <span className="truncate">{ev.label}</span>
                        {ev.sublabel && (
                          <span className="text-slate-500 font-normal ml-0.5 truncate hidden sm:inline">
                            {ev.sublabel}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Progress indicator */}
      {activeStageIdx >= 0 && (
        <div className="px-4 pb-2 text-xs text-slate-600 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse inline-block" />
          Replay at: {pipelineCfg[activeStageIdx]?.label ?? "—"}
        </div>
      )}
    </div>
  );
}
