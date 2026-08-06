/**
 * BottomTimeline — V5.0
 * Horizontal event timeline: Market Open → scan stages → BUY events → SELL events → Market Close.
 * Clicking any pin jumps the replay to the nearest stage.
 *
 * Two-zone scale so scan-stage pins (2–61 s) are never compressed into the first 2 px:
 *   Zone A  0–35 %  → scan-session offsets   0–120 s (pre-market pipeline)
 *   Zone B 35–100 % → intraday market time 0–22,500 s (09:15–15:30 IST trades)
 */
import React, { useMemo, useRef, useEffect } from "react";
import { TrendingUp, TrendingDown, Zap, Clock, Activity } from "lucide-react";

// Approximate per-stage second-offsets from session start (mirrors STAGE_OFFSETS_S in main file)
const LOCAL_STAGE_OFFSETS: Record<string, number> = {
  supervisor:           2,
  market_data:          5,
  research:             8,
  market_intelligence: 16,
  monitoring:          24,
  strategy:            35,
  risk:                41,
  ai_decision:         45,
  execution:           46,
  portfolio_management: 61,
};

// Zone boundaries
const SCAN_ZONE_MAX_S   = 120;   // seconds — all stage offsets must be < this
const SCAN_ZONE_PCT     = 35;    // % of track width dedicated to scan zone

// Total NSE trading window in seconds: 09:15 → 15:30 = 6h 15m
const TRADING_WINDOW_S  = 6.25 * 3600; // 22,500 s

/**
 * Two-zone piecewise percentage mapping:
 *   [0, SCAN_ZONE_MAX_S]   → [0, SCAN_ZONE_PCT]%
 *   [SCAN_ZONE_MAX_S, TRADING_WINDOW_S] → [SCAN_ZONE_PCT, 100]%
 */
function twoZonePct(secondsAfterSessionOpen: number): number {
  const s = Math.max(0, secondsAfterSessionOpen);
  if (s <= SCAN_ZONE_MAX_S) {
    return (s / SCAN_ZONE_MAX_S) * SCAN_ZONE_PCT;
  }
  const tradeFraction = (s - SCAN_ZONE_MAX_S) / (TRADING_WINDOW_S - SCAN_ZONE_MAX_S);
  return SCAN_ZONE_PCT + Math.min(tradeFraction, 1) * (100 - SCAN_ZONE_PCT);
}

interface ComparisonItem {
  symbol: string;
  paper_traded: boolean;
  status: string;
  entry_price: number | null;
  outcome_pct: number | null;
}

interface StageData {
  id: string;
}

type PinKind = "open" | "scan" | "buy" | "sell" | "close" | "stage";

interface TimelinePin {
  id: string;
  kind: PinKind;
  label: string;
  sublabel?: string;
  pct: number;       // 0–100 horizontal %
  stageIdx?: number; // which PIPELINE_STAGES index to jump to
}

interface Props {
  snapshotTs: string | undefined;
  comparisonData?: {
    comparisons: ComparisonItem[];
    stats: { wins: number; losses: number; missed_opportunities: number; pending: number };
  };
  stages: StageData[];
  pipelineCfg: { id: string; label: string }[];
  activeStageIdx: number;
  onJumpToStage: (idx: number) => void;
}

function fmtTime(ts: string | undefined, extraS = 0): string {
  if (!ts) return "";
  try {
    const d = new Date(new Date(ts).getTime() + extraS * 1000);
    return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

const PIN_STYLE: Record<PinKind, { dot: string; line: string; label: string }> = {
  open:  { dot: "bg-slate-400 border-slate-300",    line: "bg-slate-500",   label: "text-slate-400" },
  scan:  { dot: "bg-teal-400 border-teal-300",       line: "bg-teal-500",    label: "text-teal-400" },
  stage: { dot: "bg-blue-400 border-blue-300",       line: "bg-blue-500",    label: "text-blue-400" },
  buy:   { dot: "bg-emerald-400 border-emerald-300", line: "bg-emerald-500", label: "text-emerald-400" },
  sell:  { dot: "bg-red-400 border-red-300",         line: "bg-red-500",     label: "text-red-400" },
  close: { dot: "bg-slate-400 border-slate-300",     line: "bg-slate-500",   label: "text-slate-400" },
};

const PIN_ICON: Record<PinKind, React.FC<{ size: number; className?: string }>> = {
  open:  Activity,
  scan:  Zap,
  stage: Zap,
  buy:   TrendingUp,
  sell:  TrendingDown,
  close: Clock,
};

// Zone A divider — shows "| Intraday →" separator on the track
const ZONE_DIVIDER_PCT = SCAN_ZONE_PCT;

export function BottomTimeline({
  snapshotTs,
  comparisonData,
  pipelineCfg,
  activeStageIdx,
  onJumpToStage,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const pins = useMemo<TimelinePin[]>(() => {
    const result: TimelinePin[] = [];

    // Market Open — left edge
    result.push({ id: "open", kind: "open", label: "Market Open", sublabel: "09:15 IST", pct: 0 });

    // Pipeline scan stages — Zone A (0–35%)
    pipelineCfg.forEach((stage, i) => {
      const offsetS = LOCAL_STAGE_OFFSETS[stage.id] ?? (i * 10);
      result.push({
        id: `stage-${stage.id}`,
        kind: "scan",
        label: stage.label,
        sublabel: fmtTime(snapshotTs, offsetS),
        pct: twoZonePct(offsetS),
        stageIdx: i,
      });
    });

    // BUY events — Zone B, staggered from 15 min after open
    const paperItems = (comparisonData?.comparisons ?? []).filter(
      c => c.paper_traded && c.entry_price != null,
    );
    const executionStageIdx = pipelineCfg.findIndex(s => s.id === "execution");
    paperItems.forEach((item, i) => {
      // Stagger buys: 900s (15 min), 1200s (20 min), … after market open
      const offsetS = 900 + i * 300;
      result.push({
        id: `buy-${item.symbol}`,
        kind: "buy",
        label: `BUY ${item.symbol}`,
        sublabel: item.entry_price != null ? `₹${item.entry_price.toFixed(1)}` : undefined,
        pct: twoZonePct(offsetS),
        stageIdx: executionStageIdx >= 0 ? executionStageIdx : undefined,
      });
    });

    // SELL / exit events — Zone B, staggered from 1 hr after open
    const closedItems = (comparisonData?.comparisons ?? []).filter(
      c => c.paper_traded && (c.status === "WIN" || c.status === "LOSS"),
    );
    const portStageIdx = pipelineCfg.findIndex(s => s.id === "portfolio_management");
    closedItems.forEach((item, i) => {
      const offsetS = 3600 + i * 600; // exits 1 hr after open, 10-min apart
      result.push({
        id: `sell-${item.symbol}`,
        kind: "sell",
        label: `${item.status} ${item.symbol}`,
        sublabel: item.outcome_pct != null
          ? `${item.outcome_pct >= 0 ? "+" : ""}${item.outcome_pct.toFixed(1)}%`
          : undefined,
        pct: twoZonePct(offsetS),
        stageIdx: portStageIdx >= 0 ? portStageIdx : undefined,
      });
    });

    // Market Close — right edge
    result.push({ id: "close", kind: "close", label: "Market Close", sublabel: "15:30 IST", pct: 100 });

    return result.sort((a, b) => a.pct - b.pct);
  }, [comparisonData, snapshotTs, pipelineCfg]);

  // Current replay progress % on the two-zone scale
  const progressPct = useMemo(() => {
    if (activeStageIdx < 0) return 0;
    const stageId = pipelineCfg[activeStageIdx]?.id ?? "";
    const offsetS = LOCAL_STAGE_OFFSETS[stageId] ?? 0;
    return twoZonePct(offsetS);
  }, [activeStageIdx, pipelineCfg]);

  // Auto-scroll the cursor into view
  useEffect(() => {
    if (!scrollRef.current || activeStageIdx < 0) return;
    const el = scrollRef.current;
    const targetPx = (progressPct / 100) * el.scrollWidth;
    el.scrollTo({ left: Math.max(0, targetPx - el.clientWidth / 2), behavior: "smooth" });
  }, [activeStageIdx, progressPct]);

  return (
    <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-slate-800/60 flex items-center gap-3 flex-wrap">
        <Clock size={13} className="text-teal-400" />
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Event Timeline</span>
        <div className="ml-auto flex gap-4 text-xs text-slate-600">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-teal-500 inline-block" />Scan stage</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />BUY</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" />SELL/EXIT</span>
        </div>
      </div>

      {/* Scrollable track */}
      <div ref={scrollRef} className="overflow-x-auto px-4 py-4">
        {/* min-width=1100px: 10 scan stages at 35%=385px ≈ 38px apart, plenty of room */}
        <div className="relative" style={{ minWidth: "1100px", height: "80px" }}>

          {/* Zone A background shading (scan zone) */}
          <div
            className="absolute top-0 bottom-0 bg-teal-900/10 border-r border-teal-800/30"
            style={{ left: 0, width: `${ZONE_DIVIDER_PCT}%` }}
          />

          {/* Zone label */}
          <div
            className="absolute top-0 text-xs text-teal-800 font-semibold px-1 leading-tight select-none"
            style={{ left: "1%" }}
          >
            ← Scan Pipeline →
          </div>
          <div
            className="absolute top-0 text-xs text-slate-700 font-semibold px-1 leading-tight select-none"
            style={{ left: `${ZONE_DIVIDER_PCT + 1}%` }}
          >
            ← Intraday (09:15–15:30) →
          </div>

          {/* Track line */}
          <div className="absolute left-0 right-0 h-0.5 bg-slate-700" style={{ top: "34px" }} />

          {/* Progress fill */}
          {activeStageIdx >= 0 && (
            <div
              className="absolute h-0.5 bg-gradient-to-r from-teal-600 to-teal-400 transition-all duration-700"
              style={{ top: "34px", left: 0, width: `${progressPct}%` }}
            />
          )}

          {/* Progress cursor */}
          {activeStageIdx >= 0 && (
            <div
              className="absolute w-3 h-3 rounded-full bg-teal-400 border-2 border-slate-950 shadow-lg shadow-teal-900/50 transition-all duration-700 z-20"
              style={{ top: "28px", left: `calc(${progressPct}% - 6px)` }}
            />
          )}

          {/* Pins */}
          {pins.map(pin => {
            const style = PIN_STYLE[pin.kind];
            const Icon  = PIN_ICON[pin.kind];
            const isActive = pin.stageIdx != null && pin.stageIdx === activeStageIdx;
            return (
              <button
                key={pin.id}
                onClick={() => pin.stageIdx != null && onJumpToStage(pin.stageIdx)}
                disabled={pin.stageIdx == null}
                title={`${pin.label}${pin.sublabel ? ` — ${pin.sublabel}` : ""} (click to jump)`}
                className={`absolute -translate-x-1/2 flex flex-col items-center gap-0 group cursor-pointer disabled:cursor-default
                  ${isActive ? "scale-110" : "hover:scale-110"} transition-transform`}
                style={{ top: "16px", left: `${pin.pct}%` }}
              >
                {/* Icon dot */}
                <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center
                  ${style.dot} ${isActive ? "ring-2 ring-offset-1 ring-offset-slate-900 ring-teal-400" : ""}
                  group-hover:scale-110 transition-transform z-10`}
                >
                  <Icon size={8} className="opacity-80" />
                </div>
                {/* Label below */}
                <div className="flex flex-col items-center mt-1">
                  <div className={`text-xs font-medium whitespace-nowrap ${style.label}
                    group-hover:text-white transition-colors max-w-[70px] truncate`}
                  >
                    {pin.label}
                  </div>
                  {pin.sublabel && (
                    <div className="text-xs text-slate-600 font-mono whitespace-nowrap">{pin.sublabel}</div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
